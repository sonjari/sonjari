import { t } from "../i18n";
import { motion } from "framer-motion";
import { Check, CornerDownLeft, FileText, MessageCircleQuestion, Play, ShieldAlert, TimerReset, X } from "lucide-react";
import { useState, type ReactNode, type RefObject } from "react";
import { APPROVE_LABELS, ExternalActionPreviewBody } from "../ExternalActionPreview";
import { toolLabel } from "../trajectory";
import type { Approval, ContinuationRequest, ExternalActionPreview } from "../types";
import { GATE_ASKS, GATE_TITLES, gateCodeOf, gateSiteLabel } from "./humanGate";

const ease = [0.22, 1, 0.36, 1] as const;
const enter = { initial: { opacity: 0, y: -6 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.26, ease } };

/**
 * 사용자가 결정해야 하는 것. **화면을 덮지 않는다** — 벌어진 자리에서 자란다.
 *
 * 예전에는 전체를 가리는 덮개였다. 그러면 무엇에 대한 결정인지가 화면에서 사라진다.
 * 대신 부모가 이 카드로 스크롤해서 데려간다(놓치면 작업이 아무 말 없이 멈춰 있다).
 */
export function ApprovalCard(props: {
  approval: Approval;
  preview: ExternalActionPreview | null;
  busy: boolean;
  cardRef: RefObject<HTMLElement>;
  /** 능력을 잰 적 없는 모델이면 한 줄(`modelCaution`). 잰 모델이면 null — 매번 뜨는 경고는 아무도 안 읽는다. */
  caution?: string | null;
  /** 이 도구가 **어느 모드에서도 물어보는 것**이면 「앞으로 묻지 마」를 안 띄운다. */
  alwaysAsk?: string[];
  onDecide: (approve: boolean) => void;
  /** 승인하면서 앞으로 이런 건 묻지 않게 한다. 없으면 버튼이 안 뜬다. */
  onApproveAndRelax?: () => void;
}) {
  const { approval, preview } = props;
  const actionId = String((approval.arguments ?? {}).action_id ?? "");
  // ★ 경고는 **되돌리기 어려운 자리**에서만 띄운다 (2026-09-20 사장님 지시).
  //   폴더를 여는 것과 이 PC 에서 무언가를 실행하는 것이 그 자리다.
  const risky = approval.tool_name === "local_request_path_access"
    || approval.tool_name === "windows_open_path";
  const caution = risky ? props.caution : null;
  return (
    <motion.div className="spine-node decision" {...enter}>
      <span className="spine-dot"><ShieldAlert size={15} /></span>
      <section className="spine-decision" ref={props.cardRef}>
        <header>
          <div><strong>{t("승인해 주셔야 진행합니다")}</strong><small>{t("음성으로는 승인할 수 없습니다")}</small></div>
        </header>
        <h3>{toolLabel(approval.tool_name)}</h3>
        {/* ★ 날것 경로(「바탕화면/회의 메모.txt」) 대신 **어디에 쓰는지와 실제 경로**부터 (2026-09-24). */}
        {approval.target?.path && (
          <p className="approval-target">
            <strong>{approval.target.label}</strong>
            <code>{approval.target.path}</code>
          </p>
        )}
        <div className="decision-body">
          {preview && preview.action_id === actionId
            ? <ExternalActionPreviewBody toolName={approval.tool_name} data={preview.preview} />
            : (
              <>
                <p className="decision-pending">{t("이 작업은 미리보기가 없습니다. 넘길 값은 「자세히」에서 확인하세요.")}</p>
                <details className="decision-details">
                  <summary>{t("자세히")}</summary>
                  <pre>{JSON.stringify(approval.arguments ?? {}, null, 2)}</pre>
                </details>
              </>
            )}
        </div>
        {caution && (
          <p className="decision-caution" role="alert">
            <ShieldAlert size={14} /> {caution}
          </p>
        )}
        <div className="decision-actions">
          <button className="deny" disabled={props.busy} onClick={() => props.onDecide(false)}><X size={15} /> {t("거절")}</button>
          <button className="approve" disabled={props.busy} onClick={() => props.onDecide(true)}>
            <Check size={15} /> {APPROVE_LABELS[approval.tool_name] ?? t("승인")}
          </button>
        </div>
        {/* ★ **여기서 바로 권한을 푼다** (2026-09-21 사장님: 「계속 눌러야 되는 게 귀찮네」).
            설정 화면까지 들어가게 하면 아무도 안 바꾼다 — 귀찮은 그 순간에 손이 닿아야 한다.
            ⚠ 메일·발행·삭제처럼 **어느 모드에서도 물어보는 것**에는 안 띄운다.
               거기에 이 버튼이 뜨면 누르고도 다음에 또 물어봐서, 버튼이 거짓말이 된다. */}
        {props.onApproveAndRelax && !(props.alwaysAsk ?? []).includes(approval.tool_name) && (
          <button
            type="button"
            className="decision-relax"
            disabled={props.busy}
            onClick={props.onApproveAndRelax}
          >
            {t("승인하고, 되돌릴 수 있는 일은 앞으로 묻지 않기")}
          </button>
        )}
      </section>
    </motion.div>
  );
}

/**
 * 모델이 **선택지로 묻는** 카드(`ask_user`, 2026-09-30). 승인 카드와 같은 자리에 같은 모양으로 뜬다.
 *
 * 예전에는 애매하면 답 끝에 글로 묻고 판을 끝냈다 — 대답하면 새 판이 처음부터 다시 돌았다.
 * 이 카드는 판을 **그 자리에서** 멈춰 두고, 고르면 거기서 이어 간다.
 * - 선택지를 누르면 바로 보낸다(확인 한 번 더 없음 — 고르는 것이 곧 답이다).
 * - 「직접 적기」는 선택지에 없는 답. 「알아서 진행」은 모델이 추천한 쪽으로 가되 답에 가정을 밝히게 한다.
 */
export function QuestionCard(props: {
  approval: Approval;
  busy: boolean;
  cardRef: RefObject<HTMLElement>;
  onAnswer: (answer: string) => void;
  onStop: () => void;
}) {
  const target = props.approval.target ?? {};
  const args = props.approval.arguments ?? {};
  const question = String(target.question || args.question || "").trim();
  const options = target.options ?? [];
  const recommended = typeof target.recommended === "number" ? target.recommended : -1;
  const [typed, setTyped] = useState("");
  const send = () => { if (typed.trim()) props.onAnswer(typed.trim()); };
  return (
    <motion.div className="spine-node decision" {...enter}>
      <span className="spine-dot"><MessageCircleQuestion size={15} /></span>
      <section className="spine-decision question-card" ref={props.cardRef} aria-label={t("질문")}>
        <header>
          <div><strong>{t("답해 주시면 이어서 합니다")}</strong><small>{t("작업은 이 자리에서 기다립니다")}</small></div>
        </header>
        <h3>{question || t("어떻게 할까요?")}</h3>
        <div className="question-options" role="group" aria-label={t("선택지")}>
          {options.map((option, index) => (
            <button
              key={option.label}
              type="button"
              className={index === recommended ? "question-option recommended" : "question-option"}
              disabled={props.busy}
              onClick={() => props.onAnswer(option.label)}
            >
              <span className="question-option-label">
                {option.label}
                {index === recommended && <em className="question-badge">{t("추천")}</em>}
              </span>
              {option.description && <small>{option.description}</small>}
            </button>
          ))}
        </div>
        <form className="question-typed" onSubmit={(event) => { event.preventDefault(); send(); }}>
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={t("직접 적기")}
            aria-label={t("선택지에 없는 답 직접 적기")}
            maxLength={2000}
            disabled={props.busy}
          />
          <button type="submit" disabled={props.busy || !typed.trim()} aria-label={t("보내기")}><CornerDownLeft size={15} /></button>
        </form>
        <div className="question-footer">
          <button type="button" disabled={props.busy} onClick={() => props.onAnswer("")}>{t("알아서 진행")}</button>
          <button type="button" disabled={props.busy} onClick={props.onStop}>{t("작업 그만두기")}</button>
        </div>
      </section>
    </motion.div>
  );
}

/** 예산 카드 제목 — **이유가 맞을 때만** 그 말을 쓴다. 모르는 이유에 「시간 다 씀」을 붙이지 않는다. */
const BUDGET_TITLES: Record<string, string> = {
  time_budget: t("기본 작업 시간을 다 썼습니다"),
  step_budget: t("이번 작업의 단계 예산을 다 썼습니다"),
  claude_code_budget: t("맡긴 코딩 작업이 한 구간을 다 썼습니다"),
};

export function ContinuationCard(props: {
  continuation: ContinuationRequest;
  busy: boolean;
  cardRef: RefObject<HTMLElement>;
  onDecide: (action: "extend_3m" | "continue_task" | "finish") => void;
  /** 사람 문 카드에 붙일 「여기서 직접 하기 · 크롬 창 보기」. 위 안내 띠를 이 카드 하나로 합쳤다(2026-10-02 — 두 장이 같은 말을 했다). */
  gateActions?: ReactNode;
}) {
  const { continuation } = props;
  // ★ 같은 자리에서 헛돌아 멈춘 판(2026-09-23): 「더 할까요?」가 아니라 「여기서 막혔습니다 — 이것만 해 주세요」다.
  //   「3분 더」는 뜻이 없다(시간이 모자란 게 아니다). 사람이 손본 뒤 「이어서」, 아니면 가진 것으로 정리.
  if (continuation.reason === "stuck") {
    const report = continuation.report ?? {};
    return (
      <motion.div className="spine-node decision" {...enter}>
        <span className="spine-dot"><TimerReset size={15} /></span>
        <section className="spine-decision" ref={props.cardRef}>
          <header>
            <div><strong>{t("여기서 막혔습니다")}</strong><small>{t("안전한 지점에서 저장했습니다 — 처음부터 다시 하지 않습니다")}</small></div>
          </header>
          <p className="decision-goal">{continuation.goal}</p>
          <dl className="stuck-report">
            <dt>{t("여기까지 했습니다")}</dt><dd>{report.done}</dd>
            <dt>{t("막힌 곳")}</dt><dd>{report.blocked}</dd>
            {report.url && (<><dt>{t("그 화면")}</dt><dd className="stuck-url" title={report.url}>{gateSiteLabel(report.url)}</dd></>)}
            <dt>{t("이것만 해 주세요")}</dt><dd>{report.ask}</dd>
          </dl>
          <div className="decision-actions">
            <button className="deny" disabled={props.busy} onClick={() => props.onDecide("finish")}><FileText size={15} /> {t("여기까지 정리")}</button>
            <button className="approve" disabled={props.busy} onClick={() => props.onDecide("continue_task")}><Play size={15} fill="currentColor" /> {t("이어서")}</button>
          </div>
        </section>
      </motion.div>
    );
  }
  // ★ 사람만 열 수 있는 문(로그인·사람 확인·결제) 앞에서 멈춘 판(2026-09-29).
  //   예전엔 이 판에도 「기본 작업 시간을 다 썼습니다」가 붙었다 — 운영 58건 중 39건이 사실은 문이었다.
  //   시간이 모자란 게 아니니 「3분 더」도 없다. 사람이 문을 연 뒤 「이어서」, 아니면 가진 것으로 정리.
  const gate = gateCodeOf(continuation.reason);
  if (gate) {
    return (
      <motion.div className="spine-node decision" {...enter}>
        <span className="spine-dot"><TimerReset size={15} /></span>
        <section className="spine-decision" ref={props.cardRef}>
          <header>
            <div><strong>{GATE_TITLES[gate] ?? t("사람이 해 주셔야 하는 화면이에요")}</strong><small>{t("안전한 지점에서 저장했습니다 — 처음부터 다시 하지 않습니다")}</small></div>
          </header>
          <p className="decision-goal">{continuation.goal}</p>
          <dl className="stuck-report">
            {continuation.gate_url && (<><dt>{t("그 화면")}</dt><dd className="stuck-url" title={continuation.gate_url}>{gateSiteLabel(continuation.gate_url)}</dd></>)}
            <dt>{t("이것만 해 주세요")}</dt><dd>{GATE_ASKS[gate] ?? t("크롬 창에서 이 화면을 직접 넘겨 주세요.")} {t("끝나면 「이어서」를 눌러 주세요.")}</dd>
          </dl>
          {props.gateActions}
          <div className="decision-actions">
            <button className="deny" disabled={props.busy} onClick={() => props.onDecide("finish")}><FileText size={15} /> {t("여기까지 정리")}</button>
            <button className="approve" disabled={props.busy} onClick={() => props.onDecide("continue_task")}><Play size={15} fill="currentColor" /> {t("이어서")}</button>
          </div>
        </section>
      </motion.div>
    );
  }
  return (
    <motion.div className="spine-node decision" {...enter}>
      <span className="spine-dot"><TimerReset size={15} /></span>
      <section className="spine-decision" ref={props.cardRef}>
        <header>
          <div><strong>{t("작업을 더 이어갈까요?")}</strong><small>{t("안전한 지점에서 저장했습니다")}</small></div>
        </header>
        <h3>{BUDGET_TITLES[continuation.reason ?? ""] ?? t("작업을 잠시 멈췄습니다")}</h3>
        <p className="decision-goal">{continuation.goal}</p>
        <div className="decision-stats">
          <span><strong>{continuation.steps ?? 0}</strong>{t("단계")}</span>
          <span><strong>{continuation.successful_steps ?? 0}</strong>{t("성공")}</span>
          <span><strong>{continuation.sources ?? 0}</strong>{t("출처")}</span>
        </div>
        <div className="decision-actions three">
          <button className="deny" disabled={props.busy} onClick={() => props.onDecide("finish")}><FileText size={15} /> {t("여기까지 정리")}</button>
          <button className="deny" disabled={props.busy} onClick={() => props.onDecide("extend_3m")}><TimerReset size={15} /> {t("3분 더")}</button>
          <button className="approve" disabled={props.busy} onClick={() => props.onDecide("continue_task")}><Play size={15} fill="currentColor" /> {t("계속")}</button>
        </div>
      </section>
    </motion.div>
  );
}
