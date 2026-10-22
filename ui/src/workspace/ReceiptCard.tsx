/**
 * 첫 화면의 「이번 주 영수증」 카드 (2026-10-21 대표 결정).
 *
 * 간판은 「클로드 한도 덜기 + 검사」다. 그런데 손자리가 클로드 대신 얼마나 읽었는지는 판마다 클로드가 받는 `cost` 칸에만
 * 있었다 — 사람이 보는 곳이 없었다. 그래서 새 대화 화면에 한 주를 모은 한 장을 둔다(`GET /v1/receipt` · 백엔드 `receipt.weekly`).
 *
 * ## 지키는 것
 *
 * - 숫자는 **토큰과 페이지 수**만. 비유 · 달러 · 「약」 · 「배」 · 「무려」 없음. 큰 숫자에는 늘 「최소」(센 글자 ÷ 4.5 의 하한).
 * - 맡긴 일이 0이면 사람이 직접 시킨 일에서 읽은 페이지만 보이는 작은 판. 그것도 0이면 **카드를 숨긴다**(빈 카드 금지).
 * - 못 불러와도 숨긴다 — 첫 화면은 무엇을 하라는 초대라 고장 줄을 얹지 않는다. 못 불러온 것은 설정 › 연결의 카드(`SavingsCard`)가 말한다.
 * - 「이미지로 저장」은 백엔드가 결과물 폴더의 고정 칸(`문서\Sonjari\receipts`)에 쓴다 — 데스크톱 앱(WebView2)에서
 *   `<a download>` 는 반응이 없을 수 있다(09-17 `open_job_output` 과 같은 까닭). 브라우저로 붙은 화면에서만 내려받기로 대신한다.
 */
import { useEffect, useState } from "react";
import { isTauri, type JarvisClient } from "../backend";
import { locale, t } from "../i18n";
import type { WeeklyReceipt } from "../types";
import { formatCount, periodLabel, renderReceiptPng, type ReceiptFacts } from "./receiptImage";
import "./receipt.css";

export const RECEIPT_DAYS = 7;

export type ReceiptView = "full" | "direct" | "hidden";

/** 어떤 판을 보일까 — 맡긴 일이 있으면 온전한 판, 없고 직접 시킨 일에서 읽은 페이지가 있으면 작은 판, 둘 다 없으면 숨김. */
export function receiptView(receipt: WeeklyReceipt | null | undefined): ReceiptView {
  if (!receipt) return "hidden";
  if ((receipt.delegated?.jobs ?? 0) > 0) return "full";
  if ((receipt.direct?.pages ?? 0) > 0) return "direct";
  return "hidden";
}

/** 맡긴 쪽이 전부 클로드(클로드 코드 · 데스크톱)일 때만 「클로드」라고 쓴다. 코덱스 · 커서가 섞이면 「바깥 AI」. */
export function handedByClaude(receipt: Pick<WeeklyReceipt, "callers">): boolean {
  const names = Object.keys(receipt.callers ?? {});
  return names.length > 0 && names.every((name) => /claude|클로드/i.test(name));
}

/** 「136건」 → 숫자는 크게, 단위는 작게(v1 비평: 단위가 숫자만큼 커서 숫자가 덜 보였다). 영어는 단위가 없다. */
function Count({ template, value }: { template: string; value: string }) {
  const [before, after] = t(template, "§").split("§");
  return (
    <>
      {before && <small className="receipt-unit-sm">{before}</small>}
      <b>{value}</b>
      {after && <small className="receipt-unit-sm">{after}</small>}
    </>
  );
}

type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; short: string; onPc: boolean }
  | { kind: "downloaded" }
  | { kind: "failed" };

/** 브라우저로 붙은 화면(개발 · 다른 PC)에서만 쓰는 내려받기. 데스크톱 앱에서는 부르지 않는다. */
function downloadPng(base64: string, name: string): void {
  const link = document.createElement("a");
  link.href = `data:image/png;base64,${base64}`;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
}

export function ReceiptCard({ client, connected = true }: {
  client: Pick<JarvisClient, "getReceipt" | "saveReceiptImage" | "openFolder"> | null;
  /** 다시 이어지면 다시 읽는다 — 백엔드가 늦게 뜬 첫 화면에서도 카드가 나오게. */
  connected?: boolean;
}) {
  const [receipt, setReceipt] = useState<WeeklyReceipt | null>(null);
  const [save, setSave] = useState<SaveState>({ kind: "idle" });

  useEffect(() => {
    if (!client || !connected) return;
    let alive = true;
    client.getReceipt(RECEIPT_DAYS)
      .then((value) => { if (alive) setReceipt(value); })
      .catch(() => { if (alive) setReceipt(null); });
    return () => { alive = false; };
  }, [client, connected]);

  const view = receiptView(receipt);
  if (!receipt || view === "hidden") return null;

  const tag = locale();
  const fmt = (n: number) => formatCount(n, tag);
  const days = receipt.days || RECEIPT_DAYS;

  if (view === "direct") {
    return (
      <section className="receipt-card is-small" aria-labelledby="receipt-title">
        <header>
          <h2 id="receipt-title">{t("이번 주 영수증")}</h2>
          <span className="receipt-period">{t("최근 {0}일", days)}</span>
        </header>
        <p className="receipt-small-line">
          <span>{t("손자리가 대신 읽은 페이지")}</span>
          <strong className="receipt-num"><Count template="{0}개" value={fmt(receipt.direct.pages)} /></strong>
        </p>
      </section>
    );
  }

  const claude = handedByClaude(receipt);
  const d = receipt.delegated;
  const facts: ReceiptFacts = {
    claude, tokens: d.tokens_at_least, jobs: d.jobs, pages: d.pages, flagged: d.flagged_numbers_jobs,
    period: periodLabel(receipt.since, receipt.until),
  };

  const saveImage = async () => {
    if (!client || save.kind === "saving") return;
    setSave({ kind: "saving" });
    let png = "";
    try {
      png = await renderReceiptPng(facts, fmt);
      const result = await client.saveReceiptImage(png);
      if (result.ok) {
        setSave({ kind: "saved", short: result.short || result.name || "", onPc: true });
        return;
      }
    } catch {
      // 아래에서 갈래를 나눈다.
    }
    if (png && !isTauri()) {
      downloadPng(png, "sonjari-receipt.png");
      setSave({ kind: "downloaded" });
      return;
    }
    setSave({ kind: "failed" });
  };

  return (
    <section className="receipt-card" aria-labelledby="receipt-title">
      <header>
        <h2 id="receipt-title">{t("이번 주 영수증")}</h2>
        <span className="receipt-period">{t("최근 {0}일", days)}</span>
        <button type="button" className="receipt-save" onClick={() => void saveImage()} disabled={save.kind === "saving"}>
          {save.kind === "saving" ? t("저장하는 중…") : t("이미지로 저장")}
        </button>
      </header>

      <div className="receipt-hero">
        <p className="receipt-hero-label">{claude ? t("클로드에 안 실은 본문") : t("바깥 AI 에 안 실은 본문")}</p>
        <p className="receipt-hero-figure">
          <span className="receipt-floor">{t("최소")}</span>
          <strong className="receipt-num">{fmt(d.tokens_at_least)}</strong>
          <span className="receipt-unit">{t("토큰")}</span>
        </p>
        <p className="receipt-hero-note">
          {claude
            ? t("손자리가 이 PC 에서 대신 읽고, 클로드에게는 답과 요약만 돌려줬어요.")
            : t("손자리가 이 PC 에서 대신 읽고, 바깥 AI 에는 답과 요약만 돌려줬어요.")}
        </p>
      </div>

      <dl className="receipt-stats">
        <div>
          <dt>{claude ? t("클로드가 맡긴 일") : t("바깥 AI 가 맡긴 일")}</dt>
          <dd className="receipt-num"><Count template="{0}건" value={fmt(d.jobs)} /></dd>
        </div>
        <div>
          <dt>{t("대신 읽은 페이지")}</dt>
          <dd className="receipt-num"><Count template="{0}개" value={fmt(d.pages)} /></dd>
        </div>
        <div title={t("답에 도구가 준 적 없는 숫자가 있어서, 그 숫자를 짚어 돌려준 일이에요.")}>
          <dt>{t("근거 없는 숫자 표시")}</dt>
          <dd className="receipt-num"><Count template="{0}건" value={fmt(d.flagged_numbers_jobs)} /></dd>
        </div>
      </dl>

      <p className="receipt-basis">{t("센 글자 ÷ 4.5 로 낸 하한이라 실제는 더 커요 · 측정 판은 뺐어요")}</p>

      {save.kind === "saved" && (
        <p className="receipt-saved" role="status">
          <span>{t("저장했어요")}</span>
          {save.short && <code>{save.short}</code>}
          {save.onPc && client && (
            <button type="button" onClick={() => void client.openFolder("receipts").catch(() => undefined)}>{t("폴더 열기")}</button>
          )}
        </p>
      )}
      {save.kind === "downloaded" && <p className="receipt-saved" role="status">{t("이미지를 내려받았어요.")}</p>}
      {save.kind === "failed" && <p className="receipt-saved is-failed" role="alert">{t("이미지를 저장하지 못했어요. 다시 눌러 보세요.")}</p>}
    </section>
  );
}
