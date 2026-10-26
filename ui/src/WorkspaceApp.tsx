import { lang, t } from "./i18n";
import { setSlideFontBase } from "./workspace/slideFonts";
import { isFailureNotice, jobFailureText } from "./workspace/jobFailure";
import { foldNarration } from "./workspace/foldNarration";
import { NO_PAINT, SETTLE_MAX_MS, isSettling, onAnswerPainted, onAnswerReset, onHeadJobDone, type PaintState } from "./workspace/settling";
import { AnimatePresence, motion } from "framer-motion";
import {
  Brain, ChevronsDownUp, Code2, FileText, FolderOpen, HandHelping, Image, Loader2, Mic, Monitor, Paperclip, Send, ShieldCheck, Square, X,
} from "lucide-react";
import { ChangeEvent, ClipboardEvent, DragEvent, FormEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createBackendClient, focusWorkspaceWindow, isTauri, JarvisClient, loadBootstrap, openExternalUrl, pickNativeCodeWorkspace } from "./backend";
import { createShowcaseSource } from "./workspace/ShowcaseStrip";
import { invoke } from "@tauri-apps/api/core";
import { StageMiniWatcher } from "./stageMini";
import { filesFromTransfer, roomFor } from "./clipboardFiles";
import { fileBadge, makeImagePreview } from "./workspace/attachmentPreview";
import { nextFollowState, USER_SCROLL_GRACE_MS } from "./followOutput";
import { forgetLocalSend, type LocalSend, rememberLocalSend, takeLocalEcho } from "./localEcho";
import { MarkdownView } from "./MarkdownView";
import { splitAnswerChecks } from "./workspace/answerChecks";
import { unopenedRowsForJob, withoutUnopenedCheck } from "./workspace/unopenedRows";
import { stateLabel } from "./Orb";
import { TrajectoryNode } from "./TrajectorySpine";
import { applyLooking } from "./workspace/looking";
import { LookingAt } from "./workspace/LookingAt";
import { CapabilityDrawer } from "./workspace/CapabilityDrawer";
import { SettingsScreen } from "./workspace/SettingsScreen";
import { DISCORD_REQUESTS_EVENT, DiscordRequestBanner } from "./workspace/DiscordSection";
import { ComputerPane, ThinkingTrace } from "./workspace/ComputerPane";
import { applyDeckEvent, type DeckState } from "./workspace/DeckStage";
import { ApprovalCard, ContinuationCard, QuestionCard } from "./workspace/DecisionCards";
import { OVERLAY_MAX_WIDTH, useNarrow } from "./workspace/useNarrow";
import { MessageView } from "./workspace/MessageView";
import { useStableCallback } from "./workspace/useStableCallback";
import { ModelLoadLine } from "./workspace/ModelLoadLine";
import { VoiceMeter } from "./workspace/VoiceMeter";
import { Sidebar } from "./workspace/Sidebar";
import { TakeoverRelay, type HandoffOrigin, type TakeoverDirection, type TakeoverRelayStage } from "./workspace/TakeoverRelay";
import { Welcome } from "./workspace/Welcome";
import { ReceiptCard } from "./workspace/ReceiptCard";
import { UpdateBar } from "./workspace/UpdateBar";
import { WhatsNewBar } from "./workspace/WhatsNewBar";
import { HealthBar } from "./workspace/HealthBar";
import { ReadinessBanner } from "./workspace/ReadinessBanner";
import { modelCaution, type AgentGrade } from "./workspace/readiness";
import { JarvisMark } from "./workspace/JarvisMark";
import { setUserLabel, userLabel } from "./workspace/userLabel";
import { PilotAuthBar } from "./pilot/PilotAuthBar";
import { PilotModelPicker, pilotModel, savePilotModel, savedPilotModel, type PilotModelId } from "./pilot/PilotModelPicker";
import { LocalModelPicker, type ClaudeChoice } from "./workspace/LocalModelPicker";
import type { ClaudeLane } from "./claudeAgent/lane";
import { createClaudeLane } from "./claudeAgent/setup";
import { withClaudeLane } from "./claudeAgent/withClaudeLane";
import { brainFor, claudeButtonLabel, isClaudeBrain, setBrain as saveBrain, type Brain as BrainChoice } from "./claudeAgent/brain";
import { PermissionModePicker } from "./workspace/PermissionModePicker";
import { ReasoningPicker, loadReasoningChoice, saveReasoningChoice, type ReasoningChoice } from "./workspace/ReasoningPicker";
import { createSetupApi, type CodeUpgrade, type SetupApi } from "./setup/setupApi";
import { CodeUpgradeCard } from "./workspace/CodeUpgradeCard";
import { applyPlan, applyStep, applyVerification, buildTimeline, finishTrajectory, startTrajectory, toolLabel, type PlanItem, type Trajectory } from "./trajectory";
import { isLive, jobShownHere, jobToFollow, paneContext, whereAQueuedJobLands, withRunningFirst, withYieldedLast } from "./workspace/jobs";
import { GATE_TITLES, HUMAN_GATE_CODES, gateCodeOf, gateSiteLabel } from "./workspace/humanGate";
import { ProblemReportDialog } from "./workspace/ProblemReportDialog";
import type {
  AgentProgress, Approval, AttentionNotice,
  AutoApprovedNotice, ChatAttachment, ClaudeAgentStatus, ClaudeHandoff, ContinuationRequest, CoworkTakeoverOffer,
  ConversationHistory, ConversationMessage, ConversationSummary, ExternalActionPreview,
  GoogleStatus, JarvisEvent, JarvisState, JobOutput, JobSummary, Looking, PermissionModes,
  ScheduleRow, UndoOffer, WorkspaceMode,
} from "./types";
import { ASK_USER_TOOL } from "./types";

// 이 도구들의 승인 `arguments` 에는 {action_id} 만 들어 있다. 사람이 읽을 내용은
// /v1/external-actions/{action_id} 로 따로 가져와야 한다.
const COMMIT_TOOL_NAMES = new Set([
  "google_gmail_send", "google_calendar_create", "google_calendar_update", "google_drive_write",
  "google_calendar_delete", "naver_blog_save_draft", "naver_blog_publish",
]);
import "./workspace.css";
import "./tutorial/tutorial.css";
import { QuestBoard } from "./tutorial/QuestBoard";
import { CoachBubble } from "./tutorial/CoachBubble";
import { useTutorial } from "./tutorial/useTutorial";

type LocalAttachment = ChatAttachment & { size: number };

const WORKSPACE_MODE_KEY = "jarvis.workspace.mode";
const CODE_WORKSPACE_KEY = "jarvis.code.workspace";
const HANDOFF_ORIGINS_KEY = "jarvis.cowork.handoff-origins";

/** 「일하는 중」 블록의 말 줄 — 최근 열두 줄만(길면 답을 가린다). 단 **사람이 덧붙인 말은 지운다 하지 않는다** —
 *  긴 판에서 사람이 끼어든 말이 손자리 말에 밀려 사라지면 무엇을 시켰는지 화면에서 안 보인다(2026-10-01). */
type NarrationRow = { key: string; jobId: string; step: number; text: string; you?: boolean; fold?: boolean };

function keepNarration(rows: NarrationRow[]): NarrationRow[] {
  const machine = rows.filter((row) => !row.you);
  const dropped = new Set(machine.slice(0, Math.max(0, machine.length - 12)));
  return rows.filter((row) => !dropped.has(row));
}

/** 「키 넣기」가 못 넣은 까닭 — 본체가 돌려준 코드를 사람 말로. 무엇이 복사돼 있었는지는 되풀이하지 않는다. */
function apiKeyErrorText(code = ""): string {
  switch (code) {
    case "clipboard_empty": return t("복사해 둔 글이 없습니다 — Claude Console 에서 API 키를 복사한 뒤 다시 눌러 주세요");
    case "not_an_api_key": return t("복사한 글이 API 키 모양이 아닙니다");
    case "subscription_token": return t("구독 로그인 토큰은 쓸 수 없습니다 — Claude Console 의 API 키를 복사해 주세요");
    case "clipboard_unavailable": return t("클립보드를 읽지 못했습니다 — 잠시 뒤 다시 눌러 주세요");
    case "store_failed": return t("키를 저장하지 못했습니다");
    default: return code || t("키를 넣지 못했습니다");
  }
}

function savedWorkspaceMode(): WorkspaceMode {
  return window.localStorage.getItem(WORKSPACE_MODE_KEY) === "code" ? "code" : "cowork";
}

function savedHandoffOrigins(): Record<string, HandoffOrigin> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(HANDOFF_ORIGINS_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, HandoffOrigin> : {};
  } catch {
    return {};
  }
}

function savedCodeWorkspace(): string {
  return window.localStorage.getItem(CODE_WORKSPACE_KEY) ?? "";
}

function displayModelName(model: string): string {
  const value = model.toLowerCase();
  if (value.includes("qwen3.8") && value.includes("27b")) return "Qwen3.8 · 27B";
  if (value.includes("qwen3.5") && value.includes("9b")) return "Qwen3.5 · 9B";
  if (value.includes("gemma4")) return "Gemma 4";
  // ★ 2026-09-17 E2E 3판: 설정 › 모델에서 Granite 로 바꾸니 머리에 태그 그대로 「granite4.1」이 떴다.
  //   이름 앞 글자를 대문자로, 크기 태그는 따로 — 「Granite4.1 · 8B」.
  const [name, size] = model.split(":");
  if (!name) return model;
  const pretty = name.charAt(0).toUpperCase() + name.slice(1);
  const sizeMatch = /^(\d+(?:\.\d+)?b)/i.exec(size ?? "");
  return sizeMatch ? `${pretty} · ${sizeMatch[1].toUpperCase()}` : pretty;
}

/**
 * 보냈지만 아직 안 끝난 질문. 맨 앞이 지금 답하고 있는 것이고 뒤는 차례를 기다린다.
 *
 * 예전에는 이게 job id 하나(activeJobId)였고, 그래서 답이 나오는 동안 입력창을 잠글
 * 수밖에 없었다 — 두 번째 질문을 받아 둘 곳이 없었으니까. 백엔드 작업 큐는 원래
 * 직렬이라(JobRunner 가 한 번에 하나씩 집는다) 지금 바로 보내도 앞의 답을 방해하지
 * 않고, 앞이 끝나는 순간 알아서 이어 돈다. 화면이 잡고 있을 이유가 없었다.
 */
type PendingSend = {
  jobId: string;
  sessionId: string;
  prompt: string;
  files: Array<{ name: string; mime_type: string }>;
  createdAt: number;
};

function makeSessionId() {
  return `jarvis-${Date.now().toString(36)}`;
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = "";
  const chunk = 32_768;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  }
  return btoa(binary);
}

async function readAttachment(file: File): Promise<LocalAttachment> {
  if (file.size > 32 * 1024 * 1024) throw new Error(t("{0}: 32MB 이하 파일만 첨부할 수 있습니다.", file.name));
  const preview = await makeImagePreview(file);
  return {
    name: file.name,
    mime_type: file.type || "application/octet-stream",
    data_base64: bytesToBase64(new Uint8Array(await file.arrayBuffer())),
    size: file.size,
    ...(preview ?? {}),
  };
}

// 리허설 조종대는 개발 빌드에서만 존재한다. 동적 import 라 릴리스 번들에 안 실린다.
const FixtureBar = import.meta.env.DEV ? lazy(() => import("./fixtures/FixtureBar")) : null;


type LiveState = { phase: string; thinking: number; content: number; since: number };

/** 걸음마다 같은 단계가 이어지면 시작 시각을 지킨다 — 초는 그 단계에 들어선 때부터 센다. 빈 단계는 줄을 거둔다. */
export function applyLive(rows: Record<string, LiveState>, jobId: string, phase: string, thinking: number, content: number,
                          now = Date.now()): Record<string, LiveState> {
  const next = { ...rows };
  if (!phase) {
    delete next[jobId];
    return next;
  }
  const before = rows[jobId];
  next[jobId] = { phase, thinking, content, since: before && before.phase === phase ? before.since : now };
  return next;
}

/** 보라색 점 줄의 글. 남은 시간은 말하지 않는다(재 본 적이 없다) — 지난 초와 글자 수만. */
export function liveText(state: LiveState | undefined, now = Date.now()): string {
  if (!state) return "";
  const seconds = Math.max(0, Math.floor((now - state.since) / 1000));
  const chars = (value: number) => value.toLocaleString();
  switch (state.phase) {
    case "thinking":
      return t("모델이 생각하는 중 · {0}자 · {1}초째", chars(state.thinking), seconds);
    case "writing":
      return t("모델이 글을 쓰는 중 · {0}자 · {1}초째", chars(state.content), seconds);
    case "tool":
      return t("모델이 다음에 쓸 도구를 적는 중 · {0}초째", seconds);
    case "checking":
      return t("답을 다 썼습니다({0}자) · 검사하고 내보내는 중 · {1}초째", chars(state.content), seconds);
    default:
      return "";
  }
}

export function WorkspaceApp() {
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>(savedWorkspaceMode);
  const workspaceModeRef = useRef<WorkspaceMode>(workspaceMode);
  const [codeWorkspace, setCodeWorkspace] = useState(savedCodeWorkspace);
  // presence 는 타이머에서 불린다 — 낡은 클로저를 안 보게 ref 로 읽는다.
  const codeWorkspaceRef = useRef<string>(codeWorkspace);
  const [workspacePickerOpen, setWorkspacePickerOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const [pilotMode, setPilotMode] = useState(false);
  const [pilotModelId, setPilotModelId] = useState<PilotModelId>(savedPilotModel);
  const [state, setState] = useState<JarvisState>("idle");
  const [sessions, setSessions] = useState<ConversationSummary[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [history, setHistory] = useState<ConversationHistory | null>(null);
  // 첫 실행 마법사의 「첫 부탁 해 보기」가 ?draft= 로 입력칸을 채운다 — 보내는 건 사람이 누른다.
  const [draft, setDraft] = useState(() => new URLSearchParams(window.location.search).get("draft") ?? "");
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]);
  const [streaming, setStreaming] = useState("");
  // 판은 끝났고 답만 마저 칠해지는 판(`workspace/settling.ts`). 그동안은 흘리던 글을 거두지 않는다.
  const [settlingJobId, setSettlingJobId] = useState("");
  const paintRef = useRef<PaintState>(NO_PAINT);
  const settleTimerRef = useRef(0);
  const [thinking, setThinking] = useState(false);
  // 모델의 사고 원문. 판마다 새로 쌓고, 새 판이 시작되면 비운다.
  const [thinkingText, setThinkingText] = useState("");
  // 같은 사고의 한국어판. 3060 정찰기가 뒤따라 보내 준다 — 늦거나 안 올 수 있다.
  const [thinkingKo, setThinkingKo] = useState("");
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  // ★ **일하면서 하는 말** (2026-09-21). 걸음 목록은 「무엇을 했나」고, 이건 「왜 하나」다.
  //   ⚠ 이 말은 증거가 아니다 — 답도 아니고 원장에도 안 들어간다. 화면에만 산다.
  const [narration, setNarration] = useState<NarrationRow[]>([]);
  // 끝난 뒤에도 남는 궤적. progress 는 우측 레일용(살아 있는 동안만)이고,
  // 이쪽은 대화에 붙어 영구히 남는다 — 답이 도착할 때 근거가 지워지던 것을 고친다.
  const [trajectories, setTrajectories] = useState<Record<string, Trajectory>>({});
  // 지금 읽는 그림 조각(일마다 하나). 걸음 기록에 넣지 않는다 — 그림은 읽는 동안에만 비춘다.
  const [looking, setLooking] = useState<Record<string, Looking>>({});
  // 대화 길의 첫 글자 기다림 — 왜 처음부터 읽는지(도구 목록 · 지침이 바뀜 등)를 백엔드가 말해 준다(2026-10-25 대표). 일마다 하나.
  const [modelWait, setModelWait] = useState<Record<string, string>>({});
  /** 지금 모델이 무엇을 하나(`agent_live` · 10-25 대표) — 보라색 점 줄. 답은 다 쓴 뒤 검사를 거쳐 칠하므로 그동안 멈춘 것처럼 보였다. */
  const [live, setLive] = useState<Record<string, LiveState>>({});
  /** 판마다 그리는 장표(`deck_slide` · `deck_built` · 10-25 대표 「브라우저처럼 다 보이게」). */
  const [decks, setDecks] = useState<Record<string, DeckState>>({});
  const [activeJobId, setActiveJobId] = useState("");
  const [pending, setPending] = useState<PendingSend[]>([]);
  const [attention, setAttention] = useState<AttentionNotice | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [autoApproved, setAutoApproved] = useState<AutoApprovedNotice | null>(null);
  // 승인·계속진행은 작은 팝업에만 있었다. 팝업을 없애면서 여기로 옮긴다 — 이게
  // 없으면 되돌릴 수 없는 동작을 승인할 방법이 아예 사라진다(2026-08-06).
  const [approval, setApproval] = useState<Approval | null>(null);
  const [approvalPreview, setApprovalPreview] = useState<ExternalActionPreview | null>(null);
  const [continuation, setContinuation] = useState<ContinuationRequest | null>(null);
  const [decisionBusy, setDecisionBusy] = useState(false);
  // 지금 모델의 **능력 실측**. 승인 카드가 「이 모델은 아직 안 쟀습니다」를 말할 근거다(2026-09-20).
  const [agentGrade, setAgentGrade] = useState<AgentGrade | null>(null);
  // Ollama `/api/ps` 가 말한 **실제로 올라간 컨텍스트**. 0 이면 아직 모른다.
  const [liveContextLength, setLiveContextLength] = useState(0);
  // 권한 모드. 승인 카드가 「앞으로 묻지 마」를 띄울지 정하는 데 쓴다 —
  // 어느 모드에서도 물어보는 도구에는 그 버튼을 띄우면 안 된다(누르고도 또 물어보면 거짓말).
  const [permissionModes, setPermissionModes] = useState<PermissionModes | null>(null);
  const [reasoning, setReasoning] = useState<ReasoningChoice>(() => loadReasoningChoice());
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // 백엔드에 못 물어봤을 때 쓰는 값. config.py 의 ollama_num_ctx 와 같아야 한다 —
  // 24_576 으로 굳어 있어서, 설정 조회가 늦거나 실패하면 헤더가 "최대 24K" 라고
  // 라이브 설정이 오기 전에도 헤더가 옛 컨텍스트를 잠깐 표시하지 않게 현재 기본값과 맞춘다.
  const [contextWindow, setContextWindow] = useState(131_072);
  const [modelRoles, setModelRoles] = useState<Record<string, string>>({
    // 백엔드 설정이 오기 전 자리표시. 코드 모델은 따로 안 주면 대화 모델을 쓴다(PC 의존성 정리 2026-09-15).
    // ★ 2026-09-16: 여기 박아 둔 이름이 받지도 않은 모델을 「Gemma 4 · 128K」로 보여 줬다. 모르면 비워 둔다.
    chat: "", code: "",
  });
  const [modelContexts, setModelContexts] = useState<Record<string, number>>({});
  // 머리의 모델 고르개가 쓰는 문. 설정 화면이 쓰던 것과 같은 것 — 두 벌로 만들지 않는다.
  const [setupApi, setSetupApi] = useState<SetupApi | null>(null);
  // 코드 일을 보내는 순간의 모델 권고(2026-10-01 밤) — 대화마다 한 번. 「그냥 진행」을 누른 대화는 다시 안 띄운다.
  const [codeOffer, setCodeOffer] = useState<{ sessionId: string; offer: CodeUpgrade } | null>(null);
  const codeOfferSeen = useRef<Set<string>>(new Set());
  const [retrievalEnabled, setRetrievalEnabled] = useState(true);
  const [googleStatus, setGoogleStatus] = useState<GoogleStatus | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  // 파일을 끌고 들어왔나. 놓을 자리를 보여 주려고 둔다.
  const [dragging, setDragging] = useState(false);
  // 경과 초. **작업이 도는 동안에만** 흐른다 — 가만히 있는 화면은 프레임을 안 쓴다.
  const [elapsed, setElapsed] = useState(0);
  // ── 일감 (R1) ─────────────────────────────────────────────────────────
  // 이 창이 만들지 않은 것까지 전부. 음성으로 시킨 것, 예약이 깨운 것, MCP 로 들어온
  // 것이 다 여기 들어온다 — 사이드바 위층이 이걸 그린다.
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  // `syncPending` 이 콜백 안에서 최신 목록을 봐야 한다. state 만 보면 그 시점의
  // 낡은 값을 잡는다.
  const jobsRef = useRef<JobSummary[]>([]);
  const [schedules, setSchedules] = useState<ScheduleRow[]>([]);
  // 소요 시간을 그리는 기준 시각. 도는 일감이 있을 때만 1초마다 흐른다.
  const [now, setNow] = useState(() => Date.now() / 1000);
  // 「할 수 있는 일」 서랍 (R5). 열었을 때만 목록을 가져온다.
  const [capabilitiesOpen, setCapabilitiesOpen] = useState(false);
  // 설정(W3). 사이드바 버튼과 트레이 「설정」(Tauri 이벤트 open-settings)이 연다.
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    let stop: (() => void) | undefined;
    let alive = true;
    void import("@tauri-apps/api/event").then(({ listen }) => listen("open-settings", () => setSettingsOpen(true)))
      .then((unlisten) => { if (alive) stop = unlisten; else unlisten(); })
      .catch(() => undefined);
    return () => {
      alive = false;
      stop?.();
    };
  }, []);
  // 사용량 한도로 멈춘 외부 도구의 맥락이 들어오는 한 번뿐인 오른쪽 연출.
  // 원문을 화면 state 에 복사하지 않고 백엔드가 만든 제한 카드만 갖는다.
  const [takeoverOffer, setTakeoverOffer] = useState<CoworkTakeoverOffer | null>(null);
  const [takeoverStage, setTakeoverStage] = useState<TakeoverRelayStage>("detected");
  const [takeoverBusy, setTakeoverBusy] = useState(false);
  const [takeoverError, setTakeoverError] = useState("");
  const [handoffOrigins, setHandoffOrigins] = useState<Record<string, HandoffOrigin>>(savedHandoffOrigins);

  useEffect(() => {
    window.localStorage.setItem(HANDOFF_ORIGINS_KEY, JSON.stringify(handoffOrigins));
  }, [handoffOrigins]);

  // 카드 자체는 사건이 오기 전에 이미 만들어졌다. 여기의 짧은 두 단계는 거짓
  // 작업 시간이 아니라, 사용자가 무엇을 읽었는지 따라갈 수 있게 하는 인계 연출이다.
  useEffect(() => {
    if (!takeoverOffer) return;
    if (takeoverStage === "detected") {
      // 움직임 줄이기면 연출 없이 바로 고르는 화면으로 간다. 카드는 이미 다 읽은 값이다.
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      const timer = window.setTimeout(() => setTakeoverStage(still ? "ready" : "indexing"), still ? 0 : 620);
      return () => window.clearTimeout(timer);
    }
    if (takeoverStage === "indexing") {
      const timer = window.setTimeout(() => setTakeoverStage("ready"), 1_650);
      return () => window.clearTimeout(timer);
    }
  }, [takeoverOffer, takeoverStage]);

  // 능력 서랍을 열 때 **권한을 실제로 확인한다.**
  //
  // `scope_mismatch` 는 verify=true 일 때만 계산된다(구글에 토큰을 되물어야
  // 알 수 있다). 화면이 verify=false 로만 물어보면 권한이 모자라도 영영 모르고,
  // 재승인 버튼도 안 열린다 — 캐시된 깃발은 물어보는 순간 낡아 있다.
  useEffect(() => {
    if (!capabilitiesOpen) return;
    void clientRef.current?.getGoogleStatus(true).then(setGoogleStatus).catch(() => {});
  }, [capabilitiesOpen]);
  // 에이전트 화면 (R2). **접혀 있으면 프레임을 한 장도 안 가져온다** — 보는 쪽이
  // 간격을 정하는 것이 이 설계의 핵심이다(연출 계약 1번: 정지가 기본).
  //
  // 자리를 미리 차지하지 않는다. 일이 브라우저를 쓰기 시작하면 내려오고, 끝나면
  // 물러난다. 사람이 직접 접었으면 그 뜻을 기억한다 — 다음 일에 또 안 올라온다.
  const [computerDismissed, setComputerDismissed] = useState(false);
  // ── 만든 것 · 되돌리기 (R4) ────────────────────────────────────────────
  // 산출물은 **궤적을 펼쳤을 때만** 물어본다. 대화를 열 때마다 전부 긁어 오면
  // 목록이 455KB 였던 것과 같은 실수다. `undefined` = 아직 안 물어봤다는 뜻이라
  // 빈 서랍과 구별된다.
  const [outputs, setOutputs] = useState<Record<string, JobOutput[]>>({});
  const [undoOffers, setUndoOffers] = useState<UndoOffer[]>([]);
  const clientRef = useRef<JarvisClient | null>(null);
  // 창이 본체보다 먼저 떠서 첫 읽기가 연결 실패로 끝났는가 — 연결되면 다시 읽고 그 오류 줄을 지운다(2026-10-26 「Failed to fetch」가 남음).
  const bootFailedRef = useRef(false);
  // ── 앱 안의 Claude Agent (2026-10-26 · `claudeAgent/`) ─ 갈림은 모델 칸 하나 · 대화마다. 없으면(파일럿 · 브라우저 미리보기) 메뉴에 안 뜬다.
  const [claudeLane, setClaudeLane] = useState<ClaudeLane | null>(null);
  const [claudeStatus, setClaudeStatus] = useState<ClaudeAgentStatus | null>(null);
  const [brain, setBrainState] = useState<BrainChoice>("local");
  const [handoffs, setHandoffs] = useState<Record<string, ClaudeHandoff[]>>({});
  // 대화마다 고른 두뇌(내 PC 모델 / Claude Agent) — 대화를 옮기면 그 대화의 것으로.
  useEffect(() => {
    setBrainState(brainFor(sessionId));
  }, [sessionId, claudeLane]);
  const activeJobRef = useRef("");
  const pendingRef = useRef<PendingSend[]>([]);
  // 이 창이 방금 보냈지만 아직 job_id 를 못 받은 질문들.
  //
  // `job_queued` 는 잡을 만드는 순간 발행되므로 **POST 응답보다 먼저 도착한다.**
  // 그때 pendingRef 는 아직 비어 있어서 "내가 만든 작업"인지 판별할 수가 없고,
  // 그래서 내 질문이 화면에 두 번 실렸다(2026-08-06 사용자 화면: 같은 문장, 같은 분).
  // 답이 느릴수록 이 창이 넓어져 thinking 모드에서 특히 잘 터졌다.
  const localSendsRef = useRef<LocalSend[]>([]);
  const sessionRef = useRef("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const followOutputRef = useRef(true);
  // 사람이 마지막으로 스크롤에 **손을 댄** 시각. 이것 없이 위치만 보면, 브라우저가
  // 제멋대로 만드는 스크롤(스크롤 앵커링·부드러운 애니메이션·레이아웃 점프)까지
  // "사람이 위로 올렸다"로 읽혀 따라가기가 저 혼자 꺼진다.
  const userScrollUntilRef = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);
  // 입력칸은 **쓴 만큼 자란다.** `rows={1}` 에 자동 확장이 없어서 문자 그대로 한 줄이었고,
  // 두 줄째부터 위에 쓴 것이 안 보였다(2026-08-23 사용자 지적).
  const draftRef = useRef<HTMLTextAreaElement>(null);
  // 결정 카드는 화면을 덮지 않는다. 대신 그 자리로 데려간다 — 안 덮으면 놓칠 수
  // 있고, 놓치면 작업이 아무 말 없이 멈춰 있는다.
  const decisionRef = useRef<HTMLDivElement>(null);
  // 일감 목록을 다시 부르기로 예약해 둔 타이머. 사건 하나에 요청 하나를 보내면
  // 걸음이 붙을 때마다 목록을 다시 부르게 된다 — 뒤에 오는 것만 남긴다.
  const jobRefreshTimer = useRef(0);

  // 쓴 만큼 자라게 한다. 높이를 먼저 비워야 줄어들 때도 따라온다 —
  // scrollHeight 는 현재 높이보다 작아지지 않기 때문이다.
  useEffect(() => {
    const box = draftRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${box.scrollHeight}px`;
  }, [draft]);

  useEffect(() => {
    workspaceModeRef.current = workspaceMode;
    window.localStorage.setItem(WORKSPACE_MODE_KEY, workspaceMode);
    if (workspaceMode === "code") {
      // 넓은 창에서는 작업공간을 편다. 좁은 창(멀티태스킹 폭)에서는 대화가 먼저라 접어 두고 「작업공간」 단추로 연다(2026-09-30).
      setComputerDismissed(window.matchMedia?.(`(max-width: ${OVERLAY_MAX_WIDTH}px)`).matches ?? false);
      // Code는 시간·스텝을 자동 연장한다. 모드 전환 전에 도착한 Cowork 카드나
      // 재연결 전의 낡은 카드를 Code 화면에 끌고 오지 않는다.
      setContinuation(null);
    }
  }, [workspaceMode]);

  useEffect(() => {
    codeWorkspaceRef.current = codeWorkspace;
    window.localStorage.setItem(CODE_WORKSPACE_KEY, codeWorkspace);
  }, [codeWorkspace]);

  const chooseCodeWorkspace = useCallback(async () => {
    if (workspacePickerOpen) return;
    setWorkspacePickerOpen(true);
    setError("");
    try {
      const selected = await pickNativeCodeWorkspace(codeWorkspace);
      if (selected) setCodeWorkspace(selected);
    } catch (reason) {
      setError(t("프로젝트 폴더 선택창을 열지 못했습니다: {0}", reason instanceof Error ? reason.message : String(reason)));
    } finally {
      setWorkspacePickerOpen(false);
    }
  }, [codeWorkspace, workspacePickerOpen]);

  const refreshSessions = useCallback(async (client = clientRef.current) => {
    if (!client) return [];
    const rows = await client.getConversations();
    setSessions(rows);
    return rows;
  }, []);

  /**
   * 일감·예약 목록을 다시 읽는다.
   *
   * **주기적으로 돌리지 않는다.** 잡의 생성·종료는 전부 방송으로 오므로(모든
   * 창이 같은 소켓을 듣는다) 사건이 왔을 때만 부르면 된다. 상시 폴링은 자비스가
   * 놀 때도 화면이 일하게 만드는 짓이고, 연출 계약 1번(정지가 기본)에 어긋난다.
   */
  const refreshJobs = useCallback((client = clientRef.current) => {
    if (!client) return;
    window.clearTimeout(jobRefreshTimer.current);
    jobRefreshTimer.current = window.setTimeout(() => {
      void client.listJobs()
        .then((rows) => {
          jobsRef.current = rows;
          setJobs(rows);
        })
        .catch(() => undefined);
      // 예약은 목록이 짧고 거의 안 바뀐다. 같은 계기에 같이 읽어도 값이 싸다.
      void client.listSchedules()
        .then((rows) => setSchedules(rows.schedules ?? []))
        .catch(() => undefined);
    }, 220);
  }, []);

  /** 되돌릴 수 있는 것 목록. 무언가를 바꿨을 만한 순간에만 다시 읽는다. */
  const refreshUndo = useCallback((client = clientRef.current) => {
    if (!client) return;
    void client.listUndo().then((rows) => setUndoOffers(rows.items ?? [])).catch(() => undefined);
  }, []);

  const loadOutputs = useCallback((jobId: string) => {
    const client = clientRef.current;
    if (!client || !jobId) return;
    void client.listOutputs(jobId)
      .then((rows) => setOutputs((current) => ({ ...current, [jobId]: rows.items ?? [] })))
      // 못 읽었으면 빈 목록으로 닫는다 — 계속 다시 묻는 것이 더 나쁘다.
      .catch(() => setOutputs((current) => ({ ...current, [jobId]: [] })));
  }, []);

  /**
   * 만든 파일을 새 창에 띄운다.
   *
   * `<a href>` 로 못 하는 이유: 이 경로는 토큰을 요구하고 브라우저는 링크에
   * 헤더를 못 붙인다. 받아서 blob 으로 연다.
   */
  const openOutput = useCallback(async (jobId: string, output: JobOutput) => {
    const client = clientRef.current;
    if (!client) return;
    // ★ 2026-09-17: 데스크톱 앱에서는 아래 blob 새 창이 막혀 docx 링크가 **아무 반응이 없었다.** 파일은 이 PC 에
    //   있으니 기본 앱으로 먼저 연다. 이 PC 밖에서 붙은 화면(위성 등)일 때만 예전 길로 간다.
    const onPc = await client.openOutputOnPc(jobId, output.path).catch(() => null);
    if (onPc?.ok) return;
    if (onPc && onPc.error && onPc.error !== "not_this_pc" && onPc.error !== "not_windows") {
      setError(t("{0} 을(를) 열지 못했습니다: {1}", output.name, onPc.error));
      return;
    }
    const blob = await client.fetchOutput(jobId, output.path).catch(() => null);
    if (!blob) {
      setError(t("{0} 을(를) 열지 못했습니다. 파일이 지워졌을 수 있습니다.", output.name));
      return;
    }
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    // 창이 읽어 갈 시간을 준 뒤 놓아준다. 바로 지우면 빈 창이 뜬다.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }, []);

  /**
   * 만든 문서의 **속**을 화면 안에서 편다.
   *
   * ★ 2026-09-01. `openOutput` 은 바이트를 받아 창에 띄운다. 그런데 hwpx·docx·
   *   xlsx 는 브라우저가 못 그려서 **다운로드가 될 뿐**이었다 — 사용자가 본
   *   「미리보기도 안되고 아무것도 안되는데」가 그것이다. 여기서는 글을 받는다.
   */
  const previewOutput = useCallback(async (jobId: string, output: JobOutput) => {
    const client = clientRef.current;
    if (!client) return null;
    return client.previewOutput(jobId, output.path).catch(() => null);
  }, []);

  const runUndo = useCallback(async (undoId: string) => {
    const client = clientRef.current;
    if (!client) return;
    setError("");
    const result = await client.runUndo(undoId).catch((reason) => ({
      ok: false,
      error: reason instanceof Error ? reason.message : String(reason),
      verified: undefined as boolean | undefined,
    }));
    // 되돌리기는 **못 되돌렸을 때 그 사실을 말하는 것**이 제일 중요하다. 조용히
    // 목록에서 사라지면 되돌린 줄 알고 넘어간다.
    if (!result.ok) setError(t("되돌리지 못했습니다: {0}", result.error ?? t("이유를 알 수 없습니다")));
    else if (result.verified === false) setError(t("되돌리기를 실행했지만 결과를 확인하지 못했습니다. 화면에서 직접 확인해 주세요."));
    refreshUndo();
  }, [refreshUndo]);

  // 대기열의 맨 앞이 "지금 답하고 있는 작업"이다. 화면 곳곳이 activeJobId 하나를 보고
  // 있어서, 대기열이 바뀔 때마다 그 값을 여기서 한 번에 맞춘다.
  const syncPending = useCallback((next: PendingSend[]) => {
    pendingRef.current = next;
    setPending(next);
    // 이 화면에서 보낸 것이 없으면 **서버에서 실제로 도는 것**을 따라간다.
    // 예전에는 pending 의 맨 앞만 봐서, 이 창 밖에서 시작된 일이 영원히
    // 안 보였다(앱 재시작·MCP·예약·위성·관찰 초소). 자세한 근거는
    // `workspace/jobs.ts` 의 `jobToFollow` 주석에 있다.
    const head = jobToFollow(next[0]?.jobId ?? "", jobsRef.current);
    activeJobRef.current = head;
    setActiveJobId(head);
  }, []);

  // 앱을 켰을 때는 pending 이 비어 있고 잡 목록이 **나중에** 도착한다. 그때 한 번
  // 더 안 맞추면, 이미 도는 일이 있어도 화면은 계속 "준비됐습니다" 로 남는다 —
  // 창을 닫았다 연 사용자가 실제로 그 화면을 봤다.
  useEffect(() => {
    if (pendingRef.current.length) return;
    const next = jobToFollow("", jobs);
    if (next !== activeJobRef.current) {
      activeJobRef.current = next;
      setActiveJobId(next);
    }
  }, [jobs]);

  // 서버 기록에는 아직 없는, 보내 놓고 차례를 기다리는 질문들. 대화를 다시 불러올 때
  // 이걸 안 얹으면 방금 친 질문이 화면에서 사라졌다가 답과 함께 나타난다.
  const withQueuedMessages = useCallback((loaded: ConversationHistory): ConversationHistory => {
    const queued = pendingRef.current
      .filter((item) => item.sessionId === loaded.session_id)
      .map((item, index) => ({
        id: -(2_000_000 + index),
        session_id: item.sessionId,
        role: "user" as const,
        content: item.prompt,
        kind: "chat",
        metadata: { attachments: item.files, queued: true },
        created_at: item.createdAt,
      }));
    if (!queued.length) return loaded;
    // ★ 붙이지 말고 **시각순으로 세운다** (2026-08-23).
    //
    // 그냥 뒤에 붙이면 대화를 다시 부르는 사이 답이 먼저 도착해 있을 때
    // **질문이 답변 아래로 간다.** 사용자 화면에서 실제로 그렇게 보였다 —
    // 물은 것이 답한 것 밑에 있으면 대화가 아니다.
    //
    // 안정 정렬이라 같은 시각이면 원래 순서를 지킨다(서버가 준 차례가 먼저,
    // 방금 보낸 것이 뒤). 시각은 둘 다 초 단위 epoch 라 그대로 비교된다.
    const merged = [...loaded.messages, ...queued];
    merged.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
    return { ...loaded, messages: merged };
  }, []);

  const loadConversation = useCallback(async (nextId: string, client = clientRef.current) => {
    followOutputRef.current = true;
    setSessionId(nextId);
    sessionRef.current = nextId;
    setStreaming("");
    setProgress([]);
    setNarration([]);
    setError("");
    if (!client) return;
    // 보고 있는 대화가 바뀌었다는 것을 바로 알린다. 여기가 늦으면 그 사이 말한 것이
    // 이전 대화로 들어가거나 작은 팝업으로 새어 나간다.
    void client
      .noteWorkspacePresence(
        nextId,
        workspaceModeRef.current,
        workspaceModeRef.current === "code" ? codeWorkspaceRef.current : "",
      )
      .catch(() => undefined);
    try {
      const loaded = await client.getConversation(nextId);
      // 불러오는 사이 다른 대화로 옮겨 갔으면 늦게 도착한 것으로 덮지 않는다(맡긴 판의 방을 여는 순간이 그렇다).
      if (sessionRef.current !== nextId) return;
      setHistory(withQueuedMessages(loaded));
    } catch {
      if (sessionRef.current !== nextId) return;
      setHistory({ session_id: nextId, summary: "", has_summary: false, messages: [] });
    }
  }, [withQueuedMessages]);

  // 바깥 AI 가 맡긴 판의 방을 연다 — `whereAQueuedJobLands` 의 설명.
  //
  // `loadConversation` 과 다른 점 둘:
  //   · 흐르는 답·진행 줄을 지우지 않는다 — 방금 줄에 선 그 판의 것이다.
  //   · 사람이 「이 대화를 보고 있다」고 서버에 따로 알리지 않는다. 맡긴 판의 방을 **보는** 것은 거기서 **말하겠다**는 뜻이 아니다
  //     (주기 알림은 그대로 가지만 서버가 과제 방은 사람의 자리로 치지 않는다 — `note_workspace_presence`).
  const openDelegatedRoom = useCallback(async (roomId: string, client = clientRef.current) => {
    followOutputRef.current = true;
    setSessionId(roomId);
    sessionRef.current = roomId;
    setError("");
    setHistory(withQueuedMessages({ session_id: roomId, summary: "", has_summary: false, messages: [] }));
    if (!client) return;
    try {
      const loaded = await client.getConversation(roomId);
      if (sessionRef.current === roomId) setHistory(withQueuedMessages(loaded));
    } catch {
      // 방금 생긴 방이라 기록이 아직 없을 수 있다 — 위에서 얹은 과제 글로 충분하다.
    }
  }, [withQueuedMessages]);

  // 자리 잡던 답을 완성된 답으로 바꾼다 — 다 칠해졌거나, 한도가 지났거나, 새 판이 시작될 때.
  const finishSettling = useCallback(() => {
    if (!paintRef.current.settlingJob) return;
    paintRef.current = NO_PAINT;
    window.clearTimeout(settleTimerRef.current);
    setSettlingJobId("");
    void loadConversation(sessionRef.current);
    void refreshSessions();
  }, [loadConversation, refreshSessions]);

  useEffect(() => {
    let alive = true;
    let presenceTimer = 0;
    // 브라우저 fetch 가 본체에 닿지 못했을 때의 문구(창이 본체보다 먼저 뜸).
    const isConnectFailure = (message: string) => /failed to fetch|networkerror|load failed/i.test(message);
    // 첫 읽기를 못 한 창 — 본체가 붙으면 대화 목록 · 대화 · 판 · 상태를 다시 읽고 오류 줄을 지운다(한 번만).
    const recoverBoot = async () => {
      const client = clientRef.current;
      if (!client || !alive || !bootFailedRef.current) return;
      bootFailedRef.current = false;
      setError("");
      try {
        const rows = await refreshSessions(client);
        await loadConversation(sessionRef.current || rows[0]?.session_id || makeSessionId(), client);
        refreshJobs(client);
        refreshUndo(client);
        const snapshot = await client.getState();
        setState(snapshot.state as JarvisState);
      } catch {
        // 또 끊겼다 — 연결 신호가 다시 오면 그때 한 번 더.
        bootFailedRef.current = true;
      }
    };
    // 연결 신호가 실패보다 먼저 왔을 수도 있다 — 신호를 기다리지 않고 2초마다 직접 물어 붙으면 다시 읽는다.
    const scheduleRecover = () => {
      const retry = () => {
        if (!alive || !bootFailedRef.current) return;
        void clientRef.current?.getState().then(() => recoverBoot(), () => window.setTimeout(retry, 2_000));
      };
      window.setTimeout(retry, 2_000);
    };
    const reloadModel = async () => {
      try {
        const next = await clientRef.current?.getConfig();
        if (!next || !alive) return;
        setUserLabel(next.user_label);
        setRetrievalEnabled(next.memory_retrieval_enabled !== false);
        setContextWindow(Number(next.ollama_num_ctx || 131_072));
        setModelRoles(next.model_roles ?? {});
        setModelContexts(next.model_num_ctx ?? {});
        setHistory((current) => (current ? { ...current, context_window: Number(next.ollama_num_ctx || 0) || current.context_window } : current));
      } catch { /* 연결이 회복되거나 다음 변경이 오면 다시 읽는다 */ }
    };
    // 모델이 바뀌면 **능력 실측**도 같이 다시 읽는다 — 승인 카드의 경고가 옛 모델 것이면 거짓말이 된다.
    const reloadGrade = async () => {
      try {
        const health = await clientRef.current?.getHealth();
        if (!alive) return;
        setAgentGrade((health?.ollama?.agent_grade as AgentGrade | undefined) ?? null);
        // 올라간 모델이 바뀌면 컨텍스트도 같이 바뀐다 — 한 번에 읽어 둔다.
        setLiveContextLength(Number(health?.ollama?.context_length) || 0);
      } catch { /* 못 물어봤으면 모르는 것이다 — 겁주지 않는다 */ }
    };
    const onModelChanged = () => {
      void reloadModel();
      void reloadGrade();
    };
    window.addEventListener("ontelic:model-changed", onModelChanged);
    void reloadGrade();
    // ★ 2026-09-28: 러너 크기는 **모델을 안 바꿔도** 바뀐다(다른 앱이 32K 로 올린 러너를 받아 쓰기 · 재기동 뒤 128K).
    //   켤 때와 모델 교체 때만 읽었더니 실제 32K 인데 머리에 128K 가 몇 시간 남았다. 30초마다 다시 읽는다(한 번만 거는 효과라 재요청 고리 없음).
    const gradeTimer = window.setInterval(() => void reloadGrade(), 30_000);
    const reloadPermissions = async () => {
      try {
        const modes = await clientRef.current?.permissionMode();
        if (alive && modes) setPermissionModes(modes);
      } catch { /* 못 물어봤으면 버튼을 안 띄운다 — 모르는 것을 열어 주지 않는다 */ }
    };
    // ★ 2026-09-23: 처음엔 이 이벤트로만 읽었다. 그런데 이벤트는 단추를 눌러야 나고, 단추는 목록이
    //   있어야 뜬다 — 단추가 영영 안 떴다. 목록은 **연결될 때마다**(아래 onConnection) 읽는다.
    const onPermissionsChanged = () => void reloadPermissions();
    window.addEventListener("ontelic:permissions-changed", onPermissionsChanged);
    // ★ 2026-09-26 노트북 실측: 바깥 AI(MCP)가 맡긴 일의 작은 창이 **한 번도 안 떴다.** 감시기를 HUD(`useJarvis`)에 붙였는데,
    //   HUD 창은 08-06 에 없앴다(창 하나로 합침 — lib.rs). 앱이 도는 동안 늘 있는 창은 이 작업 창뿐이라 여기서 본다.
    //   사람이 이 창을 보고 있으면(앞에 있고 초점) 무대가 이미 보이니 작은 창은 안 띄운다.
    const stageMini = new StageMiniWatcher(
      () => {
        if (!isTauri() || (document.visibilityState === "visible" && document.hasFocus())) return;
        void invoke("open_stage_mini").catch(() => undefined);
      },
      () => { if (isTauri()) void invoke("close_stage_mini").catch(() => undefined); },
    );
    loadBootstrap().then(async (bootstrap) => {
      if (!alive) return;
      setPilotMode(bootstrap.mode === "pilot");
      // 리허설(개발 모드 전용): 마법사와 같은 `?setupFixture=3090` 으로 모델 고르개·컨텍스트 칸을 PC 별로 본다.
      const setupFixture = import.meta.env.DEV ? new URLSearchParams(window.location.search).get("setupFixture") : null;
      const rehearsal = setupFixture ? (await import("./setup/fixtureSetupApi")).createFixtureSetupApi(setupFixture) : null;
      if (rehearsal) setSetupApi(rehearsal);
      else if (bootstrap.controlToken) setSetupApi(createSetupApi(bootstrap));
      const onEvent = (event: JarvisEvent) => {
        stageMini.onEvent(event);
        const payload = event.payload ?? {};
        const jobId = String(payload.job_id ?? "");
        // 클로드가 손자리에게 맡긴 판의 상태 — 지금 보는 판이 아니어도 적어 둔다(돌아와 열면 카드가 그대로 있게).
        if (event.event === "claude_handoff") {
          if (jobId) setHandoffs((rows) => ({ ...rows, [jobId]: (payload.handoffs ?? []) as ClaudeHandoff[] }));
          return;
        }
        // 받기·자동 적용은 설정 창이 닫혀 있어도 서버에서 끝난다.
        if (event.event === "setup_model_applied" || event.event === "settings_changed") {
          void reloadModel();
          void reloadGrade();
        }
        // 설정 › 권한에서 바꿔도 입력창 옆 단추가 따라와야 한다 — 두 자리가 다른 모드를 말하면 안 된다.
        if (event.event === "settings_changed") void reloadPermissions();
        // 일감 층은 **이 창이 만든 것만** 보는 게 아니다. 잡이 생기거나 끝나거나
        // 사람을 기다리게 되는 사건이면 무조건 목록을 다시 읽는다 — 소유를 따지면
        // 음성·예약·MCP 로 들어온 일이 사이드바에서 통째로 빠진다.
        if (event.event.startsWith("job_") || event.event.startsWith("schedule_")
          || event.event.startsWith("approval_") || event.event.startsWith("agent_continuation_")) {
          refreshJobs();
        }
        // 되돌릴 것이 생기는 순간은 **쓰기 도구가 성공한 뒤**다. 잡이 끝날 때와
        // undo 관련 사건에만 다시 읽는다 — 걸음마다 부르면 목록이 안 바뀌는데도 돈다.
        if (event.event === "job_completed" || event.event.startsWith("undo_")) refreshUndo();
        if (event.event === "state_changed") setState(String(payload.to ?? "idle") as JarvisState);
        // 30분 컨텍스트 감시가 「카드 사정이 바뀌었다」고 알리면 모델 칩이 다시 읽는다(작은 점). 재기·적용 뒤에도 같다.
        if (event.event === "context_watch" || event.event === "setup_context_measured") {
          window.dispatchEvent(new Event("ontelic:context-watch"));
        }
        // 허용 목록 밖 사람이 디스코드로 말을 걸었다 — 알림 자리와 설정 칸이 목록을 다시 읽는다(카드는 GET 으로 그린다).
        if (event.event === "discord_access_requested") {
          window.dispatchEvent(new CustomEvent(DISCORD_REQUESTS_EVENT, { detail: payload }));
          return;
        }
        if (event.event === "google_oauth_connected") {
          void clientRef.current?.getGoogleStatus(true).then(setGoogleStatus);
        }
        // 말로 시킨 것은 이 화면이 만든 작업이 아니다. 세션이 같으면 내 것으로
        // 받아들여야 한다 — 그러지 않으면 받아쓰기도 답변도 화면에 안 붙고,
        // 대화가 빈 채로 "생각하는 중"만 돈다(실측 2026-08-05).
        if (event.event === "voice_routed") {
          if (String(payload.session_id ?? "") !== sessionRef.current) return;
          const spoken = String(payload.transcript ?? "").trim();
          const voiceJob = String(payload.job_id ?? "");
          // 말한 것도 대기열에 넣는다. 답이 나오는 중에 말을 걸어도 앞의 답을
          // 지우지 않고 차례로 붙는다 — 타자로 보낸 것과 같은 규칙이다.
          syncPending([
            ...pendingRef.current,
            {
              jobId: voiceJob,
              sessionId: sessionRef.current,
              prompt: spoken,
              files: [],
              createdAt: Date.now() / 1000,
            },
          ]);
          if (pendingRef.current[0]?.jobId === voiceJob) {
            setStreaming("");
            setProgress([]);
            setNarration([]);
    setNarration([]);
            setThinking(true);
          }
          if (spoken) {
            // ★ 글자로 보낼 때와 **같은 쪽지를 남긴다** (2026-08-23).
            //
            // 안 남기면 말한 것이 화면에 두 번 실린다. `voice_routed` 가 여기서
            // 얹고, 뒤이어 오는 `job_queued` 가 "내 것인지" 판별할 근거를 못 찾아
            // 한 번 더 얹기 때문이다. 위에서 `syncPending` 을 먼저 하므로 보통은
            // `alreadyMine` 에 걸리지만, **두 사건의 도착 순서가 뒤집히면** 그
            // 방어가 통째로 빠진다(사용자 화면에서 실제로 두 번 떴다).
            //
            // 쪽지는 순서와 무관하게 맞춰 준다 — 글자 경로가 2026-08-06 에 같은
            // 이유로 이 방식을 택했다. 방어를 두 벌 두는 게 아니라, **같은 한 벌**
            // 을 두 입구에 다 채우는 것이다.
            localSendsRef.current = rememberLocalSend(localSendsRef.current, spoken);
            // 내가 한 말을 먼저 띄운다. 서버가 대화에 저장하는 건 작업이 끝난
            // 뒤라, 이게 없으면 답이 나올 때까지 무엇을 말했는지 화면에 없다.
            setHistory((current) => current && ({
              ...current,
              messages: [...current.messages, {
                id: -Date.now(), role: "user", content: spoken,
                created_at: Date.now() / 1000, metadata: {},
              } as ConversationMessage],
            }));
          }
          return;
        }
        // 사람이 화면에서 처리해야 하는 상황. 작업 소유와 무관하게 띄운다 — 이 화면이
        // 사용자가 보고 있는 화면이고, 놓치면 브라우저가 조용히 멈춰 있는다.
        if (event.event === "attention_required") {
          setAttention(payload as unknown as AttentionNotice);
          return;
        }
        // 내 PC 모델이 대화 제목을 지었다(2026-10-26) — 왼쪽 목록을 다시 읽는다(제목은 본체 목록 · 제목 문이 준다).
        if (event.event === "conversation_titled") {
          void refreshSessions();
          return;
        }
        // ★ 2026-09-26 E2E: 구조로 알아본 사람 문(비밀번호 칸·보안 문자·결제 칸)에서 온텔릭은 `agent_waiting_for_human` 을 보내고
        //   멈춘다. 화면은 이 이벤트를 **아예 안 듣고 있었다** — 진행 줄 한 줄만 남고 안내 띠·「여기서 직접 하기」가 안 떴다.
        if (event.event === "agent_waiting_for_human") {
          const code = String(payload.code ?? "");
          setAttention({
            job_id: String(payload.job_id ?? ""),
            code,
            tool: "",
            title: GATE_TITLES[code] ?? t("사람이 해 주셔야 하는 화면이에요"),
            message: String(payload.message ?? "").replace(/\*\*/g, "").split("\n\n")[0],
            url: String(payload.url ?? ""),
          });
          return;
        }
        // 작업이 끝날 때까지 온텔릭에게 못 닿은 덧붙인 말 — 버리지 않고 새 작업으로 보낸다(화면에는 이미 떠 있다).
        if (event.event === "agent_steer_leftover") {
          const texts = (Array.isArray(payload.texts) ? payload.texts : []).map(String).filter(Boolean);
          if (texts.length) void sendRef.current(undefined, texts.join("\n"));
          return;
        }
        // 사람이 문을 열어 온텔릭이 이어 붙였다 — 「해 주세요」 띠가 남아 있으면 아직 할 일이 있는 줄 안다.
        if (event.event === "agent_gate_resumed") {
          const resumedJob = String(payload.job_id ?? "");
          setAttention((current) => (current && (!resumedJob || current.job_id === resumedJob) ? null : current));
          return;
        }
        if (event.event === "takeover_offered") {
          const offer = payload as unknown as CoworkTakeoverOffer;
          if (!offer.takeover_id || !offer.card) return;
          setTakeoverOffer(offer);
          setTakeoverStage("detected");
          setTakeoverBusy(false);
          setTakeoverError("");
          setComputerDismissed(false);
          void focusWorkspaceWindow();
          return;
        }
        // ── 사용자가 결정해야 하는 것들 ──────────────────────────────────
        // 작업 소유와 무관하게 받는다. 승인은 놓치면 작업이 그냥 멈춰 있는다.
        // 자동으로 지나간 일도 **화면에 보여야 한다** — 조용히 지나가면 사람이 무엇이 일어났는지 모른다.
        if (event.event === "approval_auto_approved") {
          const notice = payload as unknown as AutoApprovedNotice;
          setAutoApproved({ ...notice, at: Date.now() });
          return;
        }
        if (event.event === "approval_requested") {
          const request = payload as unknown as Approval;
          setApproval(request);
          setApprovalPreview(null);
          void focusWorkspaceWindow();
          const actionId = String((request.arguments ?? {}).action_id ?? "");
          if (actionId && COMMIT_TOOL_NAMES.has(request.tool_name)) {
            clientRef.current?.getExternalAction(actionId)
              .then((preview) => setApprovalPreview(preview))
              .catch(() => undefined);  // 미리보기가 없어도 승인 자체는 가능해야 한다
          }
          return;
        }
        if (event.event === "approval_approved" || event.event === "approval_denied") {
          setApproval(null);
          setApprovalPreview(null);
          return;
        }
        if (event.event === "agent_continuation_requested") {
          // 백엔드가 Code 예산을 자동 연장하는 것이 SSOT다. 구버전 이벤트가 늦게
          // 도착하더라도 Code 화면에 예산 승인 카드를 다시 살리지 않는다.
          // ★ 단, **막혀서 멈춘 판**은 Code 에서도 띄운다(2026-09-23) — 안 띄우면 사람이 할 일을 아무도 모른다.
          if (workspaceModeRef.current === "code" && (payload as { reason?: string }).reason !== "stuck") return;
          setContinuation(payload as unknown as ContinuationRequest);
          void focusWorkspaceWindow();
          return;
        }
        if (event.event === "agent_continuation_resumed" || event.event === "agent_resumed") {
          setContinuation(null);
          return;
        }
        if (
          event.event === "job_cancelled"
          || event.event === "job_completed"
          || event.event === "job_failed"
        ) {
          // 체크포인트가 취소·완료된 뒤 카드만 남으면 누를 때 409가 난다. 해당 잡의
          // 카드만 닫아 다른 대기 결정을 잘못 지우지 않는다.
          setContinuation((current) => current?.job_id === jobId ? null : current);
          // ★ 승인 카드도 같다 (2026-09-30 촬영 판). 취소한 판의 「문서 만들기 — 승인」 카드가 다음 판 위에 그대로 떠 있었고,
          //   누르면 죽은 판의 승인이 됐다(아무 일도 안 일어나 헷갈린다). 백엔드도 취소 때 그 승인을 만료로 바꾼다(jobs.cancel).
          setApproval((current) => current?.job_id === jobId ? null : current);
          // ★ 판이 끝나면 그 판의 경고 띠도 닫는다 (2026-09-28 대결 확인 판). 띠는 화면에 하나뿐이고 ✕ 로만 닫혀서,
          //   멈춘 판의 「같은 곳에서 계속 막히고 있습니다」가 1걸음에 성공한 **다른 대화** 밑에 떠 있었다.
          setAttention((current) => current?.job_id === jobId ? null : current);
        }
        // 새 판이 시작되면 **다른 판의 정보성 띠**(계속 막힘 등)는 닫는다. 사람이 해야 하는 문(로그인·보안 문자 등)은
        // 그 판이 아직 기다리는 중일 수 있어 남긴다.
        if (event.event === "job_queued" || event.event === "job_started") {
          setAttention((current) => current && current.job_id !== jobId && !HUMAN_GATE_CODES.has(current.code) ? null : current);
        }
        // 내가 만들지 않았어도 **지금 보고 있는 대화의 작업**이면 내 것이다.
        // 작은 HUD 에 물어본 답이 여기 실시간으로 안 붙던 이유가 이것이었다 — 같은
        // 대화인데도 새로고침해야 보였다(2026-08-06).
        if (event.event === "job_queued") {
          // ★ 앱 안 Claude 가 맡긴 판(via=app)은 방을 열지도 목록에 올리지도 않는다 (2026-10-26 대표: 「Claude Code…」 주황 방이 따로 떴다).
          //   그 판은 맡긴 Claude 대화의 맡김 카드 · 눈금자로 이미 보인다 — 갈래(`ClaudeLane.observe`)가 같은 사건을 따로 받는다.
          if (String(payload.via ?? "") === "app") return;
          const queuedSession = String(payload.session_id ?? "");
          const alreadyMine = pendingRef.current.some((item) => item.jobId === jobId);
          // ★ 바깥 AI(Claude·Codex)가 MCP 로 맡긴 일은 **대화가 달라도 따라간다** (2026-09-16).
          //   지금까지는 대화 id 가 안 맞아 통째로 안 보였다 — 온텔릭이 혼자 일하는데 화면은 비어 있었다.
          //   ★ 2026-10-09: 따라가되 **보던 대화에 끼워 넣지 않는다** — 그 판의 방을 연다(`whereAQueuedJobLands`).
          const delegated = String(payload.origin ?? "") === "mcp";
          const landing = whereAQueuedJobLands({
            delegated, queuedSession, viewedSession: sessionRef.current, waitingHere: pendingRef.current.length,
          });
          if (!jobId || alreadyMine || landing === "elsewhere") return;
          if (String(payload.kind ?? "") !== "chat") return;
          if (landing === "listed") {
            // 사람이 자기 일을 기다리는 중이다. 화면은 그대로 두고 왼쪽 목록에만 올린다.
            void refreshSessions();
            return;
          }
          const room = landing === "own-room" ? queuedSession : sessionRef.current;
          const asked = String(payload.prompt ?? "").trim();
          // 이 창이 방금 보낸 것인가. pendingRef 로는 알 수 없다 — 그건 POST 응답이
          // 돌아와야 채워지는데 이 사건이 먼저 오기 때문이다. 보내기 직전에 적어 둔
          // 쪽지를 대신 본다. jobId 는 여기서 받아 두고, **메시지는 다시 얹지 않는다**
          // (이미 화면에 있다).
          const { isEcho, rest } = takeLocalEcho(localSendsRef.current, asked);
          localSendsRef.current = rest;
          syncPending([
            ...pendingRef.current,
            { jobId, sessionId: room, prompt: asked, files: [], createdAt: Date.now() / 1000 },
          ]);
          if (delegated && !window.matchMedia?.(`(max-width: ${OVERLAY_MAX_WIDTH}px)`).matches) setComputerDismissed(false);
          // 앞 판의 답이 아직 자리 잡는 중이면 기다리지 않고 완성된 답으로 바꾼다 — 새 판이 그 풍선을 쓴다.
          finishSettling();
          if (pendingRef.current[0]?.jobId === jobId) {
            setStreaming("");
            setProgress([]);
            setNarration([]);
    setNarration([]);
            setThinking(true);
          }
          if (landing === "own-room") {
            // 과제 글은 방을 열 때 대기열에서 얹힌다(`withQueuedMessages`) — 여기서 따로 끼워 넣지 않는다.
            void openDelegatedRoom(room);
            void refreshSessions();
            return;
          }
          if (asked && !isEcho) {
            setHistory((current) => current && ({
              ...current,
              messages: [...current.messages, {
                id: -Date.now(), role: "user", content: asked,
                created_at: Date.now() / 1000, metadata: {},
              } as ConversationMessage],
            }));
          }
          return;
        }
        if (!jobId) return;
        // ★ **지금 실제로 도는 판**이 줄 맨 앞이다 (2026-10-09 낮). 서버는 사람의 판을 맡긴 판보다 먼저 꺼내고, 돌던 맡긴 판은
        //   비켜 줬다 다시 줄에 선다 — 들어온 순서와 도는 순서가 달라졌다(`withRunningFirst` 의 설명).
        //   맨 앞이 바뀌면 흘리던 글은 앞 판의 것이니 거둔다.
        if (event.event === "job_started" || event.event === "job_yielded") {
          const reordered = event.event === "job_started"
            ? withRunningFirst(pendingRef.current, jobId)
            : withYieldedLast(pendingRef.current, jobId);
          if (reordered !== pendingRef.current) {
            syncPending(reordered);
            setStreaming("");
            setThinkingText("");
            setThinkingKo("");
            setThinking(true);
          }
        }
        // 끝나는 사건은 대기열 어느 것이든 받는다. 맨 앞만 보면, 시작도 못 하고 실패한
        // 뒤쪽 작업이 영영 대기열에 남아 입력이 잠긴 것처럼 보인다.
        if (event.event === "job_completed" || event.event === "job_failed" || event.event === "job_cancelled") {
          tutorialRef.current.onJobEnded(event.event === "job_completed" ? "completed" : event.event === "job_failed" ? "failed" : "cancelled", jobId);
          setLooking((rows) => applyLooking(rows, jobId, { done: true }));
          // 궤적은 닫기만 한다. 지우면 답 옆에서 근거가 사라진다.
          // ★ 2026-09-20 노트북: 이 창이 보내지 않은 작업(원격 API·MCP·다른 창)은 아래 대기열 검사에서 걸러져
          //   궤적이 **영영 「일하는 중」**으로 남았다. 끝났다는 사실은 누가 보냈든 같다 — 대기열보다 먼저 닫는다.
          setTrajectories((rows) => rows[jobId]
            ? { ...rows, [jobId]: finishTrajectory(rows[jobId],
                event.event === "job_completed" ? "completed" : event.event === "job_failed" ? "failed" : "cancelled",
                Date.now() / 1000) }
            : rows);
          if (!pendingRef.current.some((item) => item.jobId === jobId)) {
            // ★ 2026-10-26 Claude Agent 첫 판: 대기열 밖에서 만든 판(앱 안 Claude 갈래)이 실패하면 여기서 돌아가 버려
            //   오류 문장이 화면에 한 번도 안 떴다 — 「0걸음 · 끝났습니다」만 남았다. 지금 보는 대화의 실패는 대기열과 상관없이 보인다.
            if (event.event === "job_failed" && String(payload.session_id ?? "") === sessionRef.current) {
              setError(jobFailureText(payload.error));
            }
            // ★ 멈춤은 사건이 **두 번** 온다 (2026-10-04 라이브): 버튼을 누른 순간, 그리고 판이 실제로 멈춘 순간.
            //   서버는 둘째에야 「어디까지 했는지」를 대화에 남긴다 — 첫째에서 대기열을 비웠으니 여기로 온다. 한 번 더 읽는다.
            if (event.event !== "job_completed") {
              window.setTimeout(() => { void loadConversation(sessionRef.current, client); }, 400);
            }
            return;
          }
          const wasHead = activeJobRef.current === jobId;
          const remaining = pendingRef.current.filter((item) => item.jobId !== jobId);
          if (event.event === "job_failed") setError(jobFailureText(payload.error));
          syncPending(remaining);
          if (!wasHead) return;
          // 답이 아직 칠해지는 중이면 흘리던 글을 거두지 않는다 — 다 칠해지면(또는 한도가 지나면) 그때 대화를 다시 읽는다.
          const done = onHeadJobDone(paintRef.current, jobId, event.event === "job_completed", remaining.length);
          paintRef.current = done.state;
          if (done.settle) {
            setSettlingJobId(jobId);
            setThinking(false);
            window.clearTimeout(settleTimerRef.current);
            settleTimerRef.current = window.setTimeout(finishSettling, SETTLE_MAX_MS);
            void refreshSessions(client);
            return;
          }
          setThinking(remaining.length > 0);
          setStreaming("");
          if (remaining.length > 0) { setProgress([]); setNarration([]); }
          // ★ 실패한 판도 대화를 다시 읽는다 (2026-10-04). 서버가 그 판의 질문과 「어디까지 했는지」를 대화에 남긴다 —
          //   안 읽으면 질문이 화면에서 사라지고 빨간 한 줄만 남는다.
          if (event.event === "job_completed" || event.event === "job_cancelled" || event.event === "job_failed") {
            window.setTimeout(() => {
              void loadConversation(sessionRef.current, client);
              void refreshSessions(client);
            }, 180);
          }
          return;
        }
        // ★ 판이 끝난 뒤에도 오는 답 조각 (2026-10-07). 본 창이 시킨 판의 답은 판 밖에서 칠해진다 — 그 판의 조각은
        //   「지금 도는 판」이 아니어도 받는다. 다 칠했다는 사건이 오면 대화를 다시 읽어 완성된 답으로 바꾼다.
        if (isSettling(paintRef.current, jobId)) {
          if (event.event === "agent_answer_delta") {
            setStreaming((value) => (value + String(payload.delta ?? "")).slice(-80_000));
          } else if (event.event === "agent_answer_painted") {
            finishSettling();
          }
          return;
        }
        if (jobId !== activeJobRef.current) return;
        if (event.event === "agent_started") {
          tutorialRef.current.onAgentStarted(jobId, String(payload.origin ?? ""));
          setThinkingText("");
          setThinkingKo("");
          // The workspace used to minimize itself here and hand the screen to
          // the small HUD panel. It now keeps its own answer and activity rail
          // on screen instead -- the HUD stays an orb for workspace jobs, so
          // minimizing would leave nothing visible. A browser the agent opens
          // takes foreground on its own.
          //
          // 흘려 둔 글은 여기서 지운다. 라우터가 판단하며 뿌린 초안이 남아 있으면
          // 에이전트의 진짜 답이 그 뒤에 이어붙어 **두 번 답한 것처럼** 보인다
          // (2026-08-06 사용자 지적). 백엔드도 버리는 순간 지우라고 보내지만,
          // 화면에서도 한 번 더 막는다 — 이건 놓치면 바로 눈에 띄는 종류의 오류다.
          setStreaming("");
          setThinking(true);
          setTrajectories((rows) => rows[jobId] ? rows : {
            ...rows,
            [jobId]: startTrajectory(jobId, sessionRef.current,
              pendingRef.current.find((row) => row.jobId === jobId)?.prompt ?? "", Date.now() / 1000),
          });
        } else if (event.event === "agent_thinking") {
          setThinking(true);
        } else if (event.event === "agent_thinking_ko") {
          // 원문보다 늦게 온다. 못 오면 그냥 원문이 남는다 — 그게 정상 동작이다.
          setThinkingKo((value) => (value + String(payload.delta ?? "")).slice(-40_000));
        } else if (event.event === "agent_thinking_text") {
          // 답과 달리 되받혀 지워지지 않는다 — 사고는 답이 아니라서 계획 대조가
          // 건드리지 않는다. 그래서 흘려도 「답이 나왔다 사라지는」 일이 없다.
          setThinkingText((value) => (value + String(payload.delta ?? "")).slice(-40_000));
        } else if (event.event === "agent_answer_reset") {
          paintRef.current = onAnswerReset(paintRef.current, jobId, Boolean(payload.apart));
          setStreaming("");
          setThinking(false);
        } else if (event.event === "agent_answer_painted") {
          // 판이 끝나기 전에 다 칠해졌다 — 끝날 때 기다릴 것이 없다.
          paintRef.current = onAnswerPainted(paintRef.current, jobId).state;
        } else if (event.event === "agent_answer_delta") {
          setStreaming((value) => (value + String(payload.delta ?? "")).slice(-80_000));
          setThinking(false);
        } else if (event.event === "agent_steer_applied") {
          const line = {
            key: `${jobId}:steer:${payload.step ?? 0}:${String(payload.text ?? "").slice(0, 20)}`,
            jobId,
            step: Number(payload.step ?? 0),
            text: t("덧붙이신 말을 반영합니다 — 「{0}」", String(payload.text ?? "").slice(0, 80)),
          };
          setNarration((rows) => keepNarration([...rows.filter((r) => r.key !== line.key), line]));
        } else if (event.event === "agent_transcript_step_folded") {
          // 대화를 접었다 — 말 줄에 한 줄 남긴다(2026-10-22 대표). 걸음 번호가 알림에 없어 그 판의 마지막 줄 번호를 잇는다.
          const text = foldNarration(payload);
          setNarration((rows) => {
            const last = rows.filter((r) => r.jobId === jobId && !r.you).at(-1);
            const line = { key: `${jobId}:fold:${payload.before_chars ?? 0}:${payload.after_chars ?? 0}`, jobId,
              step: last?.step ?? 0, text, fold: true };
            return keepNarration([...rows.filter((r) => r.key !== line.key), line]);
          });
        } else if (event.event === "agent_says") {
          // 같은 걸음이 두 번 오면 나중 것만 남긴다. 최근 열두 줄만 — 길면 답을 가린다.
          const line = {
            key: `${jobId}:${payload.step ?? 0}`,
            jobId,
            step: Number(payload.step ?? 0),
            text: String(payload.text ?? ""),
          };
          if (line.text) {
            setNarration((rows) => keepNarration([...rows.filter((r) => r.key !== line.key), line]));
          }
        } else if (event.event.startsWith("deck_")) {
          setDecks((rows) => {
            const next = applyDeckEvent(rows[jobId], event.event, payload);
            return next ? { ...rows, [jobId]: next } : rows;
          });
        } else if (event.event === "agent_live") {
          const phase = String(payload.phase ?? "");
          setLive((rows) => applyLive(rows, jobId, phase, Number(payload.thinking_chars ?? 0), Number(payload.content_chars ?? 0)));
        } else if (event.event === "model_wait") {
          const message = String(payload.message ?? "");
          setModelWait((rows) => {
            const next = { ...rows };
            if (message) next[jobId] = message;
            else delete next[jobId];
            return next;
          });
        } else if (event.event === "agent_looking") {
          setLooking((rows) => applyLooking(rows, jobId, payload));
        } else if (event.event === "agent_progress") {
          // 다음 걸음이 왔다 — 그림 읽기는 끝난 것이다(거두는 알림이 빠졌어도 「읽는 중」이 남지 않게).
          setLooking((rows) => applyLooking(rows, jobId, { done: true }));
          const item: AgentProgress = {
            key: `${jobId}:${payload.step ?? 0}:${payload.phase ?? ""}:${payload.tool ?? ""}`,
            jobId,
            phase: String(payload.phase ?? ""),
            message: String(payload.message ?? t("작업 중")),
            step: Number(payload.step ?? 0),
            tool: String(payload.tool ?? ""),
            status: String(payload.status ?? "running") as AgentProgress["status"],
            // 근거를 여기서 안 받으면 궤적에 안 남는다. 타입에는 처음부터 있었는데
            // **아무도 채우지 않아서** 걸음 펼침이 도구 이름만 보여 주고 있었다(R4).
            evidence: (payload.evidence ?? undefined) as AgentProgress["evidence"],
          };
          setProgress((items) => [...items.filter((row) => row.key !== item.key), item].slice(-16));
          setTrajectories((rows) => {
            const current = rows[jobId] ?? startTrajectory(jobId, sessionRef.current,
              pendingRef.current.find((row) => row.jobId === jobId)?.prompt ?? "", Date.now() / 1000);
            // 판 끝 검사(phase=verification)의 「한 번도 안 연 곳의 줄」은 오른쪽 판이 따로 읽는다(`applyVerification`).
            return { ...rows, [jobId]: applyVerification(applyStep(current, item, Date.now() / 1000), item) };
          });
          // ★ 회복하면 「같은 곳에서 계속 막히고 있습니다」를 거둔다 (2026-10-01 운영 판 f7c9e4e3). 9·10걸음이 연달아 실패해
          //   띠가 떴고, 11걸음부터 다른 길로 끝까지 잘 갔는데 띠는 판이 끝날 때까지 남아 「막혔다」로 보였다.
          //   같은 판에서 도구 걸음 하나가 성공하면 그 판의 「계속 막힘」 띠만 닫는다(사람이 해야 하는 문은 그대로).
          if (item.status === "completed" && item.tool) {
            setAttention((current) => current && current.job_id === jobId && current.code === "repeated_failure" ? null : current);
          }
        } else if (event.event === "agent_plan") {
          // 시킨 것 대조 (R3). 백엔드가 매번 전부 다시 세므로 통째로 갈아 끼운다.
          // 궤적이 아직 없을 수도 있다(사건 순서는 보장되지 않는다) — 그러면 만든다.
          const items = (Array.isArray(payload.items) ? payload.items : []) as PlanItem[];
          setTrajectories((rows) => {
            const current = rows[jobId] ?? startTrajectory(jobId, sessionRef.current,
              pendingRef.current.find((row) => row.jobId === jobId)?.prompt ?? "", Date.now() / 1000);
            return { ...rows, [jobId]: applyPlan(current, items) };
          });
        } else if (event.event === "presentation_ready") {
          const content = String(payload.display_content ?? "");
          setStreaming(content);
          setThinking(false);
        }
      };
      // 리허설(`?fixture=`)일 때만 가짜 백엔드가 들어온다. 개발 빌드 전용이고,
      // 릴리스에서는 이 팩토리가 진짜 JarvisClient 만 돌려준다.
      // Claude 갈래: 원래 사건은 그대로 화면에 흐르고, 갈래는 클로드가 맡긴 손자리 판의 사건을 클로드 판의 사건으로 한 번 더 흘린다.
      setSlideFontBase(bootstrap.baseUrl);  // 장표 미리보기 칸이 앱 글꼴을 본체에서 받는다(slideFonts)
      const lane = await createClaudeLane(bootstrap, onEvent, () => clientRef.current).catch(() => null);
      if (!alive) return;
      const route = lane ? (event: JarvisEvent) => { onEvent(event); lane.observe(event); } : onEvent;
      const client = await createBackendClient(bootstrap, route, (value) => {
        setConnected(value);
        // State arrives only as an event, so a dropped socket would otherwise
        // leave the header showing whatever the last event said.
        if (value) {
          void client.getState().then((snapshot) => setState(snapshot.state as JarvisState)).catch(() => undefined);
          void reloadModel();
          void reloadPermissions();
          if (bootFailedRef.current) void recoverBoot();
        }
      });
      if (lane) {
        withClaudeLane(client, lane);
        setClaudeLane(lane);
        void lane.runner.status().then((next) => { if (alive) setClaudeStatus(next); }).catch(() => undefined);
      }
      clientRef.current = client;
      client.connect();
      // 살아 있다는 것을 계속 알린다. 이 신호가 끊기면(창을 닫았거나 얼었거나) 백엔드는
      // 음성 답변을 다시 작은 팝업으로 보낸다 — 그때는 그게 유일하게 보이는 화면이다.
      presenceTimer = window.setInterval(() => {
        void client
          .noteWorkspacePresence(
            sessionRef.current,
            workspaceModeRef.current,
            workspaceModeRef.current === "code" ? codeWorkspaceRef.current : "",
          )
          .catch(() => undefined);
      }, 20_000);
      try {
        const config = await client.getConfig();
        // 쓰는 사람을 뭐라고 부를지는 **서버 설정에서 온다.** 화면에 박아 두었다가
        // 다른 사람에게 줄 판을 만들 때 본체 소스를 고치는 일이 생겼다(2026-09-11).
        setUserLabel(config.user_label);
        setContextWindow(Number(config.ollama_num_ctx || 131_072));
        setModelRoles(config.model_roles ?? {});
        setModelContexts(config.model_num_ctx ?? {});
        setRetrievalEnabled(config.memory_retrieval_enabled !== false);
      } catch {
        // Config discovery is informative; chat remains available if it is delayed.
      }
      // ★ 2026-09-16: 설정은 창을 열 때 한 번만 읽어서, 모델을 바꿔도 머리의 모델 표시가 옛 이름으로 남았다.
      //   설정 › 모델에서 바꾸면 다시 읽는다.
      try {
        setGoogleStatus(await client.getGoogleStatus(false));
      } catch {
        // Google is optional; local chat remains available.
      }
      const rows = await refreshSessions(client);
      await loadConversation(rows[0]?.session_id || makeSessionId(), client);
      refreshJobs(client);
      refreshUndo(client);
      try {
        const snapshot = await client.getState();
        setState(snapshot.state as JarvisState);
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        if (isConnectFailure(message)) {
          bootFailedRef.current = true;
          scheduleRecover();
        } else setError(message);
      }
    }).catch((reason) => {
      const message = reason instanceof Error ? reason.message : String(reason);
      // 본체가 아직 안 떴다(브라우저 fetch 의 연결 실패) — 날 문구 대신 기다린다는 말, 연결되면 위에서 다시 읽고 지운다.
      if (isConnectFailure(message)) {
        bootFailedRef.current = true;
        setError(t("Sonjari 본체에 연결하는 중입니다."));
        scheduleRecover();
        return;
      }
      setError(message);
    });
    return () => {
      alive = false;
      window.removeEventListener("ontelic:model-changed", onModelChanged);
      window.removeEventListener("ontelic:permissions-changed", onPermissionsChanged);
      window.clearInterval(presenceTimer);
      window.clearInterval(gradeTimer);
      window.clearTimeout(jobRefreshTimer.current);
      clientRef.current?.disconnect();
    };
  }, [finishSettling, loadConversation, openDelegatedRoom, refreshJobs, refreshSessions, refreshUndo, syncPending]);

  // 답이 흘러나오는 동안 화면도 같이 내려간다 — 읽는 사람이 손대지 않아도.
  //
  // ★ 예전 구현은 켜져 있어도 **자기를 끄고 있었다.** 고장은 두 겹이었다:
  //
  //   1. `.conversation-scroll` 에 `scroll-behavior: smooth` 가 걸려 있어서
  //      `scrollTop = scrollHeight` 가 매번 **애니메이션**을 시작했다. 토큰이
  //      초당 여러 개 오면 도착하기 전에 다음 애니메이션이 시작되므로 끝까지
  //      가지 못하고 계속 뒤처진다.
  //   2. 그 애니메이션이 스스로 scroll 이벤트를 낸다. 아래 핸들러는 그걸 사람이
  //      올린 것과 구별하지 못했고, 애니메이션 도중에는 아직 바닥이 아니므로
  //      `distanceFromBottom > 72` 가 되어 **따라가기를 꺼버렸다.** 한 번 꺼지면
  //      그 답이 끝날 때까지 안 돌아온다.
  //
  //   3. 스크롤을 만드는 것은 사람만이 아니다. 스크롤 앵커링(overflow-anchor)이
  //      위쪽 높이 변화를 상쇄하려고 scrollTop 을 **직접 옮기고**, 마크다운이
  //      늦게 자리를 잡을 때마다 그 일이 벌어진다. 위치만 보고 판단하면 그것도
  //      전부 "사람이 위로 올렸다"가 된다 — 실측에서 대화를 열자마자 바닥에서
  //      6,417px 떨어진 채 굳어 있었다. 손도 안 댔는데.
  //
  // 그래서 셋을 바꾼다. `instant` 로 즉시 바닥에 붙이고(토큰 속도를 따라갈 수
  // 있는 유일한 방법이다), CSS 로 앵커링을 끄고, 따라가기를 **끄는 것은 최근에
  // 실제 손동작이 있었을 때뿐**으로 좁힌다(휠·터치·키·스크롤바 잡기). 바닥
  // 근처로 돌아오면 이유를 묻지 않고 재개한다.
  useEffect(() => {
    if (!activeJobId) { setElapsed(0); return; }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [activeJobId]);

  // ★ 2026-09-29 밤: 대표 「3.8 은 일할 땐 빠른데 처음에 가만히 있는 시간이 길다」. 재 보니 그 시간은 **모델을
  //   그래픽카드에 올리는 70~90초**였고, 화면은 그동안 「의도와 도구를 고르는 중」이라고만 했다. 기다리는 동안
  //   몇 번 `/health` 의 `resident` 를 묻고, 안 올라와 있으면 **그 사실**을 말한다(추측이 아니라 백엔드가 본 값).
  const [coldModel, setColdModel] = useState(false);
  // 막대가 「다 올라갔다」를 먼저 알면 문구를 바로 거둔다(아래 폴링은 다음 표집 시각까지 기다린다).
  const markModelWarm = useCallback(() => setColdModel(false), []);
  useEffect(() => {
    if (!activeJobId || streaming) { setColdModel(false); return; }
    if (![3, 8, 15, 25, 40, 60, 90].includes(elapsed)) return;
    let alive = true;
    void clientRef.current?.getHealth().then((health) => {
      if (alive && health.ollama?.ok) setColdModel(health.ollama.resident === false);
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [activeJobId, elapsed, streaming]);

  // 사이드바의 소요 시간. **도는 일감이 하나라도 있을 때만** 흐른다 —
  // 끝난 줄의 "42초"는 다시 세어도 42초라서, 가만히 있는 화면이 매초 다시 그릴
  // 이유가 없다(P6: 정지 시 애니메이션 0 과 같은 규율이다).
  const hasLiveJob = jobs.some(isLive);
  useEffect(() => {
    if (!hasLiveJob) return;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [hasLiveJob]);

  /**
   * 컴퓨터 칸이 열려 있는가 — **상태가 아니라 사실에서 나온다.**
   *
   * 일이 돌면 열리고, 끝나면 닫힌다. 따로 기억하지 않는 이유: 열림/닫힘을 상태로
   * 들고 있으면 "일은 끝났는데 칸은 열려 있음" 같은 어긋난 조합이 생기고, 그걸
   * 맞추는 코드가 또 필요해진다. 사람이 접으면 그 판 동안만 닫아 둔다.
   */
  //
  // ★ 끝난 뒤에도 닫지 않는다 (P10, 2026-08-19).
  //
  //   R6 규칙은 "놀 때는 아예 없다"였고 그건 **자리를 미리 차지하지 말라**는 뜻이었다.
  //   그런데 걸음 뷰어가 생기고 나니 같은 규칙이 반대로 물었다 — 일이 끝나는 순간
  //   칸이 닫혀서, 자비스가 **무엇을 보고 그렇게 말했는지** 확인할 방법이 사라진다.
  //   근거는 답이 도착한 **뒤에** 확인하는 것이다. 그래서 마지막 잡을 붙들어 둔다.
  const [lastJobId, setLastJobId] = useState("");
  useEffect(() => { if (activeJobId) setLastJobId(activeJobId); }, [activeJobId]);
  // ★ 2026-10-05 AWS 새 PC 첫 실행: 새 대화를 열었는데 오른쪽 「컴퓨터」 칸에 **앞 대화의 판**(끝났습니다 · 19걸음 · 그때 화면)이
  //   그대로 남아 있었다. 그 칸은 지금 보는 대화의 것이어야 한다 — 대화가 바뀌면 비운다(돌고 있는 판은 그대로 따라온다).
  useEffect(() => { setLastJobId(activeJobRef.current || ""); }, [sessionId]);
  const computerJobId = activeJobId || lastJobId;
  // 작업 창이 보일 모드·폴더 — 바깥 AI 가 맡긴 판이면 그 판의 것(`paneContext`).
  const pane = paneContext(jobs.find((item) => item.id === computerJobId), { mode: workspaceMode, codeWorkspace });
  // ★ 좁은 창(인수인계 H2-C): 컴퓨터 칸은 옆에 설 자리가 없어 대화를 덮는다. 그래서 일이 시작돼도 **저절로 안 열고**,
  //   사람이 「컴퓨터」를 눌렀을 때만 연다. 넓은 창은 지금처럼 저절로 연다.
  const overlayComputer = useNarrow(OVERLAY_MAX_WIDTH);
  const computerOpen = Boolean(computerJobId) && !computerDismissed;
  // 코드 모드의 작업공간은 넓은 창에서는 늘 편다(제품의 절반). 좁은 창에서는 코워크처럼 접고 단추로만 덮어 연다(2026-09-30).
  const paneOpen = workspaceMode === "code" ? !overlayComputer || !computerDismissed : computerOpen;
  // 새 일이 시작되면 접어 둔 뜻은 만료된다 — 다음 일까지 숨기는 것은 아니다.
  useEffect(() => { if (activeJobId) setComputerDismissed(overlayComputer); }, [activeJobId, overlayComputer]);
  // ★ 2026-09-17 대화 창을 반으로 줄였더니 끝난 일의 컴퓨터 칸이 대화를 덮은 채 남았다. 위 규칙은 **새 일이 시작될 때만**
  //   봐서, 일이 끝난 뒤 창을 줄이면 열린 채였다 — 게다가 「컴퓨터」 버튼까지 덮여 닫을 길이 없었다.
  //   좁아지는 순간에도 접는다(넓어지면 다시 연다).
  useEffect(() => { setComputerDismissed(overlayComputer); }, [overlayComputer]);

  // ── 브라우저 무대 모드 (2026-09-24) ─────────────────────────────────────────
  // 온텔릭이 브라우저를 쓰는 동안은 **브라우저가 주인공**이다. 컴퓨터 칸이 넓어지고(약 65%) 대화 목록은 접힌다.
  // 걸음마다 넓어졌다 좁아졌다 하면 정신없다 — 이번 일에서 브라우저를 한 번이라도 쓰면 넓히고, 일이 끝나고 5초 뒤에 되돌린다.
  // 사람이 머리말의 「크게/작게」를 누르면 **이번 일 동안은** 그 뜻을 따른다. 사람이 크롬을 넘겨받은 동안은 접지 않는다.
  const browserInJob = useMemo(
    () => Boolean(activeJobId) && progress.some((row) => row.jobId === activeJobId && /^(browser_|site_|unity_editor_|local_make_slide)/.test(row.tool)),
    [progress, activeJobId],
  );
  // ★ 게임 팩(2026-09-28): 유니티 같은 바깥 앱도 브라우저와 같은 무대로 편다 — 비율·배치가 안 깨지고 사람 입장에서 한눈에 보인다.
  //   유니티 일은 코드 모드에서 하는 일이 많아 그때도 무대를 허락한다.
  const unityInJob = useMemo(
    () => Boolean(activeJobId) && progress.some((row) => row.jobId === activeJobId && row.tool.startsWith("unity_editor_")),
    [progress, activeJobId],
  );
  const [stageHold, setStageHold] = useState(false);
  const [stageOverride, setStageOverride] = useState<boolean | null>(null);
  // ★ 튜토리얼(퀘스트 판 · 2026-10-16 · docs/설계_튜토리얼_퀘스트판_2026-10-16.ko.md). 첫 화면의 「처음 해 볼 것」과 화면을 짚는 말풍선.
  const tutorial = useTutorial({
    english: lang() === "en",
    setDraft,
    focusDraft: () => draftRef.current?.focus(),
    setStage: setStageOverride,
    openReport: () => setReportOpen(true),
  });
  const tutorialRef = useRef(tutorial);
  tutorialRef.current = tutorial;
  const [tierGb, setTierGb] = useState<number | undefined>(undefined);
  const [claudeConnected, setClaudeConnected] = useState(false);
  useEffect(() => {
    if (!setupApi || !tutorial.showBoard) return;
    let alive = true;
    void setupApi.recommendation().then((rec) => { if (alive) setTierGb(rec?.tier_gb || rec?.card?.vram_total_gb || undefined); }).catch(() => null);
    // 퀘스트 ③ 은 클로드가 이어진 PC 에서만 보인다.
    void setupApi.connectScan().then((scan) => {
      if (alive) setClaudeConnected(scan.clients.some((client) => client.id.startsWith("claude") && client.registered === true));
    }).catch(() => null);
    return () => { alive = false; };
  }, [setupApi, tutorial.showBoard]);
  const [browserControl, setBrowserControl] = useState(false);
  // ★ 2026-09-30: 새 일이 시작되면 앞 일이 켜 둔 무대를 **먼저 내린다.** 아래 5초 타이머는 「일이 없을 때」만 돌아서,
  //   앞 일이 끝나고 5초 안에 다음 일이 시작되면(줄 선 일·연달아 보낸 말) 타이머가 취소된 채 무대가 켜진 채로 남았다 —
  //   브라우저를 한 번도 안 쓰는 일까지 무대로 보였다(대표 지적). 이 일이 브라우저를 쓰면 바로 아래 효과가 다시 켠다.
  useEffect(() => {
    if (!activeJobId) return;
    setStageOverride(null);
    setStageHold(false);
  }, [activeJobId]);
  useEffect(() => {
    if (browserInJob) { setStageHold(true); return; }
    if (activeJobId || !stageHold || browserControl) return;
    const timer = window.setTimeout(() => setStageHold(false), 5_000);
    return () => window.clearTimeout(timer);
  }, [browserInJob, activeJobId, stageHold, browserControl]);
  const stageAllowed = (workspaceMode === "cowork" || unityInJob) && computerOpen && !overlayComputer;
  // ★ 2026-09-26: 사람만 열 수 있는 문(로그인·사람 확인·결제) 앞에서 잡은 워커를 놓고 기다린다 — 그 순간 「일 끝」으로 보고
  //   무대를 접으면, 사람이 할 곳이 사라진다. 문이 열려 있는 동안은 무대를 편다.
  const gateOpen = Boolean(attention && HUMAN_GATE_CODES.has(attention.code));
  const stage = stageAllowed && (stageOverride ?? (stageHold || browserControl || gateOpen));
  const takeOverHere = useCallback(() => {
    setStageOverride(null);
    setBrowserControl(true);
    void clientRef.current?.liveControl("take").catch(() => null);
  }, []);
  // 사람 문에서 할 일 — 위 안내 띠와 아래 「이어서」 카드가 같이 쓴다.
  const gateActionButtons = (
    <div className="attention-actions">
      {/* 무대가 있으면 할 곳은 여기다 — 진짜 크롬 창은 이 화면으로 안 될 때의 뒷문. */}
      {stageAllowed && (
        <button type="button" className="attention-show-browser" onClick={takeOverHere}>
          <HandHelping size={14} /> {t("여기서 직접 하기")}
        </button>
      )}
      <button
        type="button"
        className={stageAllowed ? "attention-secondary" : "attention-show-browser"}
        onClick={() => void clientRef.current?.showBrowser().catch(() => null)}
      >
        <Monitor size={14} /> {t("크롬 창 보기")}
      </button>
    </div>
  );
  // ★ 2026-10-02 실사용: Genspark 로그인에서 위 띠와 아래 「이어서」 카드가 같은 말로 두 장 떴다. 같은 판의 사람 문 카드가
  //   떠 있으면 위 띠는 접는다 — 카드 하나에 할 일·버튼·「이어서」가 다 있다. 띠 상태(attention)는 남겨 무대는 그대로 편다.
  const gateCardCoversAttention = Boolean(
    attention && HUMAN_GATE_CODES.has(attention.code) && continuation && !approval
      && gateCodeOf(continuation.reason) && (!attention.job_id || attention.job_id === continuation.job_id),
  );
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // 접힌 대화 목록(74px)을 뺀 나머지의 65%. 대화 칸은 340px 아래로 안 줄인다.
  const stageWidth = Math.max(420, Math.min(Math.round((viewportWidth - 74) * 0.65), viewportWidth - 74 - 340));

  const hasMessages = (history?.messages.length ?? 0) > 0;

  useEffect(() => {
    if (!approval && !continuation) return;
    const frame = window.requestAnimationFrame(() => {
      decisionRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [approval, continuation]);

  const stickToBottom = useCallback(() => {
    const element = scrollRef.current;
    if (!element || !followOutputRef.current) return;
    element.scrollTo({ top: element.scrollHeight, behavior: "instant" });
  }, []);

  const markUserScrolling = useCallback(() => {
    userScrollUntilRef.current = performance.now() + USER_SCROLL_GRACE_MS;
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(stickToBottom);
    return () => window.cancelAnimationFrame(frame);
  }, [history?.messages.length, streaming, progress.length, stickToBottom]);

  // 렌더가 끝난 뒤에도 높이는 더 자란다 — 마크다운 표·코드블록·이미지는 자기
  // 시간표대로 자리를 잡는다. 그 성장은 리액트 렌더가 아니므로 위 훅이 못 본다.
  useEffect(() => {
    const column = columnRef.current;
    if (!column || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => stickToBottom());
    observer.observe(column);
    return () => observer.disconnect();
  }, [stickToBottom, hasMessages]);

  const onConversationScroll = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    followOutputRef.current = nextFollowState({
      following: followOutputRef.current,
      distanceFromBottom: element.scrollHeight - element.scrollTop - element.clientHeight,
      userScrolledRecently: performance.now() < userScrollUntilRef.current,
    });
  }, []);

  const newConversation = () => {
    // 막는 것은 **이 방에서** 판이 도는 동안뿐이다. 다른 방에서 도는 판(바깥 AI 가 맡긴 일 등)은 새 대화를 막지 않는다 —
    // 그 판은 제 방에서 계속 돌고, 새 대화에서 보낸 말은 새 일로 줄에 선다(서버가 맡긴 판을 비켜 세운다).
    if (jobShownHere(activeJobRef.current, sessionRef.current, pendingRef.current, jobsRef.current)) return;
    const next = makeSessionId();
    // ★ 새 대화는 **지금 고른 두뇌**를 이어받는다 (2026-10-26 대표 판: 같은 요청의 방이 13:52 에 둘).
    //   두뇌는 대화마다라 새 대화가 늘 「내 PC 모델」로 시작했다 — Claude 를 고른 채 새 대화에서 보낸 말이 내 PC 모델로 가서
    //   (서버 판 eb3e24b8 · 13:51:51 · 13:52:10 멈춤), 다시 Claude 를 골라 새 방에서 보냈다(13:52:01). 방 둘이 같은 제목으로 남았다.
    if (isClaudeBrain(brain)) saveBrain(next, brain);
    void loadConversation(next);
  };

  // 대화 지우기 — 되돌릴 수 없으니 한 번 묻는다. 지금 보고 있던 대화면 새 대화로 옮긴다.
  const deleteConversation = async (id: string) => {
    const client = clientRef.current;
    if (!client) return;
    const title = sessions.find((row) => row.session_id === id)?.title || t("이 대화");
    if (!window.confirm(t("「{0}」 대화를 지울까요?\n지운 대화는 되돌릴 수 없습니다.", title.slice(0, 40)))) return;
    try {
      await client.deleteConversation(id);
      if (id === sessionId) void loadConversation(makeSessionId());
      await refreshSessions(client);
    } catch (reason) {
      setError(t("대화를 지우지 못했습니다: {0}", reason instanceof Error ? reason.message : String(reason)));
    }
  };

  const onFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    setError("");
    try {
      const selected = Array.from(event.target.files ?? []).slice(0, 6 - attachments.length);
      const rows = await Promise.all(selected.map(readAttachment));
      setAttachments((current) => [...current, ...rows].slice(0, 6));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      event.target.value = "";
    }
  };

  /**
   * 클립보드·드롭으로 들어온 파일을 첨부로 받는다 (2026-08-23).
   *
   * ★ 처음엔 이미지만 받았다. 그래서 스크린샷은 되는데 **파일(pdf·xlsx)이 튕겼고**,
   *   `items` 만 보느라 어떤 판에서는 둘 다 안 됐다. 꺼내는 규칙은
   *   `clipboardFiles.filesFromTransfer` 한 곳에 있고 검사로 지킨다.
   *
   * 종류를 여기서 가리지 않는다 — 첨부가 이미 가린다(32MB·서버 형식 판정).
   * 두 곳에서 가리면 갈리고, 갈린 쪽이 조용히 틀린다.
   *
   * 글자만 붙여넣으면 아무것도 안 한다(`preventDefault` 를 안 부른다).
   */
  const takeFiles = async (data: DataTransfer | null | undefined): Promise<boolean> => {
    const files = roomFor(filesFromTransfer(data), attachments.length);
    if (!files.length) return false;
    setError("");
    try {
      const rows = await Promise.all(files.map(readAttachment));
      setAttachments((current) => [...current, ...rows].slice(0, 6));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
    return true;
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!filesFromTransfer(event.clipboardData).length) return;
    event.preventDefault();
    void takeFiles(event.clipboardData);
  };

  /**
   * 끌어다 놓기. Tauri 는 기본으로 파일 드롭을 **자기가 가로채서** 웹뷰에 안 준다
   * (`dragDropEnabled`). 그래서 이 창에서는 그 값을 꺼 두고 여기서 받는다 —
   * 붙여넣기와 같은 함수로 흘려보낸다.
   */
  const onDrop = (event: DragEvent<HTMLElement>) => {
    if (!filesFromTransfer(event.dataTransfer).length) return;
    event.preventDefault();
    setDragging(false);
    void takeFiles(event.dataTransfer);
  };

  // 답이 나오는 중에도 보낼 수 있다. 백엔드 작업 큐가 원래 직렬이라 지금 보낸 것은
  // 앞의 답을 방해하지 않고 줄을 서고, 앞이 끝나는 즉시 이어서 돈다. 화면이 입력을
  // 잠글 이유가 없었다 — 생각난 질문을 답이 끝날 때까지 들고 있어야 했던 게 이 화면의
  // 가장 답답한 부분이었다.
  const send = async (event?: FormEvent, override?: string, observe = false) => {
    event?.preventDefault();
    // `override` 는 화면이 대신 보내는 말(작업이 끝나 못 전한 덧붙인 말). 그때는 입력창·첨부를 건드리지 않는다.
    const prompt = (override ?? draft).trim();
    const client = clientRef.current;
    if (!prompt || !client) return;
    if (override === undefined) tutorialRef.current.onSent();
    const sending = override === undefined ? attachments : [];
    // 화면·기록에 남는 것 — 원본 바이트는 빼고 미리보기·크기만.
    const files = sending.map(({ data_base64: _data, ...shown }) => shown);
    const outgoing = sending.map(({ size: _size, ...file }) => file);
    const targetSession = sessionId;
    const isFirst = pendingRef.current.length === 0;
    setError("");
    followOutputRef.current = true;
    if (isFirst) {
      setThinking(true);
      setProgress([]);
    setNarration([]);
      setStreaming("");
    }
    // 입력창은 먼저 비운다. 서버 응답을 기다리는 사이 계속 남아 있으면 두 번 보내게 된다.
    if (override === undefined) {
      setDraft("");
      setAttachments([]);
    }
    // 무대에서 크롬을 넘겨받은 채로 새 일을 시키면 그 일이 2분을 기다린다 — 새로 시키는 것이 곧 「돌려준다」는 뜻이다.
    if (browserControl) void client.liveControl("release", "new_task").catch(() => null);
    // ★ 판이 돌고 있으면 **그 판에 덧붙이고**, 말은 「일하는 중」 블록 안 — 그때까지 손자리가 한 말 바로 아래에 둔다
    //   (2026-10-01, 대표: 「훅 밑에 들어가야 되는데 위에 들어가노」). 위쪽 목록에 붙이면 늘 손자리 말보다 위로 가서
    //   무엇에 대한 말인지 순서가 뒤집혀 보였다. 판이 끝나면 서버가 질문 기록의 `steer_notes` 로 남기고 말풍선이 그린다.
    const steerTarget = override === undefined && !sending.length ? activeJobRef.current : "";
    if (steerTarget && pendingRef.current.some((item) => item.jobId === steerTarget && item.sessionId === targetSession)) {
      const youKey = `${steerTarget}:you:${Date.now()}`;
      setNarration((rows) => keepNarration([...rows, { key: youKey, jobId: steerTarget, step: 0, text: prompt, you: true }]));
      try {
        await client.steerJob(steerTarget, prompt);
        return;
      } catch {
        // 이미 끝났거나 멈춰 있다 — 블록에서 거두고 새 작업으로 보낸다.
        setNarration((rows) => rows.filter((row) => row.key !== youKey));
      }
    }
    const localId = -Date.now();
    setHistory((current) => ({
      ...(current ?? { session_id: targetSession, summary: "", has_summary: false, messages: [] }),
      session_id: targetSession,
      messages: [
        ...(current?.messages ?? []),
        {
          id: localId, session_id: targetSession, role: "user", content: prompt,
          kind: "chat", metadata: { attachments: files },
          created_at: Date.now() / 1000,
        },
      ],
    }));
    // ★ 작업이 돌고 있으면 **그 작업에 덧붙인다** (2026-09-26, 사용자: 「클로드 코드 데스크톱처럼 하는 도중에 얘기해도 보고
    //   방향을 조정」). 예전에는 다음 작업으로 줄을 서서, 지금 판은 끝까지 헤맨 뒤에야 그 말을 읽었다. 첨부가 있으면 새 작업이다
    //   (걸음 사이에 파일을 끼울 자리가 없다). 그 사이 끝났으면(409) 아래 원래 길로 새 작업이 된다.
    // ★ await **앞에서** 적어 둔다. `job_queued` 가 POST 응답보다 먼저 도착하므로,
    // 여기가 await 뒤로 가면 그 사건이 이 질문을 남의 것으로 보고 화면에 또 얹는다.
    localSendsRef.current = rememberLocalSend(localSendsRef.current, prompt);
    // ★ 코드 탭에서 일을 보내는 순간, 코드 모델이 작고 이 카드에 더 큰 것이 들어가면 카드를 띄운다(막지 않는다).
    //   판단은 백엔드 규칙(`code_upgrade`) 한 곳 — 고르개의 「코드 일 추천」과 같은 답을 받는다.
    if (workspaceMode === "code" && override === undefined && setupApi && !codeOfferSeen.current.has(targetSession)) {
      codeOfferSeen.current.add(targetSession);
      void setupApi.modelPicker("code").then((view) => {
        if (view.suggestion) setCodeOffer({ sessionId: targetSession, offer: view.suggestion });
      }).catch(() => undefined);
    }
    try {
      const job = await client.sendChat(
        prompt,
        targetSession,
        outgoing,
        "screen",
        // Tells the small HUD window this answer is already on screen here.
        "workspace",
        workspaceMode,
        workspaceMode === "code" ? codeWorkspace.trim() : "",
        "",
        "",
        reasoning,
        observe,
      );
      // 사건이 먼저 도착해 이미 대기열에 들어갔을 수 있다 — 그러면 그대로 둔다.
      if (!pendingRef.current.some((item) => item.jobId === job.id)) {
        syncPending([
          ...pendingRef.current,
          { jobId: job.id, sessionId: targetSession, prompt, files, createdAt: Date.now() / 1000 },
        ]);
      }
    } catch (reason) {
      // 못 보냈으면 쪽지도 거둔다. 남겨 두면 다음에 같은 문장을 물었을 때 그 질문이
      // 화면에서 사라진다 — 남의 것으로 오해받아 얹히지 않는다.
      localSendsRef.current = forgetLocalSend(localSendsRef.current, prompt);
      if (isFirst) setThinking(false);
      // 못 보냈으면 돌려준다. 지운 채로 에러만 띄우면 방금 쓴 문장이 사라지고,
      // 화면에는 아무도 답하지 않을 질문만 남는다.
      setDraft((current) => current || prompt);
      if (override === undefined) setAttachments((current) => (current.length ? current : attachments));
      setHistory((current) => current && ({
        ...current,
        messages: current.messages.filter((message) => message.id !== localId),
      }));
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  // 사건 처리기가 늘 **지금의** send 를 부르게(처리기는 한 번 붙고, send 는 그리는 때마다 새로 만들어진다).
  const sendRef = useRef(send);
  sendRef.current = send;

  const dismissTakeover = () => {
    const id = takeoverOffer?.takeover_id;
    setTakeoverOffer(null);
    setTakeoverBusy(false);
    setTakeoverError("");
    if (id) void clientRef.current?.dismissTakeover(id).catch((reason) => {
      setError(t("이어오기 제안을 닫았지만 기록에 반영하지 못했습니다: {0}", reason instanceof Error ? reason.message : String(reason)));
    });
  };

  /**
   * ★ 진짜 코드 이어받기 (2026-09-20). 백엔드가 따로 만든 가지(worktree)에서 Code 잡을 시작한다.
   *
   * 이 함수가 없어서 `/accept` 문이 UI 에서 한 번도 안 불렸다 — 기계는 다 있는데 갈래가 없었다.
   */
  const continueTakeoverInCode = async () => {
    const offer = takeoverOffer;
    const client = clientRef.current;
    if (!offer || !client || takeoverBusy) return;
    setTakeoverBusy(true);
    setTakeoverError("");
    try {
      const started = await client.acceptCodeTakeover(offer.takeover_id);
      if (started.kind !== "started") {
        // 저장소가 아니거나 가지를 못 팠다 — 무엇이 막혔는지 그대로 보여 준다.
        setTakeoverError(started.answer || t("가지를 만들지 못했습니다"));
        return;
      }
      setTakeoverStage("transfer");
      setTakeoverOffer(null);
      refreshJobs();
    } catch (error) {
      setTakeoverError(error instanceof Error ? error.message : t("이어받기를 시작하지 못했습니다"));
    } finally {
      setTakeoverBusy(false);
    }
  };

  const continueTakeover = async (direction: TakeoverDirection, custom: string) => {
    const offer = takeoverOffer;
    const client = clientRef.current;
    if (!offer || !client || takeoverBusy) return;
    setTakeoverBusy(true);
    setTakeoverError("");
    try {
      const prepared = await client.prepareCoworkTakeover(offer.takeover_id, direction, custom);
      if (!prepared.ok || !prepared.prompt) throw new Error(prepared.error || t("인계문을 만들지 못했습니다"));
      const nextSession = makeSessionId();
      const toolName = prepared.tool_name || offer.card.tool_name || t("다른 도구");
      const visiblePrompt = custom.trim()
        ? t("{0}에서 멈춘 작업을 이어서 해줘. {1}", toolName, custom.trim())
        : t("{0}에서 멈춘 「{1}」을 {2}", toolName, offer.card.title || t("작업"), direction === "review" ? t("먼저 검토해줘") : direction === "tasks" ? t("남은 일로 정리해줘") : t("멈춘 자리부터 이어서 해줘"));
      const origin: HandoffOrigin = {
        tool: prepared.tool || offer.card.tool,
        toolName,
        title: offer.card.title || t("멈춘 작업"),
      };
      const createdAt = Date.now() / 1000;

      // 같은 화면 안에서 대화가 바뀐다는 사실을 먼저 맞춘다. 서버 응답을 기다리면
      // 왼쪽 목록과 가운데 대화가 잠깐 서로 다른 세션을 가리킨다.
      setWorkspaceMode("cowork");
      workspaceModeRef.current = "cowork";
      setSessionId(nextSession);
      sessionRef.current = nextSession;
      setStreaming("");
      setProgress([]);
    setNarration([]);
      setThinking(true);
      setHistory({
        session_id: nextSession, summary: "", has_summary: false, messages: [{
          id: -Date.now(), session_id: nextSession, role: "user", content: visiblePrompt,
          kind: "chat", metadata: { takeover_id: offer.takeover_id, source_tool: origin.tool }, created_at: createdAt,
        }],
      });
      setSessions((current) => [{
        session_id: nextSession,
        title: prepared.title || t("{0}에서 이어온 · {1}", toolName, offer.card.title || t("멈춘 작업")),
        preview: visiblePrompt,
        message_count: 1,
        updated_at: createdAt,
        has_summary: false,
      }, ...current.filter((row) => row.session_id !== nextSession)]);
      setHandoffOrigins((current) => ({ ...current, [nextSession]: origin }));
      setTakeoverStage("transfer");
      followOutputRef.current = true;
      localSendsRef.current = rememberLocalSend(localSendsRef.current, visiblePrompt);
      void client.noteWorkspacePresence(nextSession, "cowork", "").catch(() => undefined);

      const job = await client.sendChat(
        prepared.prompt, nextSession, [], "screen", "workspace", "cowork", "", visiblePrompt,
        prepared.direction ?? direction,
      );
      if (!pendingRef.current.some((item) => item.jobId === job.id)) {
        syncPending([...pendingRef.current, {
          jobId: job.id, sessionId: nextSession, prompt: visiblePrompt, files: [], createdAt,
        }]);
      }
      window.setTimeout(() => {
        setTakeoverOffer((current) => current?.takeover_id === offer.takeover_id ? null : current);
        setTakeoverBusy(false);
      }, 880);
    } catch (reason) {
      setTakeoverBusy(false);
      setTakeoverError(reason instanceof Error ? reason.message : String(reason));
      setTakeoverStage("error");
    }
  };

  const cancel = async () => {
    if (!clientRef.current || !activeJobId) return;
    await clientRef.current.cancelJob(activeJobId);
  };

  // ── 사이드바 예약 줄이 부르는 것 ────────────────────────────────────────

  const cancelSchedule = async (scheduleId: string) => {
    const client = clientRef.current;
    if (!client || !scheduleId) return;
    setError("");
    try {
      await client.cancelSchedule(scheduleId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
    refreshJobs();
  };

  // 말로 시키기. 서버가 켜고 끄기를 판정하고 우리는 그 결과만 받는다 — 화면이 자기
  // 나름의 '지금 듣는 중' 상태를 따로 들고 있으면, 승인 거절이나 만료로 서버가 마이크를
  // 놓아줬을 때 화면만 켜진 채로 남는다(선행 사고: 상태 진실은 한 곳에서만).
  const toggleVoice = async () => {
    const client = clientRef.current;
    if (!client || voiceBusy) return;
    setVoiceBusy(true);
    setError("");
    try {
      await client.togglePtt(sessionRef.current || sessionId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setVoiceBusy(false);
    }
  };

  /** 승인하면서 **앞으로 이런 건 묻지 않게** 한다 (2026-09-21 사장님: 「계속 눌러야 되는 게 귀찮네」).
   *
   *  순서가 중요하다: **먼저 승인**하고 그다음 모드를 바꾼다. 반대로 하면 모드를
   *  바꾸는 사이에 이 승인이 만료될 수 있고, 사람은 「눌렀는데 안 됐다」를 본다.
   *  모드 바꾸기가 실패해도 승인은 이미 지나갔으므로 일은 계속된다 — 말만 해 준다. */
  const approveAndRelax = async () => {
    const client = clientRef.current;
    const nonce = approval?.nonce;
    if (!client || !nonce || decisionBusy) return;
    setDecisionBusy(true);
    try {
      await client.decideApproval(nonce, true);
      setApproval(null);
      setApprovalPreview(null);
      const done = await client.setPermissionMode("reversible");
      if (done.ok) setPermissionModes(done);
      else setError(t("승인은 됐는데 권한을 못 바꿨습니다 — {0}", done.error ?? t("알 수 없는 이유")));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDecisionBusy(false);
    }
  };

  const decideApproval = async (approve: boolean, answer?: string) => {
    const client = clientRef.current;
    const nonce = approval?.nonce;
    if (!client || !nonce || decisionBusy) return;
    setDecisionBusy(true);
    try {
      await client.decideApproval(nonce, approve, answer);
      setApproval(null);
      setApprovalPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDecisionBusy(false);
    }
  };

  const decideContinuation = async (action: "extend_3m" | "continue_task" | "finish") => {
    const client = clientRef.current;
    const jobId = continuation?.job_id;
    if (!client || !jobId || decisionBusy) return;
    setDecisionBusy(true);
    try {
      await client.continueAgent(jobId, action);
      setContinuation(null);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      if (
        message.includes("agent_checkpoint_not_found_or_expired")
        || message.includes("agent_job_not_waiting_continuation")
      ) {
        // 이미 끝난 카드다. 서버 오류처럼 빨갛게 남기지 말고 화면 상태를 서버와
        // 다시 맞춘다.
        setContinuation(null);
        setError("");
        refreshJobs();
      } else {
        setError(message);
      }
    } finally {
      setDecisionBusy(false);
    }
  };

  const connectGoogle = async () => {
    const client = clientRef.current;
    // 연결돼 있어도 권한이 모자라면 다시 받는다 — 권한을 더한 날 이 줄이
    // 재승인을 통째로 막고 있었다.
    if (!client || googleBusy) return;
    if (googleStatus?.connected && !googleStatus?.scope_mismatch) return;
    setGoogleBusy(true);
    setError("");
    try {
      const started = await client.startGoogleOAuth();
      if (!started.opened_browser) throw new Error(t("Google 로그인 브라우저를 열지 못했습니다."));
      for (let attempt = 0; attempt < 450; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const status = await client.getGoogleStatus(attempt % 5 === 4);
        setGoogleStatus(status);
        if (status.connected) return;
        if (status.last_error) throw new Error(status.last_error);
      }
      throw new Error(t("Google 로그인 대기 시간이 지났습니다. 다시 연결해 주세요."));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setGoogleBusy(false);
    }
  };

  const searchableMemoryCount = history?.searchable_memory_count ?? 0;
  const contextLabel = retrievalEnabled && searchableMemoryCount > 0
    ? t("최근 대화 + 누적 요약 · 과거 기억 {0}개 검색 가능", searchableMemoryCount)
    : history?.has_summary
      ? t("이전 대화를 요약해 맥락을 최적화했습니다")
      : t("{0}개 메시지를 현재 맥락으로 사용 중", history?.messages.length ?? 0);
  const selectedPilotModel = pilotModel(pilotModelId);
  // 이 대화의 두뇌가 Claude Agent 인가 — 갈래가 있을 때만(파일럿 · 브라우저 미리보기는 늘 내 PC 모델).
  const claudeBrain = Boolean(claudeLane) && isClaudeBrain(brain);
  const claudeChoice: ClaudeChoice | undefined = claudeLane ? {
    brain,
    status: claudeStatus,
    onPick: (next) => {
      saveBrain(sessionId, next);
      setBrainState(next);
    },
    onKeyIn: async () => {
      const out = await claudeLane.runner.keyFromClipboard().catch((reason) => ({ ok: false, error: String(reason) }));
      setClaudeStatus(await claudeLane.runner.status().catch(() => null));
      return out.ok ? "" : apiKeyErrorText(out.error);
    },
    onOpen: () => { void claudeLane.runner.status().then(setClaudeStatus).catch(() => undefined); },
  } : undefined;
  const activeModel = pilotMode ? selectedPilotModel.label : workspaceMode === "code"
    ? modelRoles.code || modelRoles.chat || ""
    : modelRoles.chat || "";
  // ★ **머리의 컨텍스트는 실제로 올라간 값이다** (2026-09-21 사장님 지적).
  //
  //   예전엔 `modelContexts.code || 102_400` 이었다. 뒤엣것은 함수 안 하드 상수고,
  //   앞엣것은 백엔드가 내보내던 **덮어쓰기 원본**이었다. 그래서 설정을 131072 로
  //   고친 뒤에도 머리에는 계속 100K 가 떴다.
  //
  //   순서: ① Ollama 가 말한 실제 값 → ② 백엔드가 계산한 실효값 → ③ 대화 창 크기.
  //   추측으로 채우는 칸은 두지 않는다 — 모르면 위 칸이 비고, 그러면 아래로 내려간다.
  const residentModel = (agentGrade?.model || "").toLowerCase().replace(/:latest$/, "");
  const activeBare = (activeModel || "").toLowerCase().replace(/:latest$/, "");
  const measuredContext = residentModel && residentModel === activeBare ? liveContextLength : 0;
  const activeContext = pilotMode ? selectedPilotModel.context : (workspaceMode === "code"
    ? measuredContext || modelContexts.code || modelContexts.chat || contextWindow
    : measuredContext || history?.context_window || contextWindow);
  const activeContextLabel = activeContext >= 1_000_000 ? "1M" : `${Math.round(activeContext / 1024)}K`;
  const currentTitle = sessions.find((row) => row.session_id === sessionId)?.title || t("새 대화");
  // 가운데 대화 칸과 입력창은 **이 방의 판**만 본다(`jobShownHere`). 오른쪽 작업 창은 지금까지처럼 도는 판을 따라간다.
  const hereJobId = jobShownHere(activeJobId, sessionId, pending, jobs);
  const activityVisible = thinking || progress.length > 0 || Boolean(activeJobId);
  const elapsedLabel = elapsed >= 60 ? t("{0}분 {1}초", Math.floor(elapsed / 60), elapsed % 60) : t("{0}초", elapsed);
  const renderedMessages = history?.messages ?? [];
  // 오른쪽 판의 「확인 안 됨」 줄 — 마지막 답에 붙어 온 것. 일하는 중에는 아직 답이 없으니 비운다.
  const lastAnswerText = [...renderedMessages].reverse().find((message) => message.role === "assistant")?.content ?? "";
  // 오른쪽 판의 「열지 않은 곳 N줄」 — 이 창이 지켜본 판이면 끝 검사 알림에서, 아니면 대화 기록의 그 판 답 메타데이터에서.
  const paneUnopened = useMemo(
    () => trajectories[computerJobId]?.unopened ?? unopenedRowsForJob(renderedMessages, computerJobId),
    [trajectories, computerJobId, renderedMessages],
  );
  const paneChecks = useMemo(
    () => (hasLiveJob || activeJobId ? [] : withoutUnopenedCheck(splitAnswerChecks(lastAnswerText).checks, paneUnopened)),
    [lastAnswerText, hasLiveJob, activeJobId, paneUnopened],
  );
  // 대화와 궤적을 한 축으로. 지금 보고 있는 대화의 것만 꿴다.
  const timeline = buildTimeline(
    renderedMessages,
    Object.values(trajectories).filter((row) => row.sessionId === sessionId),
  );
  // 맨 앞은 지금 답하고 있는 것이므로 "기다리는" 축에 넣지 않는다.
  const queuedCount = Math.max(0, pending.length - 1);
  // 출처 도장의 「찾아보고 다시 답하기」 — 그 답 바로 앞의 사용자 질문을, 이번엔 보고 오라는 표시를 달아 다시 보낸다.
  const observeAgain = (message: ConversationMessage) => {
    const at = renderedMessages.findIndex((row) => row.id === message.id);
    const asked = renderedMessages.slice(0, at < 0 ? renderedMessages.length : at).reverse()
      .find((row) => row.role === "user");
    if (asked?.content) void send(undefined, asked.content, true);
  };
  // 끝내지 못한 판 아래 「이어서 하기」 — 사람이 「이어서 해줘」라고 치는 것과 같다. 대화의 마지막 말에만 붙인다.
  const lastMessageId = renderedMessages.length ? renderedMessages[renderedMessages.length - 1].id : undefined;
  const continueUnfinished = () => { void send(undefined, t("이어서 해줘")); };
  // ★ 지난 말에 넘기는 함수는 **그릴 때마다 새 함수가 아니어야** 한다 (2026-10-07). 새 함수면 지난 말 전부가 「바뀌었다」로 읽혀
  //   입력 한 글자·답 한 토큰·1초 시계마다 통째로 다시 그려졌다(메시지 80개에서 글자 하나에 135ms). 부르면 늘 최신 것을 부른다.
  const observeAgainStable = useStableCallback(observeAgain);
  const continueUnfinishedStable = useStableCallback(continueUnfinished);
  // 답이 기댄 페이지의 사진(2026-10-18). 한 번만 만든다 — 판 결과 · 사진을 안에서 잡아 두고, 말 칸(memo)이 다시 그려지지 않게.
  const showcaseSource = useMemo(() => createShowcaseSource(() => clientRef.current, (url) => void openExternalUrl(url)), []);

  return (
    <main className={`jarvis-workspace mode-${workspaceMode}${stage ? " stage-browser" : ""}`}>
      <Sidebar
        open={sidebarOpen && !stage}
        onToggle={() => setSidebarOpen((value) => !value)}
        mode={workspaceMode}
        onModeChange={setWorkspaceMode}
        state={state}
        sessions={sessions}
        sessionId={sessionId}
        connected={connected}
        busy={Boolean(hereJobId)}
        client={clientRef.current}
        jobs={jobs}
        schedules={schedules}
        now={now}
        onNewConversation={newConversation}
        onOpenConversation={(id) => void loadConversation(id)}
        onDeleteConversation={pilotMode ? undefined : (id) => void deleteConversation(id)}
        onCancelSchedule={(id) => void cancelSchedule(id)}
        onOpenCapabilities={() => setCapabilitiesOpen(true)}
        onOpenSettings={pilotMode ? undefined : () => setSettingsOpen(true)}
        privacyText={pilotMode ? t("요청한 내용은 Claude API로 전송됩니다") : undefined}
        handoffOrigins={handoffOrigins}
      />

      <section className={`workspace-main${takeoverStage === "transfer" && takeoverOffer ? " relay-transition" : ""}`}>
        <HealthBar client={clientRef.current} />
        <UpdateBar client={clientRef.current} />
        <WhatsNewBar client={clientRef.current} />
        <PilotAuthBar enabled={pilotMode} />
        <header className="workspace-header">
          <div className="workspace-heading">
            <h2>{currentTitle}</h2>
            {workspaceMode === "code" && (
              <div className="code-workspace-field" title={t("허용된 로컬 폴더만 열 수 있습니다")}>
                <button
                  type="button"
                  className="code-workspace-picker"
                  onClick={() => void chooseCodeWorkspace()}
                  disabled={workspacePickerOpen}
                  aria-label={t("Windows 폴더 선택창 열기")}
                  title={t("폴더 찾아보기")}
                >
                  {workspacePickerOpen ? <Loader2 className="spin" size={14} /> : <FolderOpen size={14} />}
                </button>
                <input
                  value={codeWorkspace}
                  onChange={(event) => setCodeWorkspace(event.target.value)}
                  placeholder={t("비워두면 대화에서 프로젝트를 찾아요")}
                  spellCheck={false}
                />
                <button
                  type="button"
                  className="code-workspace-browse"
                  onClick={() => void chooseCodeWorkspace()}
                  disabled={workspacePickerOpen}
                >
                  {t("찾아보기")}
                </button>
              </div>
            )}
          </div>
          <div className="workspace-status">
            {/* 화면을 다시 부르는 자리. **볼 것이 있을 때만** 나타난다 —
                아무것도 없을 때 회색 버튼을 두면 눌러도 아무 일이 없다. */}
            {((workspaceMode === "cowork" && Boolean(computerJobId)) || (workspaceMode === "code" && overlayComputer)) && (
              <button
                type="button"
                className={`screen-chip ${paneOpen ? "on" : ""}`}
                onClick={() => setComputerDismissed((value) => !value)}
                aria-pressed={paneOpen}
              >
                {workspaceMode === "code" ? <><Code2 size={13} /> {t("작업공간")}</> : <><Monitor size={13} /> {t("컴퓨터")}</>}
              </button>
            )}
            {/* 상태는 왼쪽 위 표식이 말한다(JarvisMark). 여기서 또 말하면 같은 것을
                두 군데서 말하는 것이고, 그러면 둘 다 안 읽힌다.
                「깊게 판단 중」만 남긴다 — 이건 상태가 아니라 **이번 답에만 붙는
                성질**이라 표식이 담을 수 없다. */}
            {thinking && <span className="thinking"><Brain size={13} /> {t("깊게 판단 중")}</span>}
            {/* 맥락 설명은 여기 툴팁으로 들어왔다. 우측 레일에 같은 말을 하는 카드가
                따로 있었는데, 한 화면에서 같은 사실을 두 번 말하면 둘 다 안 읽힌다. */}
            {pilotMode ? (
              <PilotModelPicker
                value={pilotModelId}
                onChange={(model) => {
                  savePilotModel(model);
                  setPilotModelId(model);
                }}
              />
            ) : (
              /* 모델 이름은 글씨가 아니라 **버튼**이다 (2026-09-21). Code 탭에서 누르면
                 코드 모델만, 대화 탭에서 누르면 대화 모델만 바뀐다 — 역할이 섞이면
                 코드 모델을 고르려다 대화 모델까지 갈아탄다. */
              <LocalModelPicker
                api={setupApi}
                role={workspaceMode === "code" ? "code" : "chat"}
                label={activeModel ? `${displayModelName(activeModel)} · ${activeContextLabel}` : ""}
                context={claudeBrain ? t("이 대화는 Claude Agent 가 일합니다 · 내 API 키") : workspaceMode === "code" ? t("{0} · 코드 작업 전용", activeModel) : contextLabel}
                onChanged={() => window.dispatchEvent(new Event("ontelic:model-changed"))}
                claude={claudeChoice}
              />
            )}
          </div>
        </header>

        <div
          className="conversation-scroll"
          ref={scrollRef}
          onScroll={onConversationScroll}
          // 사람이 스크롤에 손을 대는 통로 전부. 휠·터치·스크롤바 잡기·키보드.
          onWheel={markUserScrolling}
          onTouchMove={markUserScrolling}
          onPointerDown={markUserScrolling}
          onKeyDown={markUserScrolling}
        >
          {renderedMessages.length === 0 ? (
            <Welcome onSuggestion={setDraft} mode={workspaceMode} codeWorkspace={codeWorkspace} codeModel={activeModel}
              quests={workspaceMode === "cowork" && tutorial.showBoard ? (
                <QuestBoard state={tutorial.quests} tierGb={tierGb} english={lang() === "en"} claudeConnected={claudeConnected}
                  onStart={tutorial.start} onDismiss={tutorial.dismiss} onCardSeen={tutorial.cardSeen} />
              ) : null}
              receipt={workspaceMode === "cowork" && !pilotMode ? <ReceiptCard client={clientRef.current} connected={connected} /> : null} />
          ) : (
            <div className="message-column has-spine" ref={columnRef}>
              {timeline.map((entry) => (entry.kind === "message"
                ? <MessageView key={`m${entry.message.id}`} message={entry.message} onObserveAgain={observeAgainStable}
                    onContinue={entry.message.id === lastMessageId && pending.length === 0 ? continueUnfinishedStable : undefined}
                    showcase={showcaseSource} />
                : (
                  <TrajectoryNode
                    key={`t${entry.trajectory.jobId}`}
                    trajectory={entry.trajectory}
                    outputs={outputs[entry.trajectory.jobId]}
                    undo={undoOffers.filter((row) => row.job_id === entry.trajectory.jobId)}
                    onLoadOutputs={loadOutputs}
                    onOpenOutput={(jobId, output) => void openOutput(jobId, output)}
                    onPreviewOutput={previewOutput}
                    onUndo={(undoId) => void runUndo(undoId)}
                  />
                )))}
              <AnimatePresence>
                {(streaming || thinking) && (hereJobId || settlingJobId) && (
                  <motion.article className="workspace-message message-assistant streaming-message" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                    {/* Claude Agent 판이면 이름 · 표식도 그쪽 것(주황 점 · 공식 로고는 안 씀). 손자리가 맡아 하는 걸음은 오른쪽 칸에 보인다. */}
                    {claudeLane?.owns(hereJobId || settlingJobId) ? (
                      <div className="message-avatar"><span className="brain-dot claude message-claude-mark" aria-hidden /></div>
                    ) : (
                      <div className="message-avatar"><JarvisMark state="working" connected size={18} /></div>
                    )}
                    <div className="message-body">
                      <div className="message-meta"><strong>{claudeLane?.owns(hereJobId || settlingJobId) && isClaudeBrain(brain) ? claudeButtonLabel(brain) : "Sonjari"}</strong><span>{t("지금")}</span></div>
                      {/* 젬마의 사고도 여기서 보인다 (2026-08-30).
                          ★ 서버는 처음부터 두 역할 모두의 사고를 흘리고 있었다 —
                            `flush_thinking()` 은 model_role 을 안 가리고, 한국어
                            번역기(`thinking_ko`)도 마찬가지다. 그런데 **그리는 곳이
                            코드 작업공간에만 있었다.** 그래서 코워크에서는 젬마가
                            몇 분을 생각해도 화면에는 고정 문구 한 줄뿐이었고,
                            정찰기가 번역한 한국어는 만들어지자마자 버려졌다.
                            상한이 여러 곳에 있으면 낮은 쪽만 일한다는 그 사고와
                            같은 모양이다 — 여기서는 「그리는 곳」이 낮은 쪽이었다.
                          코드 모드에서는 오른쪽 칸이 이미 같은 것을 그린다.
                          두 곳에 겹쳐 두면 같은 글이 화면에 두 번 흐른다. */}
                      {workspaceMode !== "code" && (
                        <ThinkingTrace text={thinkingText} ko={thinkingKo} live={Boolean(hereJobId)} client={clientRef.current} mode={workspaceMode} translate={!claudeLane?.owns(hereJobId || settlingJobId)} />
                      )}
                      {/* 일하면서 한 말. 답이 아니라 **하는 말**이라 다른 칸에 둔다 —
                          섞으면 「했다」는 말이 결과로 읽힌다(실측에서 안 한 일을
                          했다고 적은 판이 있었다). */}
                      {narration.filter((row) => row.jobId === (hereJobId || settlingJobId)).map((row) => (row.you ? (
                        <p className="workspace-narration is-you" key={row.key}>
                          <span className="workspace-narration-you">{userLabel()}</span>
                          {row.text}
                        </p>
                      ) : (
                        <p className={`workspace-narration${row.fold ? " is-fold" : ""}`} key={row.key}>
                          {row.fold
                            ? <span className="workspace-narration-step is-fold" aria-label={t("접음")}><ChevronsDownUp size={11} /></span>
                            : <span className="workspace-narration-step">{row.step}</span>}
                          {row.text}
                        </p>
                      )))}
                      {/* 지금 읽는 그림 조각 — **말 줄 바로 아래**에 둔다 (2026-10-10 대표). 처음엔 「일하는 중」 상자 안에 넣었는데,
                          말이 쌓이면 화면이 아래를 따라가 그 상자는 위로 밀려 안 보인다. 눈이 가 있는 자리가 여기다
                          (사람에게 묻는 카드를 입력칸 위로 내린 것과 같은 까닭). */}
                      {looking[hereJobId || settlingJobId] && <LookingAt looking={looking[hereJobId || settlingJobId]} />}
                      {streaming ? <MarkdownView className="workspace-markdown">{streaming}</MarkdownView> : (
                        /* 점만 먼저 둔다. 무엇을 하는 중인지는 3초를 넘길 때만 말한다 —
                           0.3초에 답이 나와도 "판단하고 있습니다"가 뜨면 그건 거짓말이다. */
                        elapsed >= 3 && coldModel
                          ? <ModelLoadLine client={clientRef.current} onResident={markModelWarm} />
                          // 그림을 읽는 중이면 이 줄을 내지 않는다 — 「도구를 고르는 중」은 그 순간 틀린 말이고, 위의 그림이 이미 무엇을 하는지 말한다.
                          : looking[hereJobId || settlingJobId] ? null
                          : <div className="workspace-thinking"><span />{elapsed >= 3 && <p>{modelWait[hereJobId || settlingJobId] || liveText(live[hereJobId || settlingJobId]) || t("질문의 의도와 필요한 도구를 고르는 중입니다.")}</p>}</div>
                      )}
                    </div>
                  </motion.article>
                )}
              </AnimatePresence>
              {/* ★ 사람에게 묻는 카드는 **「일하는 중」 아래** — 입력칸 바로 위에 둔다 (2026-10-01 AWS, 대표). 위에 두었더니
                  모델 생각이 아래로 계속 흘러 「막혔습니다」 카드가 뜬 줄도 몰랐다. 눈이 가 있는 자리가 입력칸이다. */}
              {approval && approval.tool_name === ASK_USER_TOOL && (
                <QuestionCard
                  approval={approval}
                  busy={decisionBusy}
                  cardRef={decisionRef}
                  onAnswer={(answer) => void decideApproval(true, answer)}
                  onStop={() => void decideApproval(false)}
                />
              )}
              {approval && approval.tool_name !== ASK_USER_TOOL && (
                <ApprovalCard
                  approval={approval}
                  preview={approvalPreview}
                  busy={decisionBusy}
                  cardRef={decisionRef}
                  caution={modelCaution(agentGrade)}
                  alwaysAsk={permissionModes?.always_ask}
                  onDecide={(ok) => void decideApproval(ok)}
                  onApproveAndRelax={permissionModes && permissionModes.mode === "ask"
                    ? () => void approveAndRelax()
                    : undefined}
                />
              )}
              {!approval && continuation && (
                <ContinuationCard
                  continuation={continuation}
                  busy={decisionBusy}
                  cardRef={decisionRef}
                  onDecide={(action) => void decideContinuation(action)}
                  gateActions={gateCodeOf(continuation.reason) ? gateActionButtons : undefined}
                />
              )}
            </div>
          )}
        </div>

        <footer className="workspace-composer-shell">
          <ReadinessBanner client={clientRef.current} connected={connected} />
          {setupApi && codeOffer && codeOffer.sessionId === sessionId && workspaceMode === "code" && (
            <CodeUpgradeCard api={setupApi} offer={codeOffer.offer} onClose={() => setCodeOffer(null)}
              onChanged={() => window.dispatchEvent(new Event("ontelic:model-changed"))} />
          )}
          {/* 브라우저가 사람을 기다리며 멈춘 순간. 진행 상황 목록에 한 줄로 섞으면
              지나간다 — 이건 사용자가 뭔가 해주셔야 진행되는 유일한 종류의 사건이다. */}
          {attention && !gateCardCoversAttention && (
            <div className="attention-banner" role="alert">
              <span className="attention-banner-icon"><HandHelping size={16} /></span>
              <div>
                <strong>{attention.title}</strong>
                <p>{attention.message}</p>
                {attention.url && <small title={attention.url}>{gateSiteLabel(attention.url)}</small>}
                {HUMAN_GATE_CODES.has(attention.code) && gateActionButtons}
              </div>
              <button type="button" onClick={() => setAttention(null)} aria-label={t("확인했습니다")}><X size={14} /></button>
            </div>
          )}
          {/* 디스코드로 말을 건 새 사람(가족 · 동료 추가) — 받을지 여기서 바로 고른다. 접으면 설정 › 디스코드에 남는다. */}
          {!pilotMode && <DiscordRequestBanner client={clientRef.current} connected={connected} />}
          {/* 자동 승인 — 무엇이 지나갔는지 한 줄. 되돌리기는 작업 기록(오른쪽 칸)의 그 걸음에 붙어 있다. */}
          {autoApproved && (
            <div className="auto-approved-banner" role="status">
              <span className="auto-approved-icon"><ShieldCheck size={15} /></span>
              <div>
                <strong>{t("자동으로 진행했습니다 ·")} {toolLabel(autoApproved.tool)}</strong>
                <p>{t("되돌릴 수 있는 일이라 묻지 않았습니다. 설정 › 권한에서 끌 수 있습니다.")}</p>
              </div>
              <button type="button" onClick={() => setAutoApproved(null)} aria-label={t("확인했습니다")}><X size={14} /></button>
            </div>
          )}
          {attachments.length > 0 && (
            <div className="attachment-row">
              {attachments.map((file, index) => (
                <span key={`${file.name}-${index}`} className={file.thumbnail ? "has-thumb" : ""} title={file.name}>
                  {file.thumbnail
                    ? <img className="attachment-thumb" src={file.thumbnail} alt="" draggable={false} />
                    : file.mime_type.startsWith("image/") ? <Image size={13} /> : <b className="attachment-badge">{fileBadge(file.name, file.mime_type)}</b>}
                  <span className="attachment-name">{file.name}</span>
                  <button type="button" onClick={() => setAttachments((rows) => rows.filter((item) => item !== file))} aria-label={t("{0} 빼기", file.name)}><X size={12} /></button>
                </span>
              ))}
            </div>
          )}
          <form
            className={`workspace-composer${dragging ? " dragging" : ""}`}
            onDragOver={(event) => { if (event.dataTransfer?.types?.includes("Files")) { event.preventDefault(); setDragging(true); } }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop} onSubmit={send}>
            {/* 맞춤법 밑줄을 끈다(2026-10-13) — 가게 이름 · 제품 이름 · 조사마다 빨간 줄이 그어져 시킨 말이 틀린 글처럼 보였다. */}
            <textarea ref={draftRef} value={draft} spellCheck={false} onPaste={onPaste} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }} placeholder={hereJobId
              ? t("일하는 중에 덧붙일 말을 적으면 다음 걸음부터 반영합니다")
              : workspaceMode === "code"
                ? t("프로젝트 이름과 작업을 말하면 저장소부터 찾아 읽습니다")
                : t("Sonjari에게 메시지를 보내거나 파일을 맡겨보세요")} rows={1} />
            <div className="composer-actions">
              <input ref={fileRef} type="file" multiple hidden accept="image/*,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.epub,.rtf,.txt,.md,.csv,.tsv,.json,.jsonl,.log,.py,.js,.ts,.tsx,.html,.css,.yaml,.yml,.xml" onChange={onFiles} />
              {/* 작성칸 밑에 늘 떠 있던 「PDF · Office · 문서 · 이미지, 최대 6개/각 32MB」를
                  지우면서 그 사실을 여기로 옮겼다. 정보를 없앨 때는 갈 곳을 먼저
                  만든다 — 안 그러면 지운 게 아니라 잃은 것이다. */}
              <button
                type="button"
                className="attach-button"
                onClick={() => fileRef.current?.click()}
                disabled={attachments.length >= 6}
                title={attachments.length >= 6
                  ? t("첨부는 6개까지입니다")
                  : t("파일 첨부 — PDF · Office · 문서 · 이미지, 6개까지 각 32MB")}
                aria-label={t("파일 첨부")}
              ><Paperclip size={17} /></button>
              {/* 여기까지 마이크가 없어서, 말로 시키려면 F9를 누르거나 우측 하단
                  오브를 찾아 눌러야 했다. 켜짐 여부는 서버 상태(listening)를 그대로
                  비춘다 — 화면이 따로 기억하지 않는다. */}
              <button
                type="button"
                className={`mic-button ${state === "listening" ? "listening" : ""}`}
                onClick={() => void toggleVoice()}
                disabled={workspaceMode === "code" || !connected || voiceBusy || state === "transcribing"}
                title={state === "listening" ? t("듣는 중 — 눌러서 마치기 (F9)") : t("말로 시키기 (F9)")}
                aria-label={state === "listening" ? t("음성 입력 마치기") : t("음성 입력 시작")}
                aria-pressed={state === "listening"}
              >
                {state === "transcribing" ? <Loader2 size={17} className="spin" /> : <Mic size={17} />}
              </button>
              <VoiceMeter client={clientRef.current} active={state === "listening"} />
              {/* 추론 — 이번 일을 얼마나 깊게 생각할지(2026-09-28). 기본은 자동(보통으로 시작해 막히면 깊게). */}
              <ReasoningPicker
                value={reasoning}
                disabled={!connected}
                onChoose={(choice) => { setReasoning(choice); saveReasoningChoice(choice); }}
              />
              {/* 권한 모드 — 클로드처럼 입력창 옆에서 바로 고른다(2026-09-23). 서버에 못 물어봤으면
                  단추를 안 띄운다: 모르는 것을 아는 척 그리지 않는다. */}
              {permissionModes && (
                <PermissionModePicker
                  modes={permissionModes}
                  disabled={!connected}
                  onChoose={async (mode) => {
                    const client = clientRef.current;
                    if (!client) throw new Error(t("Sonjari에 연결되지 않았습니다"));
                    const done = await client.setPermissionMode(mode);
                    if (!done.ok) throw new Error(done.error ?? t("알 수 없는 이유"));
                    setPermissionModes(done);
                    window.dispatchEvent(new Event("ontelic:permissions-changed"));
                    return done;
                  }}
                />
              )}
              {/* 늘 떠 있던 안내 두 줄(「인덱싱 → 계획 → 패치 → 실행 검증」,
                  「PDF · Office · 문서 · 이미지…」)을 지웠다. 매번 같은 말이라
                  두 번째부터는 아무도 안 읽고, 자리만 차지한다. 첨부 규격은
                  클립 단추의 title 에 있고, 코드 모드 절차는 첫 화면(Welcome)에서
                  한 번 말한다. **지금 달라진 것만** 여기 남긴다. */}
              {queuedCount > 0 && <span>{t("질문")} {queuedCount}{t("개가 차례를 기다리는 중")}</span>}
              {/* 보내기와 중지가 함께 있어야 한다. 답이 나오는 동안 하나만 고를 수
                  있게 만들면, 다음 질문을 보내려고 지금 답을 멈추게 된다. */}
              {hereJobId && <button type="button" className="stop-button" onClick={() => void cancel()} title={t("지금 답변 중지")}><Square size={14} fill="currentColor" /></button>}
              <button type="submit" className="send-button" disabled={!draft.trim()} title={hereJobId ? t("지금 작업에 덧붙이기") : t("보내기")}><Send size={16} /></button>
            </div>
          </form>
          {error && <p className={isFailureNotice(error) ? "workspace-error is-notice" : "workspace-error"} role="status">{error}</p>}
          {/* ★ 2026-09-23 스토어 정책 11.16(생성형 AI): 사용자가 부적절한 결과를 개발자에게 알릴 수단이 있어야 한다. */}
          <small className="privacy-note">
            {claudeBrain
              ? (workspaceMode === "code"
                  ? t("Claude Agent 가 이 폴더의 파일을 직접 읽고 고칩니다 · 읽은 내용은 클로드 API 로 갑니다")
                  : t("클로드에게는 대화와 손자리가 돌려준 결과만 갑니다 · 페이지 원문은 이 PC에 남습니다"))
              : t("Sonjari는 실수할 수 있습니다. 중요한 결정은 근거와 원문을 함께 확인하세요.")}{" "}
            {/* 2026-09-29: 메일 창 대신 앱 안에서 — 보낼 내용을 보여 주고 동의받은 뒤 보낸다(ProblemReportDialog). */}
            <button type="button" className="privacy-note-link" onClick={() => setReportOpen(true)}>{t("문제 보내기")}</button>
          </small>
        </footer>
        {reportOpen && (
          <ProblemReportDialog api={clientRef.current ?? null} jobId={activeJobId || undefined} onClose={() => setReportOpen(false)} />
        )}
      </section>

      {/* 오른쪽 칸은 **에이전트가 일하는 화면**이다(R6). 놀 때는 폭 0 으로 접혀
          대화가 화면을 다 쓴다 — 자리를 미리 차지하지 않는다. */}
      {takeoverOffer ? (
        <TakeoverRelay
          offer={takeoverOffer}
          stage={takeoverStage}
          busy={takeoverBusy}
          error={takeoverError}
          caution={modelCaution(agentGrade)}
          onContinue={(direction, custom) => void continueTakeover(direction, custom)}
          onContinueInCode={() => void continueTakeoverInCode()}
          onDismiss={dismissTakeover}
        />
      ) : (
        <ComputerPane
          client={clientRef.current}
          open={paneOpen}
          mode={pane.mode}
          frameMode={workspaceMode}
          codeWorkspace={pane.codeWorkspace}
          live={hasLiveJob || Boolean(activeJobId)}
          jobId={computerJobId}
          progress={progress}
          plan={computerJobId ? trajectories[computerJobId]?.plan ?? [] : []}
          checks={paneChecks}
          unopened={paneUnopened}
          elapsedLabel={elapsedLabel}
          thinkingText={thinkingText}
          thinkingKo={thinkingKo}
          approvalActionId={String(approval?.arguments?.action_id ?? "")}
          onApprove={(approve) => void decideApproval(approve)}
          onCancel={() => void cancel()}
          onCodeFeedback={(prompt) => {
            setDraft((current) => current.trim() ? `${current.trim()}\n\n${prompt}` : prompt);
            draftRef.current?.focus();
          }}
          // ★ 2026-10-01 베타 테스터: 「이 창도 아예 닫을 수 있게 하면 좋을 듯」. 닫기는 좁은 창(덮어 뜰 때)에만 있었고,
          //   넓은 창에서는 위의 「컴퓨터」 단추를 다시 눌러야 접혔다 — 그 단추를 못 찾았다. 코워크는 넓은 창에서도 X 를 준다
          //   (다시 열기는 「컴퓨터」 단추, 새 일이 시작되면 저절로 다시 열린다). 넓은 창의 코드 작업공간은 제품의 절반이라 그대로.
          onClose={workspaceMode === "cowork" || overlayComputer ? () => setComputerDismissed(true) : undefined}
          stage={stage}
          stageWidth={stageWidth}
          onStageToggle={stageAllowed ? () => setStageOverride(!stage) : undefined}
          onControlChange={setBrowserControl}
          deck={computerJobId ? decks[computerJobId] : undefined}
          handoffs={computerJobId && claudeLane?.owns(computerJobId)
            ? handoffs[computerJobId] ?? claudeLane.handoffs(computerJobId)
            : undefined}
          localModel={displayModelName(modelRoles.chat || "")}
          onDeckAnswer={computerJobId && decks[computerJobId]
            ? (kind, value) => { void clientRef.current?.slidesAnswer(computerJobId, decks[computerJobId].title, kind, value).catch(() => null); }
            : undefined}
          onDeckOpen={computerJobId
            ? (path, reveal) => { void clientRef.current?.openOutputOnPc(computerJobId, path, reveal).catch(() => null); }
            : undefined}
          onDeckPhoto={computerJobId && decks[computerJobId]
            ? async (index, slot, file) => {
                const data = await new Promise<string>((done, fail) => {
                  const reader = new FileReader();
                  reader.onload = () => done(String(reader.result ?? ""));
                  reader.onerror = () => fail(reader.error);
                  reader.readAsDataURL(file);
                });
                await clientRef.current?.slidesPhoto(computerJobId, decks[computerJobId].title, index, slot, data);
              }
            : undefined}
        />
      )}
      <CapabilityDrawer
        client={clientRef.current}
        open={capabilitiesOpen}
        onClose={() => setCapabilitiesOpen(false)}
        connected={connected}
        google={googleStatus}
        googleBusy={googleBusy}
        onConnectGoogle={() => void connectGoogle()}
      />
      <SettingsScreen client={clientRef.current} open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      {FixtureBar && <Suspense fallback={null}><FixtureBar /></Suspense>}
      {tutorial.bubble && <CoachBubble step={tutorial.bubble} onSkip={tutorial.stop} />}
    </main>
  );
}

export default WorkspaceApp;
