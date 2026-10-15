// 화면 언어 (2026-10-02 영어판 1단계).
//
// 한국어 문장 자체가 열쇠다 — `t("저장")` 은 한국어 화면에서 그대로 「저장」, 영어 화면에서 사전의 "Save".
// 사전에 없는 문장은 한국어 그대로 나온다: 빠진 번역이 화면을 깨뜨리지 않고, 한국어 화면은 이 모듈이 없던 때와 같다.
// `{0}`·`{1}` 자리는 뒤 인자로 채운다 — `t("{0}개 남음", n)`.
import en from "./i18n/en.json";

export type Lang = "ko" | "en";

const STORAGE_KEY = "sonjari.ui_language";
const EN = en as Record<string, string>;

function detect(): Lang {
  // 시험은 한국어로 고정한다 — 가짜 브라우저(jsdom)의 언어가 en-US 라, 따라가면 한국어를 확인하는 시험이 전부 깨진다.
  if (import.meta.env?.MODE === "test") return "ko";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "ko" || saved === "en") return saved;
  } catch {
    // 저장소를 못 쓰면 윈도우 언어를 따른다.
  }
  const nav = typeof navigator !== "undefined" ? navigator.language || "" : "";
  return nav.toLowerCase().startsWith("ko") ? "ko" : "en";
}

let current: Lang = detect();

export function lang(): Lang {
  return current;
}

/** 날짜·숫자 형식 — 화면 언어를 따른다. */
export function locale(): string {
  return current === "en" ? "en-US" : "ko-KR";
}

/** 언어를 바꾸고 화면을 다시 띄운다 — 모듈이 읽힐 때 만든 문구까지 새 언어로 맞추려면 다시 읽는 게 가장 확실하다. */
export function setLang(next: Lang, reload = true): void {
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // 저장 못 해도 이번 화면은 바뀐다.
  }
  if (!reload || typeof window === "undefined") return;
  // 백엔드에도 먼저 알리고 다시 띄운다 — 백엔드가 만드는 글(카드·안내)도 같은 언어로 나오게. 못 알려도 다시 띄운다.
  void import("./backend")
    .then(async (backend) => backend.pushUiLanguage(await backend.loadBootstrap(), next))
    .catch(() => undefined)
    .finally(() => window.location.reload());
}

/** 시험 전용 — 다시 읽지 않고 언어만 바꾼다. */
export function setLangForTest(next: Lang): void {
  current = next;
}

// 인자는 템플릿 문자열 `${}` 자리에서 왔다 — 거기는 무엇이든 String() 으로 찍혔으니 같은 규칙을 따른다.
export function t(ko: string, ...args: unknown[]): string {
  let text = current === "en" ? EN[ko] ?? ko : ko;
  args.forEach((value, index) => {
    text = text.split(`{${index}}`).join(String(value));
  });
  return text;
}
