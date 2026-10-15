// @vitest-environment jsdom
/**
 * 허깅페이스에서 직접 고르기 (2026-10-01 밤) — 이 카드에 들어가는 양자화만 누를 수 있고, 막히면 직접 입력을 안내한다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { HfPicker, type HfPick } from "./HfPicker";
import type { GpuCard, SetupApi } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CARD = { index: 0, name: "NVIDIA GeForce RTX 5080", vram_total_gb: 15.9, vram_used_gb: 1, driver: "", display_active: true,
  reserve_gb: 1, usable_gb: 14.9 } as GpuCard;

function fakeApi(fail = false): SetupApi {
  return {
    hfSearch: vi.fn(async () => (fail
      ? { ok: false, error: "hf_unreachable", models: [] }
      : { ok: true, models: [{ repo: "unsloth/Qwen3.8-27B-GGUF", author: "unsloth", name: "Qwen3.8-27B-GGUF", params_b: 27.3,
          architecture: "qwen35", context_max: 262144, tools: true, best_bits: 3, downloads: 6271224, likes: 4767, updated: "", vision: true }],
        hidden: { no_tools: 5, too_big: 7 } })),
    hfFiles: vi.fn(async () => ({ ok: true, files: [
      { quant: "UD-IQ3_S", file: "a.gguf", gb: 12.04, bits: 3, fit: "fits", tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S" },
      { quant: "UD-IQ4_XS", file: "b.gguf", gb: 14.25, bits: 4, fit: "tight", tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ4_XS" },
      { quant: "UD-Q4_K_M", file: "c.gguf", gb: 16.46, bits: 4, fit: "over", tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M" },
    ], margin_gb: 1.2 })),
  } as unknown as SetupApi;
}

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

async function render(api: SetupApi, onPick: (p: HfPick | null) => void, picked: HfPick | null = null) {
  host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(<HfPicker api={api} card={CARD} busy={false} picked={picked} onPick={onPick} onGet={() => undefined} />);
  });
  return root;
}

it("lists models that fit and only lets you pick quants that fit", async () => {
  const onPick = vi.fn();
  await render(fakeApi(), onPick);
  expect(host!.textContent).toContain("Qwen3.8-27B-GGUF");
  expect(host!.textContent).toContain("숨김");
  await act(async () => {
    (host!.querySelector(".hf-row-head") as HTMLButtonElement).click();
  });
  const chips = [...host!.querySelectorAll<HTMLButtonElement>(".quant-chip")].map((b) => b.textContent);
  expect(chips.some((c) => c?.startsWith("UD-IQ3_S"))).toBe(true);
  expect(chips.some((c) => c?.startsWith("UD-IQ4_XS"))).toBe(true);
  expect(chips.some((c) => c?.startsWith("UD-Q4_K_M"))).toBe(false);
  expect(host!.textContent).toContain("더 큰 1개");
  await act(async () => {
    (host!.querySelector(".quant-chip") as HTMLButtonElement).click();
  });
  expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ repo: "unsloth/Qwen3.8-27B-GGUF" }));
});

it("tells the person what to do when Hugging Face cannot be reached", async () => {
  await render(fakeApi(true), () => undefined);
  expect(host!.textContent).toContain("허깅페이스에 닿지 못했습니다");
  expect(host!.textContent).toContain("hf.co/");
});

// ★ 2026-10-03 (레딧 댓글): 「추천」 대신 확인한 사실만 적는다.
it("labels only what was checked — no bare 「추천」", async () => {
  const api = {
    hfSearch: vi.fn(async () => ({ ok: true, models: [
      { repo: "unsloth/Qwen3.8-27B-GGUF", author: "unsloth", name: "Qwen3.8-27B-GGUF", params_b: 27.3, architecture: "qwen35",
        context_max: 262144, tools: true, best_bits: 3, downloads: 6271224, likes: 4767, updated: "", vision: true,
        recommended: true, checks: ["official_base", "pc_measured"],
        pc_measured: { quant: "UD-IQ3_S", ceiling: 65536, tokens_per_sec: 41.2 } },
      { repo: "Qwen/Qwen3-8B-GGUF", author: "Qwen", name: "Qwen3-8B-GGUF", params_b: 8.2, architecture: "qwen3",
        context_max: 32768, tools: true, best_bits: 8, downloads: 100, likes: 1, updated: "", vision: false, checks: ["official"] },
    ] })),
    hfFiles: vi.fn(async () => ({ ok: true, margin_gb: 1.2, files: [
      { quant: "UD-IQ3_S", file: "a.gguf", gb: 12.94, file_gb: 12.04, projector_gb: 0.9, bits: 3, fit: "fits", recommended: true,
        tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S", pc_measured: { ceiling: 65536, tokens_per_sec: 41.2 } },
    ] })),
  } as unknown as SetupApi;
  await render(api, () => undefined);
  const text = host!.textContent ?? "";
  expect(text).toContain("표시는 확인한 것만 적습니다");
  expect(text).toContain("✓ 이 PC 실측");
  expect(text).toContain("✓ 공식 원본");
  expect(text).toContain("✓ 공식");
  expect(text).toContain("✓ 기준 통과");
  expect(text).toContain("실제 대화로 돌려 본 것은 아닙니다");
  expect(text).not.toMatch(/(^|[^받])추천/);
  // 이 PC 에서 잰 모델이 펼쳐져 있다 — 양자화 칩에 「이 PC」·「여유 최대」, 크기는 부속 포함이라고 적는다.
  const chip = host!.querySelector(".quant-chip") as HTMLButtonElement;
  expect(chip.textContent).toContain("✓ 이 PC");
  expect(chip.textContent).toContain("여유 최대");
  expect(chip.title).toContain("화면 읽기 부속 0.90GB");
  expect(chip.title).toContain("64K");
  expect(host!.textContent).toContain("화면 읽기 부속");
});

// ★ 2026-10-07 사무실 PC 첫 설치(대표: 「UX 0점」): 「받고 확인하기」를 눌러도 그 줄에는 아무 변화가 없었다 — 진행 줄이 목록 밖에만 있었다.
const FILE = { quant: "UD-IQ3_S", file: "a.gguf", gb: 12.04, bits: 3, fit: "fits", tag: "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S" };

async function renderBusy(activeTag: string) {
  host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(
      <HfPicker api={fakeApi()} card={CARD} busy busyWhy="다른 모델을 받는 중입니다" onPick={() => undefined} onGet={() => undefined}
        picked={{ repo: "unsloth/Qwen3.8-27B-GGUF", file: FILE } as unknown as HfPick}
        activeTag={activeTag} status={<p>받는 중 42%</p>} />,
    );
  });
  await act(async () => {
    (host!.querySelector(".hf-row-head") as HTMLButtonElement).click();
  });
}

it("shows the download progress inside the row whose button was pressed", async () => {
  await renderBusy(FILE.tag);
  expect(host!.querySelector("[data-testid=hf-status]")?.textContent).toBe("받는 중 42%");
  expect(host!.querySelector("[data-testid=hf-busy-why]")).toBeNull();
});

it("says why the button is off when a different model is the one downloading", async () => {
  await renderBusy("qwen3.5:9b");
  expect(host!.querySelector("[data-testid=hf-status]")).toBeNull();
  expect(host!.querySelector("[data-testid=hf-busy-why]")?.textContent).toBe("다른 모델을 받는 중입니다");
});
