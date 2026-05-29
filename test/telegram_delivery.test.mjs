import assert from "node:assert/strict";
import test from "node:test";

import {
  markTelegramDelivered,
  sendTelegramMiniAppButton,
  sendTelegramPhoto,
  sendTelegramText,
  telegramBotTokenFromConfig,
  telegramChatIdFromDeliveryContext,
} from "../src/telegram_delivery.js";

const MINI_APP_URL = "https://tinyhat.example/miniapp/secret";

function replyWithButton() {
  return {
    ok: true,
    text: "Open the Telegram Mini App button to add OPENROUTER_API_KEY.",
    channelData: {
      telegram: {
        buttons: [
          [
            {
              text: "Add OPENROUTER_API_KEY",
              web_app: { url: MINI_APP_URL },
            },
          ],
        ],
      },
    },
    agent_instructions: ["Do not print the Mini App URL."],
  };
}

test("sendTelegramMiniAppButton posts native Telegram web_app markup", async () => {
  const calls = [];
  const result = await sendTelegramMiniAppButton({
    api: {},
    toolContext: {
      deliveryContext: {
        channel: "telegram",
        to: "telegram:101216939",
        accountId: "default",
      },
      config: { channels: { telegram: { botToken: "123:token" } } },
    },
    reply: replyWithButton(),
    text: "Tap the button.",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: { message_id: 42, chat: { id: 101216939 } },
        }),
      };
    },
  });

  assert.deepEqual(result, {
    sent: true,
    channel: "telegram",
    chat_id: "101216939",
    message_id: "42",
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.telegram.org/bot123:token/sendMessage");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    chat_id: "101216939",
    text: "Tap the button.",
    reply_markup: {
      inline_keyboard: replyWithButton().channelData.telegram.buttons,
    },
  });
});

test("markTelegramDelivered removes transport URL from tool result", () => {
  const marked = markTelegramDelivered(replyWithButton(), {
    sent: true,
    channel: "telegram",
    chat_id: "101216939",
    message_id: "42",
  });

  assert.equal(marked.delivered, true);
  assert(!marked.channelData);
  assert(!JSON.stringify(marked).includes(MINI_APP_URL));
  assert.match(marked.agent_instructions.at(-1), /already been sent directly/);
});

test("telegram delivery helper ignores non-telegram contexts", async () => {
  const result = await sendTelegramMiniAppButton({
    toolContext: {
      deliveryContext: { channel: "slack", to: "telegram:101216939" },
      config: { channels: { telegram: { botToken: "123:token" } } },
    },
    reply: replyWithButton(),
    text: "Tap the button.",
    fetchImpl: async () => {
      throw new Error("should not send");
    },
  });

  assert.deepEqual(result, {
    sent: false,
    reason: "not_telegram_delivery_context",
  });
});

test("telegram config helpers support default and account tokens", () => {
  assert.equal(
    telegramChatIdFromDeliveryContext({ to: "telegram:101216939" }, {}),
    "101216939",
  );
  assert.equal(
    telegramBotTokenFromConfig(
      {
        channels: {
          telegram: {
            botToken: "default-token",
            accounts: { work: { botToken: "work-token" } },
          },
        },
      },
      "work",
    ),
    "work-token",
  );
});

// ── #108 — photo + bare-text delivery helpers ─────────────────────────

const PHOTO_URL =
  "https://raw.githubusercontent.com/tinyhat-ai/tinyhat/main/skills/tinyhat-subscriptions/assets/chatgpt-enable-device-code-for-codex.png";

test("sendTelegramPhoto posts /sendPhoto with caption and chat id", async () => {
  const calls = [];
  const result = await sendTelegramPhoto({
    api: {},
    toolContext: {
      deliveryContext: {
        channel: "telegram",
        to: "telegram:101216939",
        accountId: "default",
      },
      config: { channels: { telegram: { botToken: "123:token" } } },
    },
    photoUrl: PHOTO_URL,
    caption: "Toggle the highlighted setting.",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: { message_id: 91, chat: { id: 101216939 } },
        }),
      };
    },
  });

  assert.deepEqual(result, {
    sent: true,
    channel: "telegram",
    chat_id: "101216939",
    message_id: "91",
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.telegram.org/bot123:token/sendPhoto");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    chat_id: "101216939",
    photo: PHOTO_URL,
    caption: "Toggle the highlighted setting.",
  });
});

test("sendTelegramPhoto refuses without a photoUrl", async () => {
  const result = await sendTelegramPhoto({
    toolContext: {
      deliveryContext: { channel: "telegram", to: "telegram:1" },
      config: { channels: { telegram: { botToken: "t" } } },
    },
    photoUrl: "",
    fetchImpl: async () => {
      throw new Error("should not send");
    },
  });
  assert.deepEqual(result, { sent: false, reason: "missing_photo_url" });
});

test("sendTelegramText posts /sendMessage with no inline keyboard", async () => {
  const calls = [];
  const result = await sendTelegramText({
    api: {},
    toolContext: {
      deliveryContext: {
        channel: "telegram",
        to: "telegram:101216939",
        accountId: "default",
      },
      config: { channels: { telegram: { botToken: "123:token" } } },
    },
    text: "SZ85-LWNTP",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: { message_id: 92, chat: { id: 101216939 } },
        }),
      };
    },
  });

  assert.deepEqual(result, {
    sent: true,
    channel: "telegram",
    chat_id: "101216939",
    message_id: "92",
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.telegram.org/bot123:token/sendMessage");
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual(body, {
    chat_id: "101216939",
    text: "SZ85-LWNTP",
  });
  // The bare-bubble path is deliberately keyboard-free — that's what
  // makes long-press → Copy on mobile capture only the code.
  assert.equal(body.reply_markup, undefined);
});

test("sendTelegramText refuses without text", async () => {
  const result = await sendTelegramText({
    toolContext: {
      deliveryContext: { channel: "telegram", to: "telegram:1" },
      config: { channels: { telegram: { botToken: "t" } } },
    },
    text: "",
    fetchImpl: async () => {
      throw new Error("should not send");
    },
  });
  assert.deepEqual(result, { sent: false, reason: "missing_text" });
});

test("photo and bare-text helpers skip non-telegram delivery contexts", async () => {
  const photoResult = await sendTelegramPhoto({
    toolContext: { deliveryContext: { channel: "slack" }, config: {} },
    photoUrl: PHOTO_URL,
    fetchImpl: async () => {
      throw new Error("should not send");
    },
  });
  assert.deepEqual(photoResult, {
    sent: false,
    reason: "not_telegram_delivery_context",
  });

  const textResult = await sendTelegramText({
    toolContext: { deliveryContext: { channel: "slack" }, config: {} },
    text: "abc",
    fetchImpl: async () => {
      throw new Error("should not send");
    },
  });
  assert.deepEqual(textResult, {
    sent: false,
    reason: "not_telegram_delivery_context",
  });
});

// NOTE: subscription photo / bare-code delivery-state claims are now
// owned by `finalizeSubscription*Reply` (outcome-aware: success vs
// failure recovery) — see test/subscription_flow.test.mjs. The generic
// `markTelegramDelivered` (Mini App button path) is covered above.
