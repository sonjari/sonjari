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

it("첫 화면 제목은 영문 슬로건 그대로 + 밑줄 · 한 줄 설명 — 코드 모드는 그대로(2026-10-27 대표)", async () => {
  const cowork = await render("cowork", "qwen3.5:9b");
  expect(cowork.querySelector("h1")?.textContent).toBe("Watch AI work in your browser.");
  expect(cowork.querySelector(".welcome-local")?.textContent).toBe("Runs on your PC.");
  expect(cowork.querySelector(".welcome-note")?.textContent).toBe("크롬, 파일, 엑셀, 한글을 직접 다루고 읽은 곳을 붙여 드립니다.");
  // 슬로건에 상표(Chrome)를 넣지 않는다 · 챗봇 얼굴이던 옛 문구는 없다
  expect(cowork.querySelector("h1")?.textContent).not.toMatch(/chrome/i);
  expect(cowork.textContent).not.toContain("무엇을 할까요?");
  expect(cowork.textContent).not.toContain("짧은 질문은 바로 답합니다");

  const code = await render("code", "qwen3.6:35b-a3b");
  expect(code.querySelector("h1")?.textContent).toBe("만들고, 눌러 보고, 고칩니다");
  expect(code.querySelector(".welcome-local")).toBeNull();
});
