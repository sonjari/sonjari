/**
 * 한국어 문장에서 **굵게** 가 별표로 찍히지 않는가 (2026-09-16 밤, 1320×840 화면 확인 중 발견).
 * 렌더 결과(HTML)로 본다 — 전처리 함수만 보면 「고쳤는데 화면은 그대로」를 못 잡는다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownView } from "./MarkdownView";

const html = (text: string) => renderToStaticMarkup(<MarkdownView>{text}</MarkdownView>);

describe("Korean emphasis", () => {
  it.each([
    ['**"내 PC에서 대신 움직여주는 AI"**로 정의해야 합니다.', '"내 PC에서 대신 움직여주는 AI"'],
    ["**'사용자의 통제권'**입니다.", "'사용자의 통제권'"],
    ["단순 AI Chat 이 아닌, ** Automation(자동화) **과 에이전트", "Automation(자동화)"],
  ])("renders %s as bold without stray asterisks", (source, bold) => {
    const out = html(source);
    expect(out).toContain(`<strong>${bold.replace(/"/g, "&quot;").replace(/'/g, "&#x27;")}</strong>`);
    expect(out).not.toContain("**");
  });

  it("keeps ordinary bold and leaves code alone", () => {
    expect(html("이건 **중요** 합니다")).toContain("<strong>중요</strong>");
    const code = html("명령 `a**b**c` 는 그대로");
    expect(code).toContain("a**b**c");
  });
});
