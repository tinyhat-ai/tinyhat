import assert from "node:assert/strict";
import test from "node:test";

import {
  buildComputerAuthFailureSupportGuidance,
  COMPUTER_AUTH_MALFORMED_TOKEN,
  computerAuthFailureDiagnostic,
  isMalformedComputerAuthError,
  TinyhatRequestError,
  TINYHAT_SUPPORT_EMAIL,
  TINYHAT_SUPPORT_TELEGRAM_USERNAME,
  TINYHAT_SUPPORT_URL,
} from "../src/support_guidance.js";

const FORBIDDEN_SUPPORT_CHANNELS = [
  "Discord",
  "support@tinyhat.com",
  "/support",
];

test("malformed-token fallback gives final Tinyhat-owned support guidance", () => {
  const reply = buildComputerAuthFailureSupportGuidance({
    computerId: 5064,
    sourceTool: "tinyhat_report_problem",
    summary: "Platform status and problem reporting failed.",
  });

  assert.equal(reply.ok, false);
  assert.equal(reply.action, "platform_auth_failure");
  assert.equal(reply.reason, COMPUTER_AUTH_MALFORMED_TOKEN);
  assert.equal(reply.support_url, TINYHAT_SUPPORT_URL);
  assert.equal(reply.support_email, TINYHAT_SUPPORT_EMAIL);
  assert.equal(
    reply.telegram_support_username,
    TINYHAT_SUPPORT_TELEGRAM_USERNAME,
  );
  assert.equal(
    reply.diagnostic_handoff,
    "Computer #5064 returning computer-auth: malformed_token on all platform API calls.",
  );
  assert.deepEqual(reply.computer, { id: "5064" });
  assert.match(reply.text, /auth token is not being accepted/);
  assert.match(
    reply.text,
    /cannot pull status, run diagnostics, or report the problem/,
  );
  assert.match(reply.text, /tinyhat_report_problem until auth is fixed/);
  assert.match(reply.text, /https:\/\/tinyhat\.ai/);
  assert.match(reply.text, /support@tinyhat\.ai/);
  assert.match(reply.text, /@tinyhatchat/);
  assert.match(reply.text, /Computer #5064 returning computer-auth: malformed_token/);
  assertForbiddenChannelsAbsent(reply);
});

test("malformed-token fallback remains usable without Computer id", () => {
  const reply = buildComputerAuthFailureSupportGuidance();

  assert.equal(
    reply.diagnostic_handoff,
    "This Computer is returning computer-auth: malformed_token on all platform API calls.",
  );
  assert.equal(reply.computer, undefined);
  assertForbiddenChannelsAbsent(reply);
});

test("malformed-token request errors are classified narrowly", () => {
  assert.equal(
    isMalformedComputerAuthError(
      new TinyhatRequestError(
        "Tinyhat request failed (401): computer-auth: malformed_token",
        {
          status: 401,
          detail: "computer-auth: malformed_token",
          path: "/hapi/v1/computers/me/platform-status",
        },
      ),
    ),
    true,
  );
  assert.equal(
    isMalformedComputerAuthError(
      new TinyhatRequestError(
        "Tinyhat request failed (401): computer-auth: missing_token",
        { status: 401, detail: "computer-auth: missing_token" },
      ),
    ),
    false,
  );
  assert.equal(
    isMalformedComputerAuthError(
      new TinyhatRequestError(
        "Tinyhat request failed (500): computer-auth: malformed_token",
        { status: 500, detail: "computer-auth: malformed_token" },
      ),
    ),
    false,
  );
});

test("diagnostic handoff is pasteable for support", () => {
  assert.equal(
    computerAuthFailureDiagnostic("abc-123"),
    "Computer #abc-123 returning computer-auth: malformed_token on all platform API calls.",
  );
});

function assertForbiddenChannelsAbsent(value) {
  const serialized = JSON.stringify(value);
  for (const forbidden of FORBIDDEN_SUPPORT_CHANNELS) {
    assert(
      !serialized.includes(forbidden),
      `fallback copy must not mention ${forbidden}`,
    );
  }
}
