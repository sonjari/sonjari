// @vitest-environment jsdom
/**
 * 모델 단계에도 Ollama 설치 칸이 나온다 (2026-10-06 스토어 공개판 첫 설치, RTX 3050 사무실 PC).
 *
 * Ollama 를 안 깐 채 「받고 적용하기」를 누르면 「위의 『Ollama 설치』를 먼저 눌러 주세요」가 떴는데 그 단추는
 * 앞 단계에만 있었다. 모델 단계에 붙는 꼴(`ollamaOnly`)은 Ollama 가 없을 때만 설치 칸을 그리고, 돌고 있으면
 * 아무것도 안 그린다. 이전 기억 칸은 이 꼴에 안 나온다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { FirstRunPanel } from "./FirstRunPanel";
import type { BackupStatus, OllamaStatus, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MISSING: OllamaStatus = { running: false, version: "", bundled: "0.35.1", managed: false, can_install: true, source: "",
  install: { phase: "idle" } };
const RUNNING: OllamaStatus = { ...MISSING, running: true, version: "0.35.1", can_install: false };
const OLD_MEMORY: BackupStatus = { enabled: true, root: "", keep: 3, generations: [], memory_empty: true, delete_confirmation: "",
  latest: { generation: "g1", created_at: 1790000000, reason: "", tables: { conversation_messages: 12, facts: 3 }, files: [] } };

function fakeApi(status: OllamaStatus): SetupApi {
  return {
    ollamaStatus: vi.fn(async () => status),
    backupStatus: vi.fn(async () => OLD_MEMORY),
    ollamaInstall: vi.fn(async () => ({ ok: true, phase: "resolving" })),
  } as unknown as SetupApi;
}

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

async function render(api: SetupApi, ollamaOnly: boolean) {
  host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(<FirstRunPanel api={api} ollamaOnly={ollamaOnly} />);
  });
  await act(async () => {});
  return host;
}

it("on the model step, a PC without Ollama gets the install button right there", async () => {
  const api = fakeApi(MISSING);
  const view = await render(api, true);

  const row = view.querySelector('[data-testid="ollama-row"]');
  expect(row).not.toBeNull();
  const button = row!.querySelector("button");
  expect(button).not.toBeNull();

  await act(async () => {
    button!.click();
  });
  expect(api.ollamaInstall).toHaveBeenCalledTimes(1);
});

it("on the model step, the old-memory question does not come along", async () => {
  const view = await render(fakeApi(MISSING), true);
  expect(view.querySelector('[data-testid="restore-row"]')).toBeNull();
});

it("on the model step, a PC where Ollama is running shows nothing", async () => {
  const view = await render(fakeApi(RUNNING), true);
  expect(view.innerHTML).toBe("");
});

it("on the first step nothing changed: the Ollama line and the old-memory question both show", async () => {
  const view = await render(fakeApi(RUNNING), false);
  expect(view.querySelector('[data-testid="ollama-row"]')).not.toBeNull();
  expect(view.querySelector('[data-testid="restore-row"]')).not.toBeNull();
});
