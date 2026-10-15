// @vitest-environment jsdom
/**
 * 첫 실행에서 화면이 본체보다 먼저 뜬다 (2026-10-01 베타 테스터 PC) — 토큰이 아직 없으면(os error 2·3) 잠깐씩 다시 읽는다.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args: unknown[]) => invoke(...args) }));

import { loadBootstrap, tokenNotYetWritten } from "./backend";

const OK = { base_url: "http://127.0.0.1:8091", control_token: "t", mode: "server" };
const MISSING = "제어 토큰을 읽지 못했습니다 (C:/Users/x/AppData/Local/Sonjari/data/control.token): 지정된 경로를 찾을 수 없습니다. (os error 3)";

beforeEach(() => {
  (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {};
  invoke.mockReset();
});
afterEach(() => {
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

it("waits while the backend has not written the token yet", async () => {
  invoke.mockRejectedValueOnce(MISSING).mockRejectedValueOnce(MISSING).mockResolvedValueOnce(OK);
  const slept: number[] = [];
  const got = await loadBootstrap(90_000, async (ms) => { slept.push(ms); });
  expect(got.controlToken).toBe("t");
  expect(slept).toEqual([2000, 2000]);
});

it("does not wait on other errors", async () => {
  invoke.mockRejectedValueOnce("제어 토큰 파일이 비어 있습니다.");
  await expect(loadBootstrap(90_000, async () => undefined)).rejects.toBe("제어 토큰 파일이 비어 있습니다.");
  expect(invoke).toHaveBeenCalledTimes(1);
});

it("gives up with something the person can do", async () => {
  invoke.mockRejectedValue(MISSING);
  await expect(loadBootstrap(0, async () => undefined)).rejects.toThrow("다시 시도");
});

it("knows which errors are worth waiting for", () => {
  expect(tokenNotYetWritten(MISSING)).toBe(true);
  expect(tokenNotYetWritten("(os error 2)")).toBe(true);
  expect(tokenNotYetWritten("(os error 5)")).toBe(false);
});
