import { describe, expect, it } from "vitest";
import { markedLines, readingTerms, takeaway, type Observation } from "./observation";

/**
 * step 이 「무엇을 보고 있나」를 말하는 규칙.
 *
 * 여기서 지키려는 것은 하나다 — **모르는 것을 아는 척하지 않는다.**
 * 셀 것이 없으면 빈 글자, 찾던 말이 없으면 빈 집합. 그 자리에 그럴듯한 문장을
 * 채워 넣으면 사람이 그걸 근거로 읽는다.
 */

function obs(over: Partial<Observation>): Observation {
  return {
    step: 1, tool: "t", ok: true, status: "", error: "", kind: "note",
    title: "", at: 0, took_ms: 0, truncated: false,
    job_id: "j", arguments: {}, payload: {}, truncation: {},
    ...over,
  } as Observation;
}

describe("takeaway — 센 것만 말한다", () => {
  it("웹 화면은 요소를 세고 제목을 붙인다", () => {
    const line = takeaway(obs({
      kind: "page",
      payload: {
        title: "무선마우스 - 다나와",
        text: "가".repeat(1200),
        elements: {
          columns: ["ref", "role", "name"],
          rows: [["1", "link", "a"], ["2", "link", "b"], ["3", "button", "c"]],
        },
      },
    }));
    expect(line).toContain("링크 2");
    expect(line).toContain("버튼 1");
    expect(line).toContain("본문 1,200자");
    expect(line).toContain("무선마우스");
  });

  it("★ 셀 것이 없으면 빈 글자 — 억지 문장을 만들지 않는다", () => {
    expect(takeaway(obs({ kind: "page", payload: { title: "빈 곳" } }))).toBe("");
    expect(takeaway(obs({ kind: "code", payload: {} }))).toBe("");
    expect(takeaway(obs({ kind: "document", payload: { text: "" } }))).toBe("");
    expect(takeaway(obs({ kind: "table", payload: { rows: [] } }))).toBe("");
    expect(takeaway(null)).toBe("");
  });

  it("코드는 줄 수와 정의 수를 센다", () => {
    const text = "def one():\n    pass\n\nclass Two:\n    pass\n";
    const line = takeaway(obs({ kind: "code", payload: { text, language: "python", line_count: 6 } }));
    expect(line).toContain("6줄");
    expect(line).toContain("python");
    expect(line).toContain("정의 2개쯤");
  });

  it("정의를 못 찾으면 정의 수를 아예 말하지 않는다", () => {
    const line = takeaway(obs({ kind: "code", payload: { text: "a = 1\nb = 2\n", language: "python" } }));
    expect(line).toContain("줄");
    expect(line).not.toContain("정의");
  });

  it("표는 행과 열을 센다", () => {
    const line = takeaway(obs({
      kind: "table",
      payload: { columns: ["대학", "학과"], rows: [["중앙대", "소프트"]], row_count: 1 },
    }));
    expect(line).toContain("1개");
    expect(line).toContain("열 2");
  });
});

describe("readingTerms — 찾던 말", () => {
  it("검색어 계열 인자만 뽑는다", () => {
    expect(readingTerms(obs({ arguments: { query: "무선마우스", path: "C:/a.txt" } }))).toEqual(["무선마우스"]);
  });

  it("★ 한 글자는 버린다 — 아무 줄에나 걸려 표시가 뜻을 잃는다", () => {
    expect(readingTerms(obs({ arguments: { query: "가" } }))).toEqual([]);
  });

  it("인자가 없으면 빈 배열", () => {
    expect(readingTerms(obs({}))).toEqual([]);
  });
});

describe("markedLines — 이건 주장이다", () => {
  const text = "첫 줄\n무선마우스 가격\n셋째 줄\n무선마우스 재고\n";

  it("찾던 말이 실제로 있는 줄만 짚는다", () => {
    expect([...markedLines(text, ["무선마우스"])]).toEqual([1, 3]);
  });

  it("대소문자를 가리지 않는다", () => {
    expect([...markedLines("Hello World\nbye", ["hello"])]).toEqual([0]);
  });

  it("★ 찾던 말이 없으면 한 줄도 안 칠한다", () => {
    expect(markedLines(text, []).size).toBe(0);
    expect(markedLines(text, ["없는말"]).size).toBe(0);
    expect(markedLines("", ["무선마우스"]).size).toBe(0);
  });

  it("너무 많이 걸리면 상한에서 멈춘다", () => {
    const many = Array.from({ length: 200 }, () => "같은 말").join("\n");
    expect(markedLines(many, ["같은 말"]).size).toBe(40);
  });
});
