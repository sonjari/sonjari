// @vitest-environment jsdom
/**
 * 허깅페이스에서 고른 모델도 「글만 읽기」로 받을 수 있다 (2026-10-13).
 *
 * 그날 6GB 노트북: 눈(그림 부속)을 단 4B 는 창 32K 로 그래픽카드에 다 못 올라갔고, 눈을 빼니 창 48K 까지 올라갔다.
 * 그 길이 목록 모델에만 있었다 — 허깅페이스에서 고른 모델에는 고르는 줄이 없었다.
 *
 * 지키는 약속:
 * - 그림 부속이 따로 오는 양자화(`projector_gb`)에서만 줄이 보인다.
 * - 말하지 않으면 예전 그대로 그림을 읽게 받는다. 「글만 읽기」를 고르면 받기에 그 뜻이 실린다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { HfPicker, type HfPick } from "./HfPicker";
import type { GpuCard, HfFile, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CARD = { index: 0, name: "시험 카드 6GB", vram_total_gb: 6, vram_used_gb: 1, driver: "", display_active: true,
  reserve_gb: 1, usable_gb: 5 } as GpuCard;
const REPO = "someone/Sample-4B-GGUF";
const WITH_PART = { quant: "UD-Q3_K_XL", file: "a.gguf", gb: 2.97, file_gb: 2.33, projector_gb: 0.64, bits: 3, fit: "fits",
  tag: `hf.co/${REPO}:UD-Q3_K_XL` } as unknown as HfFile;
const NO_PART = { quant: "Q3_K_M", file: "b.gguf", gb: 2.2, bits: 3, fit: "fits", tag: `hf.co/${REPO}:Q3_K_M` } as unknown as HfFile;

const api = (files: HfFile[]) => ({
  hfSearch: vi.fn(async () => ({ ok: true, models: [{ repo: REPO, author: "someone", name: "Sample-4B-GGUF", params_b: 4.6,
    architecture: "qwen35", context_max: 262144, tools: true, best_bits: 4, downloads: 10, likes: 1, updated: "", vision: true }] })),
  hfFiles: vi.fn(async () => ({ ok: true, files, margin_gb: 1.2 })),
} as unknown as SetupApi);

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

async function open(file: HfFile, onGet: (pick: HfPick) => void) {
  host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => {
    createRoot(host!).render(
      <HfPicker api={api([file])} card={CARD} busy={false} picked={{ repo: REPO, file }} onPick={() => undefined} onGet={onGet} />,
    );
  });
  await act(async () => {
    (host!.querySelector(".hf-row-head") as HTMLButtonElement).click();
  });
}

const chips = () => [...host!.querySelectorAll<HTMLButtonElement>('.hf-eyes [role="radio"]')];
const get = () => host!.querySelector<HTMLButtonElement>(".hf-get .setup-btn-go")!;

it("그림 부속이 따로 오는 양자화에서만 그림 읽기 줄이 보인다", async () => {
  await open(WITH_PART, () => undefined);
  expect(chips().map((chip) => chip.getAttribute("aria-checked"))).toEqual(["true", "false"]);
  expect(chips()[1].textContent).toContain("0.6GB");

  host!.remove();
  await open(NO_PART, () => undefined);
  expect(host!.querySelector(".hf-eyes")).toBeNull();
});

it("말하지 않으면 예전 그대로 그림을 읽게 받는다", async () => {
  const onGet = vi.fn();
  await open(WITH_PART, onGet);

  await act(async () => { get().click(); });

  expect(onGet).toHaveBeenCalledWith({ repo: REPO, file: WITH_PART });
});

it("글만 읽기를 고르면 받기에 그 뜻이 실리고, 무엇을 내주는지 적힌다", async () => {
  const onGet = vi.fn();
  await open(WITH_PART, onGet);

  await act(async () => { chips()[1].click(); });
  expect(chips().map((chip) => chip.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  expect(host!.querySelector(".hf-eyes .model-eyes-note")?.textContent).toContain("읽지 못합니다");
  await act(async () => { get().click(); });

  expect(onGet).toHaveBeenCalledWith({ repo: REPO, file: WITH_PART, textOnly: true });
});
