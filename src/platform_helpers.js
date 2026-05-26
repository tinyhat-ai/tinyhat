const BLOCKED_KEY_TERMS = [
  "token",
  "secret",
  "secret_value",
  "mini_app_url",
  "url",
  "private_url",
  "signed_url",
  "authorization",
];

export function parseSecretCommand(raw) {
  const text = normalizeString(raw);
  if (!text || /^(help|-h|--help)$/i.test(text)) {
    return { action: "help" };
  }
  const parts = text.split(/\s+/);
  const verb = (parts.shift() || "").toLowerCase();
  if (["list", "ls", "status", "show", "manage"].includes(verb)) {
    return { action: "list" };
  }
  if (["add", "set", "request", "need"].includes(verb)) {
    const name = parts.shift();
    if (!name) {
      return { action: "help" };
    }
    return { action: "request", name, description: parts.join(" ") || undefined };
  }
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(text)) {
    return { action: "request", name: text };
  }
  return { action: "help" };
}

export function redactObject(value) {
  if (Array.isArray(value)) {
    return value.map((nested) =>
      nested && typeof nested === "object" ? redactObject(nested) : nested,
    );
  }
  if (!value || typeof value !== "object") {
    return value ?? null;
  }
  const out = {};
  for (const [key, nested] of Object.entries(value)) {
    const normalized = key.toLowerCase();
    if (BLOCKED_KEY_TERMS.some((term) => normalized.includes(term))) {
      out[key] = "[redacted]";
    } else if (Array.isArray(nested)) {
      out[key] = nested.map((item) =>
        item && typeof item === "object" ? redactObject(item) : item,
      );
    } else if (nested && typeof nested === "object") {
      out[key] = redactObject(nested);
    } else {
      out[key] = nested;
    }
  }
  return out;
}

function normalizeString(value) {
  return String(value || "").trim();
}
