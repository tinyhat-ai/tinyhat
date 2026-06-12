import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  BEACON_FILENAME,
  announcePluginLoaded,
  beaconPath,
  listSkillsPresent,
  readDeclaredManifest,
  readDeclaredSkillRoots,
  readOwnPackageVersion,
} from "../src/load_beacon.js";

test("beaconPath honours OPENCLAW_STATE_DIR and falls back to ~/.openclaw", () => {
  assert.equal(
    beaconPath({ OPENCLAW_STATE_DIR: "/tmp/some-state" }),
    path.join("/tmp/some-state", BEACON_FILENAME),
  );
  assert.equal(
    beaconPath({}),
    path.join(os.homedir(), ".openclaw", BEACON_FILENAME),
  );
});

test("announcePluginLoaded logs one line and writes the beacon file", () => {
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-beacon-"));
  const lines = [];
  const line = announcePluginLoaded({
    env: { OPENCLAW_STATE_DIR: stateDir },
    log: (message) => lines.push(message),
    now: () => new Date("2026-06-11T00:00:00Z"),
  });

  assert.match(line, /^\[tinyhat\] plugin loaded v/);
  assert.deepEqual(lines, [line]);

  const beacon = JSON.parse(
    fs.readFileSync(path.join(stateDir, BEACON_FILENAME), "utf8"),
  );
  assert.equal(beacon.plugin, "tinyhat");
  assert.equal(beacon.version, readOwnPackageVersion());
  assert.equal(beacon.loaded_at, "2026-06-11T00:00:00.000Z");
  assert.equal(beacon.pid, process.pid);
  assert.equal(beacon.node, process.version);

  fs.rmSync(stateDir, { recursive: true, force: true });
});

test("the beacon covers the declared manifest and the skills present", () => {
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-beacon-mf-"));
  announcePluginLoaded({
    env: { OPENCLAW_STATE_DIR: stateDir },
    log: () => {},
  });

  const beacon = JSON.parse(
    fs.readFileSync(path.join(stateDir, BEACON_FILENAME), "utf8"),
  );
  const manifest = JSON.parse(
    fs.readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
  );
  // The beacon's declared block IS the manifest contract — a host that
  // can only read the beacon must see the same declaration the
  // manifest carries, not a paraphrase.
  assert.deepEqual(beacon.declared.tools, manifest.contracts.tools);
  assert.deepEqual(beacon.declared.skills, manifest.contracts.skills);
  assert.deepEqual(beacon.declared.framework, manifest.contracts.framework);
  // Every declared skill ships in this checkout, so the loader's view
  // must report all of them present.
  assert.deepEqual(
    beacon.skills_present,
    [...manifest.contracts.skills].sort(),
  );
  // The runtime caps beacon reads at 8 KiB; a manifest-covering beacon
  // must stay comfortably inside that.
  const size = fs.statSync(path.join(stateDir, BEACON_FILENAME)).size;
  assert.ok(size < 4096, `beacon is ${size} bytes; expected < 4096`);

  fs.rmSync(stateDir, { recursive: true, force: true });
});

test("readDeclaredManifest mirrors openclaw.plugin.json contracts", () => {
  const manifest = JSON.parse(
    fs.readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
  );
  const declared = readDeclaredManifest();
  assert.deepEqual(declared.tools, manifest.contracts.tools);
  assert.deepEqual(declared.skills, manifest.contracts.skills);
  assert.deepEqual(declared.framework, manifest.contracts.framework);
});

test("listSkillsPresent reports declared-root skills and tolerates junk roots", () => {
  const present = listSkillsPresent(readDeclaredSkillRoots());
  assert.ok(present.includes("tinyhat-platform"));
  assert.ok(present.includes("tinyhat-subscriptions"));
  // Unknown roots and non-string entries degrade to "nothing found"
  // instead of throwing — the beacon must never break the load.
  assert.deepEqual(listSkillsPresent(["no-such-root", 42, null]), []);
  assert.deepEqual(listSkillsPresent("not-a-list"), []);
});

test("announcePluginLoaded never throws when the state dir is unwritable", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-beacon-ro-"));
  const lockedParent = path.join(root, "locked");
  fs.mkdirSync(lockedParent, { mode: 0o500 });
  const lines = [];

  const line = announcePluginLoaded({
    env: { OPENCLAW_STATE_DIR: path.join(lockedParent, "state") },
    log: (message) => lines.push(message),
  });

  // The log line still happens; the beacon write degrades silently.
  assert.match(line, /^\[tinyhat\] plugin loaded v/);
  assert.equal(lines.length, 1);
  assert.equal(
    fs.existsSync(path.join(lockedParent, "state", BEACON_FILENAME)),
    false,
  );

  fs.chmodSync(lockedParent, 0o700);
  fs.rmSync(root, { recursive: true, force: true });
});

test("announcePluginLoaded survives a throwing logger", () => {
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "tinyhat-beacon-log-"));
  const line = announcePluginLoaded({
    env: { OPENCLAW_STATE_DIR: stateDir },
    log: () => {
      throw new Error("broken logger");
    },
  });
  assert.match(line, /^\[tinyhat\] plugin loaded v/);
  assert.equal(fs.existsSync(path.join(stateDir, BEACON_FILENAME)), true);
  fs.rmSync(stateDir, { recursive: true, force: true });
});
