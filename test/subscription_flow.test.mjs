// Usage:
//   node --test test/subscription_flow.test.mjs

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  SUBSCRIPTION_LINK_BASE_AGENT_INSTRUCTIONS,
  SUBSCRIPTION_PREREQUISITE_BASE_AGENT_INSTRUCTIONS,
  SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION,
  SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
  SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT,
  SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT_WITH_SCREENSHOT,
  buildSubscriptionLinkFailureReply,
  buildSubscriptionLinkReply,
  buildSubscriptionPrerequisiteHelpReply,
  buildSubscriptionRevertReply,
  finalizeSubscriptionLinkReply,
  finalizeSubscriptionPrerequisiteHelpReply,
} from "../src/subscription_builders.js";
import {
  CHATGPT_LINK_POLL_TIMEOUT_MS,
  startChatgptSubscriptionLink,
} from "../src/subscriptions.js";
import { jsonToolResult } from "../src/tool_results.js";

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const ALREADY_SENT = /already (been )?sent/i;

function collectOpenClawTextContent(result) {
  return result.content.reduce((chunks, item) => {
    if (item?.type === "text" && typeof item.text === "string") {
      chunks.push(item.text);
    }
    return chunks;
  }, []).join("\n");
}

// ── Platform/runtime polling budget ──────────────────────────────────

test("chatgpt link default polling budget covers heartbeat plus retry latency", () => {
  assert.ok(
    CHATGPT_LINK_POLL_TIMEOUT_MS >= 90_000,
    "chat-triggered link must wait through supervisor heartbeat skew and runtime retry",
  );
  assert.ok(
    CHATGPT_LINK_POLL_TIMEOUT_MS > 15_000,
    "regression guard: 15s timed out before real local Computers posted URL+code",
  );
});

test("chatgpt link helper keeps polling until the supervisor posts URL and code", async () => {
  const paths = [];
  let statusCalls = 0;

  const result = await startChatgptSubscriptionLink({
    pollIntervalMs: 1,
    pollTimeoutMs: 200,
    callTinyhat: async (path) => {
      paths.push(path);
      if (path.endsWith("/subscription-link/start")) {
        return { status: "pending", session_id: "session-1" };
      }
      assert.ok(path.endsWith("/subscription-link/status"));
      statusCalls += 1;
      if (statusCalls < 8) {
        return {
          status: "pending",
          pending_session: { session_id: "session-1" },
        };
      }
      return {
        status: "pending",
        pending_session: {
          session_id: "session-1",
          verification_url: "https://auth.openai.com/verify",
          user_code: "ABCD-EFGHI",
        },
      };
    },
  });

  assert.deepEqual(result, {
    verificationUrl: "https://auth.openai.com/verify",
    userCode: "ABCD-EFGHI",
  });
  assert.equal(paths[0], "/hapi/v1/computers/me/subscription-link/start");
  assert.equal(statusCalls, 8);
});

// ── Base builders are NEUTRAL — they must never claim delivery ─────────
// (Codex P1, #109: a `{ sent: false }` result must never leave a stale
// "already sent" claim, so the builders that run BEFORE delivery cannot
// contain that language at all.)

test("prerequisite-help BASE reply makes no delivery claim and uses the plain text", () => {
  const reply = buildSubscriptionPrerequisiteHelpReply();

  assert.equal(reply.action, "subscriptions.open_prerequisite_help");
  // Plain, self-contained text — no "screenshot above" reference, so it
  // is correct even if the photo send fails.
  assert.equal(reply.text, SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT);
  assert.ok(
    !/screenshot/i.test(reply.text),
    "base walkthrough text must not reference a screenshot",
  );
  assert.match(reply.text, /enable device-code/i);
  assert.match(reply.text, /workspace admin/i);

  assert.deepEqual(reply.channelData, {
    telegram: {
      photo_url: SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
      photo_caption: SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION,
    },
  });

  assert.deepEqual(
    reply.agent_instructions,
    SUBSCRIPTION_PREREQUISITE_BASE_AGENT_INSTRUCTIONS,
  );
  for (const line of reply.agent_instructions) {
    assert.ok(
      !ALREADY_SENT.test(line),
      `base prerequisite instruction must not claim delivery: ${line}`,
    );
  }
});

test("link BASE reply makes no delivery claim, hides the code from text, carries it for the follow-up", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/verify",
    userCode: "SZ85-LWNTP",
  });

  assert.equal(reply.action, "subscriptions.open_link");
  assert.equal(reply.verification_url, "https://auth.openai.com/verify");
  assert.equal(reply.user_code, "SZ85-LWNTP");

  // The whole point of #108 — the code must NOT leak into the main bubble.
  assert.ok(
    !reply.text.includes("SZ85-LWNTP"),
    "main text must not include the device code (bare-bubble path)",
  );
  assert.match(reply.text, /paste the device code from the next message/i);

  assert.deepEqual(reply.channelData.telegram.buttons, [
    [{ text: "Sign in to ChatGPT", url: "https://auth.openai.com/verify" }],
  ]);
  assert.equal(reply.channelData.telegram.followup_text, "SZ85-LWNTP");

  assert.deepEqual(
    reply.agent_instructions,
    SUBSCRIPTION_LINK_BASE_AGENT_INSTRUCTIONS,
  );
  for (const line of reply.agent_instructions) {
    assert.ok(
      !ALREADY_SENT.test(line),
      `base link instruction must not claim delivery: ${line}`,
    );
  }
});

// ── Prerequisite finalizer — success vs failure ───────────────────────

test("prerequisite finalizer SUCCESS swaps in the screenshot text + 'already sent' guidance", () => {
  const reply = buildSubscriptionPrerequisiteHelpReply();
  const final = finalizeSubscriptionPrerequisiteHelpReply(reply, {
    sent: true,
    channel: "telegram",
    chat_id: "1",
    message_id: "91",
  });

  assert.equal(final.photo_delivered, true);
  assert.equal(final.telegram_photo_delivery.message_id, "91");
  // Text now references the screenshot we KNOW landed.
  assert.equal(final.text, SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT_WITH_SCREENSHOT);
  assert.match(final.text, /screenshot I just sent/i);
  // The "already sent / do not resend" claim appears only here.
  assert.ok(
    final.agent_instructions.some(
      (l) => ALREADY_SENT.test(l) && /do not re-?send|do not paste the image/i.test(l),
    ),
    "success path must add the 'already sent, do not resend' instruction",
  );
});

test("prerequisite finalizer FAILURE keeps plain text, adds recovery, makes NO 'already sent' claim", () => {
  const reply = buildSubscriptionPrerequisiteHelpReply();
  const final = finalizeSubscriptionPrerequisiteHelpReply(reply, {
    sent: false,
    reason: "telegram_send_failed",
  });

  assert.equal(final.photo_delivered, false);
  // Plain text — must not claim a screenshot was shown.
  assert.equal(final.text, SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT);
  assert.ok(!/screenshot I just sent/i.test(final.text));
  for (const line of final.agent_instructions) {
    assert.ok(
      !ALREADY_SENT.test(line),
      `failure path must not claim the photo was sent: ${line}`,
    );
  }
  // Recovery: tell the agent NOT to claim a screenshot + convey steps in words.
  assert.ok(
    final.agent_instructions.some(
      (l) => /could NOT be delivered/i.test(l) && /Settings → Security/i.test(l),
    ),
    "failure path must add a recovery instruction with the manual steps",
  );
});

test("prerequisite finalizer treats a null/undefined delivery as failure", () => {
  const reply = buildSubscriptionPrerequisiteHelpReply();
  const final = finalizeSubscriptionPrerequisiteHelpReply(reply, undefined);
  assert.equal(final.photo_delivered, false);
  assert.deepEqual(final.telegram_photo_delivery, { sent: false });
});

// ── Link finalizer — the three real outcomes ──────────────────────────

test("link finalizer HAPPY (button + code both sent) strips channelData and adds both 'already sent' lines", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/verify",
    userCode: "SZ85-LWNTP",
  });
  const final = finalizeSubscriptionLinkReply(reply, {
    buttonDelivery: { sent: true, message_id: "10" },
    codeDelivery: { sent: true, message_id: "11" },
  });

  assert.equal(final.delivered, true);
  assert.equal(final.code_delivered, true);
  // Transport payload (raw verification URL button) never reaches the agent.
  assert.equal(final.channelData, undefined);
  assert.ok(
    final.agent_instructions.some((l) => /URL button has already been sent/i.test(l)),
  );
  assert.ok(
    final.agent_instructions.some(
      (l) => /bare Telegram message bubble/i.test(l) && /long-press/i.test(l),
    ),
  );
  assert.ok(
    final.agent_instructions.some((l) => /do not re-?paste the code/i.test(l)),
  );
});

test("link finalizer BUTTON-OK / CODE-FAIL tells the agent to paste the code, never claims the code was sent", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/verify",
    userCode: "SZ85-LWNTP",
  });
  const final = finalizeSubscriptionLinkReply(reply, {
    buttonDelivery: { sent: true, message_id: "10" },
    codeDelivery: { sent: false, reason: "telegram_send_failed" },
  });

  assert.equal(final.delivered, true);
  assert.equal(final.code_delivered, false);
  assert.equal(final.channelData, undefined);
  // The code must still be reachable so the agent can paste it.
  assert.equal(final.user_code, "SZ85-LWNTP");
  // Button claim is fine (it WAS sent); the code claim must NOT say "sent".
  assert.ok(
    final.agent_instructions.some((l) => /URL button has already been sent/i.test(l)),
  );
  assert.ok(
    !final.agent_instructions.some((l) =>
      /code has already been sent as its own bare/i.test(l),
    ),
    "must not claim the code bubble was sent when it failed",
  );
  // Recovery: paste the code now from user_code.
  assert.ok(
    final.agent_instructions.some(
      (l) => /could NOT be sent/i.test(l) && /user_code/.test(l),
    ),
    "must instruct the agent to paste the code from user_code",
  );
});

test("link finalizer BUTTON-FAIL asks the user to retry and never claims any delivery", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/verify",
    userCode: "SZ85-LWNTP",
  });
  const final = finalizeSubscriptionLinkReply(reply, {
    buttonDelivery: { sent: false, reason: "missing_telegram_bot_token" },
    codeDelivery: { sent: false, reason: "skipped_button_not_sent" },
  });

  assert.equal(final.delivered, false);
  assert.equal(final.code_delivered, false);
  assert.equal(final.channelData, undefined);
  for (const line of final.agent_instructions) {
    assert.ok(
      !ALREADY_SENT.test(line),
      `button-fail path must not claim any delivery: ${line}`,
    );
  }
  assert.ok(
    final.agent_instructions.some(
      (l) => /could NOT be delivered/i.test(l) && /retry|try .*again/i.test(l),
    ),
    "button-fail path must ask the user to retry",
  );
});

test("link finalizer always strips the transport verification URL button from the result", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/UNIQUE-MARKER",
    userCode: "AAAA-BBBBB",
  });
  for (const outcome of [
    { buttonDelivery: { sent: true }, codeDelivery: { sent: true } },
    { buttonDelivery: { sent: true }, codeDelivery: { sent: false } },
    { buttonDelivery: { sent: false }, codeDelivery: { sent: false } },
  ]) {
    const final = finalizeSubscriptionLinkReply(reply, outcome);
    assert.equal(final.channelData, undefined);
    assert.equal(final.verification_url, undefined);
    assert.ok(
      !JSON.stringify(final).includes("UNIQUE-MARKER"),
      "finalized tool payload must be safe to JSON-serialize for OpenClaw",
    );
    // The raw URL must not appear in any agent_instructions line.
    assert.ok(
      !final.agent_instructions.some((l) => l.includes("UNIQUE-MARKER")),
      "verification URL must never appear in agent_instructions",
    );
  }
});

test("subscription link final result is safe for OpenClaw content reducers", () => {
  const reply = buildSubscriptionLinkReply({
    verificationUrl: "https://auth.openai.com/codex/device",
    userCode: "6JTR-X8OS4",
  });
  const final = finalizeSubscriptionLinkReply(reply, {
    buttonDelivery: { sent: true, message_id: "10" },
    codeDelivery: { sent: true, message_id: "11" },
  });

  assert.throws(
    () => collectOpenClawTextContent(final),
    /Cannot read properties of undefined \(reading 'reduce'\)|reduce/,
    "raw finalized replies reproduce the OpenClaw wrapper failure",
  );

  const wrapped = jsonToolResult(final);
  assert.deepEqual(Object.keys(wrapped).sort(), ["content", "details"]);
  assert.equal(wrapped.content[0].type, "text");

  const text = collectOpenClawTextContent(wrapped);
  const parsed = JSON.parse(text);
  assert.equal(parsed.action, "subscriptions.open_link");
  assert.equal(parsed.delivered, true);
  assert.equal(parsed.code_delivered, true);
  assert.equal(parsed.user_code, "6JTR-X8OS4");
  assert.equal(parsed.verification_url, undefined);
  assert.equal(parsed.channelData, undefined);
  assert.deepEqual(wrapped.details, final);
});

test("jsonToolResult normalizes nullish payloads to an object payload", () => {
  const wrapped = jsonToolResult(undefined);
  assert.deepEqual(wrapped.details, {});
  assert.deepEqual(JSON.parse(collectOpenClawTextContent(wrapped)), {});
});

test("ChatGPT subscription factory tools return OpenClaw JSON tool results", () => {
  const entrypoint = readFileSync(path.join(REPO_ROOT, "src/index.js"), "utf8");

  assert.match(
    entrypoint,
    /return jsonToolResult\(\s*finalizeSubscriptionPrerequisiteHelpReply/s,
    "prerequisite-help factory tool must not return a raw object",
  );
  assert.match(
    entrypoint,
    /return jsonToolResult\(buildSubscriptionLinkFailureReply\(err\)\)/,
    "subscription-link failure path must include content[]",
  );
  assert.match(
    entrypoint,
    /return jsonToolResult\(\s*finalizeSubscriptionLinkReply/s,
    "subscription-link success path must include content[]",
  );
});

// ── Failure + revert builders ─────────────────────────────────────────

test("link-failure reply nudges the agent toward the prerequisite-help tool on disabled device-code", () => {
  const reply = buildSubscriptionLinkFailureReply(
    new Error("device-code login disabled on your ChatGPT account"),
  );

  assert.equal(reply.ok, false);
  assert.equal(reply.action, "subscriptions.open_link");
  assert.equal(reply.error, "device-code login disabled on your ChatGPT account");
  assert.match(reply.text, /enable device code authorization/i);
  assert.ok(
    reply.agent_instructions.some((line) =>
      line.includes("tinyhat_open_chatgpt_subscription_prerequisite_help"),
    ),
    "failure reply must point the agent at the prerequisite-help tool",
  );
});

test("revert reply suppresses any account / profile identifier", () => {
  const reply = buildSubscriptionRevertReply({ alreadyOnPlatformCredits: false });
  assert.equal(reply.action, "subscriptions.revert_to_platform_credits");
  assert.equal(reply.idempotent, false);
  assert.match(reply.text, /back on Tinyhat-funded credits/);
  const serialized = JSON.stringify(reply);
  assert.ok(!/@/.test(serialized), "revert reply must not contain an email-shaped string");
});

// ── Repo wiring: manifest + on-disk asset + SKILL.md ──────────────────

test("the screenshot URL constant matches a file that actually exists in the repo", () => {
  const expectedSuffix =
    "skills/tinyhat-subscriptions/assets/chatgpt-enable-device-code-for-codex.png";
  assert.ok(
    SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL.endsWith(expectedSuffix),
    "constant must end with the in-repo asset path",
  );
  assert.match(
    SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
    /^https:\/\/raw\.githubusercontent\.com\/tinyhat-ai\/tinyhat\/main\//,
  );
  const onDisk = path.join(REPO_ROOT, expectedSuffix);
  const bytes = readFileSync(onDisk);
  assert.ok(bytes.length > 1000, "screenshot must be a real (non-empty) PNG");
});

test("openclaw.plugin.json registers the new prerequisite-help tool + operation", () => {
  const manifest = JSON.parse(
    readFileSync(path.join(REPO_ROOT, "openclaw.plugin.json"), "utf8"),
  );

  assert.ok(
    manifest.contracts.tools.includes(
      "tinyhat_open_chatgpt_subscription_prerequisite_help",
    ),
  );
  assert.ok(
    manifest.contracts.tools.includes("tinyhat_open_chatgpt_subscription_link"),
  );

  const prerequisiteOp = manifest.contracts.operations.find(
    (op) => op.name === "subscriptions.open_prerequisite_help",
  );
  assert.ok(prerequisiteOp);
  assert.equal(
    prerequisiteOp.tool,
    "tinyhat_open_chatgpt_subscription_prerequisite_help",
  );
  assert.equal(prerequisiteOp.userSurface, "telegram_photo_plus_text");

  const linkOp = manifest.contracts.operations.find(
    (op) => op.name === "subscriptions.open_link",
  );
  assert.ok(linkOp);
  assert.equal(linkOp.userSurface, "telegram_url_button_plus_bare_code_bubble");
});

test("subscription SKILL.md routes the prerequisite-help tool and documents the delivery markers", () => {
  const skill = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-subscriptions/SKILL.md"),
    "utf8",
  );
  assert.match(skill, /tinyhat_open_chatgpt_subscription_prerequisite_help/);
  assert.match(skill, /code_delivered/);
  assert.match(skill, /photo_delivered/);
  assert.match(skill, /long-press.*Copy|bare.*bubble/i);
});

test("subscription guidance tracks the current OpenAI provider", () => {
  const skill = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-subscriptions/SKILL.md"),
    "utf8",
  );
  const helper = readFileSync(
    path.join(REPO_ROOT, "src/subscriptions.js"),
    "utf8",
  );
  const combined = `${skill}\n${helper}`;

  assert.match(
    combined,
    /openclaw models auth login --provider openai --device-code/,
  );
  assert.doesNotMatch(combined, /openai-codex/);
});
