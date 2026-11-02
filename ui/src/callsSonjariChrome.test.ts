import { describe, expect, it } from "vitest";
import { callsSonjariChrome } from "./backend";

// 앞창 바꾸기 허락은 사람이 손자리 크롬을 직접 부르는 말에만(2026-10-30) — 아무 말에나 주면 남이 앞을 가로챌 수 있다.
describe("callsSonjariChrome", () => {
  it("is true for the recipe command and the show-again button", () => {
    for (const text of ["/레시피", "/레시피 위키 검색", " /recipe ", "/recipe wiki", "다시 보여 줄게", "Show again"]) {
      expect(callsSonjariChrome(text)).toBe(true);
    }
  });
  it("is false for other words", () => {
    for (const text of ["레시피 알려 줘", "/레시피들", "다시 보여 줄게요 그리고", "안녕", "/recipes"]) {
      expect(callsSonjariChrome(text)).toBe(false);
    }
  });
});
