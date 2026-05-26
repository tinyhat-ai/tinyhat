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

  const deliveryContext = toolContext?.deliveryContext;
  if (deliveryContext?.channel !== "telegram") {
    return { sent: false, reason: "not_telegram_delivery_context" };
  }

  const chatId = telegramChatIdFromDeliveryContext(deliveryContext, toolContext);
  const token = telegramBotTokenFromConfig(
    toolContext?.getRuntimeConfig?.() || toolContext?.runtimeConfig || toolContext?.config || api?.config,
    deliveryContext?.accountId,
  );
  if (!chatId || !token) {
    return { sent: false, reason: chatId ? "missing_telegram_bot_token" : "missing_telegram_chat_id" };
  }

  const response = await fetchImpl(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text: String(text || "Open the Telegram Mini App button."),
      ...(deliveryContext?.threadId
        ? { message_thread_id: Number(deliveryContext.threadId) }
        : {}),
      reply_markup: { inline_keyboard: buttons },
    }),
    signal,
  });
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
    chat_id: String(payload.result?.chat?.id || chatId),
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
