/**
 * 장표 미리보기 칸의 앱 글꼴 (2026-10-26).
 *
 * 장 HTML 은 앱 글꼴(프리텐다드 등)을 아무 데도 없는 주소(`https://fonts.sonjari.invalid/…`)로 적는다 — 장을 굽는 브라우저만
 * 그 요청을 앱 폴더의 파일로 돌려준다(`slides._serve_fonts`). 미리보기 칸은 그 주소를 몰라 윈도우 글꼴로 그렸고, 글자 폭은
 * 새 글꼴로 맞춘 것이라 670장 중 28장이 넘쳐 보였다. 그래서 칸에 넣기 전에 그 주소를 본체의 글꼴 길(`/v1/slides/fonts/…`)로 바꾼다.
 */
const PLACEHOLDER = "https://fonts.sonjari.invalid/";
let fontBase = "";

/** 본체 주소를 알게 되면 한 번 부른다(`WorkspaceApp` 시작). */
export function setSlideFontBase(apiBase: string): void {
  fontBase = apiBase ? `${apiBase.replace(/\/+$/, "")}/v1/slides/fonts/` : "";
}

/** 칸에 넣을 장 HTML — 글꼴 주소만 본체로 바꾼다. 본체 주소를 모르면 그대로(윈도우 글꼴로 그린다). */
export function withSlideFonts(html: string): string {
  return fontBase && html && html.includes(PLACEHOLDER) ? html.split(PLACEHOLDER).join(fontBase) : html;
}
