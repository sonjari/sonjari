import type { Observation } from "./workspace/observation";

export type JarvisState =
  | "idle"
  | "listening"
  | "transcribing"
  | "routing"
  | "working"
  | "speaking"
  | "waiting_approval"
  | "waiting_continuation"
  | "error"
  | "stopped";

export type PresentationMode = "voice" | "hybrid" | "screen";
export type HudMode = "orb" | "panel" | "approval" | "continuation" | "attention";

// Where a job was started from. The small HUD and the full-screen WorkspaceApp
// are separate windows on one broadcast socket, so the HUD uses this to ignore
// answer traffic that belongs to the workspace window.
export type ChatOrigin = "chat" | "voice" | "workspace";
export type WorkspaceMode = "cowork" | "code";

export interface SpeechResult {
  requested?: boolean;
  ok?: boolean;
  path?: string;
  voice?: string;
  error?: string;
}

export interface Presentation {
  mode: PresentationMode;
  spoken_text: string;
  display_title: string;
  display_content: string;
  estimated_full_speech_sec?: number;
  reasons?: string[];
  speech?: SpeechResult;
}

export interface Approval {
  nonce: string;
  job_id?: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  expires_at?: number;
  status?: string;
  /** 사람이 읽을 대상 — 실제 경로와 「바탕화면에 쓰기」 같은 이름표. 백엔드가 보여 줄 때 붙인다(인자와 별개). */
  target?: {
    path?: string; place?: string; label?: string;
    /** 질문 카드(`ask_user`) — 모델이 묻는 말과 선택지, 추천 번호(없으면 -1). */
    question?: string;
    options?: { label: string; description?: string }[];
    recommended?: number;
  };
}

/** 모델이 사람에게 선택지로 묻는 도구 — 승인 틀을 빌려 멈춘다(2026-09-30). */
export const ASK_USER_TOOL = "ask_user";

// Populated for commit tools (google_gmail_send, google_calendar_create/
// _update/_delete, naver_blog_save_draft, naver_blog_publish) whose approval
// `arguments` only ever carry {action_id} -- the human-readable content lives
// in this fetched-separately preview, keyed by that action_id.
export interface ExternalActionPreview {
  action_id: string;
  kind: string;
  preview: Record<string, unknown>;
  status: string;
  created_at: number;
  expires_at: number;
}

export interface ContinuationRequest {
  job_id: string;
  goal?: string;
  reason?: "time_budget" | "step_budget" | string;
  elapsed_sec?: number;
  steps?: number;
  successful_steps?: number;
  failed_steps?: number;
  sources?: number;
  expires_at?: number;
  /** reason 이 "human_gate:<code>" 면 — 사람이 열어야 하는 그 화면의 주소(2026-09-29). */
  gate_url?: string;
  /** reason 이 "stuck" 이면 — 같은 자리에서 헛돌아 멈춘 판의 보고(2026-09-23). 모델이 아니라 코드가 센 값이다. */
  report?: { kind?: string; done?: string; blocked?: string; ask?: string; url?: string; message?: string };
}

/**
 * 사람이 화면에서 직접 처리해야 하는 상황. 봇 확인 화면, 로그인 요구, 반쯤 채워진
 * 폼, 눌렀지만 반영을 확인 못 한 저장 — 에이전트가 우회할 수 없는 것들만 온다.
 * 백엔드에서 같은 순간에 윈도우 알림과 음성도 함께 나간다.
 */
/** 되돌릴 수 있는 일이 사람 없이 지나갔다 (설정 › 권한 「되돌릴 수 있는 일은 자동 승인」, 2026-09-16). */
export interface AutoApprovedNotice {
  tool: string;
  job_id?: string;
  risk_level?: string;
  registered_risk?: string;
  reason?: string;
  at?: number;
}

export interface AttentionNotice {
  job_id: string;
  code: string;
  tool: string;
  title: string;
  message: string;
  speech?: string;
  detail?: string;
  url?: string;
  at?: number;
}

export interface JarvisEvent {
  seq?: number;
  sequence?: number;
  event: string;
  timestamp?: number;
  payload?: Record<string, unknown>;
}

export interface AgentProgress {
  key: string;
  jobId: string;
  phase: string;
  message: string;
  step: number;
  tool: string;
  status: "running" | "completed" | "partial" | "failed" | "cancelled";
  evidence?: Record<string, unknown>;
}

/**
 * 지금 읽는 그림 조각 (`agent_looking`). 걸음 기록이 아니다 — 읽는 동안에만 화면에 비추고, 다음 걸음이 오면 거둔다.
 * `image/images` 는 몇 번째 그림(읽을 그림 수), `tile/tiles` 는 그 그림의 몇 번째 조각(조각 수).
 */
export interface Looking {
  jobId: string;
  image: number;
  images: number;
  tile: number;
  tiles: number;
  /** 조각을 줄인 작은 그림(data URI). */
  picture: string;
  /** `"page"` = 그림 속 글자를 읽는 것이 아니라, 손자리가 만든 화면을 통째로 찍어 눈으로 보는 중(2026-10-11). */
  kind?: "page";
  width: number;
  height: number;
}

export interface BackendBootstrap {
  baseUrl: string;
  controlToken: string;
  mode?: "server" | "pilot";
}

export interface PilotAuthStatus {
  ready: boolean;
  method: "api_key_file" | "oauth" | "none";
  key_file_name: string;
  claude_found: boolean;
  message: string;
}

export interface PilotChatResult {
  answer: string;
  cost_usd?: number;
  duration_ms?: number;
  session_id?: string;
  model?: string;
  thinking_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  outputs?: JobOutput[];
  trace?: Observation[];
}

export interface ChatAttachment {
  name: string;
  mime_type: string;
  data_base64: string;
  /** 그림이면 기록에 남길 작은 미리보기(data URL). 원본은 `data_base64` 로 모델에게만 간다. */
  thumbnail?: string;
  width?: number;
  height?: number;
}

export interface ConversationSummary {
  session_id: string;
  title: string;
  preview: string;
  message_count: number;
  updated_at: number;
  has_summary: boolean;
  /** 바깥 AI 가 맡긴 대화면 그 호스트 이름(MCP clientInfo — 예: claude-code). 없으면 빈 값. */
  caller?: string;
}

export interface ConversationMessage {
  id: number;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  kind: string;
  metadata: Record<string, unknown>;
  created_at: number;
}

export interface ConversationHistory {
  session_id: string;
  summary: string;
  has_summary: boolean;
  searchable_memory_count?: number;
  context_window?: number;
  retrieval_enabled?: boolean;
  messages: ConversationMessage[];
}

/** 다른 AI 도구가 한도에 멈춘 순간, Cowork 오른쪽 칸으로 건너오는 읽기 전용 카드. */
export interface CoworkTakeoverCard {
  tool: string;
  tool_name: string;
  session_path: string;
  title: string;
  cwd: string;
  stop_kind: "rate_limit" | "api_error" | "aborted" | "none";
  stopped_minutes_ago: number | null;
  resets_at: number | null;
  last_request: string;
  files: string[];
  open_tasks: string[];
  request_count: number;
  git: {
    repo: boolean;
    root?: string;
    branch?: string;
    changed_count?: number;
    untracked_count?: number;
  };
  resumed_from_earlier_session?: boolean;
}

export interface CoworkTakeoverOffer {
  takeover_id: number;
  card: CoworkTakeoverCard;
  other_count?: number;
}

export interface CoworkTakeoverPrepared {
  ok: boolean;
  error?: string;
  takeover_id?: number;
  tool?: string;
  tool_name?: string;
  title?: string;
  prompt?: string;
  /** 서버가 받아들인 인계 방향. 채팅 요청의 `handoff_direction` 으로 되실어 보낸다. */
  direction?: HandoffDirection;
}

/**
 * 이어오기 캡슐에서 고른 방향. 채팅 요청에 **계약으로** 실린다 — 긴 인계문에서
 * 요구를 추측하면 「남은 일만 정리」가 계산·파일 과제로 바뀐다(W0, 2026-09-15).
 */
export type HandoffDirection = "continue" | "review" | "tasks" | "custom";

export interface JarvisPublicConfig {
  /** 화면이 쓰는 사람을 뭐라고 부를 것인가. 서버 설정(JARVIS_USER_LABEL)에서 온다. */
  user_label?: string;
  ollama_model?: string;
  ollama_num_ctx?: number;
  model_roles?: Record<string, string>;
  model_num_ctx?: Record<string, number>;
  memory_retrieval_enabled?: boolean;
  memory_retrieval_limit?: number;
}

export interface GoogleStatus {
  enabled: boolean;
  configured: boolean;
  connected: boolean;
  pending: boolean;
  project_id: string;
  credential_source?: string;
  email: string;
  name: string;
  scopes: string[];
  mode: "read_only" | "read_write";
  granted_scopes?: string[];
  scope_mismatch?: boolean;
  /** 드라이브 전체·지메일 읽기(제한 권한)를 쓰는 설치인가. 공개판은 꺼짐 — 고른 파일만 본다(인수인계 H4). */
  restricted_scopes?: boolean;
  /** 「드라이브에서 파일 고르기」로 고른 파일 수. */
  picked_files?: number;
  last_error: string;
}

export interface JobOrigin {
  jobId: string;
  origin: ChatOrigin | string;
}

export type JobStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "waiting_continuation"
  | "completed"
  | "failed"
  | "cancelled";

/**
 * 일감 한 줄. `GET /v1/jobs?view=summary` 가 주는 모양 그대로다.
 *
 * 답변 전문과 도구 걸음은 **여기 없다** — 목록이 455KB 였던 이유가 그것이었고,
 * 본문은 고른 뒤에 따로 가져온다(`getJob`).
 */
export interface JobSummary {
  id: string;
  kind: string;
  title: string;
  status: JobStatus | string;
  risk_level: string;
  error: string;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
  attempts: number;
  build: string;
  /** 어느 대화의 것인가. `POST /v1/jobs` 로 만든 잡에는 없을 수 있다(빈 문자열). */
  session_id: string;
  origin: string;
  steps: number;
  completion_state: string;
  /** 그 판이 도는 모드. 옛 서버는 안 준다. */
  workspace_mode?: string;
  /** 그 판의 작업 폴더(코드 판). 없으면 빈 문자열. */
  code_workspace?: string;
}

/** 도구 한 걸음이 장부에 남긴 줄. `agent_trace.steps[]` 의 원소다. */
export interface JobStep {
  step: number;
  tool: string;
  arguments?: Record<string, unknown>;
  ok: boolean;
  status: string;
  error: string;
  evidence?: Record<string, unknown>;
}

/** 잡 하나의 전부. `GET /v1/jobs/{id}` — 목록에는 안 실리는 본문이 여기 있다. */
export interface JobDetail extends Omit<JobSummary, "session_id" | "origin" | "steps" | "completion_state"> {
  payload?: Record<string, unknown>;
  result?: {
    answer?: string;
    completion_state?: string;
    session_id?: string;
    agent_trace?: {
      steps?: JobStep[];
      verification?: Record<string, unknown>;
    } | null;
  } | null;
}

/** 예약된 한 건. `GET /v1/schedules` 의 `schedules[]` 원소다. */
export interface ScheduleRow {
  id: string;
  title: string;
  prompt: string;
  session_id: string;
  run_at: number;
  status: string;
  created_at: number;
  updated_at: number;
  last_job_id: string;
}

/** 도구 한 개. `GET /v1/capabilities` 의 `tools[]` — `/v1/tools` 와 같은 모양이다. */
export interface CapabilityTool {
  name: string;
  description: string;
  risk_level: string;
  enabled: boolean;
  parameters?: Record<string, unknown>;
}

/** 사이트 레시피 한 개. **마누스에 없는 우리 자산**인데 코드 안에만 있었다. */
export interface RecipeSummary {
  site: string;
  description: string;
  hosts: string[];
  actions: Array<{ action: string; risk: string; params: string[]; description: string }>;
}

/** 자비스가 이름으로 아는 사이트. `seeded` = 사람이 심어 둔 것, 아니면 배운 것. */
export interface KnownSite {
  name: string;
  host: string;
  seeded: boolean;
}

export interface Capabilities {
  tools: CapabilityTool[];
  tool_count: number;
  by_risk: Record<string, number>;
  recipes: RecipeSummary[];
  sites: KnownSite[];
}

/** 그 작업이 **만든** 파일 한 개. `GET /v1/outputs?job_id=` 의 원소다. */
export interface JobOutput {
  step: number;
  tool: string;
  name: string;
  path: string;
  bytes: number;
  kind: "image" | "file" | string;
  /** 장부에는 있는데 디스크에 없을 수 있다. 그 사실을 숨기지 않는다. */
  exists: boolean;
  /** 산출물 폴더 안이라 열어서 볼 수 있는가. 밖의 파일은 내려주지 않는다. */
  viewable: boolean;
}

/**
 * 되돌릴 수 있는 것 한 개.
 *
 * `automatic: false` 는 자비스가 못 되돌린다는 뜻이고, 그때는 `manual_hint` 가
 * 사람이 할 일을 말한다 — 버튼을 숨기면 그 말도 같이 사라진다.
 */
export interface UndoOffer {
  undo_id: string;
  tool: string;
  job_id: string;
  label: string;
  automatic: boolean;
  manual_hint: string;
  what: Record<string, unknown>;
  created_at: number;
  expires_at: number;
}

/**
 * 브라우저가 지금 어떤 상태인가. `GET /v1/browser/status` 의 쓰는 부분만.
 *
 * ★ `stuck` · `circuit_open` · `attach_error` 를 화면이 **숨기면 안 된다.**
 * 자비스가 막혔는데 화면이 멀쩡해 보이는 것이 제일 나쁜 모양이다.
 */
export interface BrowserStatus {
  enabled: boolean;
  started: boolean;
  liveness: "probed" | "cached" | string;
  headless: boolean;
  read_only: boolean;
  /** "attached" 여야 진짜 크롬이다. "launched" 는 자동화 모드라 막히는 곳이 있다. */
  connect_mode: string;
  automation_flag: boolean | null;
  attach_error: string;
  last_error: string;
  stuck: boolean;
  circuit_open: boolean;
  recoveries: number;
}

/** 화면 한 장과 그 장에 붙은 사실. `objectUrl` 은 받는 쪽이 만들고 지운다. */
export interface BrowserFrame {
  ok: boolean;
  blob: Blob | null;
  pageUrl: string;
  title: string;
  /** 이 그림이 몇 초 전 것인가. 0.0 이면 방금 찍었다. */
  ageSec: number;
  fresh: boolean;
  /** 못 찍었거나 못 갱신했으면 **왜**. 그림이 있을 때도 채워질 수 있다. */
  reason: string;
}

/** 브라우저 무대의 한 장(`/v1/browser/live`). 새 장이 없으면 `blob` 이 null 이고 상태만 온다. */
export interface LiveFrame {
  blob: Blob | null;
  seq: number;
  /** 크롬 화면의 CSS 픽셀 크기 — 입력 좌표를 이 비율로 보낸다. */
  width: number;
  height: number;
  url: string;
  /** streaming · no_frames(뒤쪽 탭) · no_page · idle · backend_unreachable … */
  status: string;
  /** 사람이 넘겨받은 중인가. */
  control: boolean;
  /** 손을 안 대면 몇 초 뒤 온텔릭에게 돌려주나. */
  releaseIn: number;
}

/** 브라우저 틀(3차)이 그릴 상태 — `/v1/browser/live/state`. */
export interface LiveTab {
  id: string;
  title: string;
  url: string;
  /** 온텔릭이 지금 일하는 탭. */
  agent: boolean;
}

export interface LiveState {
  url: string;
  title: string;
  loading: boolean;
  can_back: boolean;
  can_forward: boolean;
  tabs: LiveTab[];
  /** 무대가 지금 보여 주는 탭. */
  viewing: string;
  /** 사람이 넘겨받은 동안 뜬 확인/취소 알림창 — 무대가 대신 그린다. */
  dialog: { type: "alert" | "confirm" | "prompt" | "beforeunload"; message: string; default: string; at?: number } | null;
  /** 페이지가 파일을 달라고 한다(넘겨받은 동안만). `at` 은 어느 창인지 가리는 표. */
  file_chooser: { mode: "selectSingle" | "selectMultiple"; at?: number } | null;
  control: boolean;
}

/** 사람이 누른 곳이 고르기 상자였다 — 목록을 무대가 대신 그린다. `rect` 는 크롬 화면 기준 0..1. */
export interface LiveSelect {
  options: { text: string; disabled: boolean }[];
  selected: number;
  rect: { x: number; y: number; w: number; h: number };
}

/** 무대에서 사람이 한 입력 하나. 좌표는 크롬 화면 기준 0..1. */
export type LiveInputEvent =
  | { kind: "mouse"; type: "down" | "up" | "move"; x: number; y: number; button: "left" | "right" | "middle" | "none"; clickCount?: number; ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean; fw?: number; fh?: number }
  | { kind: "wheel"; x: number; y: number; dx: number; dy: number; ctrl?: boolean; shift?: boolean; fw?: number; fh?: number }
  | { kind: "key"; type: "down" | "up"; key: string; code: string; keyCode: number; ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean }
  | { kind: "text"; text: string }
  | { kind: "select"; index: number };

export interface ScheduleList {
  action: string;
  count: number;
  schedules: ScheduleRow[];
}

export interface HudModel {
  mode: HudMode;
  state: JarvisState;
  connected: boolean;
  presentation: Presentation | null;
  approval: Approval | null;
  approvalPreview: ExternalActionPreview | null;
  continuation: ContinuationRequest | null;
  attention: AttentionNotice | null;
  activeJobId: string;
  progress: AgentProgress[];
  streamingContent: string;
  thinking: boolean;
  error: string;
  // Recently seen job -> origin, newest last. Only events whose payload carries
  // both job_id and origin add entries; the list stays small on purpose.
  jobOrigins: JobOrigin[];
}

/** Who the office camera can recognise, and whether it can recognise at all. */
export interface PeopleStatus {
  enabled: boolean;
  ok: boolean;
  models_present?: boolean;
  missing_models?: string[];
  registered: string[];
  threshold?: number;
}

/**
 * Result of sweeping the room for somebody new.
 *
 * `registered: false` is a normal outcome, not an error -- an empty room and a
 * room where two strangers are visible at once are both refusals, and they need
 * different things from the user. `reason` says which. `similarity_to_known` is
 * the evidence that whoever was registered really was new.
 */
export interface DiscoverPersonResult {
  ok: boolean;
  registered: boolean;
  name?: string;
  reason?: "no_unfamiliar_face" | "several_unfamiliar_faces" | string;
  count?: number;
  similarity_to_known?: number;
  threshold?: number;
  known_before?: string[];
  heading?: number;
  steps?: number;
  embeddings?: number;
}

/** 궤적 쪽에 정의돼 있지만 화면 여러 곳이 쓴다 — 한 이름으로 다시 내보낸다. */
export type { PlanItem } from "./trajectory";

/**
 * 걸음이 **본 것**. 타입 본체와 판정은 `workspace/observation.ts` 에 있다
 * (화면 없이 검사하려고 그쪽에 모아 두었다). 백엔드 클라이언트가 쓰기 편하게
 * 여기서 다시 내보낸다.
 */
export type { Observation, ObservationKind, StepRow } from "./workspace/observation";

/** 받을 게 있나. `available` 이 참일 때만 화면이 무언가를 말한다. */
/** 켤 때 돈 자가 점검(2026-09-18). `state`: ok 봤는데 정상 · down 봤는데 고장 · unknown 검사 자체가 못 돌았다. */
export interface SelfCheckOrgan {
  organ: string;
  state: "ok" | "down" | "unknown";
  detail: string;
  /** 이 버튼으로 고칠 수 있다(백엔드가 정한 것만). 비면 사람이 해야 한다. */
  healer: string;
}

export interface SelfCheckStatus {
  pending?: boolean;
  at?: number;
  organs?: SelfCheckOrgan[];
  down?: string[];
  healable?: string[];
  healthy?: boolean;
}

export interface SelfHealResult {
  ran: boolean;
  fixed?: boolean;
  why?: string;
  error?: string;
}

export interface UpdateStatus {
  ok: boolean;
  /** "store" = 스토어 설치(윈도우가 갱신·우리는 알리기만) · 없으면 위성(우리가 받아 갈아치움). */
  kind?: "store" | "none";
  /** 스토어 설치에서 사람이 할 일. "restart" = 껐다 켜면 적용된다. */
  how?: string;
  mine: string;
  theirs?: string;
  available?: boolean;
  file_count?: number;
  total_bytes?: number;
  reason?: string;
  /** 스토어판 「지금 업데이트」 뒤 새로 열렸을 때 한 번만 온다 — 무엇이 됐는지(실패 포함). */
  just_updated?: { ok: boolean; from: string; to: string; installed?: string; error?: string };
}

/** 자비스가 배운 사실 하나. **출처가 같이 온다** — 근거 없이는 고칠 수 없다. */
export interface LearnedFact {
  id: number;
  kind: string;
  subject: string;
  fact: string;
  /** seed = 사람이 심음 · extracted = 대화에서 뽑음 · manual = 화면에서 넣음 */
  origin: string;
  created_at: number;
  source_message_id: number;
  /** 못 찾을 수도 있다. **비었다고 숨기지 않는다** — 근거 없는 사실이 있다는
   *  것 자체가 사람이 알아야 할 정보다. */
  source: { role: string; excerpt: string; created_at: number; session_id: string } | null;
}

export interface LearnedFacts {
  count: number;
  items: LearnedFact[];
  /** 이 중 **매 턴 실제로 실려 가는** 글자 수. 서랍에 있는 것과 모델이 보는
   *  것은 다르다(상한이 있다). */
  always_on_chars: number;
  always_on_cap: number;
}

// ── 설정 화면 (W3) · 스킬 온보딩 (W4) ────────────────────────────────────────

export type SettingKind = "bool" | "int" | "str" | "choice" | "list" | "model";
export type SettingValue = boolean | number | string | string[];

export interface SettingRow {
  key: string;
  group: string;
  label: string;
  kind: SettingKind;
  help: string;
  choices: string[];
  min: number | null;
  max: number | null;
  lab: boolean;
  value: SettingValue;
  /** 화면에서 바꾼 값이면 user, 아니면 default(코드 기본·관리 설치). */
  source: "user" | "default";
  live: boolean;
  restart_required: boolean;
  /** 이 판에서 못 쓰는 기능이면 그 이유(사람 말). 빈 값이면 쓸 수 있다. */
  unavailable?: string;
}

export interface SettingsView {
  groups: { id: string; label: string }[];
  settings: SettingRow[];
  path: string;
}

export interface SettingsPatchResult extends SettingsView {
  ok: boolean;
  applied?: string[];
  restart_required?: string[];
  error?: string;
}

export interface SkillDomainRow {
  id: string;
  label: string;
  blurb: string;
  selected: boolean;
  /** triggers = 이 스킬이 붙는 한국어 낱말(배급 규칙 그대로). 비면 이름으로 지목해야 쓴다. */
  skills: { name: string; what: string; triggers?: string[] }[];
  missing: string[];
}

export interface SkillDomainsView {
  domains: SkillDomainRow[];
  selected: string[];
  active_count: number;
  total_served: number;
  route_enabled: boolean;
}

export interface BackupSummary {
  enabled: boolean;
  root: string;
  keep: number;
  generations: { generation: string; created_at: number; reason: string; tables: Record<string, number> }[];
  memory_empty: boolean;
  delete_confirmation: string;
}

/** 권한 모드 (2026-09-21). 토글 아홉 개 말고 손잡이 하나. */
export interface PermissionModes {
  /** 지금 모드. 사람이 토글을 손으로 섞어 두면 `custom` 이다 — 억지로 가까운 모드로 부르지 않는다. */
  mode: string;
  modes: { id: string; label: string; help: string }[];
  /** **어느 모드에서도 물어보는 것.** 화면이 그 사실을 정직하게 적을 수 있게 내려온다. */
  always_ask: string[];
  /** 「권한 무시」에서도 묻는 것(2026-09-23) — 결제·메일 보내기·발행. */
  never_bypass?: string[];
}

// ── 분야 팩 (0판, 2026-09-27 · 전략안 §50) ─────────────────────────────────────
export interface PackPermissions {
  reads: string[];
  writes: string[];
  runs: string[];
  network: string | boolean;
}

export interface PackInfo {
  id: string;
  name: string;
  version: string;
  kind: "content" | "code";
  summary: string;
  description: string;
  tools: string[];
  skills: string[];
  domains: string[];
  permissions: PackPermissions;
  bench: string;
  enabled: boolean;
  /** `user` = 사람이 스킬팩 폴더에 직접 넣은 것(2026-10-11). 없으면 프로그램과 같이 온 팩이다. */
  origin?: "builtin" | "user";
  /** 스킬 이름 → 그 스킬이 붙는 낱말들. 팩이 들고 온 것. */
  triggers?: Record<string, string[]>;
  /** 스킬 이름 → 그 스킬이 붙을 때 사람의 말 뒤에 붙는 한 문장(「시키는 말」). */
  asks?: Record<string, string>;
  /** 스킬 이름 → 그 일의 갈래(지금은 `web` 하나 — 「웹을 보고 와서 정리하는 일」). 팩이 적어 온 것. */
  work?: Record<string, string>;
}

export interface PacksView {
  packs: PackInfo[];
  problems: string[];
  /** 사람이 스킬팩 폴더를 넣는 자리(문서 폴더 안). */
  user_dir?: string;
}

export type UnityNextKind = "install_hub" | "open_hub" | "pick_project" | "allow_project" | "close_editor" | "ready";

export interface UnityProjectRow {
  path: string;
  name: string;
  version: string;
  editor_installed: boolean;
  editor_open: boolean;
  allowed: boolean;
}

export interface UnitySetupView {
  hub: { installed: boolean; path: string };
  editors: { version: string; path: string }[];
  license: boolean;
  projects: UnityProjectRow[];
  next: { kind: UnityNextKind; text: string; path?: string };
}

/** 게임 팩 2단계(2026-09-27) — 설정 › 팩의 「열린 에디터」 칸. 백엔드 `UnityTools.editor_view`. */
export interface UnityEditorProject {
  path: string;
  name: string;
  installed: boolean;
  other_version: boolean;
  value: string;
  /** 이어 두었지만 그 줄이 유니티가 못 읽는 자리를 가리킨다(스토어판의 예전 판이 적은 줄) — 「다시 잇기」로 고친다. */
  broken?: boolean;
  editor_open: boolean;
  connected: boolean;
  reloading: boolean;
}

/** 우리 방 — 에디터 다리를 지난 명령 기록(이 PC 에만). `share_with_coplay` 는 사람이 켰을 때만 true. */
export interface UnityRoom {
  calls: number;
  by_tool: Record<string, { calls: number; failed: number }>;
  recent: { at: number; tool: string; action: string; ok: boolean; ms: number; error?: string }[];
  shared_count: number;
  share_with_coplay: boolean;
  install_id: string;
}

export interface UnityEditorView {
  projects: UnityEditorProject[];
  room: UnityRoom;
  stage: { status: "ready" | "minimized" | "no_editor" | "unavailable"; title?: string; text?: string };
  package_version: string;
}

export interface UnityStageFrame {
  blob: Blob | null;
  seq: number;
  width: number;
  height: number;
  title: string;
  problem: string;
}

export interface UnityScheduleRun {
  at: number;
  scheduled: boolean;
  verified: boolean;
  failure: string;
  elapsed_sec?: number;
  numbers: Record<string, number>;
  worse: Record<string, [number, number]>;
}

export interface UnitySchedule {
  id: string;
  recipe: string;
  title: string;
  project: string;
  at: string;
  days: "daily" | "weekday" | "weekly";
  enabled: boolean;
  running: boolean;
  deferred: string;
  last: UnityScheduleRun | null;
  history: UnityScheduleRun[];
  watch_labels: Record<string, string>;
}

/** 설정 화면의 「바로 시킬 수 있는 점검」 한 장 — `ask` 는 대화창에 그대로 말하면 되는 문장(등록한 레시피에는 없을 수 있다). */
export interface UnityRecipeCard {
  name: string;
  title: string;
  description: string;
  ask: string;
  origin: "pack" | "registered";
}

export interface UnityDraft {
  name: string;
  title: string;
  description: string;
  risk: "L1" | "L2";
  findings: { line: number; what: string; code: string }[];
  author: string;
  verified: boolean;
  failure: string;
  ran_at: number | null;
}
