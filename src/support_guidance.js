export const TINYHAT_SUPPORT_URL = "https://tinyhat.ai";
export const TINYHAT_SUPPORT_EMAIL = "support@tinyhat.ai";
export const TINYHAT_SUPPORT_TELEGRAM_USERNAME = "@tinyhatchat";
export const COMPUTER_AUTH_MALFORMED_TOKEN = "computer-auth: malformed_token";
export const PLATFORM_AUTH_FAILURE_ACTION = "platform_auth_failure";

export class TinyhatRequestError extends Error {
  constructor(message, { status, detail, path, payload } = {}) {
    super(message);
    this.name = "TinyhatRequestError";
    this.status = status;
    this.detail = detail;
    this.path = path;
    this.payload = payload;
  }
}

export function isMalformedComputerAuthError(error) {
  const status = Number(error?.status || 0);
  const detail = normalizeString(error?.detail || error?.message);
  return status === 401 && detail.includes(COMPUTER_AUTH_MALFORMED_TOKEN);
}

export function buildComputerAuthFailureSupportGuidance({
  computerId,
  sourceTool,
  summary,
} = {}) {
  const diagnostic = computerAuthFailureDiagnostic(computerId);
  const text = [
    "Tinyhat cannot use this Computer's platform tools right now.",
    "The Computer auth token is not being accepted by the Tinyhat platform backend,",
    "so the agent cannot pull status, run diagnostics, or report the problem through tinyhat_report_problem until auth is fixed.",
    `Contact official Tinyhat support at ${TINYHAT_SUPPORT_EMAIL}, on Telegram at ${TINYHAT_SUPPORT_TELEGRAM_USERNAME}, or through ${TINYHAT_SUPPORT_URL}.`,
    `Paste this diagnostic to support: ${diagnostic}`,
  ].join(" ");

  return {
    ok: false,
    action: PLATFORM_AUTH_FAILURE_ACTION,
    reason: COMPUTER_AUTH_MALFORMED_TOKEN,
    redacted: true,
    support_url: TINYHAT_SUPPORT_URL,
    support_email: TINYHAT_SUPPORT_EMAIL,
    telegram_support_username: TINYHAT_SUPPORT_TELEGRAM_USERNAME,
    source_tool: normalizeString(sourceTool) || undefined,
    summary: normalizeString(summary) || undefined,
    computer: normalizedComputer(computerId),
    diagnostic_handoff: diagnostic,
    text,
    blocked_capabilities: ["computer.status", "support.report_problem"],
  };
}

export function computerAuthFailureDiagnostic(computerId) {
  const normalizedId = normalizeString(computerId);
  if (!normalizedId) {
    return `This Computer is returning ${COMPUTER_AUTH_MALFORMED_TOKEN} on all platform API calls.`;
  }
  return `Computer #${normalizedId} returning ${COMPUTER_AUTH_MALFORMED_TOKEN} on all platform API calls.`;
}

function normalizedComputer(computerId) {
  const normalizedId = normalizeString(computerId);
  return normalizedId ? { id: normalizedId } : undefined;
}

function normalizeString(value) {
  return String(value || "").trim();
}
