import { describe, expect, it } from "vitest";

import { NO_PAINT, SETTLE_MAX_MS, isSettling, onAnswerPainted, onAnswerReset, onHeadJobDone } from "./settling";

describe("판은 끝났는데 답이 아직 칠해지는 중일 때", () => {
  it("판 밖에서 칠한다고 알린 판이 끝나면, 흘리던 글을 거두지 않고 자리 잡기로 들어간다", () => {
    const painting = onAnswerReset(NO_PAINT, "job-1", true);
    const done = onHeadJobDone(painting, "job-1", true, 0);

    expect(done.settle).toBe(true);
    expect(isSettling(done.state, "job-1")).toBe(true);
  });

  it("다 칠했다는 사건이 오면 자리 잡기를 끝낸다", () => {
    const settling = onHeadJobDone(onAnswerReset(NO_PAINT, "job-1", true), "job-1", true, 0).state;
    const painted = onAnswerPainted(settling, "job-1");

    expect(painted.finish).toBe(true);
    expect(painted.state).toEqual(NO_PAINT);
  });

  it("판이 끝나기 전에 다 칠해졌으면 예전처럼 바로 끝낸다", () => {
    const painted = onAnswerPainted(onAnswerReset(NO_PAINT, "job-1", true), "job-1");
    expect(painted.finish).toBe(false);

    expect(onHeadJobDone(painted.state, "job-1", true, 0).settle).toBe(false);
  });

  it("예전 백엔드(판 안에서 칠한다)면 자리 잡기에 들어가지 않는다", () => {
    const painting = onAnswerReset(NO_PAINT, "job-1", false);

    expect(onHeadJobDone(painting, "job-1", true, 0).settle).toBe(false);
  });

  it("뒤에 줄 선 판이 있으면 기다리지 않는다 — 다음 판이 바로 시작한다", () => {
    const painting = onAnswerReset(NO_PAINT, "job-1", true);
    const done = onHeadJobDone(painting, "job-1", true, 1);

    expect(done.settle).toBe(false);
    expect(done.state).toEqual(NO_PAINT);
  });

  it("실패·취소로 끝난 판은 칠할 답이 없다", () => {
    const painting = onAnswerReset(NO_PAINT, "job-1", true);

    expect(onHeadJobDone(painting, "job-1", false, 0).settle).toBe(false);
  });

  it("다른 판의 사건은 자리 잡는 판을 건드리지 않는다", () => {
    const settling = onHeadJobDone(onAnswerReset(NO_PAINT, "job-1", true), "job-1", true, 0).state;

    expect(isSettling(settling, "job-2")).toBe(false);
    expect(isSettling(settling, "")).toBe(false);
    expect(onAnswerPainted(settling, "job-2")).toEqual({ state: settling, finish: false });
  });

  it("다 칠했다는 사건을 기다리는 한도는 백엔드의 칠하기 상한(6초)보다 길다", () => {
    expect(SETTLE_MAX_MS).toBeGreaterThan(6_000);
  });
});
