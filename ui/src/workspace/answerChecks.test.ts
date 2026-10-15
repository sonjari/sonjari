import { describe, expect, it } from "vitest";
import { splitAnswerChecks } from "./answerChecks";

// 표본의 이름 · 값은 지어낸 것이다. 문단의 모양만 서버가 보내는 것과 같다.
const ANSWER = [
  "가상 모델 A 가 답입니다.",
  "| 선택지 | 판단 |\n|---|---|\n| 가상 A | 가장 정합 |",
  "한 가지 주의: 숫자만 보고 단정할 수 없습니다.",
].join("\n\n");
const RATE = "⚠ **읽은 자료에 없는 비율이 있습니다: 17%** — 원문으로 확인하기 전에는 사실로 쓰지 마세요.";
const NAMES = "⚠ **읽지 않고 적은 것이 있습니다: 가상 A, 가상 B.** 이 이름들은 이번에 읽은 자료(페이지·파일) 어디에도 없습니다 — 목록 줄에서 옮겨 적었을 수 있습니다.";

describe("답 끝의 「확인할 것」을 본문에서 뗀다", () => {
  it("끝에 붙은 문단들을 떼고 본문은 그대로 남긴다", () => {
    const { body, checks } = splitAnswerChecks(`${ANSWER}\n\n${RATE}\n\n${NAMES}`);
    expect(body).toBe(ANSWER);
    expect(checks).toHaveLength(2);
    expect(checks[0]).toMatchObject({ title: "읽은 자료에 없는 비율이 있습니다", what: "17%" });
    expect(checks[1]).toMatchObject({ title: "읽지 않고 적은 것이 있습니다", what: "가상 A, 가상 B" });
    expect(checks[1].detail).toContain("목록 줄에서 옮겨 적었을 수 있습니다");
    expect(checks[0].detail).not.toContain("**");
  });

  it("확인할 것이 없는 답은 한 글자도 안 바뀐다", () => {
    expect(splitAnswerChecks(ANSWER)).toEqual({ body: ANSWER, checks: [] });
    expect(splitAnswerChecks("")).toEqual({ body: "", checks: [] });
  });

  it("답 한가운데의 ⚠ 는 모델이 쓴 글이다 — 건드리지 않는다", () => {
    const middle = `조심할 것이 있습니다.\n\n⚠ 전원을 먼저 끄세요.\n\n그다음 덮개를 엽니다.`;
    expect(splitAnswerChecks(middle)).toEqual({ body: middle, checks: [] });
    const both = `${middle}\n\n${RATE}`;
    expect(splitAnswerChecks(both).body).toBe(middle);
    expect(splitAnswerChecks(both).checks).toHaveLength(1);
  });

  it("⚠ 문단만 있는 글은 답으로 둔다 — 본문을 비우지 않는다", () => {
    expect(splitAnswerChecks(RATE)).toEqual({ body: RATE, checks: [] });
  });

  it("영어로 온 문단도 같은 모양이면 뗀다", () => {
    const english = "⚠ **Some percentages are not in what was read: 17%** — do not state them as fact before checking the source.";
    const { body, checks } = splitAnswerChecks(`Model A is the answer.\n\n${english}`);
    expect(body).toBe("Model A is the answer.");
    expect(checks[0]).toMatchObject({ title: "Some percentages are not in what was read", what: "17%" });
  });

  it("쌍점이 없는 문단은 첫 문장이 한 줄 요약이다", () => {
    const { checks } = splitAnswerChecks(`답입니다.\n\n⚠ **확인하지 못한 값이 있습니다.** 다시 열어 확인해 주세요.`);
    expect(checks[0]).toMatchObject({ title: "확인하지 못한 값이 있습니다", what: "" });
  });
});
