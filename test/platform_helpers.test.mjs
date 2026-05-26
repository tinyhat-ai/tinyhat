import assert from "node:assert/strict";
import test from "node:test";

import { parseSecretCommand, redactObject } from "../src/platform_helpers.js";

test("redactObject redacts sensitive keys nested inside arrays", () => {
  const payload = {
    runtime: {
      endpoints: [
        {
          name: "gateway",
          signed_url: "https://signed.example/abc?token=xyz",
          metadata: {
            authorization: "Bearer secret-token",
            safe_label: "keep me",
          },
          headers: [
            {
              token: "nested-token",
              label: "safe header label",
            },
          ],
        },
      ],
    },
  };

  assert.deepEqual(redactObject(payload), {
    runtime: {
      endpoints: [
        {
          name: "gateway",
          signed_url: "[redacted]",
          metadata: {
            authorization: "[redacted]",
            safe_label: "keep me",
          },
          headers: [
            {
              token: "[redacted]",
              label: "safe header label",
            },
          ],
        },
      ],
    },
  });
});

test("redactObject redacts object roots inside arrays", () => {
  assert.deepEqual(redactObject([{ url: "https://example.test/private" }, "safe"]), [
    { url: "[redacted]" },
    "safe",
  ]);
});

test("parseSecretCommand routes list and manage aliases", () => {
  assert.deepEqual(parseSecretCommand("list"), { action: "list" });
  assert.deepEqual(parseSecretCommand("manage"), { action: "list" });
});

test("parseSecretCommand routes explicit secret requests", () => {
  assert.deepEqual(parseSecretCommand("add OPENAI_API_KEY used for model access"), {
    action: "request",
    name: "OPENAI_API_KEY",
    description: "used for model access",
  });
  assert.deepEqual(parseSecretCommand("OPENAI_API_KEY"), {
    action: "request",
    name: "OPENAI_API_KEY",
  });
});

test("parseSecretCommand returns help for empty or malformed input", () => {
  assert.deepEqual(parseSecretCommand(""), { action: "help" });
  assert.deepEqual(parseSecretCommand("add"), { action: "help" });
  assert.deepEqual(parseSecretCommand("bad-name!"), { action: "help" });
});
