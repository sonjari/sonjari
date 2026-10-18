// @vitest-environment jsdom
/**
 * 첫 실행 「나에 대해 (선택)」 단계 (2026-10-18) — 세 질문만, 건너뛸 수 있고, 같은 파일(「나에 대한 지침」)에 쓴다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AboutMeCard } from "./AboutMeCard";
import type { AboutMeAnswersInput, AboutMeView, SetupApi } from "./setupApi";
import { STEPS } from "./SetupWizard";

vi.mock("../backend", () => ({ isTauri: () => false, loadBootstrap: () => Promise.reject(new Error("시험")) }));

const METER = { sent_chars: 0, tokens: 0, num_ctx: 32768, share: 0, share_pct: 0, warn: false, warn_share: 0.1, chars_per_token: 2 };
const VIEW: AboutMeView = {
  ok: true, path: "x", exists: false, content_raw: "", chars: 0, max_chars: 6000, truncated: false, has_card: false,
  // 설정 › 나에 대한 지침에서 전에 고른 말투 · 사이트 — 첫 실행 카드에는 안 보이지만 지워지면 안 된다.
  answers: { user_label: "", work_text: "", length: "", tone: "casual", sites: ["네이버"], avoid_text: "반말 금지" },
  ...METER,
};

let root: Root;
let container: HTMLDivElement;
let api: SetupApi;
let save: ReturnType<typeof vi.fn>;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  save = vi.fn(async (answers: AboutMeAnswersInput) => ({ ...VIEW, saved: true, answers: { ...VIEW.answers, ...answers, sites: [] } }));
  api = {
    aboutMe: vi.fn(async () => VIEW),
    aboutMeCardPreview: vi.fn(async (answers: AboutMeAnswersInput) => ({
      ...METER, ok: true, answers: { ...answers, sites: [] }, card_lines: answers.work_text ? [`- 하는 일: ${answers.work_text}`] : [],
      content_raw: "", chars: 0, max_chars: 6000, fits: true,
    })),
    aboutMeCardSave: save,
  } as unknown as SetupApi;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function settle() {
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
}

it("마법사 단계: 쓰임 다음 · 연결 앞에 「나에 대해」가 있다", () => {
  expect([...STEPS]).toEqual(["PC 확인", "모델", "쓰임", "나에 대해", "연결"]);
});

it("첫 실행 카드는 세 질문만 묻는다(부르는 이름 · 답 길이 · 하는 일)", async () => {
  await act(async () => { root.render(<AboutMeCard api={api} compact />); });
  await settle();
  expect(container.querySelector("#aboutme-name")).not.toBeNull();
  expect(container.querySelector("#aboutme-work")).not.toBeNull();
  expect(container.textContent).toContain("답 길이");
  expect(container.querySelector("#aboutme-sites")).toBeNull();
  expect(container.querySelector("#aboutme-avoid")).toBeNull();
  expect(container.textContent).not.toContain("말투");
});

it("저장하면 같은 파일 문으로 쓰고, 안 보이던 답(말투 · 사이트 · 하지 말 것)은 그대로 보낸다", async () => {
  const onSaved = vi.fn();
  await act(async () => { root.render(<AboutMeCard api={api} compact onSaved={onSaved} />); });
  await settle();
  const work = container.querySelector<HTMLInputElement>("#aboutme-work")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(work, "쇼핑몰 운영");
    work.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle();
  expect(container.textContent).toContain("- 하는 일: 쇼핑몰 운영");
  const saveButton = [...container.querySelectorAll("button")].find((b) => b.textContent === "이대로 저장")!;
  await act(async () => { saveButton.click(); });
  await settle();
  expect(save).toHaveBeenCalledTimes(1);
  expect(save.mock.calls[0][0]).toMatchObject({ work_text: "쇼핑몰 운영", tone: "casual", sites: "네이버", avoid_text: "반말 금지" });
  expect(onSaved).toHaveBeenCalledTimes(1);
});

it("아무것도 안 누르면 아무것도 쓰지 않는다(건너뛰기)", async () => {
  await act(async () => { root.render(<AboutMeCard api={api} compact />); });
  await settle();
  expect(save).not.toHaveBeenCalled();
});
