/**
 * 컴퓨터 칸의 **「손자리가 받았습니다」** (2026-10-26 · 대표가 승인한 시안 `generated_reports/claude_hands_mockup_1026/시안.html`).
 *
 * 클로드가 손자리에게 맡기는 순간 뜨고, 끝나면 검사 요약으로 바뀐다. 요약은 맡기기 결과(`sonjari_task_status`)에서
 * **센 숫자만** — 근거 곳 수 · 확인할 숫자 · 파일 · 시킨 것. 결과가 아직 없으면 그 칸을 비운다(지어내지 않는다).
 */
import { t } from "../i18n";
import { motion, useReducedMotion } from "framer-motion";
import type { ClaudeHandoff, DelegationSummary } from "../types";

export function checkSummary(summary: DelegationSummary | null): string {
  if (!summary) return "";
  const parts = [
    t("근거 {0}곳", summary.sources),
    summary.unsupported_numbers > 0 ? t("확인할 숫자 {0}", summary.unsupported_numbers) : t("근거 없는 숫자 0"),
  ];
  if (summary.files > 0) parts.push(t("파일 {0}개", summary.files));
  if (summary.needs_total > 0) parts.push(t("시킨 것 {0}/{1}", summary.needs_met, summary.needs_total));
  return parts.join(" · ");
}

export function HandoffCard({ handoffs, localModel }: { handoffs: ClaudeHandoff[]; localModel: string }) {
  const still = useReducedMotion();
  const latest = handoffs[handoffs.length - 1];
  if (!latest) return null;
  const model = localModel ? t("내 PC 모델({0})", localModel) : t("내 PC 모델");
  const done = latest.state === "done";
  const failed = latest.state === "failed";
  const title = done ? t("손자리가 끝냈습니다") : failed ? t("손자리가 끝내지 못했습니다") : t("손자리가 받았습니다");
  const checks = checkSummary(latest.summary);
  const line = done
    ? (checks ? t("검사: {0}", checks) : t("결과를 클로드에게 넘겼습니다"))
    : failed
      ? t("클로드가 결과를 보고 다음을 정합니다")
      : t("{0}이 이어서 합니다 · 클로드는 결과를 기다립니다", model);
  return (
    <motion.div
      key={`${latest.localJobId}:${done || failed ? "end" : "run"}`}
      className={`handoff-card${done ? " done" : ""}${failed ? " failed" : ""}`}
      role="status"
      initial={still ? false : { opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: still ? 0 : 0.42, ease: [0.22, 1, 0.36, 1] }}
    >
      <strong><i className="brain-dot local" aria-hidden />{title}</strong>
      <span>{line}</span>
      {done && checks && <span className="handoff-card-sub">{t("결과와 검사 보고서를 클로드에게 넘겼습니다")}</span>}
      {handoffs.length > 1 && <em>{t("이 판에서 손자리에게 맡긴 일 {0}개", handoffs.length)}</em>}
    </motion.div>
  );
}

/** 답 아래 영수증 줄 — CLI `result` 줄의 값만 · 손자리는 0원 · 내 PC N걸음(눈금자에 선 칸 수). */
export function ClaudeReceipt({ metadata }: { metadata: Record<string, unknown> }) {
  const cost = typeof metadata.cost_usd === "number" ? metadata.cost_usd : null;
  const input = Number(metadata.input_tokens ?? 0);
  const output = Number(metadata.output_tokens ?? 0);
  const steps = Number(metadata.local_steps ?? 0);
  const jobs = Number(metadata.local_jobs ?? 0);
  const tokens = (value: number) => (value >= 1000 ? `${(value / 1000).toFixed(1)}K` : String(value));
  const claude = [
    cost === null ? t("비용 정보 없음") : `$${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}`,
    input > 0 ? t("입력 {0}", tokens(input)) : "",
    output > 0 ? t("출력 {0}", tokens(output)) : "",
  ].filter(Boolean).join(" · ");
  return (
    <p className="claude-receipt">
      <i><span className="brain-dot claude" aria-hidden />{t("클로드")} {claude}</i>
      <i>
        <span className="brain-dot local" aria-hidden />
        {jobs > 0 ? t("손자리 0원 · 내 PC {0}걸음", steps) : t("손자리에게 맡긴 일 없음")}
      </i>
    </p>
  );
}
