#!/usr/bin/env node
// Loadability self-check for the Tinyhat OpenClaw plugin (#124).
//
// "Installed" is not "loaded": OpenClaw skips an enabled extension it
// cannot read or import WITHOUT failing the gateway, and
// `openclaw plugins inspect` reports registration, not loadability —
// it says `status: "loaded"` even when the extension entry is
// unreadable. This script is the loud check: run it AS THE USER THE
// GATEWAY RUNS AS against a plugin checkout or an installed extension
// directory, and it fails with the exact broken path or import error.
//
//   node scripts/check_plugin_load.mjs                       # repo checkout
//   node scripts/check_plugin_load.mjs --plugin-dir <dir>    # installed copy
//   node scripts/check_plugin_load.mjs --require-import      # CI: import must run
//
// Checks, in order:
//   1. manifest  — openclaw.plugin.json + package.json parse, id/entry agree
//   2. readable  — every packaged file the loader needs (manifests, src/,
//                  skills/) is readable by the CURRENT user; the classic
//                  failure is a privileged install leaving the tree
//                  root-owned while the gateway runs unprivileged
//   3. import    — the extension entry actually imports, and registering
//                  against a stub host yields the canonical tinyhat_* tools
//                  (skipped with a notice when the `openclaw` SDK is not
//                  installed next to the plugin, unless --require-import)
//
// Exit code 0 = loadable; 1 = at least one FAIL line printed.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

// Floor mirrored from REQUIRED_TOOLS in scripts/validate_openclaw_package.py.
// The authoritative expected set is `contracts.tools` from
// openclaw.plugin.json; this floor only guards against a truncated or
// tampered manifest on an installed copy (a manifest that "declares"
// fewer tools must not shrink the contract below this).
const REQUIRED_TOOLS_FLOOR = [
  "tinyhat_get_platform_status",
  "tinyhat_list_installed_packages",
  "tinyhat_list_runtime_secrets",
  "tinyhat_request_runtime_secret",
  "tinyhat_open_manage_computer_link",
  "tinyhat_open_software_updates_link",
  "tinyhat_open_terminal_link",
  "tinyhat_report_problem",
  "tinyhat_secret_command",
];

// Floor mirrored from REQUIRED_SKILLS in scripts/validate_openclaw_package.py,
// same role as REQUIRED_TOOLS_FLOOR: `contracts.skills` is authoritative,
// the floor only guards against a truncated or tampered installed manifest.
const REQUIRED_SKILLS_FLOOR = [
  "tinyhat-platform",
  "tinyhat-secrets",
  "tinyhat-computer-access",
  "tinyhat-software-updates",
  "tinyhat-runtime-status",
  "tinyhat-package-inventory",
  "tinyhat-support-report",
  "tinyhat-subscriptions",
];

const VERSION_SHAPE = /^\d+(\.\d+)+$/;

const PACKAGED_FILES = ["openclaw.plugin.json", "package.json"];
const DEFAULT_SKILL_ROOTS = ["skills"];

function parseArgs(argv) {
  const args = { pluginDir: process.cwd(), requireImport: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--plugin-dir") {
      args.pluginDir = path.resolve(String(argv[i + 1] || ""));
      i += 1;
    } else if (arg === "--require-import") {
      args.requireImport = true;
    } else if (arg === "--help" || arg === "-h") {
      console.log(
        "usage: check_plugin_load.mjs [--plugin-dir <dir>] [--require-import]",
      );
      process.exit(0);
    } else {
      console.error(`FAIL: unknown argument ${arg}`);
      process.exit(1);
    }
  }
  return args;
}

const failures = [];
function ok(message) {
  console.log(`ok: ${message}`);
}
function fail(message) {
  failures.push(message);
  console.error(`FAIL: ${message}`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function checkManifests(pluginDir) {
  let manifest = null;
  let pkg = null;
  try {
    manifest = readJson(path.join(pluginDir, "openclaw.plugin.json"));
  } catch (error) {
    fail(`openclaw.plugin.json unreadable or invalid: ${error.message}`);
  }
  try {
    pkg = readJson(path.join(pluginDir, "package.json"));
  } catch (error) {
    fail(`package.json unreadable or invalid: ${error.message}`);
  }
  if (manifest && manifest.id !== "tinyhat") {
    fail(`openclaw.plugin.json id is ${JSON.stringify(manifest.id)}, expected "tinyhat"`);
  }
  const declaredTools = Array.isArray(manifest?.contracts?.tools)
    ? manifest.contracts.tools.filter((name) => typeof name === "string" && name)
    : [];
  if (manifest && declaredTools.length === 0) {
    fail("openclaw.plugin.json contracts.tools is missing or empty");
  }
  const declaredSkills = Array.isArray(manifest?.contracts?.skills)
    ? manifest.contracts.skills.filter((name) => typeof name === "string" && name)
    : [];
  if (manifest && declaredSkills.length === 0) {
    fail("openclaw.plugin.json contracts.skills is missing or empty");
  } else if (manifest) {
    const missingFloor = REQUIRED_SKILLS_FLOOR.filter(
      (name) => !declaredSkills.includes(name),
    );
    if (missingFloor.length > 0) {
      fail(
        `openclaw.plugin.json contracts.skills shrank below the floor: ${missingFloor.join(", ")}`,
      );
    }
  }
  checkFrameworkRange(manifest);
  const skillRoots =
    Array.isArray(manifest?.skills) && manifest.skills.length > 0
      ? manifest.skills.filter((name) => typeof name === "string" && name)
      : DEFAULT_SKILL_ROOTS;
  const entries = pkg?.openclaw?.extensions;
  if (!Array.isArray(entries) || entries.length === 0) {
    fail("package.json openclaw.extensions is missing or empty");
    return { manifest, pkg, entry: null, declaredTools, declaredSkills, skillRoots };
  }
  ok("manifests parse and agree on the extension entry");
  return {
    manifest,
    pkg,
    entry: path.resolve(pluginDir, entries[0]),
    declaredTools,
    declaredSkills,
    skillRoots,
  };
}

function checkFrameworkRange(manifest) {
  if (!manifest) {
    return;
  }
  const framework = manifest?.contracts?.framework;
  if (!framework || typeof framework !== "object" || Array.isArray(framework)) {
    fail("openclaw.plugin.json contracts.framework is missing");
    return;
  }
  if (framework.name !== "openclaw") {
    fail(
      `contracts.framework.name is ${JSON.stringify(framework.name)}, expected "openclaw"`,
    );
  }
  if (typeof framework.minimum !== "string" || !VERSION_SHAPE.test(framework.minimum)) {
    fail(
      `contracts.framework.minimum must be a dotted version, got ${JSON.stringify(framework.minimum)}`,
    );
  }
  if (
    framework.maximum !== undefined &&
    (typeof framework.maximum !== "string" || !VERSION_SHAPE.test(framework.maximum))
  ) {
    fail(
      `contracts.framework.maximum must be a dotted version when set, got ${JSON.stringify(framework.maximum)}`,
    );
  }
  ok(
    `framework range declared: ${framework.name} >= ${framework.minimum}` +
      (framework.maximum ? ` <= ${framework.maximum}` : ""),
  );
}

function walkPackagedPaths(pluginDir, skillRoots) {
  const targets = [];
  for (const file of PACKAGED_FILES) {
    targets.push(path.join(pluginDir, file));
  }
  // src/ and every manifest-declared skills root are REQUIRED packaged
  // dirs: an install copy that drops one of them is exactly the silent
  // capability loss this check exists to make loud.
  const requiredDirs = ["src", ...skillRoots];
  const stack = [];
  for (const dir of requiredDirs) {
    const absolute = path.join(pluginDir, dir);
    if (!fs.existsSync(absolute)) {
      fail(`required packaged directory is missing: ${absolute}`);
      continue;
    }
    stack.push(absolute);
  }
  while (stack.length > 0) {
    const current = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch (error) {
      targets.push(current);
      if (error.code !== "ENOENT") {
        fail(
          `directory not listable by ${describeUser()}: ${current} (${error.code})`,
        );
      }
      continue;
    }
    targets.push(current);
    for (const entry of entries) {
      const child = path.join(current, entry.name);
      if (entry.name === "node_modules") {
        continue; // peer-dep link; the import check exercises it for real
      }
      if (entry.isDirectory()) {
        stack.push(child);
      } else {
        targets.push(child);
      }
    }
  }
  return targets;
}

function checkSkillContent(pluginDir, skillRoots, declaredSkills) {
  // A present-but-gutted skills root must be as loud as a missing one:
  // OpenClaw mounts skills from these roots, so zero SKILL.md entries
  // means the agent silently loses every tinyhat skill.
  const found = new Set();
  for (const root of skillRoots) {
    const absolute = path.join(pluginDir, root);
    let skillFiles = [];
    try {
      skillFiles = fs
        .readdirSync(absolute, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .filter((entry) =>
          fs.existsSync(path.join(absolute, entry.name, "SKILL.md")),
        );
    } catch {
      // Missing/unreadable roots are reported by the readability walk.
      continue;
    }
    if (skillFiles.length === 0) {
      fail(`skills root has no <skill>/SKILL.md entries: ${absolute}`);
    } else {
      ok(`skills root ${root}/ ships ${skillFiles.length} skill(s)`);
    }
    for (const entry of skillFiles) {
      found.add(entry.name);
    }
  }
  // The declared set is the contract: every contracts.skills entry must
  // survive packaging/install as <root>/<name>/SKILL.md. A dropped dir
  // is exactly the silent capability loss this check makes loud.
  const missingDeclared = (declaredSkills || []).filter(
    (name) => !found.has(name),
  );
  if (missingDeclared.length > 0) {
    fail(
      `manifest-declared skills are missing from the tree: ${missingDeclared.join(", ")}`,
    );
  } else if ((declaredSkills || []).length > 0) {
    ok(`all ${declaredSkills.length} manifest-declared skills are present`);
  }
}

function describeUser() {
  try {
    const uid = typeof process.getuid === "function" ? process.getuid() : "?";
    return `uid=${uid}`;
  } catch {
    return "the current user";
  }
}

function checkReadability(pluginDir, skillRoots) {
  let broken = 0;
  for (const target of walkPackagedPaths(pluginDir, skillRoots)) {
    let stats;
    try {
      stats = fs.statSync(target);
    } catch (error) {
      if (error.code === "ENOENT") {
        continue; // missing optional path; manifest checks cover required ones
      }
      broken += 1;
      fail(`not statable by ${describeUser()}: ${target} (${error.code})`);
      continue;
    }
    const mode = stats.isDirectory()
      ? fs.constants.R_OK | fs.constants.X_OK
      : fs.constants.R_OK;
    try {
      fs.accessSync(target, mode);
    } catch {
      broken += 1;
      fail(`not readable by ${describeUser()}: ${target}`);
    }
  }
  if (broken > 0) {
    fail(
      `${broken} packaged path(s) are unreadable — if this plugin was ` +
        "installed by a privileged process, chown the installed tree " +
        "(and the checkout) to the user the gateway runs as",
    );
    return false;
  }
  ok(`every packaged path is readable by ${describeUser()}`);
  return true;
}

async function checkImport(entry, pkg, declaredTools, requireImport) {
  if (!entry) {
    fail("no extension entry to import");
    return;
  }
  let mod;
  try {
    mod = await import(pathToFileURL(entry).href);
  } catch (error) {
    const message = String(error?.message || error);
    if (
      !requireImport &&
      error?.code === "ERR_MODULE_NOT_FOUND" &&
      /'openclaw/.test(message)
    ) {
      console.log(
        "skip: import check needs the `openclaw` package installed next " +
          "to the plugin (npm install --no-save openclaw); rerun with it " +
          "or pass --require-import in CI",
      );
      return;
    }
    fail(`extension entry failed to import: ${message}`);
    return;
  }
  const plugin = mod?.default;
  if (!plugin || plugin.id !== "tinyhat") {
    fail(
      `extension default export is not the tinyhat plugin (id=${plugin?.id})`,
    );
    return;
  }
  ok(`extension entry imports and exports plugin id "tinyhat"`);

  const toolNames = [];
  const stubHost = new Proxy(
    {},
    {
      get(_target, prop) {
        return (...args) => {
          if (String(prop) === "registerTool") {
            // Plain tools carry the name on the definition; factory tools
            // carry it on the options argument.
            const name = args[0]?.name || args[1]?.name;
            if (typeof name === "string" && name) {
              toolNames.push(name);
            }
          }
          return undefined;
        };
      },
    },
  );
  try {
    await plugin.register(stubHost);
  } catch (error) {
    fail(`plugin.register() threw against a stub host: ${error.message}`);
    return;
  }
  // The manifest is the authoritative tool contract; the hardcoded floor
  // only stops a truncated installed manifest from shrinking it.
  const expected = [...new Set([...declaredTools, ...REQUIRED_TOOLS_FLOOR])];
  const missing = expected.filter((name) => !toolNames.includes(name));
  const undeclared = toolNames.filter((name) => !expected.includes(name));
  const offBrand = toolNames.filter((name) => !name.startsWith("tinyhat_"));
  if (missing.length > 0) {
    fail(
      `registration is missing manifest-declared tools: ${missing.join(", ")}`,
    );
  }
  if (undeclared.length > 0) {
    fail(
      "registration produced tools the manifest does not declare " +
        `(manifest drift): ${undeclared.join(", ")}`,
    );
  }
  if (offBrand.length > 0) {
    fail(`registration produced non-tinyhat tool names: ${offBrand.join(", ")}`);
  }
  if (missing.length === 0 && undeclared.length === 0 && offBrand.length === 0) {
    ok(
      `registration yields ${toolNames.length} tinyhat_* tools ` +
        `(all ${expected.length} manifest-declared tools present)`,
    );
  }
  const declared = pkg?.version;
  if (declared) {
    ok(`plugin version under check: ${declared}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(args.pluginDir)) {
    fail(`plugin dir does not exist: ${args.pluginDir}`);
  } else {
    console.log(`checking plugin dir: ${args.pluginDir} as ${describeUser()}`);
    const { pkg, entry, declaredTools, declaredSkills, skillRoots } =
      checkManifests(args.pluginDir);
    const readable = checkReadability(args.pluginDir, skillRoots);
    checkSkillContent(args.pluginDir, skillRoots, declaredSkills);
    if (readable || args.requireImport) {
      await checkImport(entry, pkg, declaredTools, args.requireImport);
    } else {
      console.log("skip: import check skipped while packaged paths are unreadable");
    }
  }
  if (failures.length > 0) {
    console.error(`verdict: NOT LOADABLE (${failures.length} failure(s))`);
    process.exit(1);
  }
  console.log("verdict: loadable");
}

await main();
