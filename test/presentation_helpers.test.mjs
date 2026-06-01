import assert from "node:assert/strict";
import test from "node:test";

import {
  formatButtonReply,
  formatSecretListReply,
  formatSecretRequestReply,
  formatSoftwareUpdatesReply,
} from "../src/presentation_helpers.js";

const MINI_APP_URL =
  "https://tinyhat.example/mini/runtime-secret/add?intent=signed-token&name=OPENAI_API_KEY";

function sampleSecretPayload(overrides = {}) {
  return {
    mini_app_url: MINI_APP_URL,
    secret: {
      name: "OPENAI_API_KEY",
      description: "Used for model access",
      status: "missing",
      revision: 2,
      secret_value: "sk-never-visible",
    },
    telegram_button: {
      text: "Add OPENAI_API_KEY",
      web_app: { url: MINI_APP_URL },
    },
    ...overrides,
  };
}

function withoutChannelData(value) {
  const copy = structuredClone(value);
  delete copy.channelData;
  return copy;
}

function assertNoRawSecretTransportInVisibleReply(reply) {
  const visible = JSON.stringify(withoutChannelData(reply));
  assert(!visible.includes(MINI_APP_URL));
  assert(!visible.includes("signed-token"));
  assert(!visible.includes("mini_app_url"));
  assert(!visible.includes("secret_value"));
  assert(!visible.includes("sk-never-visible"));
}

test("formatSecretRequestReply returns safe text plus Telegram transport button", () => {
  const reply = formatSecretRequestReply(sampleSecretPayload());

  assert.equal(reply.ok, true);
  assert.equal(reply.action, "credentials.open_add_secret");
  assert.equal(
    reply.text,
    "Open the Telegram Mini App button to add OPENAI_API_KEY. Do not paste the value in chat.",
  );
  assert.deepEqual(reply.button, {
    label: "Add OPENAI_API_KEY",
    kind: "telegram_web_app",
    transport_only: true,
  });
  assert(!("unsupported_channel_text" in reply));
  assert.equal(reply.channelData.telegram.buttons[0][0].web_app.url, MINI_APP_URL);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatSecretRequestReply keeps button replies on the Telegram-native path", () => {
  const reply = formatSecretRequestReply(sampleSecretPayload());

  assert(!reply.presentation);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatSecretRequestReply degrades without raw URL when no button exists", () => {
  const reply = formatSecretRequestReply(
    sampleSecretPayload({ telegram_button: undefined }),
  );

  assert.equal(reply.ok, false);
  assert(!reply.channelData);
  assert(!reply.presentation);
  assert.match(reply.text, /Retry from Telegram or open Manage Computer/);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatSecretListReply lists metadata without exposing raw link fields", () => {
  const reply = formatSecretListReply({
    mini_app_url: MINI_APP_URL,
    telegram_button: {
      text: "Manage secrets",
      web_app: { url: MINI_APP_URL },
    },
    secrets: [
      {
        name: "OPENAI_API_KEY",
        description: "Used for model access",
        has_value: true,
        vps_status: "available",
        secret_value: "sk-never-visible",
      },
    ],
  });

  assert.match(reply.text, /OPENAI_API_KEY: saved, available/);
  assert(!("unsupported_channel_text" in reply));
  assert.equal(reply.channelData.telegram.buttons[0][0].web_app.url, MINI_APP_URL);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatSecretListReply degrades without raw URL when no button exists", () => {
  const reply = formatSecretListReply({
    mini_app_url: MINI_APP_URL,
    secrets: [
      {
        name: "OPENAI_API_KEY",
        description: "Used for model access",
        has_value: false,
        vps_status: "missing",
        secret_value: "sk-never-visible",
      },
    ],
  });

  assert.equal(reply.ok, true);
  assert.equal(reply.action, "credentials.list_metadata");
  assert.match(reply.text, /OPENAI_API_KEY: not saved, not available/);
  assert(!reply.channelData);
  assert(!reply.presentation);
  assert.match(reply.unsupported_channel_text, /Telegram Mini App button/);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatButtonReply keeps Manage Computer URLs transport-only", () => {
  const reply = formatButtonReply(
    {
      mini_app_url: MINI_APP_URL,
      message: "Manage Computer is ready.",
      telegram_button: {
        text: "Manage computer",
        web_app: { url: MINI_APP_URL },
      },
    },
    "Manage computer",
    "computer.open_manage",
  );

  assert.equal(reply.action, "computer.open_manage");
  assert.equal(reply.text, "Manage Computer is ready.");
  assert(!("unsupported_channel_text" in reply));
  assert.equal(reply.channelData.telegram.buttons[0][0].web_app.url, MINI_APP_URL);
  assertNoRawSecretTransportInVisibleReply(reply);
});

test("formatSoftwareUpdatesReply opens the Software page as transport only", () => {
  const reply = formatSoftwareUpdatesReply({
    mini_app_url: MINI_APP_URL,
    message: "Manage Computer is ready.",
    telegram_button: {
      text: "Manage computer",
      web_app: { url: MINI_APP_URL },
    },
  });

  assert.equal(reply.action, "computer.software_updates");
  assert.equal(reply.button.label, "Open Software / Updates");
  assert.match(reply.text, /Software \/ Updates/);
  assert.match(
    reply.channelData.telegram.buttons[0][0].web_app.url,
    /\/software\?/,
  );
  assertNoRawSecretTransportInVisibleReply(reply);
});
