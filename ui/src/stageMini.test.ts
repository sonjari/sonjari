import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLOSE_AFTER_MS, StageMiniWatcher } from "./stageMini";

const ev = (event: string, payload: Record<string, unknown>) => ({ event, payload });

describe("StageMiniWatcher", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("opens only when a job handed over by an outside AI uses the browser", () => {
    const open = vi.fn();
    const watcher = new StageMiniWatcher(open, vi.fn());
    watcher.onEvent(ev("agent_started", { job_id: "a", origin: "chat" }));
    watcher.onEvent(ev("agent_progress", { job_id: "a", tool: "browser_open" }));
    expect(open).not.toHaveBeenCalled();
    watcher.onEvent(ev("agent_started", { job_id: "m", origin: "mcp" }));
    watcher.onEvent(ev("agent_progress", { job_id: "m", tool: "local_read_document" }));
    expect(open).not.toHaveBeenCalled();
    watcher.onEvent(ev("agent_progress", { job_id: "m", tool: "browser_open" }));
    watcher.onEvent(ev("agent_progress", { job_id: "m", tool: "browser_extract" }));
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("closes a little after the last outside job ends, not immediately", () => {
    const close = vi.fn();
    const watcher = new StageMiniWatcher(vi.fn(), close);
    watcher.onEvent(ev("agent_started", { job_id: "m", origin: "mcp" }));
    watcher.onEvent(ev("agent_progress", { job_id: "m", tool: "site_run" }));
    watcher.onEvent(ev("job_completed", { job_id: "m" }));
    vi.advanceTimersByTime(CLOSE_AFTER_MS - 100);
    expect(close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("stays open when the next outside job starts browsing before it closes", () => {
    const open = vi.fn();
    const close = vi.fn();
    const watcher = new StageMiniWatcher(open, close);
    watcher.onEvent(ev("agent_started", { job_id: "m1", origin: "mcp" }));
    watcher.onEvent(ev("agent_progress", { job_id: "m1", tool: "browser_open" }));
    watcher.onEvent(ev("job_completed", { job_id: "m1" }));
    watcher.onEvent(ev("agent_started", { job_id: "m2", origin: "mcp" }));
    watcher.onEvent(ev("agent_progress", { job_id: "m2", tool: "browser_open" }));
    vi.advanceTimersByTime(CLOSE_AFTER_MS * 2);
    expect(close).not.toHaveBeenCalled();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

describe("StageMiniWatcher wiring", () => {
  // ★ 2026-09-26 노트북 실측: 작은 창이 한 번도 안 떴다 — 감시기가 HUD(`useJarvis`)에 붙어 있었는데 HUD 창은 08-06 에 없앴다.
  //   앱이 도는 동안 늘 있는 창은 작업 창(WorkspaceApp)뿐이다. 거기서 이벤트를 먹여야 한다.
  it("is fed by the workspace window, the only window that always runs", () => {
    const files = import.meta.glob("./WorkspaceApp.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const source = files["./WorkspaceApp.tsx"];
    expect(source).toContain("new StageMiniWatcher(");
    expect(source).toContain("stageMini.onEvent(event)");
  });
});
