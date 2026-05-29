// Usage:
//   node --test test/subscription_flow.test.mjs

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  SUBSCRIPTION_AGENT_INSTRUCTIONS,
  SUBSCRIPTION_PREREQUISITE_AGENT_INSTRUCTIONS,
  SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION,
  SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
  SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT,
  buildSubscriptionLinkFailureReply,
  buildSubscriptionLinkReply,
  buildSubscriptionPrerequisiteHelpReply,
  buildSubscriptionRevertReply,
} from "../src/subscription_builders.js";

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

test("prerequisite-help reply carries the canonical screenshot URL + caption + walkthrough", () => {
  const reply = buildSubscriptionPrerequisiteHelpReply();

  assert.equal(reply.action, "subscriptions.open_prerequisite_help");
  assert.equal(reply.text, SUBSCRIPTION_PREREQUISITE_WALKTHROUGH_TEXT);
  assert.match(reply.text, /enable device-code/i);
  assert.match(reply.text, /workspace admin/i);

  assert.deepEqual(reply.channelData, {
    telegram: {
      photo_url: SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
      photo_caption: SUBSCRIPTION_PREREQUISITE_PHOTO_CAPTION,
    },
  });

  // The canonical screenshot URL points at a real file in this repo on
  // main; pin the constant so a typo / move breaks the test rather than
  // silently shipping a broken Telegram photo URL.
  assert.match(
    SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL,
    /^https:\/\/raw\.githubusercontent\.com\/tinyhat-ai\/tinyhat\/main\//,
  );
  assert.ok(
    SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL.endsWith(
      "skills/tinyhat-subscriptions/assets/chatgpt-enable-device-code-for-codex.png",
    ),
    "screenshot URL must end with the in-repo asset path",
  );

  assert.deepEqual(reply.agent_instructions, SUBSCRIPTION_PREREQUISITE_AGENT_INSTRUCTIONS);
  assert.ok(
    reply.agent_instructions.some((line) =>
      /already been sent.*telegram/i.test(line),
    ),
    "must tell the agent the photo is already sent",
  );
  assert.ok(
    reply.agent_instructions.some((line) =>
      /do not.*re-?send.*photo|do not.*paste.*url/i.test(line),
    ),
    "must forbid re-sending the photo / pasting the URL",
  );
});

test("the screenshot URL constant matches a file that actually exists in the repo", () => {
  // Re-derive the in-repo asset path from the constant and confirm the
  // file is present on disk. Prevents a broken Telegram photo URL from
  // shipping with the next release.
  const expectedSuffix =
    "skills/tinyhat-subscriptions/assets/chatgpt-enable-device-code-for-codex.png";
  assert.ok(
    SUBSCRIPTION_PREREQUISITE_SCREENSHOT_URL.endsWith(expectedSuffix),
    "constant must end with the in-repo asset path",
  );
  const onDisk = path.join(REPO_ROOT, expectedSuffix);
  // `readFileSync` throws ENOENT if the file is missing.
  const bytes = readFileSync(onDisk);
  assert.ok(bytes.length > 1000, "screenshot must be a real (non-empty) PNG");
});

test("link-success reply puts URL+button in text but NEVER the device code", () => {
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
    "main text must not include the device code (#108 — bare bubble path)",
  );
  // Main text must direct the user to the next bubble.
  assert.match(reply.text, /paste the device code from the next message/i);
  assert.match(reply.text, /expires in about 15 minutes/i);

  // The URL+button payload stays in channelData for the tool body to fan
  // out via `sendTelegramMiniAppButton`.
  assert.deepEqual(reply.channelData.telegram.buttons, [
    [{ text: "Sign in to ChatGPT", url: "https://auth.openai.com/verify" }],
  ]);
  // The bare-code follow-up is carried separately for the tool body to
  // ship via `sendTelegramText`.
  assert.equal(reply.channelData.telegram.followup_text, "SZ85-LWNTP");

  assert.deepEqual(reply.agent_instructions, SUBSCRIPTION_AGENT_INSTRUCTIONS);
  assert.ok(
    reply.agent_instructions.some((line) =>
      /bare.*bubble|long-press/i.test(line),
    ),
    "agent_instructions must reflect the bare-bubble copy UX",
  );
  assert.ok(
    reply.agent_instructions.some((line) =>
      /do not.*re-?paste.*device code/i.test(line),
    ),
    "agent_instructions must forbid re-pasting the code in free text",
  );
});

test("link-failure reply nudges the agent toward the prerequisite-help tool on disabled device-code", () => {
  const reply = buildSubscriptionLinkFailureReply(
    new Error("device-code login disabled on your ChatGPT account"),
  );

  assert.equal(reply.ok, false);
  assert.equal(reply.action, "subscriptions.open_link");
  assert.equal(
    reply.error,
    "device-code login disabled on your ChatGPT account",
  );
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
  // The reply must not leak the OpenAI account email / profile id even
  // if the caller threads one through — the builder takes only the
  // alreadyOnPlatformCredits boolean.
  const serialized = JSON.stringify(reply);
  assert.ok(
    !/@/.test(serialized),
    "revert reply must not contain an email-shaped string",
  );
});

test("openclaw.plugin.json registers the new prerequisite-help tool + operation", () => {
  const manifest = JSON.parse(
    readFileSync(path.join(REPO_ROOT, "openclaw.plugin.json"), "utf8"),
  );

  assert.ok(
    manifest.contracts.tools.includes(
      "tinyhat_open_chatgpt_subscription_prerequisite_help",
    ),
    "prerequisite-help tool must be in contracts.tools",
  );
  assert.ok(
    manifest.contracts.tools.includes("tinyhat_open_chatgpt_subscription_link"),
    "link tool must still be in contracts.tools",
  );

  const prerequisiteOp = manifest.contracts.operations.find(
    (op) => op.name === "subscriptions.open_prerequisite_help",
  );
  assert.ok(prerequisiteOp, "subscriptions.open_prerequisite_help operation must exist");
  assert.equal(
    prerequisiteOp.tool,
    "tinyhat_open_chatgpt_subscription_prerequisite_help",
  );
  assert.equal(prerequisiteOp.userSurface, "telegram_photo_plus_text");

  const linkOp = manifest.contracts.operations.find(
    (op) => op.name === "subscriptions.open_link",
  );
  assert.ok(linkOp, "subscriptions.open_link operation must still exist");
  assert.equal(
    linkOp.userSurface,
    "telegram_url_button_plus_bare_code_bubble",
    "link operation's userSurface must reflect the bare-code-bubble UX",
  );
});

test("subscription SKILL.md routes the prerequisite-help tool and forbids re-sending the photo", () => {
  const skill = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-subscriptions/SKILL.md"),
    "utf8",
  );
  // The Route User Intent table must offer the prerequisite-help tool.
  assert.match(skill, /tinyhat_open_chatgpt_subscription_prerequisite_help/);
  // The Link section must tell the agent the code lands as its own bare
  // bubble so it doesn't re-paste.
  assert.match(skill, /code_delivered/);
  assert.match(skill, /long-press.*Copy|bare.*bubble/i);
  // The Subscription Button Contract must call out photo_delivered too.
  assert.match(skill, /photo_delivered/);
});
