/**
 * 모델 이름 한 꼴(11-04 대표: 「Qwen3.5 / Qwen 3.5 표기 통일」) — 칩 · 목록 · 집 PC 목록이 같은 이름을 쓴다.
 */
import { expect, it } from "vitest";
import { ctxShort, friendlyModelName, modelSource } from "./modelNames";

it("ollama 태그는 낱말과 판 번호를 띄우고 크기를 붙인다", () => {
  expect(friendlyModelName("qwen3.5:9b")).toBe("Qwen 3.5 9B");
  expect(friendlyModelName("qwen3.6:35b-a3b")).toBe("Qwen 3.6 35B");
  expect(friendlyModelName("mistral-small3.2:24b")).toBe("Mistral Small 3.2 24B");
  expect(friendlyModelName("granite4.1:8b")).toBe("Granite 4.1 8B");
  expect(friendlyModelName("gemma4")).toBe("Gemma 4");
});

it("hf.co 태그는 저장소 첫 낱말과 크기만", () => {
  expect(friendlyModelName("hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf")).toBe("Swift 27B");
  expect(friendlyModelName("hf.co/ornith-ai/Ornith-1.5-9B-GGUF:Q4_K_M")).toBe("Ornith 9B");
});

it("빈 값은 빈 이름 · 창 크기는 K 로", () => {
  expect(friendlyModelName("")).toBe("");
  expect(ctxShort(131072)).toBe("128K");
  expect(ctxShort(0)).toBe("");
});

it("우리 「글만 읽기」 별칭과 이름 속 크기 · 양자화 꼬리를 다듬는다 (11-04)", () => {
  expect(friendlyModelName("sonjari-text-qwen3.8-27b-swift-iq3xxs:latest")).toBe("Qwen 3.8 Swift 27B · 글만");
  expect(friendlyModelName("qwen3.8-27b-swift-gsq-mtp:iq3s")).toBe("Qwen 3.8 Swift 27B");
  expect(friendlyModelName("qwen3.8:27b-mtp-q4_K_M")).toBe("Qwen 3.8 27B");
});

it("같은 이름을 가르는 꼬리 — hf.co 는 올린 사람 · 파일 꼬리, Ollama 태그는 그대로", () => {
  expect(modelSource("hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf")).toBe("ukisai · IQ3_S-mtp");
  expect(modelSource("hf.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:IQ3_S")).toBe("ISTA-DASLab · IQ3_S");
  expect(modelSource("qwen3.8:27b-mtp-q4_K_M")).toBe("qwen3.8:27b-mtp-q4_K_M");
});
