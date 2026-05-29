function resolveTelegramSendContext({ api, toolContext }) {
  const deliveryContext = toolContext?.deliveryContext;
  if (deliveryContext?.channel !== "telegram") {
    return { ok: false, reason: "not_telegram_delivery_context" };
  }
  const chatId = telegramChatIdFromDeliveryContext(deliveryContext, toolContext);
  const token = telegramBotTokenFromConfig(
    toolContext?.getRuntimeConfig?.() ||
      toolContext?.runtimeConfig ||
      toolContext?.config ||
      api?.config,
    deliveryContext?.accountId,
  );
  if (!chatId || !token) {
    return {
      ok: false,
      reason: chatId ? "missing_telegram_bot_token" : "missing_telegram_chat_id",
    };
  }
  return { ok: true, chatId, token, deliveryContext };
}

export async function sendTelegramMiniAppButton({
  api,
  toolContext,
  reply,
  text,
  signal,
  fetchImpl = globalThis.fetch,
}) {
  const buttons = reply?.channelData?.telegram?.buttons;
  if (!Array.isArray(buttons) || buttons.length === 0) {
    return { sent: false, reason: "missing_button_payload" };
  }

  const ctx = resolveTelegramSendContext({ api, toolContext });
  if (!ctx.ok) {
    return { sent: false, reason: ctx.reason };
  }

  const response = await fetchImpl(
    `https://api.telegram.org/bot${ctx.token}/sendMessage`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: ctx.chatId,
        text: String(text || "Open the Telegram Mini App button."),
        ...(ctx.deliveryContext?.threadId
          ? { message_thread_id: Number(ctx.deliveryContext.threadId) }
          : {}),
        reply_markup: { inline_keyboard: buttons },
      }),
      signal,
    },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok !== true) {
    return {
      sent: false,
      reason: "telegram_send_failed",
      status: response.status,
      error_code: payload?.error_code,
      description: payload?.description,
    };
  }

  return {
    sent: true,
    channel: "telegram",
    chat_id: String(payload.result?.chat?.id || ctx.chatId),
    message_id: String(payload.result?.message_id || ""),
  };
}

/**
 * Send a Telegram photo by URL, with an optional caption (#108). Uses the
 * same chat-id / bot-token resolution as `sendTelegramMiniAppButton` so
 * callers can fan out (button → photo → bare-code) in one tool call and
 * share the same skip-reason semantics on non-Telegram channels.
 *
 * `photoUrl` is a public HTTPS URL Telegram can fetch (e.g. the canonical
 * settings-screenshot at this repo's `assets/`); Telegram's `sendPhoto`
 * does the actual file pull. Returns the same `{sent, reason?, ...}`
 * shape as the button sender.
 */
export async function sendTelegramPhoto({
  api,
  toolContext,
  photoUrl,
  caption,
  signal,
  fetchImpl = globalThis.fetch,
}) {
  if (!photoUrl || typeof photoUrl !== "string") {
    return { sent: false, reason: "missing_photo_url" };
  }
  const ctx = resolveTelegramSendContext({ api, toolContext });
  if (!ctx.ok) {
    return { sent: false, reason: ctx.reason };
  }

  const captionText = caption ? String(caption).slice(0, 1024) : undefined;
  const response = await fetchImpl(
    `https://api.telegram.org/bot${ctx.token}/sendPhoto`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: ctx.chatId,
        photo: photoUrl,
        ...(captionText ? { caption: captionText } : {}),
        ...(ctx.deliveryContext?.threadId
          ? { message_thread_id: Number(ctx.deliveryContext.threadId) }
          : {}),
      }),
      signal,
    },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok !== true) {
    return {
      sent: false,
      reason: "telegram_send_failed",
      status: response.status,
      error_code: payload?.error_code,
      description: payload?.description,
    };
  }
  return {
    sent: true,
    channel: "telegram",
    chat_id: String(payload.result?.chat?.id || ctx.chatId),
    message_id: String(payload.result?.message_id || ""),
  };
}

/**
 * Send a plain-text Telegram message — no inline keyboard, no buttons —
 * intended for "follow-up bubble" sends like the bare device-code drop
 * after the URL-button intro on the subscription link flow (#108). The
 * bare bubble lets the user long-press → Copy to grab only the code on
 * mobile Telegram.
 */
export async function sendTelegramText({
  api,
  toolContext,
  text,
  signal,
  fetchImpl = globalThis.fetch,
}) {
  if (!text || typeof text !== "string") {
    return { sent: false, reason: "missing_text" };
  }
  const ctx = resolveTelegramSendContext({ api, toolContext });
  if (!ctx.ok) {
    return { sent: false, reason: ctx.reason };
  }

  const response = await fetchImpl(
    `https://api.telegram.org/bot${ctx.token}/sendMessage`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: ctx.chatId,
        text: String(text).slice(0, 4000),
        ...(ctx.deliveryContext?.threadId
          ? { message_thread_id: Number(ctx.deliveryContext.threadId) }
          : {}),
      }),
      signal,
    },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok !== true) {
    return {
      sent: false,
      reason: "telegram_send_failed",
      status: response.status,
      error_code: payload?.error_code,
      description: payload?.description,
    };
  }
  return {
    sent: true,
    channel: "telegram",
    chat_id: String(payload.result?.chat?.id || ctx.chatId),
    message_id: String(payload.result?.message_id || ""),
  };
}

export function markTelegramDelivered(reply, delivery) {
  if (!delivery?.sent) {
    return reply;
  }
  const { channelData: _channelData, ...safeReply } = reply || {};
  return {
    ...safeReply,
    telegram_delivery: delivery,
    delivered: true,
    agent_instructions: [
      ...(Array.isArray(reply?.agent_instructions) ? reply.agent_instructions : []),
      "The Telegram Mini App button has already been sent directly. Do not call the message tool for this button, and never print the Mini App URL.",
    ],
  };
}

/**
 * Wrap a reply that was delivered as a Telegram **photo** (e.g. the
 * canonical screenshot for the ChatGPT-subscription prerequisite, #108).
 * The agent must not re-send the same photo or paste the photo URL into
 * chat — the plugin already delivered it.
 */
export function markTelegramPhotoDelivered(reply, delivery) {
  if (!delivery?.sent) {
    return reply;
  }
  return {
    ...(reply || {}),
    telegram_photo_delivery: delivery,
    photo_delivered: true,
    agent_instructions: [
      ...(Array.isArray(reply?.agent_instructions) ? reply.agent_instructions : []),
      "The illustrative photo has already been sent directly to the user via Telegram. Do not re-send it, do not paste the image URL, and do not describe the photo as if the user might not have seen it.",
    ],
  };
}

/**
 * Wrap a reply that has already had its **device code** (or any other
 * bare-text follow-up bubble) sent via Telegram (#108). Lets the agent
 * know that a second bubble was delivered after the main button reply so
 * it doesn't duplicate or paraphrase the value in its own free-text turn.
 */
export function markTelegramCodeDelivered(reply, delivery) {
  if (!delivery?.sent) {
    return reply;
  }
  return {
    ...(reply || {}),
    telegram_code_delivery: delivery,
    code_delivered: true,
    agent_instructions: [
      ...(Array.isArray(reply?.agent_instructions) ? reply.agent_instructions : []),
      "The 9-character device code has already been sent as its own bare Telegram message bubble so the user can long-press → Copy to grab it cleanly. Do not re-paste the code in your own free-text reply.",
    ],
  };
}

export function telegramChatIdFromDeliveryContext(deliveryContext, toolContext) {
  const raw =
    deliveryContext?.to ||
    deliveryContext?.chatId ||
    toolContext?.requesterSenderId ||
    "";
  const text = String(raw || "").trim();
  if (!text) return "";
  return text.startsWith("telegram:") ? text.slice("telegram:".length) : text;
}

export function telegramBotTokenFromConfig(config, accountId = "default") {
  const telegram = config?.channels?.telegram || {};
  const account =
    telegram?.accounts && accountId ? telegram.accounts[String(accountId)] : null;
  return String(account?.botToken || telegram?.botToken || "").trim();
}
