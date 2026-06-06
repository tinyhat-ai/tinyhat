// ChatGPT BYO subscription chat-tool reply builders + finalizers.
//
// Kept separate from `src/index.js` so the test suite can import + pin
// the reply shapes directly (the `index.js` plugin entrypoint is the
// OpenClaw registration surface, not a library). Constants — including
// the canonical security-settings screenshot URL — live here too;
// `skills/*/SKILL.md` cannot contain raw URLs per the package validator,
// so the URL stays in `src/`.
//
// Two-layer shape (Codex P1, #109 review):
//   1. `build*Reply()` produces a NEUTRAL reply — it makes NO claim that
//      anything was delivered. Its `agent_instructions` and `text` are
//      correct even if every Telegram send fails.
//   2. `finalize*Reply(reply, delivery)` runs AFTER the Telegram sends
//      and is the ONLY place delivery-state claims are made: on success
//      it adds "already sent / do not resend"; on failure it adds a
//      concrete recovery instruction (and, for the link, keeps the
//      device code reachable so the agent can paste it).
// Builders never assert delivery, so a `{ sent: false }` result can
// never leave a stale "already sent" claim in the tool result.

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

// Plain, self-contained walkthrough — makes NO claim that a screenshot
// was shown, so it stays correct when the photo send fails. The success
// finalizer swaps in the screenshot-referencing variant below.
export const SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT =
  "Before I start the link, OpenAI needs you to enable device-code " +
  "sign-in on your ChatGPT account once. On chatgpt.com → Settings → " +
  "Security → Secure sign in with ChatGPT, turn on “Enable device code " +
  "authorization for Codex”, then tell me when it's on and I'll start " +
  "the link.\n\n" +
  "Personal accounts can flip the toggle directly. Team / Business / " +
  "Enterprise: the toggle is workspace-admin-only — if it's greyed out, " +
  "ask the workspace admin to enable it.";

// Used by the success finalizer only (we know the photo landed, so the
// "I just sent" reference is accurate).
export const SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT_WITH_SCREENSHOT =
  "Before I start the link, OpenAI needs you to enable device-code " +
  "sign-in on your ChatGPT account once — the screenshot I just sent " +
  "shows the exact toggle. On chatgpt.com → Settings → Security → " +
  "Secure sign in with ChatGPT, turn on “Enable device code " +
  "authorization for Codex”, then tell me when it's on and I'll start " +
  "the link.\n\n" +
  "Personal accounts can flip the toggle directly. Team / Business / " +
  "Enterprise: the toggle is workspace-admin-only — if it's greyed out, " +
  "ask the workspace admin to enable it.";

// Base (pre-delivery) instructions — neutral; assert nothing about what
// was delivered.
export const SUBSCRIPTION_PREREQUISITE_BASE_AGENT_INSTRUCTIONS = [
  "Forward the walkthrough text to the user via `reply_via_telegram`.",
  "Do not call `tinyhat_open_chatgpt_subscription_link` until the user confirms the device-code toggle is on; otherwise the linking attempt fails with the disabled-device-code error.",
];

export const SUBSCRIPTION_LINK_BASE_AGENT_INSTRUCTIONS = [
  "Never paste any URL, query parameter, signed token, OAuth token, or secret value in chat other than the 9-character device code — the device code is the only paste-able non-secret string in this flow.",
  "The OpenAI verification URL is the v0.5 'no raw URLs in chat' exemption and reaches the user only through the inline-keyboard button; never paste it as text.",
];

/**
 * Pre-link prerequisite help reply (#108). NEUTRAL — the plain
 * walkthrough text makes no claim that a screenshot was shown. The tool
 * body sends the screenshot via Telegram photo, then calls
 * `finalizeSubscriptionPrerequisiteHelpReply` with the delivery result.
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
    agent_instructions: SUBSCRIPTION_PREREQUISITE_BASE_AGENT_INSTRUCTIONS,
  };
}

/**
 * Finalize the prerequisite-help reply with the real photo-send outcome
 * (Codex P1, #109). On success: swap to the screenshot-referencing text
 * and add the "already sent / do not resend" guidance. On failure: keep
 * the plain text and add a recovery instruction that explicitly tells the
 * agent NOT to claim a screenshot was shown and to convey the steps in
 * words instead.
 */
export function finalizeSubscriptionPrerequisiteHelpReply(reply, photoDelivery) {
  const base = reply || {};
  const baseInstructions = Array.isArray(base.agent_instructions)
    ? base.agent_instructions
    : [];
  if (photoDelivery?.sent) {
    return {
      ...base,
      text: SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT_WITH_SCREENSHOT,
      photo_delivered: true,
      telegram_photo_delivery: photoDelivery,
      agent_instructions: [
        ...baseInstructions,
        "The ChatGPT security-settings screenshot has already been sent to the user via Telegram photo. Do not re-send the photo, do not paste the image URL into chat, and do not describe the screenshot as if the user might not have seen it.",
        "Acknowledge briefly that you've shared the screenshot above, then forward the walkthrough text via `reply_via_telegram`.",
      ],
    };
  }
  return {
    ...base,
    text: SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT,
    photo_delivered: false,
    telegram_photo_delivery: photoDelivery || { sent: false },
    agent_instructions: [
      ...baseInstructions,
      "The settings screenshot could NOT be delivered to the user. Do not tell the user to look at a screenshot. Instead, walk them through the steps in your own `reply_via_telegram` message: on chatgpt.com open Settings → Security → Secure sign in with ChatGPT and turn on “Enable device code authorization for Codex”.",
    ],
  };
}

/**
 * Link-success base reply (#108). NEUTRAL — URL+button intro in `text`,
 * bare device code in `channelData.telegram.followup_text`. Asserts no
 * delivery. The tool body sends the URL+button message, then the bare
 * code bubble, then calls `finalizeSubscriptionLinkReply` with both
 * outcomes.
 */
export function buildSubscriptionLinkReply({ verificationUrl, userCode }) {
  return {
    action: "subscriptions.open_link",
    // The device code intentionally does NOT appear in `text` — it lands
    // as its own bare-bubble follow-up so long-press → Copy captures only
    // the code on mobile.
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
    agent_instructions: SUBSCRIPTION_LINK_BASE_AGENT_INSTRUCTIONS,
  };
}

/**
 * Finalize the link reply with the real URL-button + bare-code-bubble
 * send outcomes (Codex P1, #109). The transport `channelData` is always
 * stripped so the raw verification URL / button payload never reaches the
 * agent. Three outcomes:
 *
 *   - button NOT sent → the user can't reach the verification page; tell
 *     them to retry (the backend device-code session is idempotent, so a
 *     retry reuses it). `delivered: false`.
 *   - button sent + code sent → happy path; "already sent, don't resend".
 *     `delivered: true, code_delivered: true`.
 *   - button sent + code NOT sent → the button message already told the
 *     user to expect the code in a follow-up, so the agent must supply it:
 *     paste the code from `user_code` (kept on the reply). `delivered:
 *     true, code_delivered: false`.
 */
export function finalizeSubscriptionLinkReply(
  reply,
  { buttonDelivery, codeDelivery } = {},
) {
  const base = reply || {};
  const baseInstructions = Array.isArray(base.agent_instructions)
    ? base.agent_instructions
    : [];
  // Never surface the transport button payload / verification URL button
  // to the agent, regardless of outcome.
  const {
    channelData: _channelData,
    verification_url: _verificationUrl,
    ...withoutTransportData
  } = base;
  const buttonSent = !!buttonDelivery?.sent;
  const codeSent = !!codeDelivery?.sent;

  if (!buttonSent) {
    return {
      ...withoutTransportData,
      delivered: false,
      code_delivered: codeSent,
      telegram_delivery: buttonDelivery || { sent: false },
      telegram_code_delivery: codeDelivery || { sent: false },
      agent_instructions: [
        ...baseInstructions,
        "The “Sign in to ChatGPT” button could NOT be delivered to the user, so they have no way to open the verification page. Tell the user the link couldn't be started right now and ask them to say “connect my ChatGPT subscription” again to retry. Do not paste the verification URL into chat.",
      ],
    };
  }

  if (codeSent) {
    return {
      ...withoutTransportData,
      delivered: true,
      code_delivered: true,
      telegram_delivery: buttonDelivery,
      telegram_code_delivery: codeDelivery,
      agent_instructions: [
        ...baseInstructions,
        "The “Sign in to ChatGPT” URL button has already been sent to the user directly. Do not re-render the button or paste the verification URL into chat.",
        "The 9-character device code has already been sent as its own bare Telegram message bubble so the user can long-press → Copy to grab only the code on mobile. Do not re-paste the code in your own free-text reply.",
      ],
    };
  }

  // Button sent, code bubble failed — the button message already told the
  // user to paste the code from the next message, so the agent must
  // supply it. The device code is the one paste-able non-secret value in
  // this flow, so re-pasting it here is allowed.
  return {
    ...withoutTransportData,
    delivered: true,
    code_delivered: false,
    telegram_delivery: buttonDelivery,
    telegram_code_delivery: codeDelivery || { sent: false },
    agent_instructions: [
      ...baseInstructions,
      "The “Sign in to ChatGPT” URL button has already been sent to the user directly. Do not re-render the button or paste the verification URL into chat.",
      "The bare device-code bubble could NOT be sent, but the button message already told the user to paste the code from the next message. Reply now with the 9-character device code from the `user_code` field of this result so the user still receives it — the device code is the only paste-able non-secret value in this flow.",
    ],
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
