// @vitest-environment jsdom
/**
 * 그림으로 된 본문을 읽는 동안, 지금 읽는 조각을 걸음 상자 안에 비춘다 (2026-10-10).
 *
 * 대표 화면: 상세가 통이미지인 페이지에서 「본문 읽기」 한 줄만 30초 가까이 떠 있어 멈춘 것처럼 보였다.
 * 자리는 모델이 일하면서 하는 말 줄 바로 아래다(「일하는 중」 상자는 말이 쌓이면 위로 밀려 안 보인다 — 대표).
 * 지키는 것 — 조각 눈금은 실제 조각 수와 같다 · 거두는 알림에 비운다(그림이 남지 않는다) · 그림 주소가 아니면 안 그린다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import type { Looking } from "../types";
import { applyLooking } from "./looking";
import { LookingAt, frameHeight } from "./LookingAt";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const PICTURE = "data:image/jpeg;base64,AAAA";
const piece = (over: Partial<Looking> = {}): Looking => ({
  jobId: "j1", image: 1, images: 1, tile: 2, tiles: 5, picture: PICTURE, width: 240, height: 349, ...over,
});

it("조각 눈금은 조각 수만큼이고 읽은 칸·지금 칸·남은 칸이 갈린다", () => {
  act(() => root.render(<LookingAt looking={piece({ tile: 3, tiles: 5 })} />));

  const cells = [...container.querySelectorAll(".looking-rail li")].map((cell) => cell.className);
  expect(cells).toEqual(["read", "read", "now", "", ""]);
  expect(container.querySelector(".looking-count")?.textContent).toBe("조각 3/5");
  expect(container.querySelector("img")?.getAttribute("src")).toBe(PICTURE);
});

it("그림이 여러 장이면 몇 번째 그림인지도 말한다", () => {
  act(() => root.render(<LookingAt looking={piece({ image: 2, images: 3, tile: 1, tiles: 4 })} />));

  expect(container.querySelector(".looking-count")?.textContent).toBe("그림 2/3 · 조각 1/4");
});

it("조각 번호가 조각 수를 넘어 와도 눈금 밖으로 나가지 않는다", () => {
  act(() => root.render(<LookingAt looking={piece({ tile: 9, tiles: 4 })} />));

  expect(container.querySelectorAll(".looking-rail li").length).toBe(4);
  expect(container.querySelectorAll(".looking-rail li.now").length).toBe(1);
  expect(container.querySelector(".looking-count")?.textContent).toBe("조각 4/4");
});

it("틀 높이는 조각의 비율을 따르되 한도 안이다", () => {
  expect(frameHeight(240, 349)).toBe(192);
  expect(frameHeight(240, 200)).toBe(110);
  expect(frameHeight(240, 20)).toBe(72);
  expect(frameHeight(0, 0)).toBe(192);
});

it("알림을 받아 일마다 한 칸을 갈아 끼우고, 거두는 알림에 비운다", () => {
  let rows: Record<string, Looking> = {};
  rows = applyLooking(rows, "j1", { image: 1, images: 2, tile: 1, tiles: 3, width: 240, height: 349, picture: PICTURE });
  rows = applyLooking(rows, "j1", { image: 1, images: 2, tile: 2, tiles: 3, width: 240, height: 349, picture: PICTURE });
  expect(rows.j1).toMatchObject({ jobId: "j1", image: 1, images: 2, tile: 2, tiles: 3 });

  rows = applyLooking(rows, "j1", { done: true });
  expect(rows).toEqual({});
});

it("비울 것이 없으면 같은 표를 그대로 돌려준다 — 걸음 알림마다 화면을 다시 그리지 않게", () => {
  const rows: Record<string, Looking> = {};

  expect(applyLooking(rows, "j1", { done: true })).toBe(rows);
  expect(applyLooking(rows, "", { picture: PICTURE })).toBe(rows);
});

it("그림 주소가 아닌 것은 그리지 않는다", () => {
  const rows = applyLooking({}, "j1", { image: 1, images: 1, tile: 1, tiles: 1, picture: "https://example.com/x.png" });

  expect(rows).toEqual({});
});

it("만든 화면을 볼 때는 조각 눈금 대신 「페이지 전체」라고 말한다", () => {
  act(() => root.render(<LookingAt looking={piece({ kind: "page", tile: 1, tiles: 1, width: 240, height: 480 })} />));

  expect(container.querySelector("figcaption strong")?.textContent).toBe("만든 화면을 눈으로 보는 중");
  expect(container.querySelector(".looking-count")?.textContent).toBe("페이지 전체 한 장");
  expect(container.querySelector("img")?.getAttribute("alt")).toBe("손자리가 만든 화면");
});

it("알림의 종류가 그대로 실려 온다 — 다른 값은 종류로 치지 않는다", () => {
  const page = applyLooking({}, "j1", { kind: "page", image: 1, images: 1, tile: 1, tiles: 1, width: 240, height: 480, picture: PICTURE });
  const tile = applyLooking({}, "j1", { kind: "something", image: 1, images: 1, tile: 1, tiles: 3, width: 240, height: 349, picture: PICTURE });

  expect(page.j1.kind).toBe("page");
  expect(tile.j1.kind).toBeUndefined();
});
