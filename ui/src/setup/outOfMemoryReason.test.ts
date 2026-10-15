/**
 * 메모리가 모자라 못 올렸을 때 다시 설치를 시키지 않고, 무엇을 닫으면 되는지 말한다 (2026-10-01 밤 RTX 3050 6GB 노트북).
 */
import { expect, it } from "vitest";
import { outOfMemoryReason } from "./SetupWizard";

it("names the memory, the users and that reinstalling does not help", () => {
  const text = outOfMemoryReason({ used_gb: 3.1, total_gb: 6, apps: ["ollama"] });
  expect(text).toContain("메모리가 모자라");
  expect(text).toContain("3.1GB / 6GB");
  expect(text).toContain("ollama");
  expect(text).toContain("다른 Ollama");
  expect(text).toContain("다시 설치해도 풀리지 않습니다");
});

it("still says something useful when the card cannot be read", () => {
  const text = outOfMemoryReason(undefined);
  expect(text).toContain("메모리가 모자라");
  expect(text).not.toContain("undefined");
});

// ── 재는 순간 다른 모델이 올라와 밀려난 경우 (2026-10-05) ─────────────────────────────────────────
// 화면에 「적용하지 못했습니다: gpu_measurement_unavailable」이 그대로 나왔다 — 마법사가 재는 바로 그때 다른 손자리가 모델을 올렸다.
import { pushedOutReason } from "./setupApi";

it("names the model that pushed it out and says to apply again", () => {
  const text = pushedOutReason(["ornith:35b"]);
  expect(text).toContain("ornith:35b");
  expect(text).toContain("다시 적용");
  expect(text).not.toContain("gpu_measurement_unavailable");
});

it("says so plainly when nothing else was seen", () => {
  const text = pushedOutReason(undefined);
  expect(text).toContain("읽지 못했습니다");
  expect(text).not.toContain("undefined");
});
