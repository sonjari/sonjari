// @vitest-environment jsdom
/**
 * 모델을 고르기 전에 **큰 AI 와 비교한 기준점**을 깔고, 끝에 「미터기 없음」을 못 박는다 (2026-10-02 대표).
 * 모델 카드의 「제작사 주장 · 참고용」은 우리가 잰 숫자와 섞지 않고 출처·확인 날짜를 붙인다.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { ModelCard, StepModelText } from "./SetupWizard";
import type { CatalogModel } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;

afterEach(() => {
  container?.remove();
  container = null;
});

function render(node: JSX.Element): string {
  container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(node));
  const text = container.textContent ?? "";
  act(() => root.unmount());
  return text;
}

const MODEL = {
  key: "ornith1.5-35b-a3b", name: "Ornith 1.5 35B-A3B", vendor: "Ornith", ollama_tag: "hf.co/x:IQ4_XS", download_gb: 19,
  vram_gb: { "262144": 22.6 }, chain: null, roles: ["chat"], vision: false, blurb: "MoE", installed: true, fits: true,
  largest_fitting_ctx: 262144, status: "verified", license: "MIT", evidence: [], caution: "", links: [], checked_at: "",
  sources: [], vram_measured: true, memory_device: "RTX 3090 24GB", minimum_vram_gb: 22,
  vendor_claim: "SWE-bench Verified 79 (제작사 표: 같은 시험의 Qwen 3.6 35B 73.4)",
  vendor_claim_links: [{ label: "Hugging Face", url: "https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B" }],
  vendor_claim_checked: "2026-10-02",
} as unknown as CatalogModel;

it("모델 단계는 고르기 전에 큰 AI 와의 차이를 말하고 미터기 없음으로 끝난다", () => {
  const text = render(<StepModelText rec={null} asked={false} said={0} onAsk={() => {}} />);
  expect(text).toContain("클로드·챗GPT·제미나이 같은 큰 AI 가 아닙니다");
  expect(text).toContain("큰 AI 보다 못한 점");
  expect(text).toContain("미터기가 없습니다");
  expect(text).not.toContain("무제한");
  expect(text.indexOf("큰 AI 가 아닙니다")).toBeLessThan(text.indexOf("이 PC 에 맞는 모델 추천받기"));
});

it("제작사 주장은 참고용 표시·출처·확인 날짜와 함께, 없으면 아예 안 그린다", () => {
  const props = { usable: 23, recommended: null, pulsing: false, onPulseEnd: () => {}, picked: null, onPick: () => {} } as const;
  const shown = render(<ModelCard model={MODEL} {...props} />);
  expect(shown).toContain("제작사 주장 · 참고용");
  expect(shown).toContain("Sonjari가 잰 숫자가 아닙니다");
  expect(shown).toContain("SWE-bench Verified 79");
  expect(shown).toContain("확인 2026-10-02");
  const none = render(<ModelCard model={{ ...MODEL, vendor_claim: "" } as CatalogModel} {...props} />);
  expect(none).not.toContain("제작사 주장");
});
