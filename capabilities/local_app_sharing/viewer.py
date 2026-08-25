"""Browser shell plus encrypted and ordinary local app transports."""

from __future__ import annotations

from .crypto import CONTENT_ENCRYPTION_PROTOCOL

VIEWER_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Tinyhat Visual</title>
<style>[hidden]{display:none!important}html,body{height:100%;margin:0}
body{font:16px system-ui;background:#f5f5f0;color:#171717}
#loading{display:grid;place-items:center;height:100%;background:#f5f5f0}
.spinner{width:2rem;height:2rem;border:.2rem solid #d7d7d2;border-top-color:#171717;
border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
#code-page,#browser-page{box-sizing:border-box;max-width:28rem;margin:12vh auto;padding:2rem;background:white;border:1px solid #bbb}
input,button{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.75rem;font:inherit}
button,.browser-link{box-sizing:border-box;display:block;width:100%;padding:.8rem;margin-top:.75rem;
background:#171717;color:white;border:0;text-align:center;text-decoration:none;font:inherit}.error{color:#a00}
</style></head>
<body><main id="loading"><span class="spinner" role="status" aria-label="Loading"></span></main>
<main id="code-page" hidden><h1>Open Visual</h1><p>Enter the code your agent sent you.</p>
<p id="error" class="error" role="alert" hidden></p>
<form id="code-form"><label for="code">Access code</label>
<input id="code" name="code" autocomplete="one-time-code" inputmode="numeric"
pattern="[0-9]{4}" minlength="4" maxlength="4" required>
<button type="submit">Open visual</button></form></main>
<main id="browser-page" hidden><p>This encrypted Visual needs browser security features that
Telegram does not provide.</p><a id="browser-link" class="browser-link" target="_blank"
rel="noopener noreferrer">Open Visual in browser</a></main>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script>(() => {
  'use strict';
  const protocol = '__CONTENT_ENCRYPTION_PROTOCOL__';
  const plainTransport = 'none';
  const handoffProtocol = 'tinyhat-browser-handoff-v1';
  const ownerCodeProtocol = 'tinyhat-owner-access-code-v1';
  const loading = document.getElementById('loading');
  const codePage = document.getElementById('code-page');
  const browserPage = document.getElementById('browser-page');
  const browserLink = document.getElementById('browser-link');
  const codeForm = document.getElementById('code-form');
  const codeInput = document.getElementById('code');
  const error = document.getElementById('error');
  const sessionId = location.pathname.match(/^\/s\/(las_[A-Za-z0-9_-]{20,80})\/?$/)?.[1];
  const fragmentParams = new URLSearchParams(location.hash.slice(1));
  const expectedFingerprint = fragmentParams.get(protocol);
  const incomingBrowserHandoff = fragmentParams.get(handoffProtocol);
  const incomingOwnerCode = fragmentParams.get(ownerCodeProtocol);
  const telegram = window.Telegram && window.Telegram.WebApp;
  const embedded = window.top !== window.self;
  let browserHandoffUrl = '';

  function bytesToBase64Url(bytes) {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function showCode(message) {
    loading.hidden = true;
    browserPage.hidden = true;
    codePage.hidden = false;
    error.hidden = !message;
    error.textContent = message || '';
    codeInput.focus();
  }

  function canonicalFragment(browserHandoff) {
    const params = new URLSearchParams();
    params.set(protocol, expectedFingerprint);
    if (browserHandoff) params.set(handoffProtocol, browserHandoff);
    return `#${params.toString()}`;
  }

  function showBrowserHandoff(browserHandoff) {
    if (!/^bh_[A-Za-z0-9_-]{32,128}$/.test(browserHandoff || '')) {
      showCode('');
      return;
    }
    const externalUrl = `${location.origin}${location.pathname}${canonicalFragment(browserHandoff)}`;
    browserHandoffUrl = externalUrl;
    codePage.hidden = true;
    loading.hidden = true;
    browserPage.hidden = false;
    browserLink.href = externalUrl;
    if (telegram && telegram.initData && telegram.MainButton && telegram.openLink) {
      telegram.MainButton.setText('Open visual');
      telegram.MainButton.show();
      telegram.MainButton.onClick(() => telegram.openLink(externalUrl));
    }
  }

  browserLink.addEventListener('click', event => {
    if (!browserHandoffUrl || !telegram || !telegram.initData || !telegram.openLink) return;
    event.preventDefault();
    telegram.openLink(browserHandoffUrl);
  });

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

  async function configureWorker(message) {
    if (!('serviceWorker' in navigator)) throw new Error('service-worker-unavailable');
    let registration;
    try {
      registration = await navigator.serviceWorker.register(
        '/__tinyhat_share/e2ee-v3-sw.js', {scope: '/', updateViaCache: 'none'}
      );
      await navigator.serviceWorker.ready;
    } catch (_) {
      throw new Error('service-worker-unavailable');
    }
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
      worker.postMessage(message, [channel.port2]);
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
    const sessionFragment = `#${protocol}=${expectedFingerprint}`;
    sessionStorage.setItem(`tinyhat-e2ee-fragment:${sessionId}`, sessionFragment);
    await configureWorker({
      type: 'tinyhat-e2ee-configure',
      protocol,
      contentTransport: protocol,
      sessionId,
      connectionId: handshake.connection_id,
      key: bytesToBase64Url(new Uint8Array(rawKey)),
    });
    location.replace(`/s/${sessionId}/app/${sessionFragment}`);
  }

  async function openPlainApp() {
    try {
      await configureWorker({
        type: 'tinyhat-plain-configure',
        contentTransport: plainTransport,
        sessionId,
      });
    } catch (_) {
      // Relative URLs and forms still work through the prefixed app route.
    }
    location.replace(`/s/${sessionId}/app/`);
  }

  function base64UrlToBytes(value) {
    const clean = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(clean + '='.repeat((4 - clean.length % 4) % 4));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  }

  async function authorizeTelegram(browserHandoff = false) {
    return jsonFetch(`/s/${sessionId}/telegram-authorize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        telegram_init_data: telegram.initData,
        embedded,
        browser_handoff: browserHandoff,
      }),
    });
  }

  async function authorizeLink(browserHandoff = false) {
    return jsonFetch(`/s/${sessionId}/link-authorize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({embedded, browser_handoff: browserHandoff}),
    });
  }

  async function authorizeCode(accessCode, browserHandoff = false) {
    return jsonFetch(`/s/${sessionId}/code-authorize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        access_code: accessCode,
        embedded,
        browser_handoff: browserHandoff,
      }),
    });
  }

  function removeOwnerCodeFromAddress() {
    const safeFragment = new URLSearchParams(location.hash.slice(1));
    safeFragment.delete(ownerCodeProtocol);
    const serialized = safeFragment.toString();
    history.replaceState(
      null,
      '',
      `${location.pathname}${serialized ? `#${serialized}` : ''}`,
    );
  }

  async function createBrowserHandoff() {
    return jsonFetch(`/s/${sessionId}/browser-handoff`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}',
    });
  }

  async function currentAuthorization() {
    return jsonFetch(`/s/${sessionId}/session`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}',
    });
  }

  async function consumeBrowserHandoff() {
    if (!incomingBrowserHandoff) return;
    await jsonFetch(`/s/${sessionId}/browser-handoff-authorize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({browser_handoff: incomingBrowserHandoff}),
    });
    history.replaceState(null, '', `${location.pathname}${canonicalFragment()}`);
  }

  async function openOrHandoff() {
    try {
      await openEncryptedApp();
      return true;
    } catch (failure) {
      if (!String(failure && failure.message || '').startsWith('service-worker-')) {
        return false;
      }
      try {
        const authorization = await createBrowserHandoff();
        showBrowserHandoff(authorization.browser_handoff);
        return true;
      } catch (_) {
        return false;
      }
    }
  }

  async function openAuthorizedApp(authorization) {
    if (authorization && authorization.content_encryption === plainTransport) {
      await openPlainApp();
      return true;
    }
    if (!authorization || authorization.content_encryption !== protocol) return false;
    if (!expectedFingerprint) {
      showCode('This encrypted sharing link is incomplete.');
      return true;
    }
    if (!('serviceWorker' in navigator)) {
      try {
        const handoff = await createBrowserHandoff();
        showBrowserHandoff(handoff.browser_handoff);
        return true;
      } catch (_) {
        return false;
      }
    }
    return openOrHandoff();
  }

  codeForm.addEventListener('submit', async event => {
    event.preventDefault();
    loading.hidden = false;
    codePage.hidden = true;
    try {
      const authorization = await authorizeCode(codeInput.value);
      if (!await openAuthorizedApp(authorization)) throw new Error('share-open-failed');
    } catch (_) {
      showCode('That code is not valid or has expired.');
    }
  });

  (async () => {
    if (!sessionId) {
      showCode('This sharing link is incomplete.');
      return;
    }
    if (incomingOwnerCode) removeOwnerCodeFromAddress();
    if (telegram && telegram.initData) {
      telegram.ready();
      telegram.expand();
    }
    if (incomingBrowserHandoff) {
      try {
        await consumeBrowserHandoff();
      } catch (_) {
        history.replaceState(null, '', `${location.pathname}${canonicalFragment()}`);
      }
    }
    try {
      if (await openAuthorizedApp(await currentAuthorization())) return;
    } catch (_) {}
    try {
      if (await openAuthorizedApp(await authorizeLink())) return;
    } catch (_) {}
    if (telegram && telegram.initData) {
      try {
        if (await openAuthorizedApp(await authorizeTelegram())) return;
      } catch (_) {}
    }
    if (/^[0-9]{4}$/.test(incomingOwnerCode || '')) {
      try {
        if (await openAuthorizedApp(await authorizeCode(incomingOwnerCode))) return;
      } catch (_) {}
    }
    showCode('');
  })();
})();</script></body></html>""".replace(
    "__CONTENT_ENCRYPTION_PROTOCOL__", CONTENT_ENCRYPTION_PROTOCOL
).encode("utf-8")


APP_SHELL = r"""'use strict';
(() => {
  const script = document.currentScript;
  const sessionId = script && script.dataset.sessionId;
  if (!/^las_[A-Za-z0-9_-]{20,80}$/.test(sessionId || '')) return;
  const key = `tinyhat-e2ee-fragment:${sessionId}`;
  const stored = sessionStorage.getItem(key) || '';
  const fragmentPattern = /^#__CONTENT_ENCRYPTION_PROTOCOL__=[A-Za-z0-9_-]{43}$/;
  const fragment = fragmentPattern.test(stored)
    ? stored
    : fragmentPattern.test(location.hash) ? location.hash : '';
  if (fragment) sessionStorage.setItem(key, fragment);
  history.replaceState(null, '', `/s/${sessionId}${fragment}`);
})();
""".replace("__CONTENT_ENCRYPTION_PROTOCOL__", CONTENT_ENCRYPTION_PROTOCOL).encode("utf-8")


SERVICE_WORKER = r"""'use strict';
const PROTOCOL = '__CONTENT_ENCRYPTION_PROTOCOL__';
const CONFIGS = new Map();
const CLIENT_SESSIONS = new Map();
const CONFIG_DB_NAME = 'tinyhat-local-app-sharing';
const CONFIG_DB_VERSION = 1;
const CONFIG_STORE_NAME = 'e2ee-configs';

function openConfigDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(CONFIG_DB_NAME, CONFIG_DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(CONFIG_STORE_NAME)) {
        db.createObjectStore(CONFIG_STORE_NAME, {keyPath: 'sessionId'});
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('config-db-open-failed'));
  });
}

async function persistConfig(config) {
  const db = await openConfigDb();
  try {
    await new Promise((resolve, reject) => {
      const transaction = db.transaction(CONFIG_STORE_NAME, 'readwrite');
      transaction.objectStore(CONFIG_STORE_NAME).put(config);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(
        transaction.error || new Error('config-db-write-failed')
      );
      transaction.onabort = () => reject(
        transaction.error || new Error('config-db-write-aborted')
      );
    });
  } finally {
    db.close();
  }
}

async function loadConfig(sessionId) {
  const cached = CONFIGS.get(sessionId);
  if (cached) return cached;
  const db = await openConfigDb();
  let stored;
  try {
    stored = await new Promise((resolve, reject) => {
      const request = db.transaction(CONFIG_STORE_NAME, 'readonly')
        .objectStore(CONFIG_STORE_NAME).get(sessionId);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('config-db-read-failed'));
    });
  } finally {
    db.close();
  }
  if (!stored) return null;
  if (stored.contentTransport === 'none') {
    const config = {sessionId, contentTransport: 'none'};
    CONFIGS.set(sessionId, config);
    return config;
  }
  if (stored.contentTransport !== PROTOCOL || !stored.key || !stored.connectionId) return null;
  const key = await crypto.subtle.importKey(
    'raw', base64UrlToBytes(stored.key), {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']
  );
  const config = {
    sessionId,
    contentTransport: PROTOCOL,
    connectionId: stored.connectionId,
    key,
  };
  CONFIGS.set(sessionId, config);
  return config;
}

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
  if (!event.data ||
      !['tinyhat-e2ee-configure', 'tinyhat-plain-configure'].includes(event.data.type)) return;
  const reply = event.ports && event.ports[0];
  event.waitUntil((async () => {
    try {
      const {protocol, contentTransport, sessionId, connectionId, key} = event.data;
      if (!/^las_[A-Za-z0-9_-]{20,80}$/.test(sessionId)) throw new Error('invalid');
      if (event.data.type === 'tinyhat-plain-configure') {
        if (contentTransport !== 'none') throw new Error('invalid');
        const config = {sessionId, contentTransport};
        CONFIGS.set(sessionId, config);
        await persistConfig(config);
        if (event.source && event.source.id) CLIENT_SESSIONS.set(event.source.id, sessionId);
        if (reply) reply.postMessage({ok: true});
        return;
      }
      if (protocol !== PROTOCOL || contentTransport !== PROTOCOL ||
          !/^e2e_[A-Za-z0-9_-]{20,80}$/.test(connectionId)) throw new Error('invalid');
      const cryptoKey = await crypto.subtle.importKey(
        'raw', base64UrlToBytes(key), {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']
      );
      const config = {sessionId, contentTransport, connectionId, key: cryptoKey};
      CONFIGS.set(sessionId, config);
      await persistConfig({sessionId, contentTransport, connectionId, key});
      if (event.source && event.source.id) CLIENT_SESSIONS.set(event.source.id, sessionId);
      if (reply) reply.postMessage({ok: true});
    } catch (_) {
      if (reply) reply.postMessage({ok: false});
    }
  })());
});

async function sessionForClient(clientId) {
  if (!clientId) return null;
  const cached = CLIENT_SESSIONS.get(clientId);
  if (cached) return cached;
  const client = await self.clients.get(clientId);
  if (!client) return null;
  const match = new URL(client.url).pathname.match(
    /^\/s\/(las_[A-Za-z0-9_-]{20,80})(?:\/|$)/
  );
  if (!match) return null;
  CLIENT_SESSIONS.set(clientId, match[1]);
  return match[1];
}

async function routeFor(event) {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return null;
  const app = url.pathname.match(/^\/s\/(las_[A-Za-z0-9_-]{20,80})\/app(\/.*)?$/);
  if (app) {
    const sessionId = app[1];
    const config = await loadConfig(sessionId);
    if (!config) return null;
    if (event.resultingClientId) CLIENT_SESSIONS.set(event.resultingClientId, sessionId);
    return {config, target: (app[2] || '/') + url.search};
  }
  const sessionId = await sessionForClient(event.clientId);
  if (!sessionId || url.pathname.startsWith('/s/') || url.pathname.startsWith('/__tinyhat_share/')) {
    return null;
  }
  const config = await loadConfig(sessionId);
  return config ? {config, target: url.pathname + url.search} : null;
}

async function encryptedFetch(event, route) {
  const {config, target} = route;
  const headers = {};
  event.request.headers.forEach((value, name) => {
    if (!['accept-encoding', 'connection', 'content-length', 'cookie', 'host',
          'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te',
          'trailer', 'transfer-encoding', 'upgrade'].includes(name.toLowerCase())) {
      headers[name] = value;
    }
  });
  const requestBody = ['GET', 'HEAD'].includes(event.request.method)
    ? null
    : bytesToBase64Url(new Uint8Array(await event.request.clone().arrayBuffer()));
  const requestId = randomId();
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = new TextEncoder().encode(JSON.stringify({
    method: event.request.method,
    target,
    headers,
    body: requestBody,
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
  if (!outer.ok) return new Response('Visual unavailable', {status: outer.status});
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
  let body = event.request.method === 'HEAD'
    ? null
    : payload.body
      ? base64UrlToBytes(payload.body)
      : new Uint8Array();
  const contentType = responseHeaders.get('content-type') || '';
  if (body && event.request.mode === 'navigate' && /text\/html/i.test(contentType)) {
    const source = new TextDecoder().decode(body);
    const shell = `<base href="/s/${config.sessionId}/app/">` +
      `<script src="/__tinyhat_share/app-shell-v3.js" ` +
      `data-session-id="${config.sessionId}"><\/script>`;
    const head = source.match(/<head(?:\s[^>]*)?>/i);
    const html = head
      ? source.slice(0, head.index + head[0].length) + shell +
        source.slice(head.index + head[0].length)
      : shell + source;
    body = new TextEncoder().encode(html);
    responseHeaders.append('Content-Security-Policy', "worker-src 'none'");
  }
  return new Response(body, {status: payload.status, statusText: payload.reason || '', headers: responseHeaders});
}

async function plainFetch(event, route) {
  const {config, target} = route;
  const body = ['GET', 'HEAD'].includes(event.request.method)
    ? undefined
    : await event.request.clone().arrayBuffer();
  return fetch(`/s/${config.sessionId}/app${target}`, {
    method: event.request.method,
    headers: event.request.headers,
    body,
    credentials: 'include',
    redirect: 'follow',
  });
}

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith((async () => {
    const route = await routeFor(event);
    if (!route) return fetch(event.request);
    return route.config.contentTransport === 'none'
      ? plainFetch(event, route)
      : encryptedFetch(event, route);
  })());
});
""".replace("__CONTENT_ENCRYPTION_PROTOCOL__", CONTENT_ENCRYPTION_PROTOCOL).encode("utf-8")


__all__ = ["APP_SHELL", "SERVICE_WORKER", "VIEWER_PAGE"]
