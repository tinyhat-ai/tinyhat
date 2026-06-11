import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  BEACON_FILENAME,
  announcePluginLoaded,
  beaconPath,
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
