// ChatGPT BYO subscription chat-tool reply builders.
//
// Kept separate from `src/index.js` so the test suite can import + pin
// the reply shapes directly (the `index.js` plugin entrypoint is the
// OpenClaw registration surface, not a library). Constants — including
// the canonical security-settings screenshot URL — live here too;
// `skills/*/SKILL.md` cannot contain raw URLs per the package validator,
// so the URL stays in `src/`.
//
// Builders are pure: they take the platform-returned session shape and
// return the tool reply object. Telegram delivery side-effects (photo +
// URL button + bare-code follow-up) happen in the tool execute() body in
// `index.js`, fed by the `channelData.telegram.*` fields produced here.

/**
 * Canonical raw-GitHub URL for the ChatGPT security-settings screenshot
 * the user must match to enable device-code authorization (#108). The
 * plugin sends this via Telegram `sendPhoto` directly so the user can
 * spot the toggle visually instead of scanning the long ChatGPT
 * settings page from text alone.
 */
export const SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL =
  "https://raw.githubusercontent.com/tinyhat-ai/tinyhat/main/skills/tinyhat-subscriptions/assets/chatgpt-enable-device-code-for-codex.png";

export const SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION =
  "ChatGPT Security — toggle “Enable device code authorization for Codex” on.";

export const SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT =
  "Before I start the link, OpenAI needs you to enable device-code " +
  "sign-in on your ChatGPT account once (the screenshot above shows the " +
  "exact toggle). On chatgpt.com → Settings → Security → Secure sign in " +
  "with ChatGPT, turn on “Enable device code authorization for Codex”, " +
  "then tell me when it's on and I'll start the link.\n\n" +
  "Personal accounts can flip the toggle directly. Team / Business / " +
  "Enterprise: the toggle is workspace-admin-only — if it's greyed out, " +
  "ask the workspace admin to enable it.";

export const SUBSCRIPTION_PREREQUISITE_AGENT_INSTRUCTIONS = [
  "The illustrative ChatGPT security-settings screenshot has already been sent to the user via Telegram photo. Do not re-send the photo, do not paste the image URL into chat, and do not describe the screenshot as if the user might not have seen it.",
  "Send the prerequisite walkthrough text to the user via `reply_via_telegram`. Acknowledge briefly that you've shared the screenshot above and that you'll start the link as soon as they confirm the toggle is on.",
  "Do not call `tinyhat_open_chatgpt_subscription_link` until the user confirms the toggle is on; otherwise the linking attempt will fail with the disabled-device-code error.",
];

export const SUBSCRIPTION_AGENT_INSTRUCTIONS = [
  "The OpenAI verification URL has already been sent to the user as a Telegram inline-keyboard URL button targeting auth.openai.com — do not paste or re-render the URL in chat. The 9-character device code has been sent as its own bare Telegram message bubble so the user can long-press → Copy to grab only the code on mobile.",
  "Acknowledge briefly in chat that you've started the link, point at the “Sign in to ChatGPT” button, and remind the user the code (which they already see as the bare bubble) expires in about 15 minutes. Do not re-paste the device code in your own free-text reply.",
  "Never paste any other URL, query parameter, signed token, OAuth token, or secret value in chat.",
  "The OpenAI verification URL is the v0.5 'no raw URLs in chat' exemption; the device code is the only paste-able non-secret string the owner is asked to handle.",
];

/**
 * Pre-link prerequisite help reply (#108). Pairs with the
 * `tinyhat_open_chatgpt_subscription_prerequisite_help` tool body: the
 * tool sends the screenshot via Telegram photo BEFORE this reply lands,
 * so the agent's job is just to forward the walkthrough text.
 */
export function buildSubscriptionPrerequisiteHelpReply() {
  return {
    action: "subscriptions.open_prerequisite_help",
    text: SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT,
    channelData: {
      telegram: {
        photo_url: SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
        photo_caption: SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION,
      },
    },
    agent_instructions: SUBSCRIPTION_PREREQUISITE_AGENT_INSTRUCTIONS,
  };
}

/**
 * Link-success reply: URL+button intro in `text`, bare device code in
 * `channelData.telegram.followup_text` (#108). The tool body sends the
 * URL+button message first, then the bare code as its own bubble so the
 * user can long-press → Copy on mobile to grab only the code.
 */
export function buildSubscriptionLinkReply({ verificationUrl, userCode }) {
  return {
    action: "subscriptions.open_link",
    // The device code intentionally does NOT appear in `text` — it
    // lands as its own bare-bubble follow-up so long-press → Copy
    // captures only the code on mobile.
    text:
      "Sign in to ChatGPT to connect your subscription. Tap the button " +
      "below to open auth.openai.com on a device you're signed in to, " +
      "then paste the device code from the next message. The code " +
      "expires in about 15 minutes — never share it.",
    verification_url: verificationUrl,
    user_code: userCode,
    channelData: {
      telegram: {
        buttons: [[{ text: "Sign in to ChatGPT", url: verificationUrl }]],
        followup_text: userCode,
      },
    },
    agent_instructions: SUBSCRIPTION_AGENT_INSTRUCTIONS,
  };
}

export function buildSubscriptionLinkFailureReply(err) {
  const message = String(
    err?.message || err || "Subscription linking failed.",
  ).slice(0, 1023);
  return {
    ok: false,
    action: "subscriptions.open_link",
    text:
      "I couldn't start the ChatGPT subscription login. " +
      "Check that 'Enable device code authorization for Codex' is on in your " +
      "ChatGPT security settings, then ask me to try again. If you'd like " +
      "to see the toggle, ask me to walk you through it again.",
    error: message,
    agent_instructions: [
      "Surface the platform's non-secret reason verbatim if it explains the failure.",
      "If the failure looks like the device-code prerequisite is not enabled (the platform reports a 'device-code login disabled' style reason), call `tinyhat_open_chatgpt_subscription_prerequisite_help` again so the user sees the screenshot inline rather than just the error text.",
      "Never request the user's password, OAuth token, or any credential in chat.",
    ],
  };
}

export function buildSubscriptionRevertReply({ alreadyOnPlatformCredits }) {
  if (alreadyOnPlatformCredits) {
    return {
      action: "subscriptions.revert_to_platform_credits",
      text:
        "This Computer was already on Tinyhat-funded credits — nothing to revert.",
      idempotent: true,
    };
  }
  // Deliberately no `removed_profiles` / OAuth account email / profile
  // id in this reply — those would leak the user's ChatGPT account
  // identifier into the chat surface, which the operation's
  // declared `metadata_only_tool_result` userSurface forbids.
  return {
    action: "subscriptions.revert_to_platform_credits",
    text:
      "Done — you're now back on Tinyhat-funded credits. Your ChatGPT " +
      "subscription is no longer linked to this Computer.",
    idempotent: false,
  };
}

export function buildSubscriptionRevertFailureReply(err) {
  const message = String(
    err?.message || err || "Subscription revert failed.",
  ).slice(0, 1023);
  return {
    ok: false,
    action: "subscriptions.revert_to_platform_credits",
    text:
      "I couldn't revert this Computer to Tinyhat-funded credits. " +
      "Try again in a moment.",
    error: message,
  };
}
