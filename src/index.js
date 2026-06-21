import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

import { announcePluginLoaded } from "./load_beacon.js";
import { parseSecretCommand, redactObject } from "./platform_helpers.js";
import {
  formatButtonReply,
  formatSecretListReply,
  formatSecretRequestReply,
  formatSoftwareUpdatesReply,
} from "./presentation_helpers.js";
import {
  buildSubscriptionRevertCommandReply,
  handleSubscriptionCommand,
  sendSubscriptionPrerequisiteHelpReply,
  startAndSendSubscriptionLinkReply,
} from "./subscription_commands.js";
import {
  buildComputerAuthFailureSupportGuidance,
  isMalformedComputerAuthError,
  TinyhatRequestError,
} from "./support_guidance.js";
import {
  markTelegramDelivered,
  sendTelegramMiniAppButton,
} from "./telegram_delivery.js";
import { jsonToolResult } from "./tool_results.js";

const METADATA_BASE_URL_KEY = "tinyhat-platform-base-url";
const METADATA_AUDIENCE_KEY = "tinyhat-backend-audience";
const METADATA_COMPUTER_ID_KEY = "tinyhat-computer-id";
const DEV_RUNTIME_BEARER = "dev-runtime";
const SECRET_REPLY_SAFETY = "Do not paste the value in chat.";
const DEFAULT_SKILLS = [
  { name: "tinyhat-platform", role: "router" },
  { name: "tinyhat-secrets", role: "secrets" },
  { name: "tinyhat-computer-access", role: "computer_access" },
  { name: "tinyhat-software-updates", role: "software_updates" },
  { name: "tinyhat-runtime-status", role: "runtime_status" },
  { name: "tinyhat-package-inventory", role: "package_inventory" },
  { name: "tinyhat-support-report", role: "support_report" },
  { name: "tinyhat-subscriptions", role: "subscriptions" },
];

// Subscription chat-tool reply builders + the canonical screenshot URL
// live in `src/subscription_builders.js` (#108) — kept out of this
// entrypoint so the test suite can import them directly and so the
// raw-URL constant stays out of `skills/*/SKILL.md` (the package
// validator forbids `https?://` in skill markdown).

const configSchema = {
  type: "object",
  properties: {
    platformBaseUrl: { type: "string" },
    backendAudience: { type: "string" },
    devMode: { type: "boolean" },
    devBearer: { type: "string" },
    computerId: { type: "string" },
  },
  additionalProperties: false,
};

const emptyParameters = {
  type: "object",
  properties: {},
  additionalProperties: false,
};

const requestSecretParameters = {
  type: "object",
  required: ["name"],
  properties: {
    name: {
      type: "string",
      description: "Env-style secret name, for example OPENAI_API_KEY.",
    },
    description: {
      type: "string",
      description:
        "Plain-language description of why this Computer needs the secret.",
    },
    hint: {
      type: "string",
      description: "Deprecated alias for description.",
    },
  },
  additionalProperties: false,
};

const terminalLinkParameters = {
  type: "object",
  properties: {
    command: {
      type: "string",
      description:
        "Optional command to show for admin approval before terminal launch.",
    },
  },
  additionalProperties: false,
};

const supportReportParameters = {
  type: "object",
  properties: {
    summary: {
      type: "string",
      description: "Short non-secret summary of what the user says is wrong.",
    },
  },
  additionalProperties: false,
};

const commandParameters = {
  type: "object",
  properties: {
    command: {
      type: "string",
      description: "Raw slash-command args.",
    },
    commandName: { type: "string" },
    skillName: { type: "string" },
  },
  additionalProperties: false,
};

const plugin = defineToolPlugin({
  id: "tinyhat",
  name: "Tinyhat",
  description: "Tinyhat platform capabilities for managed OpenClaw Computers.",
  configSchema,
  tools: (tool) => [
    tool({
      name: "tinyhat_get_platform_status",
      description:
        "Return secret-free Tinyhat Computer, runtime, plugin, and capability status.",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        try {
          return await callTinyhat(
            runtime.config,
            "/hapi/v1/computers/me/platform-status",
            { method: "GET" },
            runtime.signal,
          );
        } catch (err) {
          if (isMalformedComputerAuthError(err)) {
            return computerAuthFailureSupportGuidance(
              runtime.config,
              runtime.signal,
              "tinyhat_get_platform_status",
            );
          }
          throw err;
        }
      },
    }),
    tool({
      name: "tinyhat_list_installed_packages",
      description:
        "List public runtime/plugin/default-skill package refs for this Computer.",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        const status = await fetchPlatformStatus(runtime.config, runtime.signal);
        return packageInventoryFromStatus(status);
      },
    }),
    tool({
      name: "tinyhat_list_runtime_secrets",
      description:
        "List metadata for runtime secrets assigned to this Computer. " +
        "Returns names/status/revisions only, never secret values.",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        return formatSecretListReply(
          await fetchSecretStatuses(runtime.config, runtime.signal),
        );
      },
    }),
    tool({
      name: "tinyhat_request_runtime_secret",
      description:
        "Create and, on Telegram, directly send a Mini App button so the " +
        "owner can add or replace one runtime secret value outside chat.",
      parameters: requestSecretParameters,
      factory: ({ api, config, toolContext }) => ({
        name: "tinyhat_request_runtime_secret",
        label: "tinyhat_request_runtime_secret",
        description:
          "Create and, on Telegram, directly send a Mini App button so the " +
          "owner can add or replace one runtime secret value outside chat.",
        parameters: requestSecretParameters,
        execute: async (_toolCallId, { name, description, hint }, signal) => {
          const runtime = resolveExecutionRuntime(config, { signal });
          runtime.signal?.throwIfAborted?.();
          const reply = formatSecretRequestReply(
            await callTinyhat(
              runtime.config,
              "/hapi/v1/computers/me/runtime-secrets/add-link",
              {
                method: "POST",
                body: JSON.stringify({
                  name,
                  description: description || hint,
                  hint,
                }),
              },
              runtime.signal,
            ),
          );
          const delivery = await sendTelegramMiniAppButton({
            api,
            toolContext,
            reply,
            text: reply.text,
            signal: runtime.signal,
          });
          return jsonToolResult(markTelegramDelivered(reply, delivery));
        },
      }),
    }),
    tool({
      name: "tinyhat_open_manage_computer_link",
      description:
        "Create a Telegram Mini App button payload for Manage Computer.",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        return formatButtonReply(
          await fetchManageComputerLink(runtime.config, runtime.signal),
          "Manage computer",
          "computer.open_manage",
        );
      },
    }),
    tool({
      name: "tinyhat_open_software_updates_link",
      description:
        "Create a Telegram Mini App button payload for Software / Updates.",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        return formatSoftwareUpdatesReply(
          await fetchManageComputerLink(runtime.config, runtime.signal),
        );
      },
    }),
    tool({
      name: "tinyhat_open_terminal_link",
      description:
        "Create a Telegram Mini App button payload for a secure terminal. " +
        "An optional command is shown for admin approval before it runs.",
      parameters: terminalLinkParameters,
      execute: async ({ command } = {}, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        return formatButtonReply(
          await fetchTerminalLink(runtime.config, runtime.signal, command),
          "Open secure terminal",
          "computer.open_terminal",
        );
      },
    }),
    tool({
      name: "tinyhat_report_problem",
      description:
        "Return redacted Tinyhat/OpenClaw support context for this Computer.",
      parameters: supportReportParameters,
      execute: async ({ summary } = {}, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        try {
          const status = await fetchPlatformStatus(runtime.config, runtime.signal);
          return supportReportFromStatus(status, summary);
        } catch (err) {
          if (isMalformedComputerAuthError(err)) {
            return computerAuthFailureSupportGuidance(
              runtime.config,
              runtime.signal,
              "tinyhat_report_problem",
              summary,
            );
          }
          throw err;
        }
      },
    }),
    tool({
      name: "tinyhat_secret_command",
      description:
        "Slash-command dispatcher for /tinyhat_secrets. Supports list/manage and add NAME.",
      parameters: commandParameters,
      execute: async ({ command = "" }, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        const parsed = parseSecretCommand(command);
        if (parsed.action === "help") {
          return secretCommandUsage();
        }
        if (parsed.action === "list") {
          return formatSecretListReply(
            await fetchSecretStatuses(runtime.config, runtime.signal),
          );
        }
        return formatSecretRequestReply(
          await callTinyhat(
            runtime.config,
            "/hapi/v1/computers/me/runtime-secrets/add-link",
            {
              method: "POST",
              body: JSON.stringify({
                name: parsed.name,
                description: parsed.description,
                hint: parsed.description,
              }),
            },
            runtime.signal,
          ),
        );
      },
    }),
    tool({
      name: "tinyhat_open_chatgpt_subscription_prerequisite_help",
      description:
        "Send the user the canonical screenshot of the ChatGPT security " +
        "setting they have to enable before a device-code link will work, " +
        "plus the matching walkthrough text. Call this when the user first " +
        "asks to connect their ChatGPT subscription, before " +
        "`tinyhat_open_chatgpt_subscription_link`.",
      parameters: emptyParameters,
      factory: ({ api, config, toolContext }) => ({
        name: "tinyhat_open_chatgpt_subscription_prerequisite_help",
        label: "tinyhat_open_chatgpt_subscription_prerequisite_help",
        description:
          "Send the prerequisite screenshot + walkthrough to the user via Telegram.",
        parameters: emptyParameters,
        execute: async (_toolCallId, _params, signal) => {
          const runtime = resolveExecutionRuntime(config, { signal });
          runtime.signal?.throwIfAborted?.();
          return jsonToolResult(
            await sendSubscriptionPrerequisiteHelpReply({
              api,
              toolContext,
              signal: runtime.signal,
            }),
          );
        },
      }),
    }),
    tool({
      name: "tinyhat_open_chatgpt_subscription_link",
      description:
        "Start a ChatGPT BYO subscription device-code login on this Computer " +
        "and return the OpenAI verification URL + 9-character device code so " +
        "the owner can approve from a signed-in device.",
      parameters: emptyParameters,
      factory: ({ api, config, toolContext }) => ({
        name: "tinyhat_open_chatgpt_subscription_link",
        label: "tinyhat_open_chatgpt_subscription_link",
        description:
          "Start a ChatGPT BYO subscription device-code login and return URL/code.",
        parameters: emptyParameters,
        execute: async (_toolCallId, _params, signal) => {
          const runtime = resolveExecutionRuntime(config, { signal });
          runtime.signal?.throwIfAborted?.();
          // Bind the platform call so the helper doesn't have to
          // know about config / token resolution. The runtime
          // supervisor (sibling repo) is the layer that spawns the
          // device-code CLI in a PTY; we just kick the link and
          // poll the backend for the URL+code result.
          const boundCall = (path, init, sig) =>
            callTinyhat(runtime.config, path, init, sig);
          return jsonToolResult(
            await startAndSendSubscriptionLinkReply({
              callTinyhat: boundCall,
              api,
              toolContext,
              signal: runtime.signal,
            }),
          );
        },
      }),
    }),
    tool({
      name: "tinyhat_revert_to_platform_credits",
      description:
        "Revert this Computer's LLM auth from the owner's ChatGPT " +
        "subscription back to Tinyhat-funded platform credits (wipes the " +
        "per-agent OAuth credential).",
      parameters: emptyParameters,
      execute: async (_params, config, context) => {
        const runtime = resolveExecutionRuntime(config, context);
        runtime.signal?.throwIfAborted?.();
        const boundCall = (path, init, sig) =>
          callTinyhat(runtime.config, path, init, sig);
        return buildSubscriptionRevertCommandReply({
          callTinyhat: boundCall,
          signal: runtime.signal,
        });
      },
    }),
  ],
});

const registerTools = plugin.register;

plugin.register = (api) => {
  registerTools(api);
  const platformConfig = api.pluginConfig ?? {};

  api.registerCommand({
    name: "tinyhat_secrets",
    nativeNames: { default: "tinyhat_secrets" },
    description: "List or request Tinyhat runtime secrets.",
    channels: ["telegram"],
    acceptsArgs: true,
    agentPromptGuidance: [
      `Use /tinyhat_secrets list to show runtime secret metadata and /tinyhat_secrets add NAME to request a Telegram Mini App secret-entry button. Never ask for secret values in chat. ${SECRET_REPLY_SAFETY}`,
    ],
    handler: async (ctx) => {
      const parsed = parseSecretCommand(ctx.args || "");
      if (parsed.action === "help") {
        return { text: secretCommandUsage().usage.join("\n") };
      }
      if (parsed.action === "list") {
        const payload = await fetchSecretStatuses(platformConfig);
        return formatSecretListReply(payload);
      }
      const payload = await callTinyhat(
        platformConfig,
        "/hapi/v1/computers/me/runtime-secrets/add-link",
        {
          method: "POST",
          body: JSON.stringify({
            name: parsed.name,
            description: parsed.description,
            hint: parsed.description,
          }),
        },
      );
      return formatSecretRequestReply(payload);
    },
  });

  api.registerCommand({
    name: "tinyhat_secrets_manage",
    nativeNames: { default: "tinyhat_secrets_manage" },
    description: "Open Tinyhat runtime secret manager.",
    channels: ["telegram"],
    acceptsArgs: false,
    agentPromptGuidance: [
      "Use /tinyhat_secrets_manage when the user wants the Tinyhat runtime secret list Mini App.",
    ],
    handler: async () => {
      const payload = await fetchSecretStatuses(platformConfig);
      return formatSecretListReply(payload);
    },
  });

  api.registerCommand({
    name: "tinyhat_computer",
    nativeNames: { default: "tinyhat_computer" },
    description: "Open Tinyhat Manage Computer.",
    channels: ["telegram"],
    acceptsArgs: false,
    agentPromptGuidance: [
      "Use /tinyhat_computer when an agent admin asks to manage or inspect this Computer.",
    ],
    handler: async () => {
      const payload = await fetchManageComputerLink(platformConfig);
      return formatButtonReply(payload, "Manage computer", "computer.open_manage");
    },
  });

  api.registerCommand({
    name: "tinyhat_software",
    nativeNames: { default: "tinyhat_software" },
    description: "Open Tinyhat Software / Updates.",
    channels: ["telegram"],
    acceptsArgs: false,
    agentPromptGuidance: [
      "Use /tinyhat_software when an agent admin asks to update, " +
        "upgrade, roll back, or inspect Tinyhat platform software versions.",
    ],
    handler: async () => {
      const payload = await fetchManageComputerLink(platformConfig);
      return formatSoftwareUpdatesReply(payload);
    },
  });

  api.registerCommand({
    name: "tinyhat_subscriptions",
    nativeNames: { default: "tinyhat_subscriptions" },
    description: "Connect ChatGPT subscription or revert to Tinyhat credits.",
    channels: ["telegram"],
    acceptsArgs: true,
    agentPromptGuidance: [
      "Use /tinyhat_subscriptions help, prerequisite, link, or revert for ChatGPT subscription flows.",
    ],
    handler: async (ctx) => {
      const runtime = resolveExecutionRuntime(platformConfig, ctx);
      runtime.signal?.throwIfAborted?.();
      const boundCall = (path, init, signal) =>
        callTinyhat(runtime.config, path, init, signal);
      return handleSubscriptionCommand({
        api,
        ctx,
        callTinyhat: boundCall,
        signal: runtime.signal,
      });
    },
  });

  api.registerCommand({
    name: "tinyhat_terminal",
    nativeNames: { default: "tinyhat_terminal" },
    description: "Open a secure Tinyhat terminal.",
    channels: ["telegram"],
    acceptsArgs: true,
    agentPromptGuidance: [
      "Use /tinyhat_terminal when an agent admin asks to open a secure terminal. Any command text is only shown for admin approval.",
    ],
    handler: async (ctx) => {
      const payload = await fetchTerminalLink(platformConfig, undefined, ctx.args);
      return formatButtonReply(payload, "Open secure terminal", "computer.open_terminal");
    },
  });
};

// Loud-load beacon (#124): runs only when the whole module evaluated
// successfully, so the log line + beacon file mean "the plugin actually
// loaded", not "the install succeeded". Hosts and
// `scripts/check_plugin_load.mjs` use it to catch silent load failures.
announcePluginLoaded();

export default plugin;

function resolveExecutionRuntime(configArg, contextArg) {
  const configCandidate =
    firstPluginConfig(configArg) ?? firstPluginConfig(contextArg) ?? {};
  return {
    config: configCandidate,
    signal: contextArg?.signal ?? configArg?.signal,
  };
}

function firstPluginConfig(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  if (looksLikePlatformConfig(value)) {
    return value;
  }
  for (const key of ["pluginConfig", "config", "toolConfig"]) {
    const nested = value[key];
    if (nested && typeof nested === "object" && looksLikePlatformConfig(nested)) {
      return nested;
    }
  }
  return null;
}

function looksLikePlatformConfig(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      [
        "platformBaseUrl",
        "backendAudience",
        "devMode",
        "devBearer",
        "computerId",
      ].some((key) => Object.prototype.hasOwnProperty.call(value, key)),
  );
}

function secretCommandUsage() {
  return {
    ok: false,
    usage: [
      "Tinyhat runtime secrets:",
      "/tinyhat_secrets list",
      "/tinyhat_secrets manage",
      "/tinyhat_secrets add OPENAI_API_KEY why it is needed",
      "",
      "Secret values are added in the Tinyhat Mini App, not in chat.",
    ],
  };
}

async function fetchPlatformStatus(config, signal) {
  return callTinyhat(
    config,
    "/hapi/v1/computers/me/platform-status",
    { method: "GET" },
    signal,
  );
}

async function fetchManageComputerLink(config, signal) {
  return callTinyhat(
    config,
    "/hapi/v1/computers/me/manage/open-link",
    { method: "POST" },
    signal,
  );
}

async function fetchSecretStatuses(config, signal) {
  return callTinyhat(
    config,
    "/hapi/v1/computers/me/runtime-secret-statuses",
    { method: "GET" },
    signal,
  );
}

async function fetchTerminalLink(config, signal, command) {
  const normalizedCommand = normalizeString(command);
  const init = normalizedCommand
    ? { method: "POST", body: JSON.stringify({ command: normalizedCommand }) }
    : { method: "POST" };
  return callTinyhat(
    config,
    "/hapi/v1/computers/me/terminal/open-link",
    init,
    signal,
  );
}

function packageInventoryFromStatus(status) {
  const platform = status?.tinyhat_platform ?? status?.platform ?? status ?? {};
  const plugin = platform?.plugin ?? status?.plugin ?? null;
  const capabilities = Array.isArray(platform?.capabilities)
    ? platform.capabilities.map((capability) => ({
        name: capability?.name,
        status: capability?.status,
        tool_name: capability?.tool_name,
      }))
    : [];
  return {
    ok: true,
    installed_by_tinyhat: {
      plugin,
      default_skills: DEFAULT_SKILLS,
      capabilities,
    },
    user_installed: status?.user_installed ?? [],
    note:
      "Tinyhat-installed defaults are reported separately from user-installed skills when the platform provides that inventory.",
  };
}

function supportReportFromStatus(status, summary) {
  const platform = status?.tinyhat_platform ?? status?.platform ?? status ?? {};
  return {
    ok: true,
    summary: normalizeString(summary) || undefined,
    redacted: true,
    computer: redactObject(status?.computer),
    runtime: redactObject(status?.runtime),
    plugin: redactObject(platform?.plugin ?? status?.plugin),
    capabilities: Array.isArray(platform?.capabilities)
      ? platform.capabilities.map((capability) => ({
          name: capability?.name,
          status: capability?.status,
        }))
      : [],
  };
}

async function computerAuthFailureSupportGuidance(
  config,
  signal,
  sourceTool,
  summary,
) {
  return buildComputerAuthFailureSupportGuidance({
    computerId: await resolveComputerId(config, signal),
    sourceTool,
    summary,
  });
}

async function callTinyhat(config, path, init, signal) {
  const baseUrl = await resolvePlatformBaseUrl(config, signal);
  const token = await resolveBearerToken(config, signal);
  const response = await fetch(baseUrl.replace(/\/+$/, "") + path, {
    ...init,
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  const text = await response.text();
  const payload = text ? parseJson(text) : {};
  if (!response.ok) {
    const detail = readDetail(payload, text);
    throw new TinyhatRequestError(
      `Tinyhat request failed (${response.status}): ${detail}`,
      { status: response.status, detail, path, payload },
    );
  }
  return payload;
}

async function resolveComputerId(config, signal) {
  const configured = normalizeString(config?.computerId);
  if (configured) {
    return configured;
  }
  const envConfigured =
    readProcessEnv("TINYHAT_COMPUTER_ID") ||
    readProcessEnv("DEV_AUTO_COMPUTER_ID");
  if (envConfigured) {
    return envConfigured;
  }
  return tryReadMetadataValue(METADATA_COMPUTER_ID_KEY, signal);
}

async function resolvePlatformBaseUrl(config, signal) {
  const configured = normalizeString(config?.platformBaseUrl);
  if (configured) {
    return configured;
  }
  const devConfigured = readProcessEnv("TINYHAT_PLATFORM_BASE_URL");
  if (devConfigured) {
    return devConfigured;
  }
  return readMetadataValue(METADATA_BASE_URL_KEY, signal);
}

async function resolveBearerToken(config, signal) {
  const isDev =
    config?.devMode === true || readProcessEnv("TINYHAT_DEV_RUNTIME") === "1";
  if (isDev) {
    return (
      normalizeString(config?.devBearer) ||
      readProcessEnv("TINYHAT_DEV_BEARER") ||
      DEV_RUNTIME_BEARER
    );
  }
  const audience =
    normalizeString(config?.backendAudience) ||
    (await readMetadataValue(METADATA_AUDIENCE_KEY, signal));
  const url =
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/" +
    `default/identity?audience=${encodeURIComponent(audience)}&format=full`;
  const response = await fetch(url, {
    signal,
    headers: { "Metadata-Flavor": "Google" },
  });
  if (!response.ok) {
    throw new Error(
      `Could not fetch Tinyhat Computer identity token (${response.status}).`,
    );
  }
  return (await response.text()).trim();
}

async function readMetadataValue(key, signal) {
  const url =
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/" +
    encodeURIComponent(key);
  const response = await fetch(url, {
    signal,
    headers: { "Metadata-Flavor": "Google" },
  });
  if (!response.ok) {
    throw new Error(`Could not read metadata ${key} (${response.status}).`);
  }
  return (await response.text()).trim();
}

async function tryReadMetadataValue(key, signal) {
  try {
    return await readMetadataValue(key, signal);
  } catch {
    return "";
  }
}

function normalizeString(value) {
  return String(value || "").trim();
}

function readProcessEnv(name) {
  if (typeof process === "undefined" || !process.env) {
    return "";
  }
  return normalizeString(process.env[name]);
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function readDetail(payload, fallback) {
  if (payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return String(fallback || "").slice(0, 240) || "unknown error";
}
