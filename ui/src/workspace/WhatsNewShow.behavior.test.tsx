// @vitest-environment jsdom
/**
 * 업데이트 쇼(2026-10-26) — 세 장면이 그려지고, 「예시 화면」 표시가 늘 붙고, 예시 장표는 진짜 장표 칸(DeckStage)으로 흐른다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WhatsNewShowStage } from "./WhatsNewShow";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  Object.assign(globalThis, {
    IS_REACT_ACT_ENVIRONMENT: true,
    ResizeObserver: class { observe() {} disconnect() {} unobserve() {} },
  });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

it("클로드 장면: 맡김 → 받았습니다 → 영수증까지 흐르고 예시 표시가 붙는다", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "claude-hands" }} />));
  expect(container.querySelector(".wns-example")?.textContent).toBe("예시 화면");
  expect(container.textContent).toContain("기다리는 중");
  await act(async () => { vi.advanceTimersByTime(7000); });
  expect(container.textContent).toContain("손자리가 받았습니다");
  expect(container.querySelector(".wns-receipt.is-on")?.textContent).toContain("$0.07");
  expect(container.querySelector(".wns-receipt.is-on")?.textContent).toContain("0원");
});

it("장표 장면: 진짜 장표 칸에 결 셋 → 장이 흐른다", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "deck-build" }} />));
  await act(async () => { vi.advanceTimersByTime(400); });
  expect(container.querySelectorAll(".deck-pick").length).toBe(3);
  await act(async () => { vi.advanceTimersByTime(6000); });
  expect(container.querySelector(".deck-main iframe")).not.toBeNull();
});

it("글꼴 장면: 같은 표지를 옛 글꼴 · 지금 글꼴 두 칸으로 그린다", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "pptx-fonts" }} />));
  const frames = container.querySelectorAll(".wns-wipe iframe");
  expect(frames.length).toBe(2);
  for (const frame of Array.from(frames)) expect(frame.getAttribute("sandbox")).toBe("allow-same-origin");
  await act(async () => { vi.advanceTimersByTime(3200); });
  expect(container.querySelector(".wns-wipe.is-wiped")).not.toBeNull();
  expect(container.querySelector(".wns-file.is-on")?.textContent).toContain(".pptx");
});
