import { describe, expect, it } from "vitest";

import { ollamaLine } from "./FirstRunPanel";
import type { OllamaStatus } from "./setupApi";

const base: OllamaStatus = {
  running: false, version: "", bundled: "", managed: false, can_install: true,
  source: "https://github.com/ollama/ollama/releases", install: { phase: "idle" },
};

describe("ollamaLine", () => {
  it("uses a running Ollama as is", () => {
    expect(ollamaLine({ ...base, running: true, version: "0.12.0" })).toContain("그대로 씁니다");
    expect(ollamaLine({ ...base, running: true, version: "0.12.0", managed: true })).toContain("Sonjari가 켰습니다");
  });

  it("shows download progress and the hash check as separate steps", () => {
    expect(ollamaLine({ ...base, install: { phase: "downloading", received: 50, total: 200 } })).toContain("25%");
    expect(ollamaLine({ ...base, install: { phase: "verifying" } })).toContain("해시");
  });

  it("names the failure instead of hiding it", () => {
    expect(ollamaLine({ ...base, install: { phase: "error", error: "hash_mismatch" } })).toContain("hash_mismatch");
  });
});
