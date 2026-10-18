// @vitest-environment jsdom
/**
 * 설정 › 나에 대한 지침 (2026-10-18) — 3분 카드 · 길이 자 · 원문 편집기 · 가져온 줄 고르기.
 *
 * 화면은 줄을 만들지 않는다(백엔드 미리보기를 그대로 그린다) · 사람이 「이대로 저장」을 눌러야 쓴다 ·
 * 상한을 넘으면 백엔드가 거절한 까닭을 사람 말로 보인다 · 비밀이 걷힌 줄은 고를 수 없다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  AboutMeAnswersInput, AboutMeCardPreview, AboutMeImportLines, AboutMeView, SetupApi,
} from "../setup/setupApi";
import { ImportLinePicker } from "../setup/AboutMeCard";
import { AboutMeSection } from "./AboutMeSection";

const METER = { sent_chars: 40, tokens: 80, num_ctx: 32768, share: 0.0024, share_pct: 0.2, warn: false, warn_share: 0.1, chars_per_token: 2 };

function viewOf(extra: Partial<AboutMeView> = {}): AboutMeView {
  return {
    ok: true, path: "C:\\data\\JARVIS_PROFILE.md", exists: true, content_raw: "- 손으로 쓴 줄\n", chars: 8, max_chars: 6000,
    truncated: false, has_card: false,
    answers: { user_label: "가람", work_text: "학원 운영", length: "", tone: "polite", sites: ["네이버"], avoid_text: "" },
    ...METER, ...extra,
  };
}

/** 백엔드 줄 규칙의 **모양만** 흉내 낸 가짜 — 시험이 보는 것은 화면이 그 결과를 그대로 그리는가다. */
function linesOf(a: AboutMeAnswersInput): string[] {
  return [
    ...(a.work_text ? [`- 하는 일: ${a.work_text}`] : []),
    ...(a.length === "short" ? ["- 답은 짧게, 핵심부터."] : []),
    ...(a.tone === "polite" ? ["- 말투는 정중하게, 존댓말로."] : []),
  ];
}

let root: Root;
let container: HTMLDivElement;
let api: SetupApi;
let calls: Record<string, ReturnType<typeof vi.fn>>;
let current: AboutMeView;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  current = viewOf();
  calls = {
    aboutMe: vi.fn(async () => current),
    aboutMeCardPreview: vi.fn(async (answers: AboutMeAnswersInput): Promise<AboutMeCardPreview> => ({
      ...METER, ok: true, answers: { ...answers, sites: [] }, card_lines: linesOf(answers), content_raw: "", chars: 30,
      max_chars: 6000, fits: true,
    })),
    aboutMeCardSave: vi.fn(async (answers: AboutMeAnswersInput) => ({ ...viewOf({ has_card: true }), saved: true, card_lines: linesOf(answers) })),
    aboutMeSave: vi.fn(async (content: string) => (content.length > 20
      ? viewOf({ ok: false, error: "too_long", chars: content.length, max_chars: 20 })
      : viewOf({ content_raw: content, saved: true }))),
    aboutMeOpen: vi.fn(async () => ({ ok: true, path: "C:\\data\\JARVIS_PROFILE.md" })),
    aboutMeImportLines: vi.fn(async (): Promise<AboutMeImportLines> => ({
      ok: true, import_id: 7, tool_name: "Claude Code", source_path: "~\\.claude\\CLAUDE.md", allowed_count: 2,
      lines: [
        { index: 0, raw: "# 전역 지침", allowed: true, reason: "" },
        { index: 1, raw: "", allowed: false, reason: "blank" },
        { index: 2, raw: "검증 키: [비밀 걷어 냄: API 키]", allowed: false, reason: "secret" },
        { index: 3, raw: "결론부터 말한다.", allowed: true, reason: "" },
      ],
    })),
    aboutMeAppendImport: vi.fn(async () => viewOf({ added: 1, refused: [] })),
  };
  api = calls as unknown as SetupApi;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(node: React.ReactNode) {
  await act(async () => { root.render(node); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((el) => el.textContent?.trim().startsWith(label));
  if (!found) throw new Error(`단추 없음: ${label}\n${container.textContent}`);
  return found as HTMLButtonElement;
}

async function click(el: Element) {
  await act(async () => { (el as HTMLElement).click(); });
  await act(async () => { await Promise.resolve(); });
}

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { await Promise.resolve(); });
}

it("카드는 저장된 답으로 채워 열리고, 부르는 이름은 설정 값을 보인다", async () => {
  await render(<AboutMeSection api={api} />);
  expect(container.querySelector<HTMLInputElement>("#aboutme-name")!.value).toBe("가람");
  expect(container.querySelector<HTMLInputElement>("#aboutme-work")!.value).toBe("학원 운영");
  expect(container.querySelector<HTMLInputElement>("#aboutme-sites")!.value).toBe("네이버");
  const polite = [...container.querySelectorAll("[role=radio]")].find((el) => el.textContent === "정중하게")!;
  expect(polite.getAttribute("aria-checked")).toBe("true");
});

it("고르기를 바꾸면 백엔드 미리보기를 그대로 보이고, 「이대로 저장」을 눌러야 쓴다", async () => {
  await render(<AboutMeSection api={api} />);
  await click(button("짧게"));
  const last = calls.aboutMeCardPreview.mock.calls.at(-1)!;
  expect(last[0]).toMatchObject({ length: "short", work_text: "학원 운영", sites: "네이버" });
  expect(last[1]).toBe("ko");
  const preview = container.querySelector("[data-testid=aboutme-preview]")!;
  expect(preview.textContent).toContain("- 답은 짧게, 핵심부터.");
  expect(calls.aboutMeCardSave).not.toHaveBeenCalled();
  await click(button("이대로 저장"));
  expect(calls.aboutMeCardSave).toHaveBeenCalledTimes(1);
  expect(calls.aboutMeCardSave.mock.calls[0][0]).toMatchObject({ length: "short", user_label: "가람" });
  expect(container.textContent).toContain("저장했습니다 · 다음 대화부터 씁니다");
});

it("같은 칩을 다시 누르면 고르기가 풀린다", async () => {
  await render(<AboutMeSection api={api} />);
  await click(button("정중하게"));
  expect(calls.aboutMeCardPreview.mock.calls.at(-1)![0]).toMatchObject({ tone: "" });
});

it("길이 자는 창의 N% 를 보이고, 10% 를 넘으면 살짝 경고한다", async () => {
  current = viewOf({ tokens: 4000, share: 0.122, share_pct: 12.2, warn: true, chars: 5000 });
  await render(<AboutMeSection api={api} />);
  const meters = [...container.querySelectorAll("[data-testid=aboutme-meter]")];
  const saved = meters.at(-1)!;
  expect(saved.textContent).toContain("창의 12.2%");
  expect(saved.textContent).toContain("약 4000토큰 · 5000자 / 6000자");
  expect(saved.textContent).toContain("창의 10% 를 넘었습니다");
});

it("원문 편집기: 상한을 넘으면 백엔드 까닭을 사람 말로 보이고, 고친 글은 저장된다", async () => {
  await render(<AboutMeSection api={api} />);
  const area = container.querySelector<HTMLTextAreaElement>("textarea")!;
  expect(area.value).toBe("- 손으로 쓴 줄\n");
  await type(area, "가".repeat(25));
  await click(button("저장"));
  expect(calls.aboutMeSave).toHaveBeenCalledWith("가".repeat(25));
  expect(container.querySelector("[role=alert]")!.textContent).toContain("20자까지입니다(지금 25자)");
  await type(area, "- 짧은 줄");
  await click(button("저장"));
  expect(calls.aboutMeSave).toHaveBeenLastCalledWith("- 짧은 줄");
  expect(container.textContent).toContain("저장했습니다 · 다음 대화부터 씁니다");
});

it("「파일 열기」는 경로 없이 그 파일 하나만 연다", async () => {
  await render(<AboutMeSection api={api} />);
  await click(button("파일 열기"));
  expect(calls.aboutMeOpen).toHaveBeenCalledWith();
});

it("가져온 지침: 고른 줄만 더하고, 비밀이 걷힌 줄은 고를 수 없고, 빈 줄은 안 보인다", async () => {
  await render(<ImportLinePicker api={api} importId={7} />);
  expect(container.textContent).toContain("고른 줄만 「나에 대한 지침」에 더해져");
  const boxes = [...container.querySelectorAll<HTMLInputElement>("input[type=checkbox]")];
  expect(boxes).toHaveLength(3); // 빈 줄은 그리지 않는다
  const secretRow = boxes.find((box) => box.closest("li")!.textContent!.includes("비밀 걷어 냄"))!;
  expect(secretRow.disabled).toBe(true);
  expect(secretRow.closest("li")!.textContent).toContain("비밀이 걷힌 줄 · 더할 수 없음");
  expect(button("고른 0줄").disabled).toBe(true);
  const conclusion = boxes.find((box) => box.closest("li")!.textContent!.includes("결론부터"))!;
  await click(conclusion);
  await click(button("고른 1줄을"));
  expect(calls.aboutMeAppendImport).toHaveBeenCalledWith(7, [3]);
  expect(container.textContent).toContain("1줄을 「나에 대한 지침」에 더했습니다");
  expect(calls.aboutMeImportLines).toHaveBeenCalledTimes(2); // 더한 뒤 다시 읽어 「이미 들어 있음」을 보인다
});
