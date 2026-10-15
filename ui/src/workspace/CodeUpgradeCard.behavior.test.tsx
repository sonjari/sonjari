// @vitest-environment jsdom
/**
 * 코드 일을 보내는 순간의 모델 권고 카드 (2026-10-01 밤) — 막지 않고, 받으면 코드 역할에만, 「그냥 진행」이면 닫힌다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { CodeUpgrade, ModelRole, SetupApi } from "../setup/setupApi";
import { CodeUpgradeCard } from "./CodeUpgradeCard";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const OFFER: CodeUpgrade = { tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S", name: "Qwen 3.8 27B · 3비트(IQ3_S)", size_gb: 12.97,
  params_b: 27.3, current: "qwen3.5:9b", current_params_b: 9, installed: false, measured: false, basis: "규칙 추천 — …" };

async function render(onClose = () => undefined) {
  const pulled: Array<[string, number | undefined, ModelRole | undefined]> = [];
  const api = {
    pullTag: vi.fn(async (tag: string, ctx?: number, role?: ModelRole) => { pulled.push([tag, ctx, role]); return { ok: true, model_key: tag, status: "pulling", completed: 0, total: 0 }; }),
    modelPicker: vi.fn(async () => ({ pulls: {} })),
  } as unknown as SetupApi;
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<CodeUpgradeCard api={api} offer={OFFER} onClose={onClose} />); });
  return { host, pulled };
}

it("says the work goes on, and pulls for the code role only", async () => {
  const { host, pulled } = await render();
  expect(host.textContent).toContain("지금 일은 그대로 진행됩니다");
  expect(host.textContent).toContain("규칙 추천");
  await act(async () => { host.querySelector<HTMLButtonElement>(".code-upgrade-go")!.click(); });
  expect(pulled).toEqual([[OFFER.tag, 65536, "code"]]);
  expect(host.textContent).toContain("받는 중");
});

it("「그냥 진행」 closes it", async () => {
  const onClose = vi.fn();
  const { host } = await render(onClose);
  const close = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("그냥 진행"))!;
  await act(async () => { close.click(); });
  expect(onClose).toHaveBeenCalled();
});
