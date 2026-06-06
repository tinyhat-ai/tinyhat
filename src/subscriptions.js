// ChatGPT BYO subscription helpers.
//
// The chat-tool flow goes through the platform backend:
//
//   1. POST /hapi/v1/computers/me/subscription-link/start  (bumps mode → pending)
//   2. GET  /hapi/v1/computers/me/subscription-link/status (polls for URL + code)
//   3. POST /hapi/v1/computers/me/subscription-link/revert (back to platform_credits)
//
// The runtime supervisor is the layer that actually spawns the
// `openclaw models auth login --provider openai --device-code`
// CLI in a PTY — see the sibling runtime repo for the heartbeat-command
// handler. This plugin must not import `node:child_process` or
// `node:fs` for OAuth state because OpenClaw's plugin installer
// rejects packages that match dangerous-code patterns; the Tinyhat
// plugin ships through the normal install flow.
//
// All endpoint calls go via `callTinyhat()` from `src/index.js` (passed
// in by the tool body) so they reuse the Computer-bearer-token auth +
// platform base URL resolution that every other Tinyhat tool uses.

export const CHATGPT_LINK_POLL_INTERVAL_MS = 1_500;
// The chat tool starts a platform row, then waits for the supervisor's next
// heartbeat to receive the command, spawn the OpenClaw device-code CLI, retry
// transient pre-code failures, and POST URL+code back. A 15s budget raced real
// local Computers where the code arrived just after the tool returned failure.
// This is only the plugin-side ceiling: OpenClaw's tool-call abort signal still
// wins first because the loop checks `signal` and passes it into `callTinyhat`.
export const CHATGPT_LINK_POLL_TIMEOUT_MS = 90_000;

/**
 * Start (or retrieve, if already in flight) a ChatGPT BYO device-code
 * link session for this Computer. Returns `{ verificationUrl, userCode }`
 * once the supervisor has reported them; throws on timeout / failure.
 *
 * Idempotent at the backend boundary: re-calling while a session is
 * pending preserves the existing session_id (the supervisor's
 * in-flight CLI keeps polling auth.openai.com — we don't reset).
 *
 * Caller supplies the bound `callTinyhat` and `signal` (so the tool
 * body owns the abort lifecycle).
 */
export async function startChatgptSubscriptionLink({
  callTinyhat,
  signal,
  pollIntervalMs = CHATGPT_LINK_POLL_INTERVAL_MS,
  pollTimeoutMs = CHATGPT_LINK_POLL_TIMEOUT_MS,
}) {
  // Kick off (or retrieve) the link session. The backend bumps the
  // row to pending + signals the supervisor via the heartbeat command;
  // the supervisor runs the CLI and POSTs URL+code back via the
  // separate `/me/subscription-link-result` reporter.
  await callTinyhat(
    "/hapi/v1/computers/me/subscription-link/start",
    { method: "POST", body: "{}" },
    signal,
  );

  // Poll until the supervisor's first result POST lands the URL+code,
  // or the supervisor reports linked/failed before we ever saw them
  // (unlikely but possible if the user is freakishly fast).
  const deadline = Date.now() + pollTimeoutMs;
  while (Date.now() < deadline) {
    signal?.throwIfAborted?.();
    const status = await callTinyhat(
      "/hapi/v1/computers/me/subscription-link/status",
      { method: "GET" },
      signal,
    );
    const session = status?.pending_session;
    const url =
      typeof session?.verification_url === "string"
        ? session.verification_url
        : null;
    const code =
      typeof session?.user_code === "string" ? session.user_code : null;
    if (url && code) {
      return { verificationUrl: url, userCode: code };
    }
    if (status?.status === "failed") {
      const reason =
        typeof status.last_error === "string" && status.last_error.trim()
          ? status.last_error
          : "Subscription link failed before a device code was issued.";
      throw new Error(reason);
    }
    if (status?.status === "linked") {
      // Edge case: somehow already linked without us seeing the
      // intermediate URL/code. Caller's reply builder treats this
      // as a degenerate success.
      throw new Error(
        "Subscription already linked — open Settings → External subscriptions to confirm.",
      );
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  throw new Error(
    "Timed out waiting for the device-code URL and code. Ask the user to try again in a moment.",
  );
}

/**
 * Revert this Computer to Tinyhat-funded platform credits. The
 * backend flips the row to platform_credits + bumps the config
 * revision; the supervisor's next apply tick wipes the per-agent
 * OpenClaw OAuth profile and rewrites `openclaw.json` to the
 * OpenRouter / pi-runtime path.
 *
 * Returns `{ alreadyOnPlatformCredits }` — a boolean the reply
 * builder uses to phrase the chat response. The profile id / email
 * the backend may have removed is **deliberately not returned**;
 * those values must never enter chat or tool-output per the v0.5
 * "secret value never enters chat or tool output" policy and the
 * `metadata_only_tool_result` userSurface declared on the operation.
 */
export async function revertChatgptSubscriptionAuth({ callTinyhat, signal }) {
  const result = await callTinyhat(
    "/hapi/v1/computers/me/subscription-link/revert",
    { method: "POST", body: "{}" },
    signal,
  );
  // The backend's `idempotent` flag tells us whether the row was
  // already in platform_credits (no work needed) vs. actually
  // flipped. We pass that through as the only non-secret signal the
  // reply builder needs; profile ids / emails are NOT surfaced.
  return {
    alreadyOnPlatformCredits: Boolean(result?.idempotent),
  };
}
