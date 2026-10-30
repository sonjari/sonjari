// @vitest-environment jsdom
/**
 * 「쓰는 법」 쇼 — 움직임을 줄인 사람에게는 장면마다 마지막 모습만 보인다(타이머 없이).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import { UsageShowStage } from "./UsageShow";

vi.mock("../backend", () => ({ isTauri: () => false }));

let root: Root;
let container: HTMLDivElement;

beforeAll(() => {
  // 「움직임 줄이기」를 켠 화면. framer-motion 은 처음 쓸 때 한 번 읽는다.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: query.includes("prefers-reduced-motion"), media: query, onchange: null,
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
    }),
  });
});

beforeEach(() => {
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
});

const show = async (scene: "this-pc" | "handoff" | "limit" | "anywhere") => {
  await act(async () => root.render(<UsageShowStage scene={scene} />));
};

it("1장: 슬로건은 머리말로 올라앉아 있고, 마지막 컷(초록 시험)이 보인다", async () => {
  await show("this-pc");
  expect(container.querySelector(".us-hero.is-on")).toBeNull();
  expect(container.querySelector(".us-dock:not(.is-hidden) .us-slogan-main")?.textContent).toBe("Watch AI work in your browser.");
  expect(container.querySelector(".us-dock .us-slogan-sub")?.textContent).toBe("Runs on your PC.");
  expect(container.querySelector(".us-cut.is-active")?.getAttribute("aria-label")).toBe("코드까지 고치기");
  expect(container.querySelector(".us-term.is-green")?.textContent).toContain("1개 통과");
  expect(container.querySelector(".us-file.is-on")).not.toBeNull();
});

it("2장: 가격 넷을 다 읽고 클로드가 마무리한 모습", async () => {
  await show("handoff");
  expect(container.querySelectorAll(".us-rivals li.is-read")).toHaveLength(4);
  expect(container.querySelector(".wns-handoff.is-done")).not.toBeNull();
  expect(container.querySelector(".us-line.is-flash")?.textContent).toContain("8,500 ~ 12,000");
});

it("3장: 영수증까지 떠 있는 모습", async () => {
  await show("limit");
  expect(container.querySelector(".us-receipt.is-on")?.textContent).toContain("6,401");
  expect(container.querySelector<HTMLElement>(".us-meter-pc b")?.style.width).toBe("100%");
});

it("4장: 세 곳에서 보낸 것이 다 이 PC 에 도착한 모습", async () => {
  await show("anywhere");
  expect(container.querySelectorAll(".us-pcnode li.is-got")).toHaveLength(3);
  expect(container.querySelector(".wns-bead")).toBeNull();
});

it("모든 장면에 「예시 화면」 표시가 붙는다", async () => {
  for (const scene of ["this-pc", "handoff", "limit", "anywhere"] as const) {
    await show(scene);
    expect(container.querySelector(".wns-example")?.textContent).toBe("예시 화면");
  }
});
