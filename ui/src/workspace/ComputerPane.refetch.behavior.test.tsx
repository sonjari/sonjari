// @vitest-environment jsdom
/**
 * 걸음이 「도는 중 → 끝」으로 바뀌면 본문을 다시 연다 (2026-10-26 대표 첫 실제 판).
 *
 * Claude 가 pytest 를 돌린 걸음을 열었더니 줄 번호 「1」만 있었다. 본문은 걸음 번호가 바뀔 때만 열렸다 — 마지막 걸음을 따라가는
 * 동안 그 걸음은 도는 중(명령 결과 전)에 한 번 열리고, 결과가 와도 번호가 같아 다시 안 열렸다.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import { ComputerPane } from "./ComputerPane";
import type { Observation, StepRow } from "./observation";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function bashStep(status: "running" | "completed", text: string): Observation {
  return {
    job_id: "claude-1", step: 1, tool: "Bash", ok: true, status, error: "", kind: "code", title: "Bash", at: 1, took_ms: 0,
    truncated: false, arguments: { command: "python -m pytest -q test_price.py" }, payload: { command: "python -m pytest -q test_price.py", text }, truncation: {},
    actor: "claude",
  };
}

it("명령 걸음의 결과가 오면 같은 걸음 번호여도 본문을 다시 연다", async () => {
  let current = bashStep("running", "$ python -m pytest -q test_price.py");
  const row = (): StepRow => {
    const { job_id: _j, arguments: _a, payload: _p, truncation: _t, ...rest } = current;
    return rest;
  };
  const known: Partial<JarvisClient> = {
    listSteps: vi.fn(async () => ({ job_id: "claude-1", count: 1, items: [row()] })),
    getStep: vi.fn(async () => structuredClone(current)),
  };
  // 이 칸이 부르는 나머지(미리보기 · 상태)는 빈 답으로.
  const client = new Proxy(known, {
    get: (target, key) => (key in target ? target[key as keyof JarvisClient] : async () => ({})),
  }) as JarvisClient;
  act(() => {
    root.render(
      <ComputerPane client={client} open live jobId="claude-1" progress={[]} plan={[]} elapsedLabel="3초" onCancel={() => undefined} mode="code" codeWorkspace="D:/repo" />,
    );
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(50); });
  expect(container.querySelector(".obs-code")?.textContent).toContain("python -m pytest");
  expect(container.querySelector(".obs-code")?.textContent).not.toContain("2 passed");

  current = bashStep("completed", "$ python -m pytest -q test_price.py\n..   [100%]\n2 passed in 0.01s");
  await act(async () => { await vi.advanceTimersByTimeAsync(2_500); });
  expect(container.querySelector(".obs-code")?.textContent).toContain("2 passed in 0.01s");
  expect(known.getStep).toHaveBeenCalledTimes(2);
});
