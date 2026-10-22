// @vitest-environment jsdom
/**
 * 첫 화면 「이번 주 영수증」 (2026-10-21). 숫자는 토큰 · 페이지 수만, 큰 숫자에는 「최소」.
 * 맡긴 일이 0이면 직접 시킨 일의 페이지만 보이는 작은 판, 그것도 0이면 카드가 없다(빈 카드 금지).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import { setLangForTest } from "../i18n";
import type { WeeklyReceipt } from "../types";
import { handedByClaude, ReceiptCard, receiptView, RECEIPT_DAYS } from "./ReceiptCard";
import { periodLabel, receiptImageText } from "./receiptImage";

function receipt(extra: Partial<WeeklyReceipt> = {}): WeeklyReceipt {
  return {
    days: 7, since: 1_760_400_000, until: 1_761_004_800,
    delegated: { jobs: 136, pages: 611, tokens_at_least: 912788, chars: 4107770, flagged_numbers_jobs: 9 },
    direct: { jobs: 495, pages: 418 }, callers: { "Claude Code": 136 }, measurement_jobs_skipped: 36,
    basis: "센 글자 수 ÷ 4.5 의 하한입니다.", ...extra,
  };
}

function fakeClient(value: WeeklyReceipt | Error) {
  return {
    getReceipt: vi.fn(() => (value instanceof Error ? Promise.reject(value) : Promise.resolve(value))),
    saveReceiptImage: vi.fn(async () => ({ ok: true, short: "Sonjari\\receipts\\sonjari-receipt-2026-10-21.png" })),
    openFolder: vi.fn(async () => ({ ok: true })),
  };
}

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
  setLangForTest("ko");
});

async function show(client: ReturnType<typeof fakeClient>) {
  await act(async () => { root.render(<ReceiptCard client={client} />); });
  await act(async () => { await Promise.resolve(); });
}

it("큰 숫자 하나(최소 N 토큰)와 세 숫자를 천 단위 쉼표로 보인다 — 약 · 배 · 금액은 없다", async () => {
  const client = fakeClient(receipt());
  await show(client);
  expect(client.getReceipt).toHaveBeenCalledWith(RECEIPT_DAYS);
  const text = container.textContent ?? "";
  expect(container.querySelector(".receipt-hero-figure")?.textContent).toBe("최소912,788토큰");
  expect(text).toContain("클로드에 안 실은 본문");
  expect(text).toContain("클로드가 맡긴 일136건");
  expect(text).toContain("대신 읽은 페이지611개");
  expect(text).toContain("근거 없는 숫자 표시9건");
  expect(text).toContain("센 글자 ÷ 4.5");
  expect(text).not.toMatch(/약 |배|무려|\$|원\b|%/);
  expect(container.querySelector(".receipt-save")).not.toBeNull();
});

it("맡긴 일이 0이면 직접 시킨 일에서 읽은 페이지만 — 토큰 · 저장 단추가 없는 작은 판", async () => {
  await show(fakeClient(receipt({
    delegated: { jobs: 0, pages: 0, tokens_at_least: 0, chars: 0, flagged_numbers_jobs: 0 }, callers: {},
  })));
  const card = container.querySelector(".receipt-card");
  expect(card?.classList.contains("is-small")).toBe(true);
  expect(card?.textContent).toContain("손자리가 대신 읽은 페이지418개");
  expect(card?.textContent).not.toContain("토큰");
  expect(container.querySelector(".receipt-save")).toBeNull();
});

it("맡긴 일도 직접 읽은 페이지도 0이면 카드가 아예 없다(빈 카드 금지)", async () => {
  await show(fakeClient(receipt({
    delegated: { jobs: 0, pages: 0, tokens_at_least: 0, chars: 0, flagged_numbers_jobs: 0 },
    direct: { jobs: 12, pages: 0 }, callers: {},
  })));
  expect(container.innerHTML).toBe("");
});

it("못 불러오면 첫 화면에 고장 줄을 얹지 않고 숨는다", async () => {
  await show(fakeClient(new Error("404")));
  expect(container.innerHTML).toBe("");
});

it("코덱스 · 커서가 섞이면 「클로드」라고 하지 않는다", async () => {
  expect(handedByClaude({ callers: { "Claude Code": 3 } })).toBe(true);
  expect(handedByClaude({ callers: { "Claude Code": 3, Codex: 1 } })).toBe(false);
  expect(handedByClaude({ callers: {} })).toBe(false);
  await show(fakeClient(receipt({ callers: { "Claude Code": 100, Cursor: 36 } })));
  expect(container.textContent).toContain("바깥 AI 에 안 실은 본문");
  expect(container.textContent).not.toContain("클로드");
});

it("receiptView — full · direct · hidden", () => {
  expect(receiptView(null)).toBe("hidden");
  expect(receiptView(receipt())).toBe("full");
  expect(receiptView(receipt({ delegated: { jobs: 0, pages: 0, tokens_at_least: 0, chars: 0, flagged_numbers_jobs: 0 } }))).toBe("direct");
});

it("저장하면 백엔드가 정한 짧은 자리(집 경로 없이)를 보이고, 폴더 열기는 고정 칸 이름으로만 부른다", async () => {
  const client = fakeClient(receipt());
  // jsdom 에는 캔버스가 없다 — 그림 그리기는 리허설 화면에서 따로 본다.
  const proto = HTMLCanvasElement.prototype as unknown as Record<string, unknown>;
  const savedGet = proto.getContext;
  const savedUrl = proto.toDataURL;
  proto.getContext = () => new Proxy({}, { get: (_t, key) => (key === "measureText" ? () => ({ width: 10 }) : () => undefined), set: () => true });
  proto.toDataURL = () => "data:image/png;base64,AAAA";
  try {
    await show(client);
    await act(async () => { (container.querySelector(".receipt-save") as HTMLButtonElement).click(); });
    await act(async () => { await Promise.resolve(); });
    expect(client.saveReceiptImage).toHaveBeenCalledWith("AAAA");
    const saved = container.querySelector(".receipt-saved");
    expect(saved?.textContent).toContain("저장했어요");
    expect(saved?.querySelector("code")?.textContent).toBe("Sonjari\\receipts\\sonjari-receipt-2026-10-21.png");
    await act(async () => { (saved?.querySelector("button") as HTMLButtonElement).click(); });
    expect(client.openFolder).toHaveBeenCalledWith("receipts");
  } finally {
    proto.getContext = savedGet;
    proto.toDataURL = savedUrl;
  }
});

it("그림의 글에는 숫자와 고정 문구뿐 — 이름 · 메일 · 경로가 들어갈 칸이 없다", () => {
  const text = receiptImageText({ claude: true, tokens: 912788, jobs: 136, pages: 611, flagged: 9, period: "2026.10.14 – 10.21" },
    (n) => n.toLocaleString("ko-KR"));
  const all = JSON.stringify(text);
  expect(text.number).toBe("912,788");
  expect(text.floor).toBe("최소");
  expect(all).not.toMatch(/@|\\\\|Users|C:/);
  expect(text.site).toBe("sonjari.com");
});

it("기간 표시 — 같은 해면 뒤쪽 해를 뺀다", () => {
  const since = new Date(2026, 9, 14, 16, 30).getTime() / 1000;
  const until = new Date(2026, 9, 21, 16, 30).getTime() / 1000;
  expect(periodLabel(since, until)).toBe("2026.10.14 – 10.21");
  expect(periodLabel(undefined, until)).toBe("");
});

it("영어 화면도 자연스러운 문장으로 — 사전에 다 있다", async () => {
  const dict = en as Record<string, string>;
  for (const key of ["이번 주 영수증", "클로드에 안 실은 본문", "최소", "토큰", "이미지로 저장", "근거 없는 숫자 표시",
    "센 글자 ÷ 4.5 로 낸 하한이라 실제는 더 커요 · 측정 판은 뺐어요", "손자리가 대신 읽은 페이지"]) {
    expect(dict[key], key).toBeTruthy();
  }
  setLangForTest("en");
  await show(fakeClient(receipt()));
  const text = container.textContent ?? "";
  expect(container.querySelector(".receipt-hero-figure")?.textContent).toBe("At least912,788tokens");
  expect(text).toContain("This week's receipt");
  expect(text).toContain("Jobs from Claude136");
  expect(text).not.toMatch(/[가-힣]/);
});
