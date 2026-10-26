import { describe, expect, it } from "vitest";
import { setSlideFontBase, withSlideFonts } from "./slideFonts";

describe("장표 미리보기 칸의 앱 글꼴 주소", () => {
  const html = "<style>@font-face{src:url('https://fonts.sonjari.invalid/pretendard/Pretendard-Regular.woff2')}</style><section>가</section>";

  it("본체 주소를 모르면 그대로 둔다", () => {
    setSlideFontBase("");
    expect(withSlideFonts(html)).toBe(html);
  });

  it("본체의 글꼴 길로 바꾼다 — 다른 글은 건드리지 않는다", () => {
    setSlideFontBase("http://127.0.0.1:8091/");
    const out = withSlideFonts(html);
    expect(out).toContain("url('http://127.0.0.1:8091/v1/slides/fonts/pretendard/Pretendard-Regular.woff2')");
    expect(out).not.toContain("fonts.sonjari.invalid");
    expect(out).toContain("<section>가</section>");
    expect(withSlideFonts("<section>없음</section>")).toBe("<section>없음</section>");
  });
});
