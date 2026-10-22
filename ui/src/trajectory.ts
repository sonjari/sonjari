/**
 * 작업 궤적 — 자비스가 무엇을 했는지 붙들어 둔다.
 *
 * 예전에는 도구 걸음이 우측 레일에만 살았고, **답이 도착하는 순간 지워졌다.**
 * (실측 2026-08-19: 걸음이 7개까지 붙었다가 job_completed 직후 0.)
 * 답과 근거가 따로 놀면 "했다고 말했는데 안 했다"를 화면에서 잡을 방법이 없다.
 * 그래서 걸음을 대화와 같은 축에 꿰고, 끝난 뒤에는 한 줄로 접어서 남긴다.
 */
import { t } from "./i18n";
import type { AgentProgress, ConversationMessage } from "./types";

export interface TrajectoryStep {
  key: string;
  step: number;
  tool: string;
  message: string;
  status: AgentProgress["status"];
  at: number;
  /** 그 걸음이 남긴 근거. 주소·개수·확인한 값 — 있는 것만 온다(없으면 undefined). */
  evidence?: Record<string, unknown>;
}

/**
 * 시킨 것 한 줄 — 백엔드 `plan.py` 가 프롬프트에서 **결정론적으로** 뽑은 요구다 (R3).
 *
 * LLM 이 세운 계획이 아니다. 지어낸 계획은 아무도 대조하지 않으므로 더 조용히
 * 틀린다(`plan.py` 첫머리). 그래서 뽑을 수 있는 것만 적게 뽑고 확실하게 대조한다:
 * 개수("4개는 직접 열어 읽어라") · 사이트("크몽에서") · 행위("임시저장까지").
 */
export interface PlanItem {
  kind: "count" | "site" | "action" | string;
  label: string;
  met: boolean;
  /** 지금까지 실제로 어땠는가 — "3개 읽음" 처럼. 이게 없으면 얼마나 왔는지 모른다. */
  saw: string;
}

export interface Trajectory {
  jobId: string;
  sessionId: string;
  prompt: string;
  startedAt: number;
  endedAt?: number;
  status: "running" | "completed" | "failed" | "cancelled";
  steps: TrajectoryStep[];
  /** 없으면 뽑을 수 있는 요구가 없었다는 뜻이다 — 빈 체크리스트를 그리지 않는다. */
  plan?: PlanItem[];
}

/**
 * 밖을 바꾸는 도구. 이 목록에 없으면 "읽기만 했다"고 말한다.
 *
 * 모르는 도구를 읽기로 치면 안 되므로, 판정은 **이름이 아니라 목록**으로 한다.
 * 새 쓰기 도구를 만들면 여기에 넣어라 — 안 넣으면 화면이 "읽기만 함"이라고
 * 거짓말한다. (같은 구멍으로 눈금이 두 번 샜다.)
 */
export const WRITE_TOOLS = new Set([
  "google_gmail_send", "google_calendar_create", "google_calendar_update", "google_drive_write",
  "google_calendar_delete", "google_drive_upload", "google_docs_write",
  "naver_blog_save_draft", "naver_blog_publish",
  "browser_fill", "browser_click_submit", "browser_form_submit", "browser_submit",
  // 2026-08-20: 눈금(`measure_autonomy.py`)이 이 셋을 "분류 안 된 도구 14건"으로
  // 띄웠다. 화면에서도 같은 구멍이었다 — 이것들만 쓴 잡이 "읽기만 함"으로 보였다.
  "browser_click_confirmed", "browser_fill_form", "browser_select_option",
  "file_write", "file_delete", "shell_run",
  "local_write_file", "local_apply_edit", "local_delete_file",
  "artifact_from_observations",
  "hwp_apply_edit",
  "hwp_apply_format",
  "hwp_export_pdf",
  "claude_code_delegate",
]);

export function isWriteTool(tool: string): boolean {
  return WRITE_TOOLS.has(tool);
}

export function startTrajectory(jobId: string, sessionId: string, prompt: string, at: number): Trajectory {
  return { jobId, sessionId, prompt, startedAt: at, status: "running", steps: [] };
}

/** 같은 걸음이 running → completed 로 두 번 온다. 덮어쓰되 자리는 지킨다. */
export function applyStep(trajectory: Trajectory, item: AgentProgress, at: number): Trajectory {
  const step: TrajectoryStep = {
    key: `${item.step}:${item.tool}:${item.phase}`,
    step: item.step,
    tool: item.tool,
    message: item.message,
    status: item.status,
    at,
    evidence: item.evidence,
  };
  const index = trajectory.steps.findIndex((row) => row.step === step.step && row.tool === step.tool);
  const steps = index >= 0
    ? trajectory.steps.map((row, i) => (i === index ? { ...step, at: row.at } : row))
    : [...trajectory.steps, step];
  return { ...trajectory, steps };
}

/** 대조표가 왔다. 걸음과 달리 **통째로 갈아 끼운다** — 서버가 매번 전부 다시 센다. */
export function applyPlan(trajectory: Trajectory, items: PlanItem[]): Trajectory {
  return { ...trajectory, plan: items };
}

/** 시킨 것 중 몇 개를 채웠나. 요구가 없으면 `null` — "0/0" 은 아무 말도 아니다. */
export function planProgress(trajectory: Trajectory): { met: number; total: number } | null {
  const plan = trajectory.plan ?? [];
  if (!plan.length) return null;
  return { met: plan.filter((item) => item.met).length, total: plan.length };
}

export function finishTrajectory(trajectory: Trajectory, status: Trajectory["status"], at: number): Trajectory {
  return { ...trajectory, status, endedAt: at };
}

export interface TrajectorySummary {
  steps: number;
  failed: number;
  seconds: number;
  tools: string[];
  wrote: boolean;
  label: string;
}

/** 접힌 한 줄. 여기 적히는 것은 전부 실제로 센 값이다. */
export function summarize(trajectory: Trajectory): TrajectorySummary {
  const done = trajectory.steps.filter((s) => s.status !== "running");
  const failed = trajectory.steps.filter((s) => s.status === "failed").length;
  const seconds = Math.max(0, Math.round((trajectory.endedAt ?? Date.now() / 1000) - trajectory.startedAt));
  const tools = [...new Set(trajectory.steps.map((s) => s.tool).filter(Boolean))];
  const wrote = tools.some(isWriteTool);
  const parts = [t("{0}걸음", done.length || trajectory.steps.length), t("{0}초", seconds)];
  if (failed) parts.push(t("{0}실패", failed));
  parts.push(wrote ? t("바꾼 것 있음") : t("읽기만 함"));
  return { steps: trajectory.steps.length, failed, seconds, tools, wrote, label: parts.join(" · ") };
}

/**
 * 걸음이 남긴 근거를 **한 줄로** 추린다 (R4).
 *
 * 통째로 펼치지 않는 이유: 증거 사전에는 도구마다 다른 칸이 열댓 개씩 들어 있고
 * (`_step_evidence` 는 "뺄 것만 정하고 나머지는 싣는다"), 그걸 다 그리면 걸음
 * 하나가 화면 한 폭을 먹는다. 여기서는 **어디서 무엇을 봤는지**만 남긴다.
 *
 * 주소를 맨 앞에 두는 이유: "했다고 말했는데 안 했다"를 잡는 것이 궤적의 목적이고,
 * 그 판정에 제일 먼저 쓰이는 것이 출처다.
 */
const EVIDENCE_SKIP = new Set(["action", "instruction", "site_first_redirect"]);

export function evidenceLine(step: TrajectoryStep, limit = 3): string {
  // ★ 2026-09-20 노트북: 마지막 「검증」 걸음은 내부 점검표 전체를 싣는다 — `verified=아니오 · stop_reason=model_answered ·
  //   completion_state=answered` 가 사람 화면에 그대로 찍혔다. 그건 어디서 무엇을 봤는지(근거)가 아니다.
  if (step.tool === "verification") return "";
  const evidence = step.evidence ?? {};
  const parts: string[] = [];
  const url = String(evidence.url ?? "");
  if (url) parts.push(url);
  const cost = Number(evidence.total_cost_usd ?? 0);
  if (step.tool === "claude_code_delegate" && Number.isFinite(cost)) {
    parts.push(t("예상비용 ${0}", cost.toFixed(4)));
  }
  for (const [key, value] of Object.entries(evidence)) {
    if (parts.length >= limit) break;
    if (key === "url" || key === "total_cost_usd" || key === "session_id" || EVIDENCE_SKIP.has(key)) continue;
    if (value === null || value === undefined || value === "") continue;
    // 긴 문자열과 목록은 여기 자리가 없다. 숫자·짧은 값·참거짓만 남긴다.
    if (typeof value === "boolean") parts.push(t("{0}={1}", key, value ? t("예") : t("아니오")));
    else if (typeof value === "number") parts.push(`${key}=${value}`);
    else if (typeof value === "string" && value.length <= 40) parts.push(`${key}=${value}`);
  }
  return parts.join(" · ");
}

/** 사람이 읽을 도구 이름. 없으면 원래 이름을 그대로 보여 준다(숨기지 않는다). */
/**
 * 도구 이름 → 사람 말 (2026-08-24 전면 보강).
 *
 * ## 왜 다 채웠나
 *
 * 21개만 적혀 있었고 실제로 불린 것은 76종이었다. 라이브 실측에서 **1,881번이
 * `browser_open_result` 같은 날 이름 그대로** 화면에 찍혔다 — 가장 많이 불린 도구가
 * 가장 안 읽히는 이름으로 나오고 있었던 셈이다. 사용자가 "저거 영어로 나오노"라고
 * 하신 게 이것이다.
 *
 * ## 왜 또 빠졌나
 *
 * 손으로 관리하는 목록이라서다. 이 저장소는 같은 병을 세 번 앓았다 — 눈금의
 * 도구 분류표에서 두 번, 관측 종류에서 한 번. 그래서 이번엔 둘을 같이 넣는다:
 *
 *     1. 107종 **전부** 적는다 (도구 스키마에서 뽑아 맞췄다)
 *     2. 그래도 새 도구는 생긴다 → `toolLabel` 이 **모양으로** 읽을 만하게 만든다
 *     3. 검사가 지킨다 (`tests/test_tool_labels.py` — 파이썬 쪽 스키마와 대조)
 *
 * 3번이 진짜 자물쇠다. 새 도구를 만든 날 검사가 빨개진다.
 */
const TOOL_LABELS: Record<string, string> = {
  // ── Claude 가 통째로 맡기는 문 (MCP) ──
  sonjari_task: t("맡은 일 받기"),
  sonjari_task_status: t("맡은 일 결과 알려 주기"),
  sonjari_guide: t("Sonjari 사용법 읽기"),
  sonjari_story: t("Sonjari 서기 카드 읽기"),
  // 이름 2단계(2026-09-29) 전 기록 — 지난 작업을 다시 열어도 이름표가 나오게.
  ontelic_task: t("맡은 일 받기"),
  ontelic_task_status: t("맡은 일 결과 알려 주기"),
  ontelic_guide: t("Sonjari 사용법 읽기"),
  // ── 브라우저 ──
  browser_open: t("브라우저 열기"),
  browser_open_result: t("결과 열어 보기"),
  browser_search: t("검색"),
  browser_site_search: t("사이트에서 검색"),
  browser_result_list: t("결과 목록 읽기"),
  browser_extract: t("본문 읽기"),
  browser_read: t("본문 읽기"),
  browser_snapshot: t("화면 훑어보기"),
  browser_scroll: t("끝까지 훑기"),
  browser_load_more: t("더 불러오기"),
  browser_find: t("화면에서 찾기"),
  browser_links: t("링크 모으기"),
  browser_click: t("누르기"),
  browser_click_confirmed: t("확인하고 누르기"),
  browser_hover: t("올려놓고 보기"),
  browser_click_at: t("좌표 누르기"),
  browser_page_data: t("받아 온 데이터 보기"),
  ui_read_value: t("화면 값 그림으로 읽기"),
  browser_site_sources: t("공개 출처 찾기"),
  browser_type_at: t("좌표 칸에 입력"),
  browser_fill: t("입력"),
  browser_fill_form: t("양식 채우기"),
  browser_form_submit: t("양식 보내기"),
  browser_press: t("키 누르기"),
  browser_select_option: t("고르기"),
  browser_pick_suggestion: t("자동완성에서 고르기"),
  browser_file_upload: t("파일 올리기"),
  browser_back: t("뒤로 가기"),
  browser_wait: t("기다리기"),
  browser_tabs: t("탭 목록"),
  browser_switch_tab: t("탭 바꾸기"),
  browser_close: t("탭 닫기"),
  browser_screenshot: t("화면 찍기"),
  browser_probe_frames: t("안쪽 틀 살피기"),
  browser_dismiss_dialog: t("알림창 닫기"),
  browser_handle_dialog: t("알림창 처리"),
  browser_verify: t("제대로 됐는지 확인"),
  // ── 검색·바깥 출처 ──
  naver_web: t("네이버 웹검색"),
  naver_news: t("네이버 뉴스"),
  google_trend: t("구글 트렌드"),
  github_search: t("깃허브 검색"),
  hackernews_top: t("해커뉴스"),
  reddit_hot: t("레딧"),
  evidence_check: t("출처 확인"),
  // ── 우리 데이터 ──
  inhouse_lookup: t("우리 데이터 조회"),
  admission_quant_lookup: t("입시 수치 조회"),
  admission_candidates_by_grade: t("성적으로 후보 찾기"),
  admission_major_profile_lookup: t("학과 정보 조회"),
  admission_major_semantic_search: t("학과 의미 검색"),
  career_strategy_lookup: t("진로 전략 조회"),
  // ── 내 컴퓨터 ──
  file_read: t("파일 읽기"),
  file_write: t("파일 쓰기"),
  local_list_directory: t("폴더 목록"),
  local_index_codebase: t("코드 저장소 색인"),
  browser_download: t("문서 내려받기"),
  clipboard_write: t("클립보드에 올리기"),
  local_write_document: t("문서 만들기"),
  local_edit_spreadsheet: t("엑셀 셀 고치기"),
  local_grep: t("코드에서 찾기"),
  local_glob: t("파일 패턴 찾기"),
  local_read_text_file: t("파일 읽기"),
  local_read_document: t("문서 읽기"),
  local_search_files: t("파일 찾기"),
  local_write_text_file: t("파일 쓰기"),
  local_write_file: t("작업 파일 쓰기"),
  local_apply_edit: t("파일 일부 고치기"),
  local_delete_file: t("파일 지우기"),
  local_run_project_command: t("프로젝트 검증 실행"),
  unity_project_info: t("유니티 프로젝트 훑기"),
  unity_list_recipes: t("유니티 레시피 목록"),
  unity_run_recipe: t("유니티 레시피 실행"),
  unity_try_script: t("클로드·코덱스 초안 돌려 보기"),
  unity_editor_status: t("유니티 에디터 상태 보기"),
  unity_editor_look: t("유니티 에디터 안 읽기"),
  unity_editor_change: t("유니티 에디터에서 바꾸기"),
  unity_editor_undo: t("유니티 에디터 되돌리기"),
  clipboard_read: t("클립보드 읽기"),
  shell_probe: t("명령 확인"),
  sandbox_run: t("직접 계산해 보기"),
  artifact_from_observations: t("근거를 파일로 만들기"),
  sandbox_fetch: t("만든 파일 가져오기"),
  sandbox_reset: t("작업판 비우기"),
  claude_code_delegate: t("클로드(내 구독)에게 넘김"),
  // ── 윈도우 창 ──
  windows_list_open_windows: t("열린 창 목록"),
  windows_focus_window: t("창 앞으로"),
  windows_open_path: t("파일 열기"),
  local_request_path_access: t("폴더를 열어 달라고 요청"),
  ask_user: t("선택지로 묻기"),
  local_preview_page: t("만든 화면 띄워 보기"),
  local_run_shell: t("명령 한 줄 돌려 보기"),
  local_find_symbol: t("이 이름 어디서 쓰나 찾기"),
  windows_uia_snapshot: t("창 훑어보기"),
  windows_uia_preview: t("창에서 할 일 미리보기"),
  windows_visual_preview: t("창 미리 보기"),
  windows_execute_preview: t("창 조작 실행"),
  windows_copy_from_window: t("창에서 복사"),
  hwp_list_open: t("열린 한글 문서 확인"),
  hwp_read: t("한글 문서 읽기"),
  hwp_preview_edit: t("한글 편집 미리보기"),
  hwp_apply_edit: t("한글 편집 적용"),
  hwp_preview_format: t("한글 서식 미리보기"),
  hwp_apply_format: t("한글 서식 적용"),
  hwp_export_pdf: t("한글 → PDF 저장"),
  ui_find_target: t("누를 곳 찾기"),
  ui_click_target: t("찾은 곳 누르기"),
  ui_verify: t("제대로 눌렸는지 확인"),
  // ── 구글 ──
  google_gmail_search: t("메일 찾기"),
  google_gmail_prepare_send: t("메일 초안 만들기"),
  google_gmail_send: t("메일 보내기"),
  google_calendar_upcoming: t("일정 보기"),
  google_calendar_prepare_create: t("일정 초안 만들기"),
  local_edit_document: t("문서 고침"),
  google_calendar_create: t("일정 등록"),
  google_drive_prepare_write: t("드라이브 업로드 준비"),
  google_drive_write: t("드라이브에 올림"),
  google_calendar_prepare_update: t("일정 수정 준비"),
  google_calendar_update: t("일정 수정"),
  google_calendar_prepare_delete: t("일정 삭제 준비"),
  google_calendar_delete: t("일정 삭제"),
  google_drive_search: t("드라이브에서 찾기"),
  google_drive_read: t("드라이브 문서 읽기"),
  // ── 네이버 블로그 ──
  naver_blog_prepare_post: t("블로그 글 준비"),
  naver_blog_fill_editor: t("블로그 편집기 채우기"),
  naver_blog_prepare_save_draft: t("임시저장 준비"),
  naver_blog_save_draft: t("블로그 임시저장"),
  naver_blog_prepare_publish: t("발행 준비"),
  naver_blog_publish: t("블로그 발행"),
  // ── 예약·지켜보기 ──
  schedule_create: t("예약 걸기"),
  schedule_list: t("예약 목록"),
  schedule_cancel: t("예약 취소"),
  watch_create: t("지켜보기 시작"),
  watch_list: t("지켜보는 것 목록"),
  watch_cancel: t("지켜보기 그만"),
  // ── 카메라 ──
  look_at_camera: t("카메라로 보기"),
  camera_look: t("카메라로 보기"),
  camera_status: t("카메라 상태"),
  camera_start_live: t("카메라 켜기"),
  camera_stop_live: t("카메라 끄기"),
  camera_who_is_there: t("누가 있는지 보기"),
  camera_find_person: t("사람 찾기"),
  camera_register_face: t("얼굴 등록"),
  camera_register_new_person: t("새 사람 등록"),
  camera_forget_face: t("얼굴 지우기"),
  camera_gimbal_mode: t("짐벌 모드"),
  camera_recenter: t("카메라 정면으로"),
  // ── 레시피·스킬·자기 점검 ──
  site_list: t("아는 사이트 목록"),
  site_run: t("사이트 레시피 실행"),
  site_draft_recipe: t("레시피 초안 쓰기"),
  site_review_draft: t("레시피 초안 검토"),
  site_promote_draft: t("레시피 확정"),
  skill_list: t("쓸 수 있는 요령 목록"),
  skill_read: t("요령 읽기"),
  self_check: t("자기 상태 점검"),
  self_heal: t("스스로 고치기"),
  // ── 갈래 고르기(라우터가 부르는 것) ──
  use_browser: t("브라우저로 가기"),
  use_google_workspace: t("구글로 가기"),
  use_local_computer: t("내 컴퓨터로 가기"),
  use_scheduler: t("예약으로 가기"),
  use_naver_blog: t("블로그로 가기"),
  use_camera_control: t("카메라로 가기"),
};

/**
 * 목록에 없는 도구도 **읽을 만하게** 만든다.
 *
 * 목록은 반드시 낡는다. 낡았을 때 사람이 `browser_open_result` 를 보는 것과
 * 「브라우저 · open result」를 보는 것은 다르다 — 뒤쪽은 적어도 어느 갈래의
 * 일인지는 알려 준다. 검사가 목록을 채우게 만들고, 이건 그 사이의 그물이다.
 */
const FAMILY: Array<[string, string]> = [
  ["browser_", t("브라우저")],
  ["google_calendar_", t("일정")],
  ["google_gmail_", t("메일")],
  ["google_drive_", t("드라이브")],
  ["google_", t("구글")],
  ["naver_blog_", t("블로그")],
  ["naver_", t("네이버")],
  ["local_", t("내 컴퓨터")],
  ["windows_", t("윈도우 창")],
  ["camera_", t("카메라")],
  ["admission_", t("입시 데이터")],
  ["schedule_", t("예약")],
  ["watch_", t("지켜보기")],
  ["sandbox_", t("작업판")],
  ["claude_code_", "Claude Code"],
  ["site_", t("사이트 레시피")],
  ["skill_", t("요령")],
  ["ui_", t("화면 조작")],
  ["self_", t("자기 점검")],
];

export function toolLabel(tool: string): string {
  const known = TOOL_LABELS[tool];
  if (known) return known;
  for (const [prefix, family] of FAMILY) {
    if (tool.startsWith(prefix)) {
      const rest = tool.slice(prefix.length).replace(/_/g, " ");
      return rest ? `${family} · ${rest}` : family;
    }
  }
  return tool.replace(/_/g, " ");
}

export type TimelineEntry =
  | { kind: "message"; at: number; message: ConversationMessage }
  | { kind: "trajectory"; at: number; trajectory: Trajectory };

/**
 * 대화와 궤적을 한 축으로 꿴다.
 *
 * 시각이 같으면 궤적을 **뒤에** 둔다 — 질문이 먼저 있고 그 다음에 일을 하기 때문이다
 * (질문은 화면이 먼저 얹으므로 서버 시각과 같은 초가 되는 일이 잦다).
 */
export function buildTimeline(messages: ConversationMessage[], trajectories: Trajectory[]): TimelineEntry[] {
  // ★ 2026-10-01 스토어 촬영 18번: 작업 기록 상자가 **질문 위**에 붙었다. 서버는 질문·답을 작업이 **끝날 때** 저장하는데
  //   상자는 **시작 시각**으로 줄을 서서, 몇 분 걸린 판은 상자가 질문보다 앞섰다. 질문이 자기 작업 번호(`metadata.job_id`)를
  //   들고 있으면 상자를 그 질문의 시각에 붙인다 — 같은 시각이면 아래 rank 가 질문 → 상자 → 답 순서로 둔다.
  //   번호가 없는 옛 기록은 예전처럼 시작 시각으로 둔다.
  const askedAt = new Map<string, number>();
  for (const message of messages) {
    const jobId = message.role === "user" ? message.metadata?.job_id : undefined;
    if (typeof jobId === "string" && jobId && !askedAt.has(jobId)) askedAt.set(jobId, message.created_at);
  }
  const entries: TimelineEntry[] = [
    ...messages.map((message) => ({ kind: "message" as const, at: message.created_at, message })),
    ...trajectories.map((trajectory) => ({
      kind: "trajectory" as const,
      at: askedAt.get(trajectory.jobId) ?? trajectory.startedAt,
      trajectory,
    })),
  ];
  // ★ 2026-09-20 노트북: 옛 비교는 시각이 같고 둘 다 메시지면 순서와 상관없이 -1 이었다(모순된 비교).
  //   서버는 질문과 답을 같은 시각으로 저장하므로 정렬이 답을 질문 위로 올렸다. 같으면 **들어온 차례**를 지킨다.
  //   같은 시각이면 질문 → 작업 기록 → 답. (질문과 답이 같은 시각으로 저장되는 일이 있어, 상자를 질문 시각에 붙이면
  //   답보다 앞에 와야 한다.)
  const rank = (entry: TimelineEntry) => (entry.kind === "trajectory" ? 1 : entry.message.role === "user" ? 0 : 2);
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => (a.entry.at - b.entry.at) || (rank(a.entry) - rank(b.entry)) || (a.index - b.index))
    .map(({ entry }) => entry);
}
