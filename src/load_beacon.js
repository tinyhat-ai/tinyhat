// Load beacon: make a successful plugin load loudly observable.
//
// The plugin cannot report its own absence — if OpenClaw skips an
// enabled-but-unloadable extension (unreadable files after a privileged
// install, an SDK API mismatch, anything), no plugin code runs and the
// agent silently loses every tinyhat tool and skill. This module is the
// plugin's half of making that failure detectable from the outside:
//
//   1. one unmistakable log line on load, so gateway logs show explicit
//      success (its absence while the plugin is enabled = load failure);
//   2. a best-effort beacon file under the OpenClaw state dir, so a host
//      supervisor or `scripts/check_plugin_load.mjs` can verify the load
//      deterministically instead of inferring it from "install succeeded".
//
// The beacon must NEVER break the plugin: every step is wrapped, and a
// failure to write degrades to the log line alone.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const BEACON_FILENAME = "tinyhat-plugin-loaded.json";

export function readOwnPackageVersion() {
  try {
    const raw = fs.readFileSync(
      new URL("../package.json", import.meta.url),
      "utf8",
    );
    const version = JSON.parse(raw)?.version;
    return typeof version === "string" && version ? version : "unknown";
  } catch {
    return "unknown";
  }
}

export function beaconPath(env = process.env) {
  const stateDir =
    String(env?.OPENCLAW_STATE_DIR || "").trim() ||
    path.join(os.homedir(), ".openclaw");
  return path.join(stateDir, BEACON_FILENAME);
}

export function announcePluginLoaded({
  env = process.env,
  log = console.error,
  now = () => new Date(),
} = {}) {
  const version = readOwnPackageVersion();
  const line = `[tinyhat] plugin loaded v${version} pid=${process.pid} node=${process.version}`;
  try {
    log(line);
  } catch {
    // A broken logger must not break the load.
  }
  try {
    const target = beaconPath(env);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(
      target,
      JSON.stringify(
        {
          plugin: "tinyhat",
          version,
          loaded_at: now().toISOString(),
          pid: process.pid,
          node: process.version,
        },
        null,
        2,
      ) + "\n",
    );
  } catch {
    // Best-effort: an unwritable state dir degrades to the log line.
  }
  return line;
}
