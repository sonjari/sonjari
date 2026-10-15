// @vitest-environment jsdom
/**
 * 입력창 「추론」 칩 (2026-09-28). 기본은 **자동**, 눌러서 고르면 그 값이 올라가고 이 PC 에 기억된다.
 * 서버 쪽 뜻(자동 = 보통으로 시작해 막히면 깊게)은 `tests/test_reasoning_chip.py` 가 잰다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReasoningPicker, loadReasoningChoice, saveReasoningChoice } from "./ReasoningPicker";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  window.localStorage.clear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("defaults to auto when nothing was remembered", () => {
  expect(loadReasoningChoice()).toBe("auto");
});

it("remembers the last choice on this PC", () => {
  saveReasoningChoice("deep");
  expect(loadReasoningChoice()).toBe("deep");
});

it("opens and reports the chosen level", () => {
  const onChoose = vi.fn();
  act(() => root.render(<ReasoningPicker value="auto" onChoose={onChoose} />));
  const chip = host.querySelector<HTMLButtonElement>(".reasoning-chip")!;
  expect(chip.textContent).toContain("자동");

  act(() => chip.click());
  const options = [...host.querySelectorAll<HTMLButtonElement>('[role="option"]')];
  expect(options.map((node) => node.querySelector("strong")?.textContent)).toEqual(["자동", "빠르게", "보통", "깊게"]);

  act(() => options[3].click());
  expect(onChoose).toHaveBeenCalledWith("deep");
  expect(host.querySelector('[role="listbox"]')).toBeNull();
});
