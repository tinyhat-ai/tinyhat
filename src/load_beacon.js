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

function cleanNameList(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((name) => typeof name === "string" && name);
}

export function readDeclaredManifest() {
  // The declared capability surface from openclaw.plugin.json, so the
  // beacon covers WHAT loaded, not just THAT something loaded. A host
  // that cannot inspect the live tool registry can compare this
  // beacon-carried declaration against the manifest it expects without
  // inventing data. Returns null when the manifest is unreadable — the
  // beacon then degrades to the load facts alone.
  try {
    const manifest = JSON.parse(
      fs.readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
    );
    const contracts = manifest?.contracts ?? {};
    const declared = {
      tools: cleanNameList(contracts.tools),
      skills: cleanNameList(contracts.skills),
    };
    const framework = contracts.framework;
    if (framework && typeof framework === "object" && !Array.isArray(framework)) {
      declared.framework = framework;
    }
    return declared;
  } catch {
    return null;
  }
}

export function listSkillsPresent(skillRoots) {
  // Skill directories that actually carry a SKILL.md at load time,
  // under each manifest-declared skills root. This is the loader's
  // view of the tree; a declared skill absent from this list is the
  // silent capability loss the beacon exists to make observable.
  const present = [];
  for (const root of Array.isArray(skillRoots) ? skillRoots : []) {
    if (typeof root !== "string" || !root) {
      continue;
    }
    let entries;
    try {
      entries = fs.readdirSync(new URL(`../${root}/`, import.meta.url), {
        withFileTypes: true,
      });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }
      try {
        fs.accessSync(
          new URL(`../${root}/${entry.name}/SKILL.md`, import.meta.url),
          fs.constants.R_OK,
        );
        present.push(entry.name);
      } catch {
        // Unreadable or missing SKILL.md: not present from the
        // loader's point of view.
      }
    }
  }
  return present.sort();
}

export function readDeclaredSkillRoots() {
  try {
    const manifest = JSON.parse(
      fs.readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
    );
    const roots = cleanNameList(manifest?.skills);
    return roots.length > 0 ? roots : ["skills"];
  } catch {
    return ["skills"];
  }
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
    const payload = {
      plugin: "tinyhat",
      version,
      loaded_at: now().toISOString(),
      pid: process.pid,
      node: process.version,
    };
    // Manifest coverage (best-effort, never load-breaking): the
    // declared tools/skills/framework range this load was built from,
    // plus the skill dirs the loader can actually see. Hosts use this
    // to verify the declared manifest without registry access.
    const declared = readDeclaredManifest();
    if (declared) {
      payload.declared = declared;
      payload.skills_present = listSkillsPresent(readDeclaredSkillRoots());
    }
    fs.writeFileSync(target, JSON.stringify(payload, null, 2) + "\n");
  } catch {
    // Best-effort: an unwritable state dir degrades to the log line.
  }
  return line;
}
