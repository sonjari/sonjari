// @vitest-environment jsdom
/**
 * 설정 › 모델에서도 허깅페이스에서 고른다 (2026-10-01 밤 대표: 「마법사 말고 설정에서도」).
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { SetupApi } from "../setup/setupApi";
import { ModelSection } from "./ModelSection";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("the settings model list has a Hugging Face tab that pulls with the card's context", async () => {
  const pulled: Array<[string, number | undefined]> = [];
  const api = {
    models: vi.fn(async () => ({ models: [], pulls: {}, selection: null, satellite: false })),
    profile: vi.fn(async () => ({ gpus: [{ index: 0, name: "NVIDIA GeForce RTX 3090", vram_total_gb: 24, vram_used_gb: 1,
      driver: "", display_active: false, reserve_gb: 0.5, usable_gb: 23.5 }] })),
    hfSearch: vi.fn(async () => ({ ok: true, models: [{ repo: "empero-ai/Qwen3.8-35B-A3B-Distill-GGUF", author: "empero-ai",
      name: "Qwen3.8-35B-A3B-Distill-GGUF", params_b: 35.5, architecture: "qwen35moe", context_max: 262144, tools: true,
      best_bits: 4, downloads: 438152, likes: 165, updated: "", vision: true }], hidden: { no_tools: 0, too_big: 0 } })),
    hfFiles: vi.fn(async () => ({ ok: true, margin_gb: 1.2, files: [
      { quant: "IQ4_XS", file: "a.gguf", gb: 20.53, bits: 4, fit: "fits", recommended: true,
        tag: "hf.co/empero-ai/Qwen3.8-35B-A3B-Distill-GGUF:IQ4_XS" }] })),
    pullTag: vi.fn(async (tag: string, ctx?: number) => { pulled.push([tag, ctx]); return { ok: true, model_key: tag, status: "pulling", completed: 0, total: 0 }; }),
  } as unknown as SetupApi;
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<ModelSection api={api} />); });
  const tab = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => b.textContent?.includes("허깅페이스"))!;
  await act(async () => { tab.click(); });
  expect(host.textContent).toContain("Qwen3.8-35B-A3B-Distill-GGUF");
  // 규칙 추천이 아닌 모델(제작자가 믿을 목록 밖)은 펼쳐 두지 않는다 — 사람이 눌러 연다.
  await act(async () => { host.querySelector<HTMLButtonElement>(".hf-row-head")!.click(); });
  await act(async () => { host.querySelector<HTMLButtonElement>(".quant-chip")!.click(); });
  await act(async () => { host.querySelector<HTMLButtonElement>(".hf-get .setup-btn-go")!.click(); });
  expect(pulled).toEqual([["hf.co/empero-ai/Qwen3.8-35B-A3B-Distill-GGUF:IQ4_XS", 65536]]);
});
