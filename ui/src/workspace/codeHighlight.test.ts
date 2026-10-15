import { describe, expect, it } from "vitest";
import { tokenize, tokenizeLine } from "./codeHighlight";

/** 이 검사가 이 파일의 존재 이유다 — 색칠이 원문을 바꾸면 그건 위조다. */
function rejoin(text: string, language: string): string {
  return tokenize(text, language)
    .map((line) => line.map((token) => token.text).join(""))
    .join("\n");
}

describe("★ 토막을 이어 붙이면 원문이다", () => {
  const samples: Array<[string, string]> = [
    ["typescript", `const a = "hello"; // 주석\nfunction go(x) { return x + 1; }`],
    ["python", `def go(x):\n    return f"{x}"  # 주석\n`],
    ["json", `{"a": 1, "b": [true, null]}`],
    ["sql", "select * from t where a = 'x' -- 주석"],
    ["css", ".a { color: rgb(var(--text-1)); }"],
    ["tsx", `<div className="a">{x}</div>`],
    ["typescript", "const 한글 = '값'; // 한글 주석"],
    ["typescript", "const broken = 'not closed"],
    ["typescript", ""],
  ];
  for (const [language, text] of samples) {
    it(`${language}: ${text.slice(0, 28).replace(/\n/g, "⏎")}`, () => {
      expect(rejoin(text, language)).toBe(text);
    });
  }
});

describe("무엇을 무엇으로 보나", () => {
  it("문자열을 통째로 잡는다 — 안에 있는 낱말은 예약어가 아니다", () => {
    const tokens = tokenizeLine(`const a = "return if";`, "typescript");
    expect(tokens.find((t) => t.kind === "string")?.text).toBe(`"return if"`);
    expect(tokens.filter((t) => t.kind === "keyword").map((t) => t.text)).toEqual(["const"]);
  });

  it("주석은 줄 끝까지다", () => {
    const tokens = tokenizeLine(`go(); // const 는 여기서 예약어가 아니다`, "typescript");
    const comment = tokens.find((t) => t.kind === "comment");
    expect(comment?.text).toBe("// const 는 여기서 예약어가 아니다");
  });

  it("파이썬 주석은 # 다 — 언어마다 다르다", () => {
    expect(tokenizeLine("x = 1  # 주석", "python").some((t) => t.kind === "comment")).toBe(true);
    expect(tokenizeLine("x = 1  # 주석", "typescript").some((t) => t.kind === "comment")).toBe(false);
  });

  it("부르는 이름은 따로 표시한다", () => {
    const tokens = tokenizeLine("shape(tool, args)", "python");
    expect(tokens.find((t) => t.kind === "def")?.text).toBe("shape");
  });

  it("숫자는 숫자로, 이름 속 숫자는 아니다", () => {
    expect(tokenizeLine("x = 42", "python").some((t) => t.kind === "number" && t.text === "42")).toBe(true);
    expect(tokenizeLine("var2 = 1", "python").some((t) => t.kind === "number" && t.text === "2")).toBe(false);
  });

  it("이스케이프된 따옴표에서 문자열이 안 끊긴다", () => {
    const tokens = tokenizeLine(`const a = "그는 \\"네\\" 라고 했다";`, "typescript");
    expect(tokens.find((t) => t.kind === "string")?.text).toBe(`"그는 \\"네\\" 라고 했다"`);
  });

  it("모르는 언어면 색만 덜 칠한다 — 글자는 그대로다", () => {
    const text = "이건 아무 언어도 아니다 { } 42";
    expect(rejoin(text, "무슨언어")).toBe(text);
  });
});
