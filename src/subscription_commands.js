import {
  buildSubscriptionLinkFailureReply,
  buildSubscriptionLinkReply,
  buildSubscriptionPrerequisiteHelpReply,
  buildSubscriptionRevertFailureReply,
  buildSubscriptionRevertReply,
  finalizeSubscriptionLinkReply,
  finalizeSubscriptionPrerequisiteHelpReply,
} from "./subscription_builders.js";
import {
  revertChatgptSubscriptionAuth,
  startChatgptSubscriptionLink,
} from "./subscriptions.js";
import {
  sendTelegramMiniAppButton,
  sendTelegramPhoto,
  sendTelegramText,
} from "./telegram_delivery.js";

export async function sendSubscriptionPrerequisiteHelpReply({
  api,
  toolContext,
  signal,
  fetchImpl,
}) {
  const reply = buildSubscriptionPrerequisiteHelpReply();
  const photoDelivery = await sendTelegramPhoto({
    api,
    toolContext,
    photoUrl: reply.channelData.telegram.photo_url,
    caption: reply.channelData.telegram.photo_caption,
    signal,
    fetchImpl,
  });
  // The finalizer is the only place delivery-state claims are made:
  // success -> "already sent"; failure -> recovery guidance.
  return finalizeSubscriptionPrerequisiteHelpReply(reply, photoDelivery);
}

export async function sendSubscriptionLinkReply({
  api,
  toolContext,
  session,
  signal,
  fetchImpl,
}) {
  const reply = buildSubscriptionLinkReply(session);
  // Send the URL-button intro first so the user sees the "Sign in to
  // ChatGPT" tap target right after the prerequisite walkthrough.
  const buttonDelivery = await sendTelegramMiniAppButton({
    api,
    toolContext,
    reply,
    text: reply.text,
    signal,
    fetchImpl,
  });
  // Only attempt the bare-code bubble when the button reached the user; a
  // lone code bubble with no verification button would just confuse them.
  let codeDelivery = { sent: false, reason: "skipped_button_not_sent" };
  if (buttonDelivery?.sent) {
    codeDelivery = await sendTelegramText({
      api,
      toolContext,
      text: reply.channelData?.telegram?.followup_text || session.userCode,
      signal,
      fetchImpl,
    });
  }
  return finalizeSubscriptionLinkReply(reply, {
    buttonDelivery,
    codeDelivery,
  });
}

export async function startAndSendSubscriptionLinkReply({
  callTinyhat,
  api,
  toolContext,
  signal,
  fetchImpl,
}) {
  try {
    const session = await startChatgptSubscriptionLink({
      callTinyhat,
      signal,
    });
    return sendSubscriptionLinkReply({
      api,
      toolContext,
      session,
      signal,
      fetchImpl,
    });
  } catch (err) {
    return buildSubscriptionLinkFailureReply(err);
  }
}

export async function buildSubscriptionRevertCommandReply({
  callTinyhat,
  signal,
}) {
  try {
    return buildSubscriptionRevertReply(
      await revertChatgptSubscriptionAuth({ callTinyhat, signal }),
    );
  } catch (err) {
    return buildSubscriptionRevertFailureReply(err);
  }
}

export async function handleSubscriptionCommand({
  api,
  ctx = {},
  callTinyhat,
  signal,
  fetchImpl,
}) {
  const parsed = parseSubscriptionCommand(ctx.args || "");
  if (parsed.action === "help") {
    return { text: subscriptionCommandUsage().usage.join("\n") };
  }
  if (parsed.action === "prerequisite") {
    return sendSubscriptionPrerequisiteHelpReply({
      api,
      toolContext: ctx,
      signal,
      fetchImpl,
    });
  }
  if (parsed.action === "revert") {
    return buildSubscriptionRevertCommandReply({ callTinyhat, signal });
  }
  return startAndSendSubscriptionLinkReply({
    callTinyhat,
    api,
    toolContext: ctx,
    signal,
    fetchImpl,
  });
}

export function parseSubscriptionCommand(raw) {
  const text = normalizeString(raw).toLowerCase();
  if (!text || ["help", "-h", "--help"].includes(text)) {
    return { action: "help" };
  }
  const verb = text.split(/\s+/)[0];
  if (
    [
      "before",
      "enable",
      "help",
      "prereq",
      "prerequisite",
      "security",
      "settings",
      "setup",
    ].includes(verb)
  ) {
    return { action: "prerequisite" };
  }
  if (
    [
      "back",
      "credits",
      "disconnect",
      "platform",
      "platform-credits",
      "revert",
      "stop",
      "unlink",
    ].includes(verb)
  ) {
    return { action: "revert" };
  }
  if (
    [
      "chatgpt",
      "codex",
      "connect",
      "link",
      "login",
      "openai",
      "signin",
      "sign-in",
      "start",
      "subscription",
    ].includes(verb)
  ) {
    return { action: "link" };
  }
  return { action: "help" };
}

export function subscriptionCommandUsage() {
  return {
    ok: false,
    usage: [
      "Tinyhat ChatGPT subscription:",
      "/tinyhat_subscriptions prerequisite",
      "/tinyhat_subscriptions link",
      "/tinyhat_subscriptions revert",
      "",
      "Never share your ChatGPT password or OAuth token in chat.",
    ],
  };
}

function normalizeString(value) {
  return String(value || "").trim();
}
