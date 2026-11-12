import { describe, expect, it } from "vitest";
import { statusKind } from "../setup/ModelPlace";

describe("노란 카드 대신 자리 그림이 상태를 말한다 (11-08 대표 「이모티콘 말고 그림으로」)", () => {
  it("문제가 없으면 자리 그대로", () => {
    expect(statusKind("here", null)).toBe("here");
    expect(statusKind("satellite", undefined)).toBe("satellite");
  });
  it("이 기기 쪽 문제는 점이, 집 PC 쪽 문제는 선이 말한다", () => {
    expect(statusKind("here", "ollama_starting")).toBe("here-wait");
    expect(statusKind("here", "ollama_down")).toBe("here-off");
    expect(statusKind("here", "model_missing")).toBe("here-off");
    expect(statusKind("satellite", "home_unreachable")).toBe("down");
    expect(statusKind("satellite", "home_model_missing")).toBe("far-missing");
  });
});
