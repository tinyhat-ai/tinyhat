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

function runCheck(args) {
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: "utf8",
  });
  return {
    code: result.status,
    out: `${result.stdout}\n${result.stderr}`,
  };
}

// A minimal synthetic plugin dir: enough shape for the manifest and
// readability checks without importing the real OpenClaw SDK.
function makeFixturePlugin() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-loadcheck-"));
  fs.writeFileSync(
    path.join(dir, "openclaw.plugin.json"),
    JSON.stringify({ id: "tinyhat" }),
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
  fs.writeFileSync(
    path.join(dir, "src", "index.js"),
    'import "openclaw/plugin-sdk/tool-plugin";\nexport default {};\n',
  );
  fs.mkdirSync(path.join(dir, "skills", "tinyhat-platform"), {
    recursive: true,
  });
  fs.writeFileSync(
    path.join(dir, "skills", "tinyhat-platform", "SKILL.md"),
    "# fixture\n",
  );
  return dir;
}

test("passes a readable fixture and skips import when openclaw is absent", () => {
  const dir = makeFixturePlugin();
  const { code, out } = runCheck(["--plugin-dir", dir]);
  assert.equal(code, 0, out);
  assert.match(out, /every packaged path is readable/);
  assert.match(out, /skip: import check needs the `openclaw` package/);
  assert.match(out, /verdict: loadable/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("--require-import turns a missing openclaw SDK into a loud failure", () => {
  const dir = makeFixturePlugin();
  const { code, out } = runCheck(["--plugin-dir", dir, "--require-import"]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: extension entry failed to import/);
  assert.match(out, /verdict: NOT LOADABLE/);
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

test("a missing plugin dir fails loudly", () => {
  const { code, out } = runCheck([
    "--plugin-dir",
    path.join(os.tmpdir(), "tinyhat-loadcheck-does-not-exist"),
  ]);
  assert.equal(code, 1, out);
  assert.match(out, /FAIL: plugin dir does not exist/);
});
