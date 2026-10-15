// @vitest-environment jsdom
/**
 * 끝내기 전에 다 됐는지 한 줄씩 (2026-10-12).
 *
 * 금색 단추만 따라 눌러 온 사람이 무엇이 됐고 무엇이 안 됐는지를 끝에서 본다. 지키는 것: 된 것만 됐다고 적는다 ·
 * 안 된 줄에는 그 자리에서 누를 단추가 있다 · 이 PC 에 없는 도구는 「없어도 된다」로 적는다 · 아직 못 찾아본 도구는 줄이 없다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { SetupReadiness, readinessRows } from "./SetupWizard";
import type { ConnectClient, ConnectScan } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const client = (over: Partial<ConnectClient>): ConnectClient =>
  ({ id: "claude_desktop", name: "Claude Desktop", installed: true, registered: false, can_apply: true, reason: "", ...over }) as ConnectClient;
const scanOf = (...clients: ConnectClient[]) => ({ clients } as unknown as ConnectScan);

it("says the model is ready only when it was actually applied", () => {
  expect(readinessRows({ modelName: "", modelCtx: 0, scan: null })).toEqual([
    { id: "model", state: "todo", text: "모델 · 아직 적용하지 않았습니다", fix: "model" },
  ]);
  const [model] = readinessRows({ modelName: "Sample 27B", modelCtx: 65536, scan: null });
  expect(model).toEqual({ id: "model", state: "done", text: "모델 · Sample 27B · 창 64K 로 돌려 봤습니다" });
});

it("makes no row for a tool it has not looked for yet", () => {
  expect(readinessRows({ modelName: "M", modelCtx: 32768, scan: null }).map((row) => row.id)).toEqual(["model"]);
});

it("offers the fix on the row when Claude is running and still unconnected", () => {
  const rows = readinessRows({ modelName: "M", modelCtx: 32768, scan: scanOf(client({ running: true, reason: "running" })) });
  expect(rows[1]).toMatchObject({ id: "claude_desktop", state: "todo", fix: "restart_claude" });
});

it("marks connected tools done and missing tools as fine to skip", () => {
  const rows = readinessRows({
    modelName: "M", modelCtx: 32768,
    scan: scanOf(client({ registered: true }), client({ id: "claude_code", name: "Claude Code", installed: true, registered: null, reason: "cli_missing" })),
  });
  expect(rows.map((row) => [row.id, row.state])).toEqual([["model", "done"], ["claude_desktop", "done"], ["claude_code", "skip"]]);
  expect(rows[2].fix).toBeUndefined();
  const none = readinessRows({ modelName: "M", modelCtx: 32768, scan: scanOf(client({ installed: false })) });
  expect(none[1]).toMatchObject({ state: "skip" });
  expect(none[1].text).toContain("없어도 Sonjari는 됩니다");
});

it("sends the person to the right place when they press the fix", async () => {
  const onFix = vi.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => {
    createRoot(host).render(<SetupReadiness onFix={onFix} rows={[
      { id: "model", state: "todo", text: "모델 · 아직 적용하지 않았습니다", fix: "model" },
      { id: "claude_desktop", state: "todo", text: "Claude 앱 · 켜져 있어 아직 못 이었습니다", fix: "restart_claude" },
      { id: "claude_code", state: "done", text: "Claude Code · 이었습니다" },
    ]} />);
  });
  const buttons = [...host.querySelectorAll("button")];
  expect(buttons.map((button) => button.textContent)).toEqual(["모델 고르러 가기", "지금 닫고 잇기"]);
  await act(async () => { buttons[0].click(); });
  await act(async () => { buttons[1].click(); });
  expect(onFix.mock.calls).toEqual([["model"], ["restart_claude"]]);
  host.remove();
});
