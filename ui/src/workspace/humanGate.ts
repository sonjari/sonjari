import { t } from "../i18n";
/** 사람만 열 수 있는 문 — 백엔드 `human_gate.HUMAN_GATE_CODES` 와 같은 이름(한쪽만 고치면 조용히 안 걸린다). */
export const HUMAN_GATE_CODES = new Set(["bot_check", "login_required", "payment_required"]);

export const GATE_TITLES: Record<string, string> = {
  login_required: t("로그인이 필요해요"),
  bot_check: t("사람인지 확인하는 화면이에요"),
  payment_required: t("결제 정보를 넣는 화면이에요"),
};

/** 문 앞에서 사람이 해 주실 일 — 카드의 「이것만 해 주세요」 줄. */
export const GATE_ASKS: Record<string, string> = {
  login_required: t("크롬 창에서 로그인해 주세요."),
  bot_check: t("크롬 창에서 확인(보안 문자·퍼즐)을 끝내 주세요."),
  payment_required: t("결제 정보는 크롬 창에서 직접 넣어 주세요."),
};

/** 카드에 보일 「그 화면」 — 사이트 이름과 짧은 경로만(2026-10-02 실사용).
 *  Genspark 로그인 카드에 여러 줄짜리 OAuth 주소(client_id·redirect_uri·state …)가 통째로 떠서 읽을 수가 없었다.
 *  사람에게 필요한 건 「어느 사이트의 무슨 화면」뿐이다. 쿼리·조각은 버리고 경로는 짧을 때만 붙인다. */
export function gateSiteLabel(url: string | undefined): string {
  const text = String(url ?? "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    const host = parsed.hostname.replace(/^www\./, "");
    const path = parsed.pathname.replace(/\/+$/, "");
    return path && path.length <= 40 ? `${host}${path}` : host;
  } catch {
    return text.length > 60 ? `${text.slice(0, 57)}…` : text;
  }
}

/** 체크포인트 이유 `human_gate:<code>` 에서 문 종류를 꺼낸다. 사람 문이 아니면 빈 문자열. */
export function gateCodeOf(reason: string | undefined): string {
  const text = String(reason ?? "");
  return text.startsWith("human_gate:") ? text.slice("human_gate:".length) : "";
}
