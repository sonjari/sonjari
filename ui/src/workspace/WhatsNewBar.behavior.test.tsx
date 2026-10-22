// @vitest-environment jsdom
/**
 * 업데이트 뒤 「바뀐 것 보기」 한 줄 (2026-10-20 대표 「지금 사용자는 바뀐 걸 아예 모른다」).
 * 백엔드가 `show: true` 일 때만 그리고, 누르면 펼치고, 닫으면 「봤다」를 적는다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import { WhatsNewBar } from "./WhatsNewBar";

vi.mock("../backend", () => ({ isTauri: () => false }));

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

function fakeClient(show: boolean) {
  return {
    getWhatsNew: vi.fn(async () => ({ show, version: "0.4.26.0", changes: "더 정확하게\n- 고친 것 하나", tour: "이미 되는 것\n- 디스코드로 일 시키기" })),
    markWhatsNewSeen: vi.fn(async () => ({ ok: true })),
  } as unknown as JarvisClient & { markWhatsNewSeen: ReturnType<typeof vi.fn> };
}

it("새 판이면 한 줄을 띄우고, 누르면 바뀐 것과 이미 되는 것을 펼친다", async () => {
  const client = fakeClient(true);
  await act(async () => root.render(<WhatsNewBar client={client} />));
  expect(container.textContent).toContain("Sonjari 0.4.26.0 로 업데이트됐습니다");
  expect(container.textContent).not.toContain("고친 것 하나");
  const open = [...container.querySelectorAll("button")].find((b) => b.textContent === "바뀐 것 보기")!;
  await act(async () => { open.click(); });
  expect(container.textContent).toContain("고친 것 하나");
  expect(container.textContent).toContain("디스코드로 일 시키기");
});

it("닫으면 봤다고 적고 사라진다", async () => {
  const client = fakeClient(true);
  await act(async () => root.render(<WhatsNewBar client={client} />));
  const close = [...container.querySelectorAll("button")].find((b) => b.textContent === "닫기")!;
  await act(async () => { close.click(); });
  expect(client.markWhatsNewSeen).toHaveBeenCalledWith("0.4.26.0");
  expect(container.textContent).toBe("");
});

it("보여 줄 게 없으면 아무것도 그리지 않는다", async () => {
  await act(async () => root.render(<WhatsNewBar client={fakeClient(false)} />));
  expect(container.textContent).toBe("");
});

// ── 슬라이드 (2026-10-21 대표 「피피티마냥 한눈에」) ─────────────────────────────

const SLIDES = [
  { title: "한 번 보여 주면 배웁니다", body: "직접 해 보이시면 배웁니다.", try: "이렇게 말해 보세요: 「배우기 시작」" },
  {
    title: "자주 읽는 사이트는 첫 대답이 빨라집니다", body: "값만 읽습니다.", try: "따로 켜실 것은 없습니다.",
    visual: { kind: "stat", label: "첫 글자가 나오기까지", before: 16, after: 4.3, unit: "초", basis: "이 PC · 같은 책 3권" },
  },
  { title: "세 번째 장", body: "마지막입니다." },
];

function slideClient() {
  return {
    getWhatsNew: vi.fn(async () => ({ show: true, version: "0.4.30.0", changes: "이번에 새로 생긴 것\n- 긴 목록 한 줄", tour: "", slides: SLIDES })),
    markWhatsNewSeen: vi.fn(async () => ({ ok: true })),
  } as unknown as JarvisClient & { markWhatsNewSeen: ReturnType<typeof vi.fn> };
}

const button = (label: string) => [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === label)!;
const dialog = () => document.querySelector("[role=dialog]");
const press = (key: string) => window.dispatchEvent(new KeyboardEvent("keydown", { key }));

it("슬라이드가 있는 판은 「바뀐 것 보기」가 가운데 창을 열고 한 장씩 넘긴다", async () => {
  const client = slideClient();
  await act(async () => root.render(<WhatsNewBar client={client} />));
  await act(async () => { button("바뀐 것 보기").click(); });
  expect(dialog()?.textContent).toContain("한 번 보여 주면 배웁니다");
  expect(document.querySelectorAll(".wn-dots button")).toHaveLength(3);
  expect(document.querySelector(".wn-dots [aria-current=step]")?.getAttribute("aria-label")).toBe("1번째 장: 한 번 보여 주면 배웁니다");
  expect(dialog()?.textContent).not.toContain("긴 목록 한 줄");
  await act(async () => { button("다음").click(); });
  // 숫자 장에는 잰 조건이 같이 보인다
  expect(dialog()?.textContent).toContain("4.3초");
  expect(dialog()?.textContent).toContain("이 PC · 같은 책 3권");
  await act(async () => { press("ArrowRight"); });
  expect(dialog()?.textContent).toContain("세 번째 장");
  await act(async () => { press("ArrowLeft"); });
  expect(dialog()?.textContent).toContain("자주 읽는 사이트는");
});

it("「나중에 보기」 · Esc 는 창만 닫고 봤다고 적지 않는다 — 위 한 줄은 남는다", async () => {
  const client = slideClient();
  await act(async () => root.render(<WhatsNewBar client={client} />));
  await act(async () => { button("바뀐 것 보기").click(); });
  await act(async () => { press("Escape"); });
  expect(dialog()).toBeNull();
  await act(async () => { button("바뀐 것 보기").click(); });
  await act(async () => { button("나중에 보기").click(); });
  expect(dialog()).toBeNull();
  expect(client.markWhatsNewSeen).not.toHaveBeenCalled();
  expect(container.textContent).toContain("0.4.30.0");
});

it("마지막 장에서 전체 목록을 펼쳐 볼 수 있고, 「다 봤어요」는 봤다고 적는다", async () => {
  const client = slideClient();
  await act(async () => root.render(<WhatsNewBar client={client} />));
  await act(async () => { button("바뀐 것 보기").click(); });
  expect(button("바뀐 것 전부 보기")).toBeUndefined();
  await act(async () => { press("ArrowRight"); press("ArrowRight"); });
  await act(async () => { button("바뀐 것 전부 보기").click(); });
  expect(dialog()?.textContent).toContain("긴 목록 한 줄");
  await act(async () => { button("다 봤어요").click(); });
  expect(client.markWhatsNewSeen).toHaveBeenCalledWith("0.4.30.0");
  expect(dialog()).toBeNull();
  expect(container.textContent).toBe("");
});
