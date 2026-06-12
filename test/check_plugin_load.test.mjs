import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SCRIPT = fileURLToPath(
  new URL("../scripts/check_plugin_load.mjs", import.meta.url),
);

const FIXTURE_TOOLS = [
  "tinyhat_get_platform_status",
  "tinyhat_list_installed_packages",
  "tinyhat_list_runtime_secrets",
  "tinyhat_request_runtime_secret",
  "tinyhat_open_manage_computer_link",
  "tinyhat_open_software_updates_link",
  "tinyhat_open_terminal_link",
  "tinyhat_report_problem",
  "tinyhat_secret_command",
  "tinyhat_open_chatgpt_subscription_link",
  "tinyhat_open_chatgpt_subscription_prerequisite_help",
  "tinyhat_revert_to_platform_credits",
];

// The skills floor the script demands even from a truncated manifest.
const FIXTURE_SKILLS = [
  "tinyhat-platform",
  "tinyhat-secrets",
  "tinyhat-computer-access",
  "tinyhat-software-updates",
  "tinyhat-runtime-status",
  "tinyhat-package-inventory",
  "tinyhat-support-report",
];

const FIXTURE_FRAMEWORK = { name: "openclaw", minimum: "2026.6.1" };

function runCheck(args) {
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: "utf8",
  });
  return {
    code: result.status,
    out: `${result.stdout}\n${result.stderr}`,
  };
}

// A minimal synthetic plugin dir. By default the entry is SDK-free and
// registers exactly the manifest-declared tools, so the import leg runs
// in unit tests without an `openclaw` install; pass
// `entryImportsOpenclaw: true` to exercise the SDK-missing paths.
function makeFixturePlugin({
  declaredTools = FIXTURE_TOOLS,
  registerTools = FIXTURE_TOOLS,
  declaredSkills = FIXTURE_SKILLS,
  shippedSkills = null,
  framework = FIXTURE_FRAMEWORK,
  includeSkills = true,
  entryImportsOpenclaw = false,
} = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-loadcheck-"));
  const contracts = { tools: declaredTools };
  if (declaredSkills !== null) {
    contracts.skills = declaredSkills;
  }
  if (framework !== null) {
    contracts.framework = framework;
  }
  fs.writeFileSync(
    path.join(dir, "openclaw.plugin.json"),
    JSON.stringify({
      id: "tinyhat",
      skills: ["skills"],
      contracts,
    }),
  );
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({
      name: "tinyhat",
      version: "0.0.0-test",
      type: "module",
      openclaw: { extensions: ["./src/index.js"] },
    }),
  );
  fs.mkdirSync(path.join(dir, "src"));
  const entrySource = entryImportsOpenclaw
    ? 'import "openclaw/plugin-sdk/tool-plugin";\nexport default {};\n'
    : `const TOOLS = ${JSON.stringify(registerTools)};
export default {
  id: "tinyhat",
  register(api) {
    for (const name of TOOLS) {
      api.registerTool({ name, execute: () => {} });
    }
  },
};
`;
  fs.writeFileSync(path.join(dir, "src", "index.js"), entrySource);
  if (includeSkills) {
    for (const name of shippedSkills ?? declaredSkills ?? ["tinyhat-platform"]) {
      fs.mkdirSync(path.join(dir, "skills", name), { recursive: true });
      fs.writeFileSync(path.join(dir, "skills", name, "SKILL.md"), "# fixture\n");
    }
  }
  return dir;
}

test("passes a fixture whose registration matches the manifest contract", () => {
  const dir = makeFixturePlugin();
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 0, out);
  assert.match(out, /every packaged path is readable/);
  assert.match(out, /skills root skills\/ ships 7 skill\(s\)/);
  assert.match(out, /all 7 manifest-declared skills are present/);
  assert.match(out, /framework range declared: openclaw >= 2026\.6\.1/);
  assert.match(out, /all 12 manifest-declared tools present/);
  assert.match(out, /verdict: loadable/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a manifest-declared skill missing from the tree fails loudly", () => {
  const dir = makeFixturePlugin({
    shippedSkills: FIXTURE_SKILLS.filter((name) => name !== "tinyhat-secrets"),
  });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(
    out,
    /FAIL: manifest-declared skills are missing from the tree: tinyhat-secrets/,
  );
  assert.match(out, /verdict: NOT LOADABLE/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a manifest without contracts.skills fails loudly", () => {
  const dir = makeFixturePlugin({ declaredSkills: null });
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(
    out,
    /FAIL: openclaw.plugin.json contracts.skills is missing or empty/,
  );
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a truncated manifest cannot shrink the skills contract below the floor", () => {
  const dir = makeFixturePlugin({
    declaredSkills: ["tinyhat-platform"],
    shippedSkills: ["tinyhat-platform"],
  });
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: openclaw.plugin.json contracts.skills shrank below the floor/);
  assert.match(out, /tinyhat-secrets/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a manifest without contracts.framework fails loudly", () => {
  const dir = makeFixturePlugin({ framework: null });
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: openclaw.plugin.json contracts.framework is missing/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a malformed framework range fails loudly", () => {
  const dir = makeFixturePlugin({
    framework: { name: "openclaw", minimum: "latest" },
  });
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(
    out,
    /FAIL: contracts.framework.minimum must be a dotted version, got "latest"/,
  );
  fs.rmSync(dir, { recursive: true, force: true });
});

test("skips import when the openclaw SDK is absent (non-CI default)", () => {
  const dir = makeFixturePlugin({ entryImportsOpenclaw: true });
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 0, out);
  assert.match(out, /skip: import check needs the `openclaw` package/);
  assert.match(out, /verdict: loadable/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("--require-import turns a missing openclaw SDK into a loud failure", () => {
  const dir = makeFixturePlugin({ entryImportsOpenclaw: true });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: extension entry failed to import/);
  assert.match(out, /verdict: NOT LOADABLE/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a dropped skills/ tree fails loudly", () => {
  // Review repro on the first iteration of this script: an installed
  // copy without skills/ must never report loadable — the agent would
  // silently lose every tinyhat skill.
  const dir = makeFixturePlugin({ includeSkills: false });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(
    out,
    new RegExp(
      `FAIL: required packaged directory is missing: ${path.join(dir, "skills")}`,
    ),
  );
  assert.match(out, /verdict: NOT LOADABLE/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a skills root without SKILL.md entries fails loudly", () => {
  const dir = makeFixturePlugin({ includeSkills: false });
  fs.mkdirSync(path.join(dir, "skills", "empty-skill"), { recursive: true });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: skills root has no <skill>\/SKILL\.md entries/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("registering only a subset of manifest-declared tools fails loudly", () => {
  // Review repro: nine of twelve declared tools must not pass.
  const dir = makeFixturePlugin({ registerTools: FIXTURE_TOOLS.slice(0, 9) });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: registration is missing manifest-declared tools/);
  assert.match(out, /tinyhat_open_chatgpt_subscription_link/);
  assert.match(out, /verdict: NOT LOADABLE/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a truncated manifest cannot shrink the contract below the floor", () => {
  // An installed manifest declaring a single tool must still demand the
  // canonical floor set.
  const dir = makeFixturePlugin({
    declaredTools: ["tinyhat_get_platform_status"],
    registerTools: ["tinyhat_get_platform_status"],
  });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: registration is missing manifest-declared tools/);
  assert.match(out, /tinyhat_secret_command/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("registering a tool the manifest does not declare fails as drift", () => {
  const dir = makeFixturePlugin({
    registerTools: [...FIXTURE_TOOLS, "tinyhat_surprise_tool"],
  });
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /manifest drift.*tinyhat_surprise_tool/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("an unreadable packaged file fails loudly with the exact path", (t) => {
  if (typeof process.getuid === "function" && process.getuid() === 0) {
    t.skip("running as root: chmod 000 stays readable");
    return;
  }
  const dir = makeFixturePlugin();
  const target = path.join(dir, "src", "index.js");
  fs.chmodSync(target, 0o000);

  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(out, new RegExp(`FAIL: not readable by uid=\\d+: ${target}`));
  assert.match(out, /chown the installed tree/);
  assert.match(out, /verdict: NOT LOADABLE/);

  fs.chmodSync(target, 0o644);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a manifest without contracts.tools fails loudly", () => {
  const dir = makeFixturePlugin();
  fs.writeFileSync(
    path.join(dir, "openclaw.plugin.json"),
    JSON.stringify({ id: "tinyhat", skills: ["skills"] }),
  );
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: openclaw.plugin.json contracts.tools is missing or empty/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("a missing plugin dir fails loudly", () => {
  const { code, out } = runCheck([
    "--plugin-dir",
    path.join(os.tmpdir(), "tinyhat-loadcheck-does-not-exist"),
  ]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: plugin dir does not exist/);
});
