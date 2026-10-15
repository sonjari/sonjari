import { t } from "../i18n";
/**
 * 화면이 **쓰는 사람을 뭐라고 부를 것인가.**
 *
 * ★ 2026-09-11. 이 이름이 UI 소스 다섯 곳에 박혀 있었다. 그래서 다른 사람에게 줄
 *   판을 만들 때 본체 소스를 고쳐야 했고, 실제로 그렇게 고친 것이 사용자 화면에
 *   그대로 나왔다 — 「자비스 나는 누구게」에 상대 이름이 떴다.
 *
 *   이름은 **판마다 다른 값**이지 코드가 아니다. 서버 설정(`JARVIS_USER_LABEL`)에서
 *   받아 여기 한 곳에 둔다. 기본값도 여기 하나뿐이라, 다음에 또 박아 넣을 자리가 없다.
 */
export const DEFAULT_USER_LABEL = t("사용자");

let current = DEFAULT_USER_LABEL;

export function setUserLabel(value: string | undefined | null): void {
  const next = (value ?? "").trim();
  current = next || DEFAULT_USER_LABEL;
}

export function userLabel(): string {
  return current;
}

/** 아바타에 넣을 한 글자. 이름의 첫 글자다. */
export function userInitial(): string {
  return current.slice(0, 1) || DEFAULT_USER_LABEL.slice(0, 1);
}
