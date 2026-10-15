// @vitest-environment jsdom
/**
 * 앞 물음이 안 끝났으면 다시 묻지 않는다 (2026-10-07 「Sonjari 시작하기」가 안 눌린다 — poll.ts 머리말).
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { pollUnlessBusy } from "./poll";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("does not ask again while the last ask is still out", async () => {
  let release: () => void = () => undefined;
  const ask = vi.fn(() => new Promise<void>((resolve) => { release = resolve; }));
  const stop = pollUnlessBusy(ask, 1000);

  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(1);   // 느린 물음 하나 — 다섯 번 쌓이지 않는다

  release();
  await vi.advanceTimersByTimeAsync(1000);
  expect(ask).toHaveBeenCalledTimes(2);   // 끝나면 다음 차례에 다시 묻는다
  stop();
});

it("keeps asking after an ask that failed, and stops when told", async () => {
  const ask = vi.fn(async () => { throw new Error("닿지 못함"); });
  const stop = pollUnlessBusy(ask, 1000);

  await vi.advanceTimersByTimeAsync(3000);
  expect(ask).toHaveBeenCalledTimes(3);

  stop();
  await vi.advanceTimersByTimeAsync(3000);
  expect(ask).toHaveBeenCalledTimes(3);
});
