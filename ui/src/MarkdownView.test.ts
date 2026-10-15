/**
 * 수식이 **원문 그대로 찍히지 않는가.**
 *
 * 2026-08-21 실측: 자비스 답에 `$\rightarrow$` 가 그대로 보였다. 화면에는
 * "$\rightarrow$ AI가 분석한 오답 패턴 그래프" 라고 찍혔다 — 화살표가 아니라.
 *
 * 원인은 인코딩이 아니라 **렌더러였다.** 튜터랩(web/alture-console)은 KaTeX
 * (remark-math + rehype-katex)를 쓰는데 자비스 UI 에는 그 배선이 없었다.
 * `remark-gfm` 만 물려 있어서 `$...$` 는 그냥 글자였다.
 *
 * ★ 두 벌을 두면 갈린다 — 델리미터 정규화는 콘솔의
 *   `src/utils/normalizeLatexDelimiters.ts` 와 **같은 처리**여야 한다.
 */
import { describe, expect, it } from "vitest";
import { normalizeJarvisMarkdown, normalizeLatexDelimiters } from "./MarkdownView";

describe("normalizeLatexDelimiters", () => {
  it("백엔드가 쓰는 \\(...\\) 를 remark-math 가 아는 $...$ 로 바꾼다", () => {
    expect(normalizeLatexDelimiters(String.raw`값은 \(x^2\) 이다`)).toBe("값은 $x^2$ 이다");
  });

  it("블록 수식 \\[...\\] 는 $$...$$ 가 된다", () => {
    expect(normalizeLatexDelimiters(String.raw`\[a+b\]`)).toBe("$$a+b$$");
  });

  it("수식 내용 자체는 안 건드린다 — 델리미터만 바꾼다", () => {
    expect(normalizeLatexDelimiters(String.raw`\(\frac{1}{4}\)`)).toBe(String.raw`$\frac{1}{4}$`);
  });

  it("수식이 없으면 그대로 둔다", () => {
    expect(normalizeLatexDelimiters("그냥 한국어 문장")).toBe("그냥 한국어 문장");
  });

  it("빈 값도 죽지 않는다", () => {
    expect(normalizeLatexDelimiters("")).toBe("");
  });
});

describe("normalizeJarvisMarkdown", () => {
  it("★ 스크린샷의 그 문자열이 살아서 KaTeX 까지 간다", () => {
    // `$...$` 는 이미 remark-math 가 아는 모양이라 정규화가 건드리지 않는다.
    // 여기서 확인하는 것은 **표 보정이 수식을 망가뜨리지 않는가** 이다.
    const out = normalizeJarvisMarkdown(String.raw`$\rightarrow$ AI가 분석한 오답 패턴 그래프`);
    expect(out).toContain(String.raw`$\rightarrow$`);
  });

  it("표 보정과 수식 변환이 같이 걸려도 서로 안 망가진다", () => {
    const out = normalizeJarvisMarkdown(String.raw`| a | b |\n| --- | --- |\n행 \(x\) 끝`);
    expect(out).toContain("$x$");
  });

  it("줄바꿈 정규화는 그대로 남는다", () => {
    expect(normalizeJarvisMarkdown("a\r\nb")).toBe("a\nb");
  });
});
