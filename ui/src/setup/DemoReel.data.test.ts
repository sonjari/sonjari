/**
 * 영어 화면의 「실제로 한 판」 자료 (2026-10-05).
 *
 * 영어 스토어 스크린샷의 첫 화면(PC 확인)에 한국어 과제(네이버 뉴스)가 보였다. 영어 화면에는 영어로 돌린 실제 판을 쓴다.
 * 이 자료는 손으로 지어내는 것이 아니라 판의 기록에서 뽑는 것이라, 모양이 깨지면 화면이 조용히 이상해진다 — 그것만 본다.
 */
import { expect, it } from "vitest";
import replayEn from "./demoReplay.en.json";
import replayKo from "./demoReplay.json";

const HANGUL = /[가-힣]/;

it("영어 판 자료에는 한국어가 없다 — 날짜 한 칸만 화면 언어로 바꿔 그린다", () => {
  const { recorded_on: recordedOn, ...rest } = replayEn;
  expect(JSON.stringify(rest)).not.toMatch(HANGUL);
  expect(recordedOn).toMatch(/^\d{4}년 \d{1,2}월 \d{1,2}일$/);
});

it("걸음 시각은 앞에서 뒤로 흐르고 판의 길이를 넘지 않는다", () => {
  for (const replay of [replayEn, replayKo]) {
    const times = replay.beats.map((beat) => beat.at);
    expect([...times].sort((a, b) => a - b)).toEqual(times);
    expect(times[times.length - 1]).toBeLessThanOrEqual(replay.real_seconds);
  }
});

it("결과 표는 두 칸이고 칸 이름을 싣는다", () => {
  expect(replayEn.result.columns).toHaveLength(2);
  expect(replayEn.result.rows.length).toBeGreaterThanOrEqual(3);
  for (const row of replayEn.result.rows) expect(row.title && row.press).toBeTruthy();
});
