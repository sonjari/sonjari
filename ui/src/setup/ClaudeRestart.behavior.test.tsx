// @vitest-environment jsdom
/**
 * Claude Desktop 을 손자리가 대신 닫고 · 잇고 · 다시 켠다 (2026-10-12).
 *
 * 처음 깐 두 사람이 같은 자리에서 헤맸다 — 금색 단추만 따라 누르면 「닫으면 잇습니다」를 지나쳐 끝났고, 「껐다 켜라」는
 * 글로만 있었다. 지키는 것: 묻기 전에는 아무것도 끄지 않는다 · 안 꺼지면 직접 끄는 법을 말한다 · 단추에 하는 일을 적는다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ClaudeRestartDialog, ConnectPanel, desktopAwaitingRestart } from "./ConnectPanel";
import type { ConnectClient, ConnectRestartResult, ConnectScan, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function desktop(over: Partial<ConnectClient> = {}): ConnectClient {
  return { id: "claude_desktop", name: "Claude Desktop", installed: true, registered: false, can_apply: true,
    reason: "running", running: true, ...over } as ConnectClient;
}

function scanOf(...clients: ConnectClient[]): ConnectScan {
  return { server_name: "sonjari", entry: {}, clients, not_supported: [],
    hooks: { claude_code_session_start: false, can_apply: false } } as unknown as ConnectScan;
}

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(node); });
  return host;
}

const buttonNamed = (host: HTMLElement, text: string) =>
  [...host.querySelectorAll("button")].find((item) => item.textContent?.trim() === text) as HTMLButtonElement | undefined;

it("knows when a running Claude Desktop is the thing standing between the person and a connection", () => {
  expect(desktopAwaitingRestart(scanOf(desktop()))?.id).toBe("claude_desktop");
  expect(desktopAwaitingRestart(scanOf(desktop({ running: false, waiting_for_close: true })))?.id).toBe("claude_desktop");
  expect(desktopAwaitingRestart(scanOf(desktop({ registered: true })))).toBeNull();          // 이미 이었다
  expect(desktopAwaitingRestart(scanOf(desktop({ running: false })))).toBeNull();            // 꺼져 있다 — 그냥 이으면 된다
  expect(desktopAwaitingRestart(scanOf(desktop({ installed: false })))).toBeNull();
  expect(desktopAwaitingRestart(scanOf(desktop({ can_apply: false })))).toBeNull();          // 쓸 설정 파일이 없다
  expect(desktopAwaitingRestart(null)).toBeNull();
});

it("asks first, and closes Claude only after the person presses", async () => {
  const restart = vi.fn(async (): Promise<ConnectRestartResult> => ({ ok: true, desktop: "restarted" }));
  const onDone = vi.fn();
  const onClose = vi.fn();
  const host = await mount(<ClaudeRestartDialog api={{ connectRestartDesktop: restart } as unknown as SetupApi}
    doneLabel="Sonjari 시작하기" onDone={onDone} onClose={onClose} />);

  expect(restart).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Claude 를 다시 켤까요?");
  expect(host.textContent).toContain("끊깁니다");                       // 무엇을 잃는지 누르기 전에 말한다

  await act(async () => { buttonNamed(host, "닫고 · 잇고 · 다시 켜기")!.click(); });
  expect(restart).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Claude 가 다시 켜지고 있습니다");
  await act(async () => { buttonNamed(host, "Sonjari 시작하기")!.click(); });
  expect(onDone).toHaveBeenCalledWith({ ok: true, desktop: "restarted" });
  expect(onClose).not.toHaveBeenCalled();
});

it("leaves everything alone when the person says later", async () => {
  const restart = vi.fn();
  const onClose = vi.fn();
  const host = await mount(<ClaudeRestartDialog api={{ connectRestartDesktop: restart } as unknown as SetupApi}
    doneLabel="닫기" onDone={() => undefined} onClose={onClose} />);
  await act(async () => { buttonNamed(host, "나중에")!.click(); });
  expect(restart).not.toHaveBeenCalled();
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("says how to quit Claude by hand when it would not close, and lets the person try again", async () => {
  const restart = vi.fn(async (): Promise<ConnectRestartResult> => ({ ok: false, error: "claude_desktop_did_not_close" }));
  const onDone = vi.fn();
  const host = await mount(<ClaudeRestartDialog api={{ connectRestartDesktop: restart } as unknown as SetupApi}
    doneLabel="닫기" onDone={onDone} onClose={() => undefined} />);
  await act(async () => { buttonNamed(host, "닫고 · 잇고 · 다시 켜기")!.click(); });
  expect(host.querySelector('[role="alert"]')!.textContent).toContain("작업 표시줄 오른쪽 구석");
  expect(buttonNamed(host, "닫고 · 잇고 · 다시 켜기")).toBeTruthy();     // 다시 누를 수 있다
  expect(onDone).not.toHaveBeenCalled();
});

it("tells the person to reopen Claude themselves when we connected but could not start it", async () => {
  const restart = vi.fn(async (): Promise<ConnectRestartResult> => ({ ok: true, desktop: "closed_only" }));
  const host = await mount(<ClaudeRestartDialog api={{ connectRestartDesktop: restart } as unknown as SetupApi}
    doneLabel="닫기" onDone={() => undefined} onClose={() => undefined} />);
  await act(async () => { buttonNamed(host, "닫고 · 잇고 · 다시 켜기")!.click(); });
  expect(host.textContent).toContain("직접 다시 켜 주세요");
});

it("offers the button on the Claude Desktop row while it is running, and reports what it found", async () => {
  const scan = scanOf(desktop(), { id: "cursor", name: "Cursor", installed: false, registered: false, can_apply: false, reason: "not_installed" } as ConnectClient);
  const seen: ConnectScan[] = [];
  const api = {
    connectScan: vi.fn(async () => scan),
    guideSkillStatus: vi.fn(async () => { throw new Error("none"); }),
  } as unknown as SetupApi;
  const host = await mount(<ConnectPanel api={api} onScan={(found) => seen.push(found)} />);
  await act(async () => { await Promise.resolve(); });
  expect(seen.at(-1)).toBe(scan);
  expect(buttonNamed(host, "지금 닫고 잇기")).toBeTruthy();
  await act(async () => { buttonNamed(host, "지금 닫고 잇기")!.click(); });
  expect(host.querySelector('[role="dialog"]')!.textContent).toContain("Claude 를 다시 켤까요?");
});
