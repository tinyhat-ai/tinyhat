const SECRET_BUTTON_UNAVAILABLE_TEXT =
  "Retry from Telegram or open Manage Computer. Do not paste the value in chat.";

const TRANSPORT_ONLY_INSTRUCTIONS = [
  "Render the Telegram button payload when the channel supports buttons.",
  "Do not print, summarize, or fallback to any Mini App URL from channelData.",
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

export function formatButtonReply(payload, fallbackLabel, action = "computer.open") {
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

export function buttonTransport(button, fallbackLabel) {
  const label = normalizeString(button?.text) || fallbackLabel;
  return {
    button: {
      label,
      kind: "telegram_web_app",
      transport_only: true,
    },
    channelData: { telegram: { buttons: [[button]] } },
    presentation: {
      blocks: [
        {
          type: "text",
          text: `${label} is attached as a Telegram Mini App button.`,
        },
      ],
    },
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
    unsupported_channel_text:
      "This action needs a Telegram Mini App button. Retry from Telegram or Manage Computer.",
    agent_instructions: TRANSPORT_ONLY_INSTRUCTIONS,
  };
  if (!hasTelegramWebAppButton(button)) {
    return base;
  }
  return {
    ...base,
    ...buttonTransport(button, fallbackLabel),
  };
}

function hasTelegramWebAppButton(button) {
  return Boolean(button?.web_app?.url);
}

function normalizeString(value) {
  return String(value || "").trim();
}
