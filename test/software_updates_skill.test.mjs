import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const REPO_ROOT = path.resolve(new URL("..", import.meta.url).pathname);

test("manifest registers the Software / Updates operation", () => {
  const manifest = JSON.parse(
    readFileSync(path.join(REPO_ROOT, "openclaw.plugin.json"), "utf8"),
  );

  assert.ok(
    manifest.contracts.tools.includes("tinyhat_open_software_updates_link"),
  );
  const operation = manifest.contracts.operations.find(
    (op) => op.name === "computer.software_updates",
  );
  assert.ok(operation);
  assert.equal(operation.tool, "tinyhat_open_software_updates_link");
  assert.equal(operation.userSurface, "telegram_web_app_button");
});

test("software update skill explains latest, rollback, and heartbeat apply", () => {
  const skill = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-software-updates/SKILL.md"),
    "utf8",
  );

  assert.match(skill, /tinyhat_open_software_updates_link/);
  assert.match(skill, /Update to latest/);
  assert.match(skill, /rollback/);
  assert.match(skill, /heartbeat/);
  assert.match(skill, /not\s+recreated/);
});

test("platform router delegates upgrade intents to the focused skill", () => {
  const router = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-platform/SKILL.md"),
    "utf8",
  );
  const runtime = readFileSync(
    path.join(REPO_ROOT, "skills/tinyhat-runtime-status/SKILL.md"),
    "utf8",
  );

  assert.match(router, /tinyhat-software-updates/);
  assert.match(router, /tinyhat_open_software_updates_link/);
  assert.match(runtime, /route to `tinyhat-software-updates`/);
});
