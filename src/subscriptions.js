// ChatGPT BYO subscription helpers — runs OpenClaw's device-code CLI
// directly inside the Computer's sandbox (no backend round-trip).
//
// Per the v0.6.0-A architecture decision recorded on the tinyloop
// monorepo PR for issue #534: the Mini App entry point goes through
// the backend + supervisor heartbeat-command flow (browser can't exec
// a CLI), but the chat entry point keeps it simple — the plugin tool
// spawns `openclaw models auth login --provider openai-codex
// --device-code`, parses URL+code from stdout, returns them to the
// agent via the Telegram URL-button transport. The CLI keeps polling
// auth.openai.com in the background; when the user approves, OpenClaw
// writes the OAuth credential to `auth-profiles.json`; the supervisor's
// next tick detects the new profile and rewrites `openclaw.json`.

import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

const OPENAI_VERIFICATION_URL_PREFIX = "https://auth.openai.com/";
const DEVICE_CODE_PARSE_TIMEOUT_MS = 15_000;
const PROVIDER = "openai-codex";

// Resolve where OpenClaw stores per-agent auth profiles. Mirrors the
// supervisor's `OPENCLAW_STATE_DIR` resolution: prod default
// `/var/lib/tinyhat-openclaw/agents/<agentId>/agent/auth-profiles.json`;
// dev (`--dev`) `~/.openclaw-dev/agents/<agentId>/agent/auth-profiles.json`.
// AgentId default is `main` for single-agent runtimes.
function resolveAuthProfilesPath({ stateDir, agentId } = {}) {
  const resolvedStateDir =
    stateDir ||
    process.env.OPENCLAW_STATE_DIR ||
    (process.env.OPENCLAW_DEV
      ? join(homedir(), ".openclaw-dev")
      : "/var/lib/tinyhat-openclaw");
  const resolvedAgentId = agentId || process.env.OPENCLAW_AGENT_ID || "main";
  return join(
    resolvedStateDir,
    "agents",
    resolvedAgentId,
    "agent",
    "auth-profiles.json",
  );
}

// PTY-allocate a CLI invocation via `script`. OpenClaw 2026.5.19+'s
// `models auth login --device-code` rejects non-TTY stdin (verified in
// the preflight memo). Linux util-linux `script` supports
// `-qfc "<cmd>" /dev/null`; BSD `script` (macOS) takes the command as
// trailing positional args after `-q /dev/null`. We try Linux first and
// fall back to BSD for maintainer dev.
function spawnUnderPty(commandWords) {
  const isLinux = process.platform === "linux";
  if (isLinux) {
    return spawn(
      "script",
      ["-qfc", commandWords.map(shellQuote).join(" "), "/dev/null"],
      { stdio: ["ignore", "pipe", "pipe"], detached: true },
    );
  }
  return spawn("script", ["-q", "/dev/null", ...commandWords], {
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
}

function shellQuote(arg) {
  return /^[A-Za-z0-9_\-./@:=]+$/.test(arg) ? arg : `'${arg.replace(/'/g, "'\\''")}'`;
}

// Strip ANSI / cursor-positioning sequences so the URL/Code lines we
// match below are readable. OpenClaw's CLI emits pretty-print boxes
// with ANSI for the device-code panel.
function stripAnsi(text) {
  // ESC [ ... letter (CSI) — covers cursor moves, colors, screen clears.
  let cleaned = text.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, "");
  // ESC ] ... BEL / ESC \ (OSC) — terminal title etc.
  cleaned = cleaned.replace(/\x1b\][0-9;].*?(\x07|\x1b\\)/g, "");
  return cleaned.replace(/\r\n?/g, "\n");
}

const URL_LINE_RE = /URL:\s*(https:\/\/\S+)/;
const CODE_LINE_RE = /Code:\s*([A-Z0-9]{4}-[A-Z0-9]{5})/;

/**
 * Run `openclaw models auth login --provider openai-codex --device-code`
 * in a PTY, parse stdout until URL+code arrive (or timeout), and return
 * them. Leaves the CLI subprocess running (detached) so its background
 * poll of auth.openai.com can complete after the user approves —
 * OpenClaw writes the OAuth credential to disk on success.
 *
 * Returns `{ verificationUrl, userCode }` on success, or throws if the
 * CLI errors / times out before emitting URL+code.
 */
export async function startChatgptDeviceCodeLogin({
  openclawBin = "openclaw",
  timeoutMs = DEVICE_CODE_PARSE_TIMEOUT_MS,
  extraArgs = [],
} = {}) {
  const child = spawnUnderPty([
    openclawBin,
    "models",
    "auth",
    "login",
    "--provider",
    PROVIDER,
    "--device-code",
    ...extraArgs,
  ]);

  let buffer = "";
  let resolved = false;

  return await new Promise((resolve, reject) => {
    const settleSuccess = (verificationUrl, userCode) => {
      if (resolved) return;
      resolved = true;
      // Don't kill the subprocess — let it keep polling
      // auth.openai.com so OpenClaw can write the OAuth credential
      // to disk when the user approves. We unref so this Node
      // process can still exit normally.
      child.unref();
      // Validate URL allowlist defensively in-plugin too (the
      // Tinyhat backend allowlists this on the Mini App path; for
      // the chat path the platform never sees the URL, so the
      // plugin is the only check between OpenClaw's stdout and the
      // user's Telegram screen).
      if (!verificationUrl.startsWith(OPENAI_VERIFICATION_URL_PREFIX)) {
        return reject(
          new Error(
            `OpenClaw device-code emitted an off-allowlist URL: ${verificationUrl}`,
          ),
        );
      }
      resolve({ verificationUrl, userCode });
    };

    const settleFailure = (err) => {
      if (resolved) return;
      resolved = true;
      try {
        child.kill("SIGTERM");
      } catch {
        /* already dead */
      }
      reject(err);
    };

    const timeoutHandle = setTimeout(() => {
      settleFailure(
        new Error(
          `Timed out after ${timeoutMs}ms waiting for OpenClaw device-code URL+code`,
        ),
      );
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      buffer += stripAnsi(chunk.toString("utf8"));
      const urlMatch = buffer.match(URL_LINE_RE);
      const codeMatch = buffer.match(CODE_LINE_RE);
      if (urlMatch && codeMatch) {
        clearTimeout(timeoutHandle);
        settleSuccess(urlMatch[1], codeMatch[1]);
      }
    });
    child.stderr.on("data", (chunk) => {
      buffer += stripAnsi(chunk.toString("utf8"));
    });
    child.on("error", (err) => {
      clearTimeout(timeoutHandle);
      settleFailure(err);
    });
    child.on("exit", (code) => {
      if (resolved) return;
      clearTimeout(timeoutHandle);
      // Surface a known-error case verbatim per preflight memo §Q1
      // so the agent can relay the non-secret reason to the user.
      const hint = buffer.includes("device-code login")
        ? buffer
        : `openclaw exited (${code}) before URL+code: ${buffer.slice(-400)}`;
      settleFailure(new Error(hint));
    });
  });
}

/**
 * Wipe the per-agent OAuth credential for `openai-codex`.
 *
 * Edits `auth-profiles.json` to remove the `openai-codex:*` entries
 * (preserves any other-provider profiles). If the resulting file is
 * empty, leaves it as `{ "version": 1, "profiles": {} }` so the file
 * shape stays valid for the next login.
 *
 * The supervisor (PR-B on tinyloophub/tinyhat--runtimes--openclaw) is
 * the canonical wipe path for admin-driven revert (reassignment /
 * recycle), and it also strips the matching `auth.profiles.<id>` entry
 * from `openclaw.json` per preflight §Q3. The chat tool path leaves
 * that to the supervisor's next tick — we only have to remove the
 * file-side credential here.
 *
 * Returns `{ removedProfiles }` listing the profile ids wiped. Throws
 * if the auth-profiles file doesn't exist (nothing to wipe).
 */
export async function revertChatgptSubscriptionAuth({ authProfilesPath } = {}) {
  const path = authProfilesPath || resolveAuthProfilesPath();
  let raw;
  try {
    raw = await fs.readFile(path, "utf8");
  } catch (err) {
    if (err && err.code === "ENOENT") {
      return { removedProfiles: [] };
    }
    throw err;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`auth-profiles.json at ${path} is not valid JSON`);
  }
  const profiles =
    parsed && typeof parsed === "object" && parsed.profiles && typeof parsed.profiles === "object"
      ? parsed.profiles
      : {};
  const removed = [];
  for (const profileId of Object.keys(profiles)) {
    if (profileId.startsWith(`${PROVIDER}:`)) {
      delete profiles[profileId];
      removed.push(profileId);
    }
  }
  if (removed.length === 0) {
    return { removedProfiles: [] };
  }
  const next = {
    version: parsed && typeof parsed === "object" && parsed.version ? parsed.version : 1,
    profiles,
  };
  // Atomic write so a partial truncate can't strand other profiles.
  const tmpPath = `${path}.tmp`;
  await fs.mkdir(dirname(path), { recursive: true });
  await fs.writeFile(tmpPath, JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
  await fs.rename(tmpPath, path);
  return { removedProfiles: removed };
}

// Exposed for tests; treat as internal otherwise.
export const __internal = {
  resolveAuthProfilesPath,
  spawnUnderPty,
  stripAnsi,
  URL_LINE_RE,
  CODE_LINE_RE,
};
