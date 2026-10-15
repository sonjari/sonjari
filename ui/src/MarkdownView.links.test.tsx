// @vitest-environment jsdom
/**
 * 답 속 링크 (2026-10-01 밤 베타 테스터: 「표의 링크를 눌러도 안 된다」) — 기본 브라우저로 열고, https:// 가 빠진 주소도 연다.
 */
import { expect, it } from "vitest";
import { externalUrl } from "./MarkdownView";

it("keeps full links and fixes bare domain links", () => {
  expect(externalUrl("https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1")).toBe("https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1");
  expect(externalUrl("www.saramin.co.kr/zf_user/jobs/view?rec_idx=1")).toBe("https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1");
  expect(externalUrl("jobkorea.co.kr/Recruit/GI_Read/1")).toBe("https://jobkorea.co.kr/Recruit/GI_Read/1");
});

it("refuses what is not a web address", () => {
  expect(externalUrl("file:///C:/Windows/system32/calc.exe")).toBe("");
  expect(externalUrl("javascript:alert(1)")).toBe("");
  expect(externalUrl("#section")).toBe("");
  expect(externalUrl(undefined)).toBe("");
});
