import { describe, expect, it } from "vitest";
import { applyLive, liveText } from "./WorkspaceApp";

describe("purple dot live line (10-25)", () => {
  it("keeps the start time while the phase stays the same and counts seconds from it", () => {
    let rows = applyLive({}, "j", "writing", 0, 120, 1_000);
    rows = applyLive(rows, "j", "writing", 0, 840, 24_000);
    expect(rows.j.since).toBe(1_000);
    expect(liveText(rows.j, 24_500)).toBe("모델이 글을 쓰는 중 · 840자 · 23초째");
  });

  it("restarts the clock on a new phase and clears on an empty one", () => {
    let rows = applyLive({}, "j", "thinking", 300, 0, 0);
    rows = applyLive(rows, "j", "checking", 300, 1_573, 9_000);
    expect(liveText(rows.j, 12_000)).toBe("답을 다 썼습니다(1,573자) · 검사하고 내보내는 중 · 3초째");
    expect(applyLive(rows, "j", "", 0, 0).j).toBeUndefined();
    expect(liveText(undefined)).toBe("");
  });
});
