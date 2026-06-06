// OpenClaw tool wrappers consume MCP-style tool results with a `content[]`
// array. Factory-style tools that return raw objects can trip wrapper code
// that reduces over `result.content`, so keep the shape centralized and
// executable in pure unit tests.

export function jsonToolResult(payload) {
  const safePayload = payload ?? {};
  return {
    content: [{ type: "text", text: JSON.stringify(safePayload, null, 2) }],
    details: safePayload,
  };
}
