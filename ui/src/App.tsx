import { t } from "./i18n";
import { AnimatePresence, motion } from "framer-motion";
import { Brain, CalendarClock, Check, CheckCircle2, ChevronDown, CircleAlert, Clock3, FileText, HandHelping, Image as ImageIcon, Loader2, Mail, Play, Send, ShieldAlert, Square, TimerReset, X, XCircle } from "lucide-react";
import { FormEvent, lazy, Suspense, useState } from "react";
import { hideNativeHud, startNativeHudDrag } from "./backend";
import { MarkdownView } from "./MarkdownView";
import { Orb, stateLabel } from "./Orb";
import { APPROVE_LABELS, ExternalActionPreviewBody } from "./ExternalActionPreview";
import type { AgentProgress, Approval, AttentionNotice, ContinuationRequest, ExternalActionPreview, Presentation } from "./types";
import { ASK_USER_TOOL } from "./types";
import { useJarvis } from "./useJarvis";
import { WorkspaceApp } from "./WorkspaceApp";
import { GATE_TITLES, gateCodeOf } from "./workspace/humanGate";
const MiniStage = lazy(() => import("./workspace/MiniStage"));

// 첫 실행 마법사는 한 번 쓰고 끝나는 화면이라 따로 불러온다(작업 화면 번들을 키우지 않는다).
const SetupWizard = lazy(() => import("./setup/SetupWizard"));
// 이어받기(전략안 §44) — 가끔 여는 화면이라 같은 이유로 따로 불러온다.
const TakeoverPage = lazy(() => import("./takeover/TakeoverPage"));


const ease = [0.22, 1, 0.36, 1] as const;

function Header({ title, modelState, connected, onCollapse }: {
  title: string;
  modelState: Parameters<typeof Orb>[0]["state"];
  connected: boolean;
  onCollapse: () => void;
}) {
  return (
    <header
      className="panel-header"
      data-tauri-drag-region
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        const target = event.target as HTMLElement;
        if (target.closest("button, input, a, [data-no-drag]")) return;
        void startNativeHudDrag();
      }}
    >
      <Orb state={modelState} connected={connected} onPress={() => undefined} compact />
      <div className="panel-heading" data-tauri-drag-region>
        <span className="eyebrow">Sonjari</span>
        <h1>{title}</h1>
      </div>
      <span className={`connection-dot ${connected ? "online" : ""}`} title={connected ? t("연결됨") : t("연결 중")} />
      <button className="icon-button" data-no-drag onClick={onCollapse} aria-label={t("접기")}><ChevronDown size={18} /></button>
      <button className="icon-button" data-no-drag onClick={() => void hideNativeHud()} aria-label={t("숨기기")}><X size={17} /></button>
    </header>
  );
}

function PromptBar({ onSend, error }: { onSend: (prompt: string) => Promise<void>; error: string }) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const prompt = value.trim();
    if (!prompt || submitting) return;
    setSubmitting(true);
    try {
      await onSend(prompt);
      setValue("");
    } catch {
      // The parent keeps the input and renders the actionable backend error.
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <div className="prompt-area" data-no-drag>
      <form className="prompt-bar" onSubmit={submit} data-no-drag>
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && event.nativeEvent.isComposing) event.preventDefault();
          }}
          placeholder={submitting ? t("전송 중…") : t("Sonjari에게 이어서 물어보기")}
          disabled={submitting}
          data-no-drag
        />
        <button type="submit" aria-label={t("보내기")} disabled={!value.trim() || submitting} data-no-drag>
          <Send size={16} />
        </button>
      </form>
      {error && <p className="prompt-error" role="alert">{error}</p>}
    </div>
  );
}

function AgentProgressView({ items, active, busy, thinking, onCancel }: {
  items: AgentProgress[];
  active: boolean;
  busy: boolean;
  thinking: boolean;
  onCancel: () => Promise<void>;
}) {
  if (!items.length) return null;
  return (
    <section className="agent-progress" aria-label={t("Sonjari 작업 진행 상황")}>
      <div className="agent-progress-head">
        <span className={thinking ? "thinking-live" : ""}>{thinking ? <><Brain size={12} /> {t("Gemma가 깊게 판단 중")}</> : active ? t("컴퓨터 작업 진행 중") : t("작업 기록")}</span>
        {active && (
          <button type="button" onClick={() => void onCancel()} disabled={busy} data-no-drag>
            <Square size={11} fill="currentColor" /> {t("작업 중지")}
          </button>
        )}
      </div>
      <ol>
        {items.map((item) => (
          <li key={item.key} className={`progress-${item.status}`}>
            {item.status === "running" ? <Loader2 size={13} className="progress-spinner" /> : item.status === "completed" ? <CheckCircle2 size={13} /> : item.status === "partial" ? <CircleAlert size={13} /> : <XCircle size={13} />}
            <span>{item.message}</span>
            {item.step > 0 && <small>{item.step}</small>}
          </li>
        ))}
      </ol>
    </section>
  );
}

function AnswerPanel({ presentation, state, connected, error, progress, activeJobId, streamingContent, thinking, busy, onCancel, onCollapse, onSend }: {
  presentation: Presentation;
  state: Parameters<typeof Orb>[0]["state"];
  connected: boolean;
  error: string;
  progress: AgentProgress[];
  activeJobId: string;
  streamingContent: string;
  thinking: boolean;
  busy: boolean;
  onCancel: () => Promise<void>;
  onCollapse: () => void;
  onSend: (prompt: string) => Promise<void>;
}) {
  return (
    <motion.section
      className="hud-panel aurora-glass"
      initial={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      animate={{ opacity: 1, width: [68, 420, 480], height: [68, 74, 660], borderRadius: [34, 38, 34] }}
      exit={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      transition={{ duration: 0.46, times: [0, 0.42, 1], ease }}
    >
      <Header title={presentation.display_title || t("답변")} modelState={state} connected={connected} onCollapse={onCollapse} />
      {presentation.mode === "hybrid" && presentation.spoken_text && (
        <motion.div className="spoken-summary" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16, ease }}>
          <span className="summary-wave">◈</span>
          <p>{presentation.spoken_text}</p>
        </motion.div>
      )}
      <AgentProgressView items={progress} active={Boolean(activeJobId)} busy={busy} thinking={thinking} onCancel={onCancel} />
      <motion.article className="answer-scroll" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22, duration: 0.36, ease }}>
        {streamingContent || presentation.display_content ? (
          <MarkdownView>{streamingContent || presentation.display_content}</MarkdownView>
        ) : (
          <p className="working-copy">{t("브라우저에서 필요한 내용을 직접 확인하고 있습니다.")}</p>
        )}
      </motion.article>
      <div className="panel-footer">
        <span>{presentation.estimated_full_speech_sec ? t("전체 음성 약 {0}초", Math.ceil(presentation.estimated_full_speech_sec)) : t("화면 답변")}</span>
        <PromptBar onSend={onSend} error={error} />
      </div>
    </motion.section>
  );
}

function ContinuationPanel({ request, connected, busy, onContinue, onCollapse }: {
  request: ContinuationRequest;
  connected: boolean;
  busy: boolean;
  onContinue: (action: "extend_3m" | "continue_task" | "finish") => Promise<void>;
  onCollapse: () => void;
}) {
  return (
    <motion.section
      className="hud-panel continuation-panel"
      initial={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      animate={{ opacity: 1, width: [68, 420, 480], height: [68, 74, 470], borderRadius: [34, 38, 34] }}
      exit={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      transition={{ duration: 0.42, times: [0, 0.44, 1], ease }}
    >
      <Header title={t("작업을 더 이어갈까요?")} modelState="waiting_continuation" connected={connected} onCollapse={onCollapse} />
      <div className="continuation-body">
        <div className="continuation-icon"><TimerReset size={25} /></div>
        <p className="continuation-kicker">{t("안전한 단계에서 작업을 저장했습니다")}</p>
        <h2>{gateCodeOf(request.reason)
          ? t("{0} — 크롬에서 끝내 주시면 이어갑니다", GATE_TITLES[gateCodeOf(request.reason)] ?? t("사람이 해 주셔야 하는 화면이에요"))
          : request.reason === "step_budget" ? t("이번 작업의 단계 예산을 사용했습니다")
          : request.reason === "time_budget" ? t("기본 작업 시간을 사용했습니다")
          : t("작업을 잠시 멈췄습니다")}</h2>
        <p className="continuation-goal">{request.goal}</p>
        <div className="continuation-stats">
          <span><strong>{request.steps ?? 0}</strong>{t("단계 수행")}</span>
          <span><strong>{request.successful_steps ?? 0}</strong>{t("단계 성공")}</span>
          <span><strong>{request.sources ?? 0}</strong>{t("개 출처")}</span>
        </div>
      </div>
      <div className="continuation-actions">
        <button className="finish" disabled={busy} onClick={() => void onContinue("finish")}><FileText size={15} /> {t("여기까지 정리")}</button>
        <button className="extend" disabled={busy} onClick={() => void onContinue("extend_3m")}><TimerReset size={15} /> {t("3분 더")}</button>
        <button className="continue" disabled={busy} onClick={() => void onContinue("continue_task")}><Play size={15} fill="currentColor" /> {t("이번 작업 계속")}</button>
      </div>
    </motion.section>
  );
}

function AttentionPanel({ notice, connected, onDismiss }: {
  notice: AttentionNotice;
  connected: boolean;
  onDismiss: () => void;
}) {
  // 승인 카드와 일부러 다르게 생겼다. 여기엔 고를 것이 없다 — 브라우저는 이미 화면에
  // 떠 있고, 할 일은 그쪽에서 하는 것이다. 버튼을 두 개 두면 그중 하나가 "자비스가
  // 알아서 해줄 것"처럼 읽힌다.
  return (
    <motion.section
      className="hud-panel attention-panel"
      initial={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      animate={{ opacity: 1, width: [68, 420, 480], height: [68, 74, 402], borderRadius: [34, 38, 34] }}
      exit={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      transition={{ duration: 0.42, times: [0, 0.44, 1], ease }}
    >
      <Header title={t("확인이 필요합니다")} modelState="working" connected={connected} onCollapse={onDismiss} />
      <div className="attention-body">
        <div className="attention-icon"><HandHelping size={25} /></div>
        <h2>{notice.title}</h2>
        <p className="attention-message">{notice.message}</p>
        {notice.url && <p className="attention-url">{notice.url}</p>}
        {notice.detail && <pre className="attention-detail">{notice.detail}</pre>}
        <span className="attention-tool">{notice.tool}</span>
      </div>
      <div className="attention-actions">
        <button className="dismiss" onClick={onDismiss}><Check size={16} /> {t("확인했습니다")}</button>
      </div>
    </motion.section>
  );
}

function ApprovalPanel({ approval, approvalPreview, connected, busy, onDecision, onCollapse }: {
  approval: Approval;
  approvalPreview: ExternalActionPreview | null;
  connected: boolean;
  busy: boolean;
  onDecision: (approve: boolean, answer?: string) => Promise<void>;
  onCollapse: () => void;
}) {
  const expiresIn = approval.expires_at ? Math.max(0, Math.ceil(approval.expires_at - Date.now() / 1000)) : null;
  // 질문 카드(`ask_user`) — 작은 창에서도 고를 수 있어야 한다. 「승인」만 있으면 답 없이 넘어간다.
  if (approval.tool_name === ASK_USER_TOOL) {
    const options = approval.target?.options ?? [];
    const recommended = approval.target?.recommended ?? -1;
    return (
      <motion.section
        className="hud-panel approval-panel"
        initial={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
        animate={{ opacity: 1, width: [68, 420, 480], height: [68, 74, 430], borderRadius: [34, 38, 34] }}
        exit={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
        transition={{ duration: 0.42, times: [0, 0.44, 1], ease }}
      >
        <Header title={t("답해 주시면 이어서 합니다")} modelState="waiting_approval" connected={connected} onCollapse={onCollapse} />
        <div className="approval-body">
          <h2>{approval.target?.question || String(approval.arguments?.question ?? "")}</h2>
          <div className="question-options">
            {options.map((option, index) => (
              <button key={option.label} type="button" disabled={busy}
                className={index === recommended ? "question-option recommended" : "question-option"}
                onClick={() => void onDecision(true, option.label)}>
                <span className="question-option-label">{option.label}{index === recommended && <em className="question-badge">{t("추천")}</em>}</span>
                {option.description && <small>{option.description}</small>}
              </button>
            ))}
          </div>
        </div>
        <div className="approval-actions">
          <button className="deny" disabled={busy} onClick={() => void onDecision(false)}><X size={17} /> {t("그만두기")}</button>
          <button className="approve" disabled={busy} onClick={() => void onDecision(true, "")}><Check size={17} /> {t("알아서 진행")}</button>
        </div>
      </motion.section>
    );
  }
  const previewMatches = approvalPreview?.action_id === approval.arguments?.action_id;
  const approveLabel = APPROVE_LABELS[approval.tool_name] ?? t("승인");
  return (
    <motion.section
      className="hud-panel approval-panel"
      initial={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      animate={{ opacity: 1, width: [68, 420, 480], height: [68, 74, 430], borderRadius: [34, 38, 34] }}
      exit={{ opacity: 0, width: 68, height: 68, borderRadius: 34 }}
      transition={{ duration: 0.42, times: [0, 0.44, 1], ease }}
    >
      <Header title={t("작업 승인이 필요해요")} modelState="waiting_approval" connected={connected} onCollapse={onCollapse} />
      <div className="approval-body">
        <p className="approval-kicker">{t("음성으로는 승인할 수 없습니다")}</p>
        <h2>{approval.tool_name}</h2>
        {previewMatches && approvalPreview ? (
          <ExternalActionPreviewBody toolName={approval.tool_name} data={approvalPreview.preview} />
        ) : (
          <>
            <div className="approval-icon"><ShieldAlert size={25} /></div>
            <pre>{JSON.stringify(approval.arguments ?? {}, null, 2)}</pre>
          </>
        )}
        {expiresIn !== null && <span className="expires"><Clock3 size={14} /> {expiresIn}{t("초 안에 선택")}</span>}
      </div>
      <div className="approval-actions">
        <button className="deny" disabled={busy} onClick={() => void onDecision(false)}><X size={17} /> {t("거절")}</button>
        <button className="approve" disabled={busy} onClick={() => void onDecision(true)}><Check size={17} /> {approveLabel}</button>
      </div>
    </motion.section>
  );
}

function HudApp() {
  const { model, busy, togglePtt, sendChat, cancelActiveJob, continueAgent, decideApproval, collapse, dismissAttention } = useJarvis();
  const status = model.error || stateLabel(model.state, model.connected);
  return (
    <main className={`hud-stage mode-${model.mode}`}>
      <AnimatePresence mode="wait">
        {model.mode === "attention" && model.attention ? (
          <AttentionPanel key="attention" notice={model.attention} connected={model.connected} onDismiss={dismissAttention} />
        ) : model.mode === "panel" && model.presentation ? (
          <AnswerPanel key="panel" presentation={model.presentation} state={model.state} connected={model.connected} error={model.error} progress={model.progress} activeJobId={model.activeJobId} streamingContent={model.streamingContent} thinking={model.thinking} busy={busy} onCancel={cancelActiveJob} onCollapse={collapse} onSend={sendChat} />
        ) : model.mode === "approval" && model.approval ? (
          <ApprovalPanel key="approval" approval={model.approval} approvalPreview={model.approvalPreview} connected={model.connected} busy={busy} onDecision={decideApproval} onCollapse={collapse} />
        ) : model.mode === "continuation" && model.continuation ? (
          <ContinuationPanel key="continuation" request={model.continuation} connected={model.connected} busy={busy} onContinue={continueAgent} onCollapse={collapse} />
        ) : (
          <motion.div key="orb" className="orb-shell" initial={{ opacity: 0, scale: 0.72 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.72 }} transition={{ duration: 0.24, ease }} data-tauri-drag-region>
            <Orb state={model.state} connected={model.connected} disabled={busy} onPress={() => void togglePtt()} />
            <AnimatePresence>
              {(model.state !== "idle" || !model.connected || Boolean(model.error)) && (
                <motion.div className={`status-pill ${model.error ? "status-error" : ""}`} initial={{ opacity: 0, x: 16, scale: 0.88 }} animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0, x: 12, scale: 0.9 }} transition={{ duration: 0.2, ease }}>{status}</motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}

export default function App() {
  const mode = new URLSearchParams(window.location.search).get("mode");
  if (mode === "setup") {
    return (
      <Suspense fallback={null}>
        <SetupWizard />
      </Suspense>
    );
  }
  if (mode === "takeover") {
    return (
      <Suspense fallback={null}>
        <TakeoverPage />
      </Suspense>
    );
  }
  if (mode === "workspace") {
    return <WorkspaceApp />;
  }
  if (mode === "mini") {
    return (
      <Suspense fallback={null}>
        <MiniStage />
      </Suspense>
    );
  }
  return <HudApp />;
}
