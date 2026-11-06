/**
 * 화면이 도는 OS (2026-11-03 맥판). 맥 WebKit 의 userAgent 에는 `Macintosh` 가 들어 있다.
 * 사람에게 보이는 안내(작업 표시줄 · 시작 메뉴 ↔ 메뉴 막대 · 응용 프로그램 폴더)를 OS 에 맞춰 고를 때만 쓴다.
 */
export const isMac: boolean =
  typeof navigator !== "undefined" && /Mac/i.test(`${navigator.userAgent || ""} ${navigator.platform || ""}`);
