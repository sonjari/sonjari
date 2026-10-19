// @vitest-environment jsdom
/**
 * 설정 › 연결의 「이번 주 손자리가 클로드 대신 읽은 양」 카드 (2026-10-19).
 * 하한만 말한다 — 「최소 N 토큰」 · 근거 한 줄. 약 · 배 · % · 금액 · 시간은 없다. 멈춘 일은 나눠 적는다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import type { SavingsReceipt } from "../types";
import { SAVINGS_DAYS, SavingsCard } from "./SavingsCard";

const BASIS = "바깥 AI 가 맡긴 일에서 이 PC 가 읽은 본문 글자 수(센 값)를 토큰당 4.5자로 나눈 하한을 판마다 더했습니다.";

function receipt(extra: Partial<SavingsReceipt> = {}): SavingsReceipt {
  return {
    kind: "floor", days: 7, since: 0, until: 0, tokens_at_least: 711872, text_chars: 3203604, reads: 392,
    jobs: { total: 108, done: 104, stopped: 4, with_reads: 99 }, in_progress: 0,
    by_host: [{ host: "Claude Code", tokens_at_least: 711872, jobs: 108, names: ["Claude Code"] }],
    top: [{ job_id: "a", prompt: "레딧 세 게시판 조사", tokens_at_least: 48473, host: "Claude Code", status: "done", finished_at: 1 }],
    excluded: { no_host_name: 411, person_via_discord: 24, measurement: 0 },
    host_word: "claude", basis: BASIS, ...extra,
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
});

async function render(getSavings: (days?: number) => Promise<SavingsReceipt>) {
  await act(async () => { root.render(<SavingsCard client={{ getSavings }} />); });
}

it("하한 한 줄과 맡긴 일 수 · 근거를 보이고, 부풀리는 말은 없다", async () => {
  const getSavings = vi.fn(async () => receipt());
  await render(getSavings);

  expect(getSavings).toHaveBeenCalledWith(SAVINGS_DAYS);
  const text = container.textContent ?? "";
  expect(text).toContain("이번 주 손자리가 클로드 대신 읽은 양");
  expect(text).toContain("최소 711,872 토큰");
  expect(text).toContain("(맡긴 일 108건)");
  expect(text).toContain("끝난 일 104건 · 멈춘 일 4건");
  expect(text).toContain(BASIS);
  expect(text).toContain("레딧 세 게시판 조사");
  expect(text).not.toMatch(/약|배|%|\$|달러|아꼈|절약|시간/);
});

it("코덱스가 섞이면 「클로드 대신」이라 하지 않고, 맡긴 일이 없으면 없다고 말한다", async () => {
  await render(async () => receipt({ host_word: "outside_ai", jobs: { total: 0, done: 0, stopped: 0, with_reads: 0 }, top: [] }));

  const text = container.textContent ?? "";
  expect(text).toContain("이번 주 손자리가 바깥 AI 대신 읽은 양");
  expect(text).toContain("지난 7일 동안 바깥 AI 가 맡긴 일이 없습니다.");
  expect(text).not.toContain("최소");
});

it("못 불러오면 숨지 않고 한 줄로 말한다", async () => {
  await render(async () => { throw new Error("offline"); });

  expect(container.textContent).toContain("손자리가 대신 읽은 양을 불러오지 못했습니다.");
});

it("영어 사전에 카드 문장이 다 있고, 영어에도 부풀리는 말이 없다", () => {
  const EN = en as Record<string, string>;
  const keys = [
    "이번 주 손자리가 클로드 대신 읽은 양", "이번 주 손자리가 바깥 AI 대신 읽은 양", "최소 {0} 토큰", "(맡긴 일 {0}건)",
    "끝난 일 {0}건 · 멈춘 일 {1}건 — 멈춘 일도 읽은 것은 셉니다.", "지난 7일 동안 바깥 AI 가 맡긴 일이 없습니다.",
    "가장 많이 덜어 준 일", "손자리가 대신 읽은 양을 불러오지 못했습니다.",
  ];
  for (const key of keys) {
    expect(EN[key], key).toBeTruthy();
    expect(EN[key]).not.toMatch(/\babout\b|\baround\b|\btimes\b|%|\$|saved time|faster/i);
  }
  expect(EN["최소 {0} 토큰"]).toContain("At least");
});
