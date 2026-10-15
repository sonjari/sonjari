import { describe, expect, it } from "vitest";
import {
  followingStep,
  latestOfTab,
  stepBeside,
  tabCounts,
  tabOf,
  truncationNotes,
  failureLine,
  type Observation,
  type ObservationKind,
  type StepRow,
} from "./observation";

function row(step: number, kind: ObservationKind, extra: Partial<StepRow> = {}): StepRow {
  return {
    step, kind, tool: "t", ok: true, status: "completed", error: "",
    title: "t", at: 0, took_ms: 0, truncated: false, ...extra,
  };
}

describe("어느 칸에 속하는가", () => {
  it("종류를 칸으로 옮긴다", () => {
    expect(tabOf("page")).toBe("screen");
    expect(tabOf("code")).toBe("file");
    expect(tabOf("document")).toBe("file");
    expect(tabOf("files")).toBe("file");
    expect(tabOf("table")).toBe("data");
    expect(tabOf("draft")).toBe("made");
  });

  it("모르는 종류도 버리지 않는다 — 데이터로 떨어진다", () => {
    expect(tabOf("바깥것" as ObservationKind)).toBe("data");
  });

  it("칸마다 몇 걸음인지 센다", () => {
    const rows = [row(1, "files"), row(2, "code"), row(3, "page"), row(4, "page")];
    expect(tabCounts(rows)).toEqual({ screen: 2, file: 2, data: 0, made: 0 });
  });

  it("칸을 누르면 그 칸의 마지막 걸음으로 간다", () => {
    const rows = [row(1, "page"), row(2, "code"), row(3, "page")];
    expect(latestOfTab(rows, "screen")).toBe(3);
    expect(latestOfTab(rows, "file")).toBe(2);
    expect(latestOfTab(rows, "made")).toBeNull();
  });
});

describe("어느 걸음을 보고 있나", () => {
  it("아무도 안 골랐으면 마지막 걸음을 따라간다", () => {
    expect(followingStep([row(1, "page"), row(2, "code")], null)).toBe(2);
  });

  it("★ 사람이 고른 걸음이 있으면 따라가지 않는다", () => {
    // 읽던 화면이 발밑에서 바뀌는 것이 제일 나쁘다.
    const rows = [row(1, "page"), row(2, "code"), row(3, "page")];
    expect(followingStep(rows, 1)).toBe(1);
  });

  it("고른 걸음이 사라졌으면(오래돼 버려짐) 다시 따라간다", () => {
    expect(followingStep([row(4, "page")], 1)).toBe(4);
  });

  it("걸음이 하나도 없으면 고를 것이 없다", () => {
    expect(followingStep([], 2)).toBeNull();
  });

  it("← → 는 이웃으로만 간다 — 끝에서 감기지 않는다", () => {
    const rows = [row(1, "page"), row(2, "code"), row(5, "table")];
    expect(stepBeside(rows, 2, 1)).toBe(5);
    expect(stepBeside(rows, 2, -1)).toBe(1);
    expect(stepBeside(rows, 1, -1)).toBe(1);
    expect(stepBeside(rows, 5, 1)).toBe(5);
  });

  it("고른 것이 없으면 마지막 걸음을 보고 있는 것으로 친다", () => {
    // 따라가는 중(pinned 없음)이면 지금 보이는 것은 마지막 걸음이다.
    // 그러니 ← 는 그 바로 앞으로 가고, → 는 갈 데가 없어 제자리다.
    const rows = [row(1, "page"), row(2, "code")];
    expect(stepBeside(rows, null, -1)).toBe(1);
    expect(stepBeside(rows, null, 1)).toBe(2);
  });
});

function observation(truncation: Observation["truncation"]): Observation {
  return {
    ...row(1, "page"), job_id: "j", arguments: {}, payload: {}, truncation,
  };
}

describe("무엇이 잘렸는지 말한다", () => {
  it("아무것도 안 잘렸으면 아무 말도 안 한다", () => {
    expect(truncationNotes(observation({}), 100)).toEqual([]);
  });

  it("보관소가 끊었으면 원문 길이와 보관 길이를 같이 적는다", () => {
    const notes = truncationNotes(observation({ store: true, char_count: 200000 }), 120000);
    expect(notes[0]).toContain("200,000자");
    expect(notes[0]).toContain("120,000자");
  });

  it("도구가 끊었으면 다시 읽어야 한다고 말한다", () => {
    const notes = truncationNotes(observation({ tool: true, char_count: 80000 }), 80000);
    expect(notes[0]).toContain("80,000자");
    expect(notes[0]).toContain("다시 읽어야");
  });

  it("★ 모델이 본 양이 본문보다 짧으면 그 사실을 따로 적는다", () => {
    // 사고 Q: 본문의 23%가 조용히 사라졌다. 침묵으로 오는 고장이라 반드시 적는다.
    const notes = truncationNotes(
      observation({ store: true, char_count: 200000, to_model: 30000, model_cut: true }),
      120000,
    );
    expect(notes).toHaveLength(2);
    expect(notes[1]).toContain("30,000자만");
  });
});

describe("실패한 걸음", () => {
  it("성공한 걸음에는 아무 말도 안 붙인다", () => {
    expect(failureLine(row(1, "page"))).toBe("");
  });

  it("이유가 있으면 이유를 적는다", () => {
    expect(failureLine(row(1, "page", { ok: false, error: "timeout" }))).toContain("timeout");
  });

  it("이유가 없으면 없다고 말한다 — 빈칸으로 두지 않는다", () => {
    expect(failureLine(row(1, "page", { ok: false }))).toContain("이유를 남기지 않았습니다");
  });
});
