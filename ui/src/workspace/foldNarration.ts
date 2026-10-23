/**
 * 대화를 접었다는 한 줄 (2026-10-22 대표 — 「접을 때 화면에 띄워 주면 좋겠다」).
 *
 * 백엔드는 계단식 접기를 할 때마다 `agent_transcript_step_folded` 를 내보내고 있었는데(`agent.py` · 접기 전 정리 한 장),
 * 화면이 그 알림을 받지 않아 사람은 몰랐다. 접은 뒤에는 모델이 옛 걸음의 원문 대신 줄인 글을 보므로, 그 순간을 말 줄에 남긴다.
 * 숫자는 알림이 준 글자 수 그대로 — 토큰으로 바꾸거나 부풀리지 않는다.
 */
import { lang, t } from "../i18n";

export interface FoldPayload {
  before_chars?: number;
  after_chars?: number;
  sheet_chars?: number;
}

/** 글자 수를 짧게 — 한국어는 「4.2만 자」, 영어는 「42k chars」. */
export function charsLabel(chars: number): string {
  const n = Math.max(0, Math.round(chars));
  if (lang() === "en") return n >= 1000 ? `${Math.round(n / 1000)}k chars` : `${n} chars`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1).replace(/\.0$/, "")}만 자`;
  return `${n.toLocaleString("ko-KR")}자`;
}

export function foldNarration(payload: FoldPayload): string {
  const before = Number(payload.before_chars ?? 0);
  const after = Number(payload.after_chars ?? 0);
  const sizes = before > 0 && after > 0 ? t(" · {0} → {1}", charsLabel(before), charsLabel(after)) : "";
  const sheet = Number(payload.sheet_chars ?? 0) > 0 ? t(" · 이어 갈 정리 한 장을 남겼습니다") : "";
  return t("대화가 길어져 앞 기록을 접었습니다") + sizes + sheet;
}
