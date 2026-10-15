// @vitest-environment jsdom
/**
 * 설정 › 모델 — 그림을 켠 채로는 빠듯한 칸은 「글만 읽기」 메모리와 표시를 보인다 (2026-10-15).
 *
 * 사무실 6GB 노트북: 「Qwen 3.5 4B (3비트) · 48K 까지 · 4.9GB — 가능」을 눌렀더니 그림을 단 채 올라가 카드에 70.7% 만 올라갔다.
 * 이제 백엔드가 그 칸을 글만 읽기로 정하고(`text_only` · `text_only_need_gb`) 적용도 그렇게 한다. 화면은 그 값을 그대로 보인다.
 *
 * 지키는 약속:
 * - `text_only` 칸은 글만 읽기 메모리(4.2GB)와 「글만 읽기」를 보인다 — 그림을 켠 어림값(4.9GB)을 보이지 않는다.
 * - 옛 백엔드(그 칸이 없다)는 예전 화면 그대로다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { CatalogModel, SetupApi } from "../setup/setupApi";
import { ModelSection } from "./ModelSection";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const hosts: HTMLElement[] = [];
afterEach(() => {
  hosts.splice(0).forEach((host) => host.remove());
});

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.appendChild(host);
  hosts.push(host);
  await act(async () => { createRoot(host).render(node); });
  return host;
}

function row(extra: Partial<CatalogModel>): CatalogModel {
  return {
    key: "qwen3.5-4b-q3", name: "Qwen 3.5 4B (3비트)", vendor: "Alibaba · Unsloth 압축", ollama_tag: "hf.co/unsloth/Qwen3.5-4B-GGUF:UD-Q3_K_XL",
    download_gb: 3.1, vram_gb: { "49152": 4.9, "32768": 4.3 }, roles: ["chat"], vision: true, installed: true, fits: true,
    largest_fitting_ctx: 49152, status: "verified", license: "Apache 2.0", evidence: [], caution: "", links: [],
    ...extra,
  } as unknown as CatalogModel;
}

function apiWith(model: CatalogModel): SetupApi {
  return {
    models: vi.fn(async () => ({ models: [model], pulls: {}, satellite: false,
      selection: { catalog_key: "", chat_model: "hf.co/unsloth/Qwen3.5-4B-GGUF:UD-IQ3_XXS", num_ctx: 32768 } })),
    profile: vi.fn(async () => ({ gpus: [{ index: 0, name: "시험 카드", vram_total_gb: 6, vram_used_gb: 1.2,
      driver: "", display_active: true, reserve_gb: 1, usable_gb: 5 }] })),
  } as unknown as SetupApi;
}

const fitText = (host: HTMLElement) => host.querySelector(".model-row-fit")!.textContent ?? "";

it("글만 읽기 칸은 글만 읽기 메모리와 표시를 보인다", async () => {
  const host = await mount(<ModelSection api={apiWith(row({ text_only: true, text_only_need_gb: 4.21 }))} />);
  expect(fitText(host)).toContain("4.2GB");
  expect(fitText(host)).toContain("글만 읽기");
  expect(fitText(host)).not.toContain("4.9GB");
});

it("옛 백엔드(칸이 없다)는 예전 그대로다", async () => {
  const host = await mount(<ModelSection api={apiWith(row({}))} />);
  expect(fitText(host)).toContain("4.9GB");
  expect(fitText(host)).not.toContain("글만 읽기");
});
