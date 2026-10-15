import { t } from "./i18n";
import type { AgentProgress, Approval, AttentionNotice, ContinuationRequest, ExternalActionPreview, HudModel, JarvisEvent, JarvisState, Presentation } from "./types";

export const initialHudModel: HudModel = {
  mode: "orb",
  state: "idle",
  connected: false,
  presentation: null,
  approval: null,
  approvalPreview: null,
  continuation: null,
  attention: null,
  activeJobId: "",
  progress: [],
  streamingContent: "",
  thinking: false,
  error: "",
  jobOrigins: [],
};

const JOB_ORIGIN_MEMORY = 24;

// The full-screen WorkspaceApp renders its own answers, so the small HUD stays
// out of the way for jobs it started -- except for the decisions the workspace
// has no UI for. Those must always reach the HUD or an L2 action started from
// the workspace could never be approved.
const WORKSPACE_ALLOWED_EVENTS = new Set([
  "approval_requested",
  "approval_approved",
  "approval_denied",
  "external_action_preview_loaded",
  "agent_continuation_requested",
  "agent_continuation_resumed",
  // Workspace 잡의 결정 카드가 열린 뒤 취소·완료되면 그 카드도 닫혀야 한다.
  // 이 셋을 억제하면 백엔드에는 체크포인트가 없는데 HUD만 계속 409를 낸다.
  "job_cancelled",
  "job_completed",
  "job_failed",
  // 사람이 화면에서 처리해야 하는 상황도 승인과 같은 급이다. 전체화면을 보고 있지
  // 않을 수도 있고(브라우저가 앞에 떠 있다), 그때 유일하게 보이는 창이 여기다.
  "attention_required",
]);

function rememberJobOrigin(model: HudModel, jobId: string, origin: string): HudModel {
  if (!jobId || !origin) return model;
  const known = model.jobOrigins.find((item) => item.jobId === jobId);
  if (known?.origin === origin) return model;
  return {
    ...model,
    jobOrigins: [...model.jobOrigins.filter((item) => item.jobId !== jobId), { jobId, origin }].slice(
      -JOB_ORIGIN_MEMORY,
    ),
  };
}

function originOf(model: HudModel, jobId: string, payloadOrigin: string): string {
  if (payloadOrigin) return payloadOrigin;
  if (!jobId) return "";
  return model.jobOrigins.find((item) => item.jobId === jobId)?.origin ?? "";
}

const validStates = new Set<JarvisState>([
  "idle",
  "listening",
  "transcribing",
  "routing",
  "working",
  "speaking",
  "waiting_approval",
  "waiting_continuation",
  "error",
  "stopped",
]);

/** 백엔드와 **실제로 왕복해서** 받아 온 상태를 반영한다.
 *
 * ★ 지난 에러도 여기서 지운다 (2026-08-12 실측). UI 가 백엔드보다 21초 먼저 떠서
 * (17:08:31 vs 17:08:52) 첫 `getState()` 가 연결 거부로 넘어졌고, 화면에
 * "TypeError: Failed to fetch" 가 박혔다. 웹소켓은 뒤에 붙어 "로컬 연결됨" 초록불이
 * 켜졌는데 **에러를 지우는 코드가 없어서** 둘이 동시에 떠 있었다.
 *
 * 왕복이 성공했다는 것은 그 에러가 이미 지난 일이라는 뜻이다. 연결 플래그가 아니라
 * **성공한 왕복**으로 판정한다 — 이 저장소가 여러 번 배운 규칙이 화면에도 똑같이 맞다.
 */
export function applyStateSnapshot(current: HudModel, state: JarvisState): HudModel {
  return { ...current, state, error: "" };
}

export function reduceJarvisEvent(current: HudModel, message: JarvisEvent): HudModel {
  const payload = message.payload ?? {};
  const eventJobId = String(payload.job_id ?? "");
  const payloadOrigin = String(payload.origin ?? "");
  const model = rememberJobOrigin(current, eventJobId, payloadOrigin);

  if (
    originOf(model, eventJobId, payloadOrigin) === "workspace" &&
    !WORKSPACE_ALLOWED_EVENTS.has(message.event)
  ) {
    return model;
  }

  switch (message.event) {
    case "connected":
      return { ...model, connected: true, error: "" };
    case "state_changed": {
      const next = String(payload.to ?? "") as JarvisState;
      if (!validStates.has(next)) return model;
      return {
        ...model,
        state: next,
        error: next === "error" ? String(payload.reason ?? t("처리 중 문제가 생겼습니다.")) : model.error,
      };
    }
    case "presentation_ready": {
      const presentation = payload as unknown as Presentation;
      if (!presentation.mode) return model;
      return {
        ...model,
        presentation,
        approval: null,
        continuation: null,
        streamingContent: "",
        thinking: false,
        mode: String(payload.origin ?? "voice") === "chat" || presentation.mode !== "voice" ? "panel" : "orb",
        error: presentation.speech?.ok === false ? presentation.speech.error ?? t("음성 재생 실패") : "",
      };
    }
    case "agent_started": {
      const jobId = String(payload.job_id ?? "");
      const keepPanel = String(payload.origin ?? "") === "chat" || model.mode === "panel";
      return {
        ...model,
        mode: keepPanel ? "panel" : model.mode,
        state: "working",
        activeJobId: jobId,
        progress: [],
        streamingContent: "",
        thinking: false,
        continuation: null,
        presentation: keepPanel
          ? model.presentation ?? {
              mode: "screen",
              spoken_text: "",
              display_title: t("Sonjari 작업 중"),
              display_content: "",
            }
          : model.presentation,
        error: "",
      };
    }
    case "agent_progress": {
      const progress: AgentProgress = {
        key: `${String(payload.job_id ?? "")}:${Number(payload.step ?? 0)}:${String(payload.phase ?? "")}:${String(payload.tool ?? "")}`,
        jobId: String(payload.job_id ?? ""),
        phase: String(payload.phase ?? ""),
        message: String(payload.message ?? t("작업 중")),
        step: Number(payload.step ?? 0),
        tool: String(payload.tool ?? ""),
        status: String(payload.status ?? "running") as AgentProgress["status"],
        evidence: payload.evidence as Record<string, unknown> | undefined,
      };
      const previous = model.progress.filter((item) => item.key !== progress.key);
      return { ...model, progress: [...previous, progress].slice(-12), thinking: progress.phase === "planning" ? model.thinking : false };
    }
    case "agent_thinking":
      return { ...model, thinking: true };
    case "agent_answer_reset":
      return { ...model, streamingContent: "", thinking: false };
    case "agent_answer_delta":
      return {
        ...model,
        streamingContent: (model.streamingContent + String(payload.delta ?? "")).slice(-60000),
        thinking: false,
      };
    case "agent_time_warning": {
      const progress: AgentProgress = {
        key: `${String(payload.job_id ?? "")}:time-warning`,
        jobId: String(payload.job_id ?? ""),
        phase: "time_warning",
        message: t("작업 시간이 {0}초 남았습니다", Number(payload.remaining_sec ?? 0)),
        step: Number(payload.steps ?? 0),
        tool: "",
        status: "running",
      };
      return { ...model, progress: [...model.progress.filter((item) => item.key !== progress.key), progress].slice(-12) };
    }
    case "agent_continuation_requested":
      return {
        ...model,
        mode: "continuation",
        state: "waiting_continuation",
        activeJobId: String(payload.job_id ?? ""),
        continuation: payload as unknown as ContinuationRequest,
        thinking: false,
      };
    case "agent_continuation_resumed":
    case "agent_resumed": {
      // The continuation card is the one panel a workspace job may open, so the
      // HUD has to collapse back to the orb once that job resumes.
      const workspaceJob = originOf(model, eventJobId, payloadOrigin) === "workspace";
      return {
        ...model,
        mode: workspaceJob ? "orb" : "panel",
        state: "working",
        continuation: null,
        activeJobId: workspaceJob ? model.activeJobId : String(payload.job_id ?? model.activeJobId),
        thinking: false,
      };
    }
    case "agent_finished":
      return { ...model, state: "working", thinking: false, continuation: null };
    case "attention_required": {
      const notice = payload as unknown as AttentionNotice;
      if (!notice.title) return model;
      // 승인창은 덮지 않는다 — 그건 사람이 결정을 내리는 중이고, 그 위에 안내 카드를
      // 띄우면 결정이 사라진다. 확인 요청은 알림과 음성으로도 이미 나갔다.
      if (model.mode === "approval" || model.mode === "continuation") {
        return { ...model, attention: notice };
      }
      return { ...model, mode: "attention", attention: notice };
    }
    case "attention_cleared":
      return { ...model, mode: model.mode === "attention" ? "orb" : model.mode, attention: null };
    case "approval_requested":
      return {
        ...model,
        mode: "approval",
        state: "waiting_approval",
        approval: payload as unknown as Approval,
        approvalPreview: null,
        continuation: null,
      };
    case "external_action_preview_loaded": {
      const preview = payload as unknown as ExternalActionPreview;
      // Stale-response guard: only apply if it's still the action_id the
      // currently displayed approval is waiting on (the approval may have
      // moved on -- decided, expired, replaced -- by the time this lands).
      const currentActionId = String(model.approval?.arguments?.action_id ?? "");
      if (!currentActionId || preview.action_id !== currentActionId) return model;
      return { ...model, approvalPreview: preview };
    }
    case "approval_approved":
    case "approval_denied":
      return { ...model, mode: "orb", approval: null, approvalPreview: null, state: "idle", thinking: false };
    case "job_failed":
      return {
        ...model,
        state: "error",
        thinking: false,
        continuation: model.continuation?.job_id === eventJobId ? null : model.continuation,
        error: String(payload.error ?? t("작업을 완료하지 못했습니다.")),
      };
    case "job_cancelled": {
      const jobId = String(payload.job_id ?? "");
      const progress = model.progress.map((item) =>
        item.jobId === jobId && item.status === "running" ? { ...item, status: "cancelled" as const } : item,
      );
      return {
        ...model,
        state: "idle",
        activeJobId: model.activeJobId === jobId ? "" : model.activeJobId,
        progress,
        thinking: false,
        continuation: null,
      };
    }
    case "job_completed":
      return {
        ...model,
        activeJobId: model.activeJobId === String(payload.job_id ?? "") ? "" : model.activeJobId,
        thinking: false,
        continuation: model.continuation?.job_id === eventJobId ? null : model.continuation,
      };
    case "runtime_stopped":
      return { ...model, connected: false, state: "stopped" };
    default:
      return model;
  }
}
