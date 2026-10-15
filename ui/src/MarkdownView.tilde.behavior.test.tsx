// @vitest-environment jsdom
/**
 * 한국어 범위 표기 「1~5」 (2026-10-01 테스터 시험 답) — 「1/4~1/8 … (BC1~5)」의 두 물결표 사이가 취소선이 되어
 * 「1/41/8」로 보였다. 취소선은 `~~두 개~~` 일 때만 그린다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("./backend", () => ({ isTauri: () => false, openLinkInOntelicBrowser: async () => false }));

import { MarkdownView } from "./MarkdownView";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("keeps single tildes as range marks, not strikethrough", () => {
  act(() => root.render(<MarkdownView>{"DXT 로 바꾸면 1/4~1/8 수준으로 줄어듭니다. 압축은 BC1~5 중 고릅니다."}</MarkdownView>));
  expect(host.querySelector("del")).toBeNull();
  expect(host.textContent).toContain("1/4~1/8");
  expect(host.textContent).toContain("BC1~5");
});

it("still draws strikethrough for double tildes", () => {
  act(() => root.render(<MarkdownView>{"~~취소~~ 됨"}</MarkdownView>));
  expect(host.querySelector("del")?.textContent).toBe("취소");
});
