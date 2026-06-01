const SECRET_BUTTON_UNAVAILABLE_TEXT =
  "Retry from Telegram or open Manage Computer. Do not paste the value in chat.";
const TELEGRAM_BUTTON_UNAVAILABLE_TEXT =
  "This action needs a Telegram Mini App button. Retry from Telegram or Manage Computer.";

const TRANSPORT_ONLY_INSTRUCTIONS = [
  "Render the Telegram button payload when the channel supports buttons.",
  "Do not print, summarize, or fallback to any Mini App URL.",
  "If buttons are unavailable, tell the user to retry from Telegram or Manage Computer.",
];

export function formatSecretListReply(payload) {
  const secrets = Array.isArray(payload?.secrets) ? payload.secrets : [];
  const button = payload?.telegram_button;
  const lines =
    secrets.length === 0
      ? ["No Tinyhat runtime secrets are configured for this Computer yet."]
      : [
          "Tinyhat runtime secrets:",
          ...secrets.map((secret) => {
            const name = normalizeString(secret?.name) || "(unnamed)";
            const saved = secret?.in_platform || secret?.has_value ? "saved" : "not saved";
            const available =
              normalizeString(secret?.vps_status) === "available"
                ? "available"
                : "not available";
            const description = normalizeString(secret?.description);
            return `- ${name}: ${saved}, ${available}${description ? ` - ${description}` : ""}`;
          }),
        ];

  return withSafeButtonTransport({
    action: "credentials.list_metadata",
    text: lines.join("\n"),
    secrets: secrets.map(publicSecretMetadata),
    button,
    fallbackLabel: "Manage secrets",
  });
}

export function formatSecretRequestReply(payload) {
  const secret = publicSecretMetadata(payload?.secret);
  const secretName = secret.name || "this secret";
  const button = payload?.telegram_button;

  if (!hasTelegramWebAppButton(button)) {
    return {
      ok: false,
      action: "credentials.open_add_secret",
      text:
        `I could not render a Telegram button for ${secretName}. ` +
        SECRET_BUTTON_UNAVAILABLE_TEXT,
      secret,
      unsupported_channel_text: SECRET_BUTTON_UNAVAILABLE_TEXT,
      agent_instructions: TRANSPORT_ONLY_INSTRUCTIONS,
    };
  }

  return withSafeButtonTransport({
    action: "credentials.open_add_secret",
    text: `Open the Telegram Mini App button to add ${secretName}. Do not paste the value in chat.`,
    secret,
    button,
    fallbackLabel: `Add ${secretName}`,
  });
}

export function formatButtonReply(payload, fallbackLabel, action) {
  const button = payload?.telegram_button;
  const message = normalizeString(payload?.message);
  if (!hasTelegramWebAppButton(button)) {
    return {
      ok: false,
      action,
      text: message || `${fallbackLabel} is not available from this channel.`,
      unsupported_channel_text: `${fallbackLabel} must be opened from Telegram or Manage Computer.`,
      agent_instructions: TRANSPORT_ONLY_INSTRUCTIONS,
    };
  }
  return withSafeButtonTransport({
    action,
    text: message || `${fallbackLabel} is available from the Telegram button.`,
    button,
    fallbackLabel,
  });
}

export function formatSoftwareUpdatesReply(payload) {
  return formatButtonReply(
    {
      ...withMiniAppChildPath(payload, "software", "Open Software / Updates"),
      message:
        "Open Software / Updates in Manage Computer. Choose Update to " +
        "latest, or pick a release to roll back.",
    },
    "Open Software / Updates",
    "computer.software_updates",
  );
}

export function buttonTransport(button, fallbackLabel) {
  const label = normalizeString(button?.text) || fallbackLabel;
  return {
    button: {
      label,
      kind: "telegram_web_app",
      transport_only: true,
    },
    channelData: { telegram: { buttons: [[button]] } },
  };
}

export function publicSecretMetadata(secret) {
  return {
    name: normalizeString(secret?.name) || undefined,
    description: normalizeString(secret?.description) || undefined,
    status: normalizeString(secret?.status) || undefined,
    revision: secret?.revision ?? undefined,
    in_platform: Boolean(secret?.in_platform || secret?.has_value),
    vps_status: normalizeString(secret?.vps_status) || undefined,
  };
}

function withSafeButtonTransport({ action, text, secret, secrets, button, fallbackLabel }) {
  const base = {
    ok: true,
    action,
    text,
    ...(secret ? { secret } : {}),
    ...(secrets ? { secrets } : {}),
    agent_instructions: TRANSPORT_ONLY_INSTRUCTIONS,
  };
  if (!hasTelegramWebAppButton(button)) {
    return {
      ...base,
      unsupported_channel_text: TELEGRAM_BUTTON_UNAVAILABLE_TEXT,
    };
  }
  return {
    ...base,
    ...buttonTransport(button, fallbackLabel),
  };
}

function withMiniAppChildPath(payload, childPath, buttonText) {
  const button = payload?.telegram_button;
  if (!hasTelegramWebAppButton(button)) {
    return payload;
  }
  return {
    ...payload,
    telegram_button: {
      ...button,
      text: buttonText,
      web_app: {
        ...button.web_app,
        url: appendPathSegment(button.web_app.url, childPath),
      },
    },
  };
}

function appendPathSegment(value, segment) {
  const text = normalizeString(value);
  if (!text) {
    return text;
  }
  try {
    const url = new URL(text);
    const suffix = String(segment).replace(/^\/+/, "");
    url.pathname = `${url.pathname.replace(/\/+$/, "")}/${suffix}`;
    return url.toString();
  } catch {
    return text;
  }
}

function hasTelegramWebAppButton(button) {
  return Boolean(button?.web_app?.url);
}

function normalizeString(value) {
  return String(value || "").trim();
}
