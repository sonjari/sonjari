/**
 * 수식이 **실제로 그려지는가** — 부품 판을 올려도 (2026-10-16).
 *
 * 공개 직후 Dependabot 이 katex 0.17 을 짚었다(0.18.2 아래 · 프로토타입 오염). 0.18.10 으로 올리면서 rehype-katex(0.16 을
 * 기대함)가 끌어오던 옛 katex 도 `overrides` 로 같은 판에 묶었다. 옆 시험(MarkdownView.test.ts)은 수식 기호 고르기만 보고
 * 그리기는 안 본다 — 판이 어긋나 그리기가 깨져도 시험은 초록이었을 것이다. 여기서는 화면에 내는 컴포넌트를 그대로 그려 본다.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownView } from "./MarkdownView";

describe("MarkdownView 수식 그리기", () => {
  it("인라인 · 블록 수식이 katex 로 그려지고 원문이 남지 않는다", () => {
    const html = renderToStaticMarkup(
      <MarkdownView>{"합은 $a^2+b^2=c^2$ 이다.\n\n$$\\frac{1}{2}\\sum_{i=1}^{n} x_i \\rightarrow \\infty$$\n"}</MarkdownView>,
    );
    expect(html.match(/class="katex"/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain("katex-error");
    const shown = html.replace(/<annotation[^>]*>[\s\S]*?<\/annotation>/g, "");
    expect(shown).not.toContain("\\frac");
    expect(shown).not.toContain("$");
  });

  it("모델이 낸 \\( \\) · \\[ \\] 꼴도 그려진다", () => {
    const html = renderToStaticMarkup(<MarkdownView>{"넓이는 \\(\\pi r^2\\) 이다.\n\n\\[x = \\frac{-b}{2a}\\]\n"}</MarkdownView>);
    expect(html.match(/class="katex"/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain("katex-error");
  });
});
