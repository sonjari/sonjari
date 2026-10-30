import { describe, expect, it } from "vitest";

import { chooseStage, stageChoiceFor } from "./stageChoice";

// 10-29 촬영: 일하는 도중 「크게 보기」를 눌러도 따라가는 판 번호가 비었다 같은 판으로 돌아올 때마다 지워졌다.
describe("크게/작게는 그 판에 대한 뜻이다", () => {
  it("따라가는 판이 잠깐 비었다 같은 판으로 돌아와도 뜻이 남는다", () => {
    const choice = chooseStage("job-a", true);
    expect(stageChoiceFor(choice, "job-a")).toBe(true);
    expect(stageChoiceFor(choice, "")).toBeNull(); // 비어 있는 동안은 자동
    expect(stageChoiceFor(choice, "job-a")).toBe(true); // 돌아오면 다시 그 뜻
  });

  it("다른 판에는 먹지 않는다 — 그 판은 자동이다", () => {
    expect(stageChoiceFor(chooseStage("job-a", false), "job-b")).toBeNull();
  });

  it("자동으로 되돌리면 뜻이 없다", () => {
    expect(chooseStage("job-a", null)).toBeNull();
    expect(stageChoiceFor(null, "job-a")).toBeNull();
  });
});
