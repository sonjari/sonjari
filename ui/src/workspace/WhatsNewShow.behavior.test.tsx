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

it("레시피 장면: / 명령 → 배우는 중 걸음 셋 → 한 번 해 보기 셋 다 맞음 → 검증된 레시피로 저장", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "recipe-learn" }} />));
  expect(container.querySelector(".slash-menu")?.textContent).toContain("/레시피");
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(container.querySelector(".recipe-learn:not(.is-replay)")?.querySelectorAll("li").length).toBe(3);
  expect(container.querySelector(".wns-band.is-learning")).not.toBeNull();
  await act(async () => { vi.advanceTimersByTime(3600); });
  expect(container.querySelectorAll(".recipe-learn.is-replay li.is-ok").length).toBe(3);
  await act(async () => { vi.advanceTimersByTime(1000); });
  expect(container.querySelector(".wns-recipe-saved.is-on")?.textContent).toContain("검증된 레시피로 저장");
});

it("모델 장면: 똑똑함 · 빠름 두 카드에 잰 숫자", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "smart-fast" }} />));
  await act(async () => { vi.advanceTimersByTime(2500); });
  const cards = container.querySelectorAll(".wns-model.is-badged");
  expect(Array.from(cards).map((card) => card.querySelector(".wns-model-badge")?.textContent)).toEqual(["똑똑함", "빠름"]);
  expect(cards[0].textContent).toContain("12개 중 12개");
  expect(cards[1].textContent).toContain("12개 중 10개");
});

it("알림 장면: 끝났어요 → 기다려요 → 막혔어요가 차례로 진짜 알림 그림과 뜬다", async () => {
  await act(async () => root.render(<WhatsNewShowStage visual={{ kind: "show", scene: "notify" }} />));
  expect(container.querySelector(".wns-toast")).toBeNull();
  for (const [at, kind] of [[1000, "done"], [3300, "waiting"], [3300, "stuck"]] as const) {
    await act(async () => { vi.advanceTimersByTime(at); });
    const toast = container.querySelector(".wns-toast");
    expect(toast?.classList.contains(`is-${kind}`)).toBe(true);
    expect(toast?.querySelector("img")?.getAttribute("src")).toContain(`hero_${kind}_ko.png`);
  }
});
