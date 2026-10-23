import { afterEach, expect, it } from "vitest";
import { setLangForTest } from "../i18n";
import { charsLabel, foldNarration } from "./foldNarration";

afterEach(() => setLangForTest("ko"));

it("접은 줄은 알림이 준 글자 수 그대로 · 정리 한 장을 남겼을 때만 그 말을 붙인다", () => {
  expect(foldNarration({ before_chars: 81_234, after_chars: 42_000, sheet_chars: 900 }))
    .toBe("대화가 길어져 앞 기록을 접었습니다 · 8.1만 자 → 4.2만 자 · 이어 갈 정리 한 장을 남겼습니다");
  expect(foldNarration({ before_chars: 9_000, after_chars: 4_500, sheet_chars: 0 }))
    .toBe("대화가 길어져 앞 기록을 접었습니다 · 9,000자 → 4,500자");
  expect(foldNarration({})).toBe("대화가 길어져 앞 기록을 접었습니다");
  expect(charsLabel(50_000)).toBe("5만 자");
});

it("영어 화면은 영어로", () => {
  setLangForTest("en");
  expect(foldNarration({ before_chars: 81_234, after_chars: 42_000, sheet_chars: 1 }))
    .toBe("The conversation got long, so earlier steps were folded · 81k chars → 42k chars · a summary to carry on was kept");
});
