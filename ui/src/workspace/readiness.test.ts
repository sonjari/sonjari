import { describe, expect, it } from "vitest";
import { modelCaution, readinessProblem } from "./readiness";

describe("부탁하기 전에 준비 상태를 말한다", () => {
  it("Ollama 에 닿지 않으면 엔진부터", () => {
    expect(readinessProblem({ ok: false, model: "gemma4:26b-a4b-it-qat", error: "connection refused" })?.kind).toBe("ollama_down");
  });

  it("켜는 중이면 고장이라고 말하지 않는다 (2026-09-20 노트북 — 켜지기까지 14초)", () => {
    const problem = readinessProblem({ ok: false, error: "connection refused", starting: true });
    expect(problem?.kind).toBe("ollama_starting");
    expect(problem?.title).not.toContain("닿지 않");
    expect(problem?.action).toBeUndefined(); // 누를 것이 없다 — 저절로 사라진다
  });

  it("켜기가 연달아 실패했으면 그때는 고장이라고 말한다", () => {
    expect(readinessProblem({ ok: false, starting: false, autostart_error: "serve_exited:1" })?.kind).toBe("ollama_down");
  });

  it("엔진은 있는데 설정된 모델을 안 받았으면 모델 고르기", () => {
    const problem = readinessProblem({ ok: true, model: "gemma4:26b-a4b-it-qat", model_available: false });
    expect(problem?.kind).toBe("model_missing");
    expect(problem?.detail).toContain("gemma4:26b-a4b-it-qat");
  });

  it("준비됐거나 값을 모르면 아무 말도 안 한다", () => {
    expect(readinessProblem({ ok: true, model: "qwen3.5:9b", model_available: true })).toBeNull();
    expect(readinessProblem(null)).toBeNull();
    // 옛 백엔드는 model_available 을 안 준다 — 모르면 막지 않는다.
    expect(readinessProblem({ ok: true, model: "qwen3.5:9b" })).toBeNull();
  });
});

describe("약한 모델에 권한을 줄 때는 화면이 먼저 말한다 (2026-09-20 사장님 지시)", () => {
  it("능력을 잰 적 없는 모델이면 경고 한 줄", () => {
    const line = modelCaution({
      model: "qwen3.5:4b",
      measured: false,
      chain: null,
      label: "능력을 잰 적 없음",
      detail: "온텔릭이 이 모델로 사슬 벤치를 돌린 적이 없습니다.",
    });
    expect(line).toContain("qwen3.5:4b");
    expect(line).toContain("잰 적이 없");
  });

  it("잰 모델이면 아무 말도 안 한다 — 매번 뜨는 경고는 아무도 안 읽는다", () => {
    expect(modelCaution({
      model: "qwen3.5:9b",
      measured: true,
      chain: { ok: 9, total: 10, ctx: 131072 },
      label: "사슬 벤치 9/10 실측",
      detail: "Qwen 3.5 9B — 조사해서 파일까지 만든 판 9/10",
    })).toBeNull();
    // 옛 백엔드는 이 칸을 안 준다 — 모르면 겁주지 않는다.
    expect(modelCaution(undefined)).toBeNull();
  });
});
