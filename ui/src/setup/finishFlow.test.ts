/**
 * 「Sonjari 시작하기」는 어느 것이 멈춰도 화면을 넘긴다 (2026-10-06 스토어판 첫 설치, 6GB 노트북 — 「눌러도 반응 없음」).
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FINISH_RECORD_MS, FINISH_SWITCH_MS, finishSetupFlow } from "./finishFlow";

const never = () => new Promise<never>(() => undefined);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

it("when everything answers, the app switches the window and nothing else happens", async () => {
  const goSameWindow = vi.fn();
  const done = finishSetupFlow({ record: async () => "ok", switchWindow: async () => undefined, goSameWindow });
  await vi.runAllTimersAsync();

  expect(await done).toEqual({ recorded: "ok", switched: "window" });
  expect(goSameWindow).not.toHaveBeenCalled();
});

it("a backend that never answers the record does not hold the button", async () => {
  const switchWindow = vi.fn(async () => undefined);
  const done = finishSetupFlow({ record: never, switchWindow, goSameWindow: vi.fn() });

  await vi.advanceTimersByTimeAsync(FINISH_RECORD_MS - 1);
  expect(switchWindow).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(2);

  expect(switchWindow).toHaveBeenCalledTimes(1);
  expect(await done).toEqual({ recorded: "timeout", switched: "window" });
});

it("a record that fails still goes on", async () => {
  const done = finishSetupFlow({
    record: async () => {
      throw new Error("backend down");
    },
    switchWindow: async () => undefined,
    goSameWindow: vi.fn(),
  });
  await vi.runAllTimersAsync();
  expect(await done).toEqual({ recorded: "failed", switched: "window" });
});

it("the startup-task request is started but never waited for", async () => {
  const startup = vi.fn(never);
  const switchWindow = vi.fn(async () => undefined);
  const done = finishSetupFlow({ record: async () => "ok", startup, switchWindow, goSameWindow: vi.fn() });
  await vi.advanceTimersByTimeAsync(0);

  expect(startup).toHaveBeenCalledTimes(1);
  expect(switchWindow).toHaveBeenCalledTimes(1);
  expect(await done).toEqual({ recorded: "ok", switched: "window" });
});

it("a window switch that never comes back falls to the same window", async () => {
  const goSameWindow = vi.fn();
  const done = finishSetupFlow({ record: async () => "ok", switchWindow: never, goSameWindow });

  await vi.advanceTimersByTimeAsync(FINISH_SWITCH_MS - 1);
  expect(goSameWindow).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(2);

  expect(goSameWindow).toHaveBeenCalledTimes(1);
  expect(await done).toEqual({ recorded: "ok", switched: "same_window" });
});

it("outside the packaged app it goes to the same window", async () => {
  const goSameWindow = vi.fn();
  const done = finishSetupFlow({ record: async () => "ok", goSameWindow });
  await vi.runAllTimersAsync();
  expect(await done).toEqual({ recorded: "ok", switched: "same_window" });
  expect(goSameWindow).toHaveBeenCalledTimes(1);
});

it("even when all three hang, the screen moves within the two limits", async () => {
  const goSameWindow = vi.fn();
  const done = finishSetupFlow({ record: never, startup: never, switchWindow: never, goSameWindow });
  await vi.advanceTimersByTimeAsync(FINISH_RECORD_MS + FINISH_SWITCH_MS + 5);

  expect(goSameWindow).toHaveBeenCalledTimes(1);
  expect(await done).toEqual({ recorded: "timeout", switched: "same_window" });
});
