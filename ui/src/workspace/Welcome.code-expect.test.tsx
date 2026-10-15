// @vitest-environment jsdom
/**
 * 코드 탭 시작 전 한 줄 (§55-13 기대 맞추기 2, 2026-10-01) — 작은 코드 모델이면 무엇을 잘하고 무엇을 클로드에게 맡길지 알린다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { Welcome, paramsInTag } from "./Welcome";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(mode: "code" | "cowork", codeModel: string) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => {
    createRoot(host).render(<Welcome onSuggestion={() => undefined} mode={mode} codeModel={codeModel} />);
  });
  return host;
}

it("reads the size in a model tag", () => {
  expect(paramsInTag("qwen3.5:9b")).toBe(9);
  expect(paramsInTag("qwen3.6:35b-a3b")).toBe(35);
  expect(paramsInTag("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL")).toBe(27);
  expect(paramsInTag("my-model")).toBe(0);
});

it("a small code model is told what it is for, a big one is not", async () => {
  expect((await render("code", "qwen3.5:9b")).querySelector(".code-expect")?.textContent).toContain("클로드(Claude Code)가 더 잘합니다");
  expect((await render("code", "qwen3.6:35b-a3b")).querySelector(".code-expect")).toBeNull();
  expect((await render("cowork", "qwen3.5:9b")).querySelector(".code-expect")).toBeNull();
});
