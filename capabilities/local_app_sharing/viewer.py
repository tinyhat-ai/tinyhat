"""Browser shell and service worker for encrypted local app sharing."""

from __future__ import annotations

from .crypto import CONTENT_ENCRYPTION_PROTOCOL

VIEWER_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open shared Tinyhat app</title>
<style>[hidden]{display:none!important}html,body{height:100%;margin:0}
body{font:16px system-ui;background:#f5f5f0;color:#171717}
#loading{display:grid;place-items:center;height:100%;background:#f5f5f0}
.spinner{width:2rem;height:2rem;border:.2rem solid #d7d7d2;border-top-color:#171717;
border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
#code-page{box-sizing:border-box;max-width:28rem;margin:12vh auto;padding:2rem;background:white;border:1px solid #bbb}
input,button{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.75rem;font:inherit}
button{background:#171717;color:white;border:0}.error{color:#a00}
#app{display:block;width:100%;height:100%;border:0;background:white}</style></head>
<body><main id="loading"><span class="spinner" role="status" aria-label="Loading"></span></main>
<main id="code-page" hidden><h1>Open shared app</h1><p>Enter the code your agent sent you.</p>
<p id="error" class="error" role="alert" hidden></p>
<form id="code-form"><label for="code">Access code</label>
<input id="code" name="code" autocomplete="one-time-code" inputmode="numeric"
pattern="[0-9]{4}" minlength="4" maxlength="4" required>
<button type="submit">View app</button></form></main>
<iframe id="app" title="Shared app" sandbox="allow-scripts" hidden></iframe>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script>(() => {
  'use strict';
  const protocol = '__CONTENT_ENCRYPTION_PROTOCOL__';
  const loading = document.getElementById('loading');
  const codePage = document.getElementById('code-page');
  const codeForm = document.getElementById('code-form');
  const codeInput = document.getElementById('code');
  const error = document.getElementById('error');
  const appFrame = document.getElementById('app');
  const sessionId = location.pathname.match(/^\/s\/(las_[A-Za-z0-9_-]{20,80})\/?$/)?.[1];
  const expectedFingerprint = new URLSearchParams(location.hash.slice(1)).get(protocol);
  const telegram = window.Telegram && window.Telegram.WebApp;

  function bytesToBase64Url(bytes) {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function showCode(message) {
    loading.hidden = true;
    appFrame.hidden = true;
    codePage.hidden = false;
    error.hidden = !message;
    error.textContent = message || '';
    codeInput.focus();
  }

  async function jsonFetch(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options});
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  async function verifyServerKey(keyPayload) {
    if (keyPayload.content_encryption !== protocol || !expectedFingerprint) {
      throw new Error('link-key-missing');
    }
    const serverKey = await crypto.subtle.importKey(
      'jwk', keyPayload.public_key_jwk, {name: 'ECDH', namedCurve: 'P-256'}, true, []
    );
    const spki = await crypto.subtle.exportKey('spki', serverKey);
    const digest = await crypto.subtle.digest('SHA-256', spki);
    if (bytesToBase64Url(new Uint8Array(digest)) !== expectedFingerprint ||
        keyPayload.fingerprint !== expectedFingerprint) {
      throw new Error('link-key-mismatch');
    }
    return serverKey;
  }

  async function configureWorker(session, connection, rawKey) {
    if (!('serviceWorker' in navigator)) throw new Error('service-worker-unavailable');
    const registration = await navigator.serviceWorker.register(
      '/__tinyhat_share/e2ee-v1-sw.js', {scope: '/'}
    );
    await navigator.serviceWorker.ready;
    const worker = registration.active || registration.waiting || registration.installing;
    if (!worker) throw new Error('service-worker-unavailable');
    await new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      const timer = setTimeout(() => reject(new Error('service-worker-timeout')), 5000);
      channel.port1.onmessage = event => {
        clearTimeout(timer);
        if (event.data && event.data.ok) resolve();
        else reject(new Error('service-worker-configuration-failed'));
      };
      worker.postMessage({
        type: 'tinyhat-e2ee-configure',
        protocol,
        sessionId: session,
        connectionId: connection,
        key: bytesToBase64Url(new Uint8Array(rawKey)),
      }, [channel.port2]);
    });
    if (!navigator.serviceWorker.controller) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
          reject(new Error('service-worker-control-timeout'));
        }, 5000);
        function onControllerChange() {
          if (!navigator.serviceWorker.controller) return;
          clearTimeout(timer);
          navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
          resolve();
        }
        navigator.serviceWorker.addEventListener('controllerchange', onControllerChange);
        onControllerChange();
      });
    }
  }

  async function openEncryptedApp() {
    if (!sessionId || !expectedFingerprint) throw new Error('link-key-missing');
    const keyPayload = await jsonFetch(`/s/${sessionId}/e2ee-key`);
    const serverKey = await verifyServerKey(keyPayload);
    const browserKeys = await crypto.subtle.generateKey(
      {name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']
    );
    const browserPublicJwk = await crypto.subtle.exportKey('jwk', browserKeys.publicKey);
    const handshake = await jsonFetch(`/s/${sessionId}/e2ee-handshake`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({browser_public_jwk: browserPublicJwk}),
    });
    if (handshake.content_encryption !== protocol) throw new Error('handshake-failed');
    const shared = await crypto.subtle.deriveBits(
      {name: 'ECDH', public: serverKey}, browserKeys.privateKey, 256
    );
    const baseKey = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
    const info = new TextEncoder().encode(
      `${protocol}\0${sessionId}\0${expectedFingerprint}`
    );
    const key = await crypto.subtle.deriveKey(
      {name: 'HKDF', hash: 'SHA-256', salt: base64UrlToBytes(handshake.salt), info},
      baseKey,
      {name: 'AES-GCM', length: 256},
      true,
      ['encrypt', 'decrypt'],
    );
    const rawKey = await crypto.subtle.exportKey('raw', key);
    await configureWorker(sessionId, handshake.connection_id, rawKey);
    codePage.hidden = true;
    loading.hidden = true;
    appFrame.src = `/s/${sessionId}/app/`;
    appFrame.hidden = false;
  }

  function base64UrlToBytes(value) {
    const clean = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(clean + '='.repeat((4 - clean.length % 4) % 4));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  }

  async function authorizeTelegram() {
    await jsonFetch(`/s/${sessionId}/telegram-authorize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({telegram_init_data: telegram.initData}),
    });
  }

  codeForm.addEventListener('submit', async event => {
    event.preventDefault();
    loading.hidden = false;
    codePage.hidden = true;
    try {
      await jsonFetch(`/s/${sessionId}/code-authorize`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({access_code: codeInput.value}),
      });
      await openEncryptedApp();
    } catch (_) {
      showCode('That code is not valid or has expired.');
    }
  });

  (async () => {
    if (!sessionId || !expectedFingerprint) {
      showCode('This sharing link is incomplete.');
      return;
    }
    if (telegram && telegram.initData) {
      telegram.ready();
      telegram.expand();
    }
    try {
      await openEncryptedApp();
      return;
    } catch (_) {}
    if (telegram && telegram.initData) {
      try {
        await authorizeTelegram();
        await openEncryptedApp();
        return;
      } catch (_) {}
    }
    showCode('');
  })();
})();</script></body></html>""".replace(
    "__CONTENT_ENCRYPTION_PROTOCOL__", CONTENT_ENCRYPTION_PROTOCOL
).encode("utf-8")


SERVICE_WORKER = r"""'use strict';
const PROTOCOL = '__CONTENT_ENCRYPTION_PROTOCOL__';
const CONFIGS = new Map();
const CLIENT_SESSIONS = new Map();

function base64UrlToBytes(value) {
  const clean = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(clean + '='.repeat((4 - clean.length % 4) % 4));
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

function bytesToBase64Url(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function requestAad(sessionId, connectionId, requestId) {
  return new TextEncoder().encode(
    `${PROTOCOL}\0request\0${sessionId}\0${connectionId}\0${requestId}`
  );
}

function responseAad(sessionId, connectionId, requestId) {
  return new TextEncoder().encode(
    `${PROTOCOL}\0response\0${sessionId}\0${connectionId}\0${requestId}`
  );
}

function randomId() {
  return bytesToBase64Url(crypto.getRandomValues(new Uint8Array(18)));
}

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

self.addEventListener('message', event => {
  if (!event.data || event.data.type !== 'tinyhat-e2ee-configure') return;
  const reply = event.ports && event.ports[0];
  event.waitUntil((async () => {
    try {
      const {protocol, sessionId, connectionId, key} = event.data;
      if (protocol !== PROTOCOL || !/^las_[A-Za-z0-9_-]{20,80}$/.test(sessionId) ||
          !/^e2e_[A-Za-z0-9_-]{20,80}$/.test(connectionId)) throw new Error('invalid');
      const cryptoKey = await crypto.subtle.importKey(
        'raw', base64UrlToBytes(key), {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']
      );
      CONFIGS.set(sessionId, {sessionId, connectionId, key: cryptoKey});
      if (event.source && event.source.id) CLIENT_SESSIONS.set(event.source.id, sessionId);
      if (reply) reply.postMessage({ok: true});
    } catch (_) {
      if (reply) reply.postMessage({ok: false});
    }
  })());
});

function routeFor(event) {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return null;
  const app = url.pathname.match(/^\/s\/(las_[A-Za-z0-9_-]{20,80})\/app(\/.*)?$/);
  if (app) {
    const sessionId = app[1];
    const config = CONFIGS.get(sessionId);
    if (!config) return null;
    if (event.resultingClientId) CLIENT_SESSIONS.set(event.resultingClientId, sessionId);
    return {config, target: (app[2] || '/') + url.search};
  }
  const sessionId = CLIENT_SESSIONS.get(event.clientId);
  if (!sessionId || url.pathname.startsWith('/s/') || url.pathname.startsWith('/__tinyhat_share/')) {
    return null;
  }
  const config = CONFIGS.get(sessionId);
  return config ? {config, target: url.pathname + url.search} : null;
}

async function encryptedFetch(event, route) {
  const {config, target} = route;
  if (!['GET', 'HEAD'].includes(event.request.method)) {
    return new Response('Read-only shared app', {status: 405});
  }
  const headers = {};
  for (const name of ['accept', 'accept-language', 'if-none-match', 'if-modified-since', 'range']) {
    const value = event.request.headers.get(name);
    if (value) headers[name] = value;
  }
  const requestId = randomId();
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = new TextEncoder().encode(JSON.stringify({
    method: event.request.method,
    target,
    headers,
  }));
  const ciphertext = await crypto.subtle.encrypt(
    {name: 'AES-GCM', iv: nonce, additionalData: requestAad(
      config.sessionId, config.connectionId, requestId
    )},
    config.key,
    plaintext,
  );
  const outer = await fetch(`/s/${config.sessionId}/encrypted`, {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      content_encryption: PROTOCOL,
      connection_id: config.connectionId,
      request_id: requestId,
      nonce: bytesToBase64Url(nonce),
      ciphertext: bytesToBase64Url(new Uint8Array(ciphertext)),
    }),
  });
  if (!outer.ok) return new Response('Shared app unavailable', {status: outer.status});
  const encrypted = await outer.json();
  const decrypted = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: base64UrlToBytes(encrypted.nonce),
      additionalData: responseAad(config.sessionId, config.connectionId, requestId),
    },
    config.key,
    base64UrlToBytes(encrypted.ciphertext),
  );
  const payload = JSON.parse(new TextDecoder().decode(decrypted));
  const responseHeaders = new Headers();
  for (const pair of payload.headers || []) {
    if (Array.isArray(pair) && pair.length === 2) responseHeaders.append(pair[0], pair[1]);
  }
  const body = event.request.method === 'HEAD'
    ? null
    : payload.body
      ? base64UrlToBytes(payload.body)
      : new Uint8Array();
  return new Response(body, {status: payload.status, statusText: payload.reason || '', headers: responseHeaders});
}

self.addEventListener('fetch', event => {
  const route = routeFor(event);
  if (route) event.respondWith(encryptedFetch(event, route));
});
""".replace("__CONTENT_ENCRYPTION_PROTOCOL__", CONTENT_ENCRYPTION_PROTOCOL).encode("utf-8")


__all__ = ["SERVICE_WORKER", "VIEWER_PAGE"]
