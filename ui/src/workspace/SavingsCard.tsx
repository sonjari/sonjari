/**
 * 설정 › 연결 맨 위의 작은 카드 — 「이번 주 손자리가 클로드 대신 읽은 양」 (2026-10-19 대표 결정).
 *
 * 바깥 AI(클로드 코드 등)가 MCP 로 맡긴 판에서 손자리가 이 PC 에서 읽은 본문의 **하한** 토큰을 지난 7일 치로 모은다
 * (`GET /v1/savings` · 백엔드 `savings_receipt`). 연결 화면에 둔 까닭: 이 숫자는 「클로드를 손자리에 이었기 때문에」 생긴다.
 *
 * ## 지키는 것
 *
 * - 「최소 N 토큰」과 근거 한 줄만 말한다. 약 · 배 · 금액 · 「한도의 몇 %」로 바꾸지 않는다 — 우리가 잰 근거가 없다.
 * - 시간을 아꼈다는 말을 하지 않는다(로컬은 더 느릴 수 있다).
 * - 멈춘 판도 읽었으면 센다 — 그래서 끝난 판 · 멈춘 판을 나눠 적는다.
 * - 못 불러오면 조용히 숨지 않고 한 줄로 말한다.
 */
import { locale, t } from "../i18n";
import { useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import type { SavingsReceipt } from "../types";

export const SAVINGS_DAYS = 7;

/** 카드의 제목 — 맡긴 쪽이 전부 클로드일 때만 「클로드 대신」. */
export function savingsTitle(receipt: Pick<SavingsReceipt, "host_word">): string {
  return receipt.host_word === "claude"
    ? t("이번 주 손자리가 클로드 대신 읽은 양")
    : t("이번 주 손자리가 바깥 AI 대신 읽은 양");
}

function tokens(n: number): string {
  return Math.max(0, Math.floor(n)).toLocaleString(locale());
}

export function SavingsCard({ client }: { client: Pick<JarvisClient, "getSavings"> }) {
  const [receipt, setReceipt] = useState<SavingsReceipt | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    client.getSavings(SAVINGS_DAYS)
      .then((value) => { if (alive) setReceipt(value); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [client]);

  if (failed) {
    return <p className="settings-note savings-card" role="status">{t("손자리가 대신 읽은 양을 불러오지 못했습니다.")}</p>;
  }
  if (!receipt) return null;
  const jobs = receipt.jobs;
  return (
    <section className="savings-card" aria-label={savingsTitle(receipt)}>
      <h3>{savingsTitle(receipt)}</h3>
      {jobs.total === 0 ? (
        <p className="settings-note">{t("지난 7일 동안 바깥 AI 가 맡긴 일이 없습니다.")}</p>
      ) : (
        <>
          <p className="savings-figure">
            <strong>{t("최소 {0} 토큰", tokens(receipt.tokens_at_least))}</strong>
            <span>{t("(맡긴 일 {0}건)", jobs.total)}</span>
          </p>
          {jobs.stopped > 0 && (
            <p className="settings-note">{t("끝난 일 {0}건 · 멈춘 일 {1}건 — 멈춘 일도 읽은 것은 셉니다.", jobs.done, jobs.stopped)}</p>
          )}
          <p className="settings-note savings-basis">{receipt.basis}</p>
          {receipt.top.length > 0 && (
            <details className="savings-top">
              <summary>{t("가장 많이 덜어 준 일")}</summary>
              <ol>
                {receipt.top.map((item) => (
                  <li key={item.job_id}>
                    <span className="savings-top-prompt">{item.prompt}</span>
                    <span className="savings-top-tokens">{t("최소 {0} 토큰", tokens(item.tokens_at_least))}</span>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </>
      )}
    </section>
  );
}
