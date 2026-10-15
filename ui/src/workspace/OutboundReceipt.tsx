import { t } from "../i18n";
import { callerLabel } from "./TakeoverRelay";

/** 서버가 답 기록에 남긴 영수증(`outbound.outbound_record`) — 바깥 AI 가 맡긴 판에만 있다. */
export type OutboundRecord = {
  host?: string;
  needs?: { label: string; met: boolean }[];
  refined?: { kind: string; count: number }[];
  needs_total?: number;
  needs_met?: number;
  refined_count?: number;
};

/**
 * 한 줄 영수증 (2026-10-15 · 전략안 §55-32). 대표: 「정제해서 나간다 · 데이터의 주권은 당신」.
 *
 * 평소엔 한 줄 — 「Claude Code에게 보냄 · 필요한 것 2/3 · 정제 1」. 펼치면 무엇을 보냈고 무엇을 가렸는지.
 * 「이 PC 에 남긴 원문 ○자」는 아직 싣지 않는다 — 지금 세는 값은 하한이고, 두 손 견주기로 역검증한 뒤에만 띄운다.
 * 일하는 쪽은 차갑게(숫자 · 항목), 보이는 쪽은 조용히 — 출처 도장과 같은 결의 글씨로 답 아래에 둔다.
 */
export function OutboundReceipt({ record }: { record: OutboundRecord }) {
  const needs = Array.isArray(record.needs) ? record.needs : [];
  const refined = Array.isArray(record.refined) ? record.refined : [];
  const total = Number(record.needs_total ?? needs.length);
  const met = Number(record.needs_met ?? needs.filter((item) => item.met).length);
  const hidden = Number(record.refined_count ?? refined.reduce((sum, item) => sum + Number(item.count || 0), 0));
  const line = [
    t("{0}에게 보냄", callerLabel(String(record.host || ""))),
    total > 0 ? t("필요한 것 {0}/{1}", met, total) : "",
    t("정제 {0}", hidden),
  ].filter(Boolean).join(" · ");
  return (
    <details className="message-outbound">
      <summary>{line}</summary>
      <ul>
        {needs.map((item) => (
          <li key={`n-${item.label}`} className={item.met ? "sent" : "missing"}>
            <span>{item.met ? t("보냄") : t("비어 있음")}</span>{item.label}
          </li>
        ))}
        {refined.map((item) => (
          <li key={`r-${item.kind}`} className="hidden">
            <span>{t("가림")}</span>{t("{0} {1}개", t(item.kind), item.count)}
          </li>
        ))}
      </ul>
      <p>
        {hidden > 0
          ? t("가린 것은 바깥으로 나가지 않았습니다. 이 PC 의 기록에는 원문이 그대로 남아 있습니다.")
          : t("이 답은 그대로 나갔습니다. 주민번호 · 카드 번호 · 비밀 키 · 연락처 모양은 나갈 때 가립니다.")}
      </p>
    </details>
  );
}
