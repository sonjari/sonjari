/**
 * 일감 목록의 판정 — **화면 없이 검사할 수 있게** 여기 모은다 (R1).
 *
 * 이 창은 지금까지 채팅만 보여 줬다. 그런데 백엔드는 컴퓨터를 쓰는 에이전트고,
 * 작업 중앙값이 143초다(2026-08-19 실측 50건: 중앙값 143초 · 상위10% 314초 ·
 * 최장 2시간 52분). 채팅창이 다루도록 만들어진 시간 규모가 아니다.
 *
 * 그 50건 중 8건이 취소였다(16%). 실패가 아니라 **기다리다 포기한 것**에 가깝다 —
 * 대화를 옮기면 도는 일이 화면에서 사라졌으니 살아 있는지 알 방법이 없었다.
 * 그래서 일감을 대화와 같은 층에 올린다.
 */
import { t, locale } from "../i18n";
import type { JobSummary, ScheduleRow, WorkspaceMode } from "../types";

/** 아직 끝나지 않은 상태들. 이 목록에 있으면 사이드바 위층에 남는다. */
export const LIVE_STATUSES = new Set(["queued", "running", "waiting_approval", "waiting_continuation"]);

export function isLive(job: JobSummary): boolean {
  return LIVE_STATUSES.has(job.status);
}

/**
 * 살아 있는 것 안에서의 차례. 작은 것이 위다.
 *
 * 사람이 손대야 움직이는 것(승인·계속진행)이 **도는 것보다 위**에 온다. 놓치면
 * 작업이 아무 말 없이 멈춰 있기 때문이다 — 그게 취소 16%의 절반쯤 되는 이유다.
 */
const LIVE_ORDER: Record<string, number> = {
  waiting_approval: 0,
  waiting_continuation: 1,
  running: 2,
  queued: 3,
};

/** 끝난 것 중 목록에 남길 개수. 지난 대화가 아래 층에 또 있으므로 짧게 둔다. */
export const DONE_KEEP = 6;

export interface JobGroups {
  live: JobSummary[];
  done: JobSummary[];
}

export function groupJobs(jobs: JobSummary[], keep = DONE_KEEP): JobGroups {
  const live = jobs.filter(isLive).sort(
    (a, b) => (LIVE_ORDER[a.status] ?? 9) - (LIVE_ORDER[b.status] ?? 9) || a.created_at - b.created_at,
  );
  const done = jobs
    .filter((job) => !isLive(job))
    .sort((a, b) => (b.finished_at ?? b.updated_at) - (a.finished_at ?? a.updated_at))
    .slice(0, keep);
  return { live, done };
}

/**
 * 이 일감이 얼마나 걸렸나(초). 도는 중이면 **지금까지**.
 *
 * 시작 시각이 없으면(아직 차례를 기다리는 중) 0 이다 — 만든 시각부터 세면
 * 큐에서 기다린 시간이 일한 시간으로 둔갑한다(사고 S 의 셋째와 같은 모양).
 */
export function elapsedSec(job: JobSummary, now = Date.now() / 1000): number {
  if (!job.started_at) return 0;
  const end = job.finished_at ?? now;
  return Math.max(0, Math.round(end - job.started_at));
}

/** 계기값 표기. 화면에서는 `--font-mono` + tabular-nums 로 그린다. */
export function durationLabel(seconds: number): string {
  if (seconds < 60) return t("{0}초", seconds);
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("{0}분 {1}초", minutes, seconds % 60);
  return t("{0}시간 {1}분", Math.floor(minutes / 60), minutes % 60);
}

const STATUS_LABELS: Record<string, string> = {
  queued: t("차례 기다리는 중"),
  running: t("일하는 중"),
  waiting_approval: t("승인을 기다림"),
  waiting_continuation: t("계속할지 물음"),
  completed: t("끝"),
  failed: t("못 끝냄"),
  cancelled: t("멈춤"),
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/**
 * 그 줄에 적는 상태 말. **"끝"과 "덜 채우고 끝"을 가른다.**
 *
 * `completion_state` 가 `complete` 가 아닌 채로 끝난 판이 있다 — 시킨 것을 다
 * 못 채웠는데 예산이 떨어져 답한 경우다. 그걸 그냥 "끝"으로 적으면 화면이
 * 다 됐다고 거짓말한다(색은 이미 `toneOf` 가 주황으로 가른다).
 */
export function jobStateLabel(job: JobSummary): string {
  // ★ 2026-09-17 첫 실행 E2E: 「한 줄로 자기소개해 줘」가 「덜 채우고 끝」으로 찍혔다. 대조할 요구가 없는 대화는
  //   `answered`·`unmeasured` 로 끝나는데, `complete` 가 아니면 다 덜 채웠다고 적고 있었다. 색(`toneOf`)은 이미
  //   `partial` 만 갈랐다 — 글자와 색이 서로 다른 말을 했다. 둘 다 `partial` 로 맞춘다.
  if (job.status === "completed" && job.completion_state === "partial") {
    return t("덜 채우고 끝");
  }
  return statusLabel(job.status);
}

/**
 * 색으로 갈리는 축 (P3 규칙: 유채색은 뜻이 있을 때만).
 *   hold  주황 — 사람이 눌러야 움직인다
 *   agent 보라 — 자비스가 일하는 중
 *   safe  초록 — 됐다
 *   fail  빨강 — 안 됐다
 *   mute  무채 — 그 밖에
 */
export type JobTone = "hold" | "agent" | "safe" | "fail" | "mute";

export function toneOf(job: JobSummary): JobTone {
  if (job.status === "waiting_approval" || job.status === "waiting_continuation") return "hold";
  if (job.status === "running") return "agent";
  if (job.status === "failed") return "fail";
  // 끝나긴 했는데 시킨 것을 다 못 채운 판. `complete` 가 아닌 값이 그 뜻이다 —
  // 이걸 초록으로 칠하면 화면이 "다 됐다"고 거짓말한다.
  if (job.status === "completed") return job.completion_state === "partial" ? "hold" : "safe";
  return "mute";
}

/** 위험 등급이 사람에게 뜻하는 것. 숫자만 보여 주면 아무 말도 안 한 것이다. */
const RISK_LABELS: Record<string, string> = {
  L0: t("읽기만"),
  L1: t("조작"),
  L2: t("되돌릴 수 없음"),
  L3: t("되돌릴 수 없음"),
  L4: t("되돌릴 수 없음"),
};

export function riskLabel(level: string): string {
  return RISK_LABELS[level] ?? level;
}

/**
 * 한 줄에 적는 계기값. 여기 적히는 것은 전부 실제로 센 값이다.
 *
 * 시도 횟수는 1보다 클 때만 적는다 — 모든 줄에 "1회"라고 붙어 있으면 아무도
 * 안 읽고, 안 읽히는 경보는 없는 것과 같다(사고 S).
 */
export function jobMetrics(job: JobSummary, now = Date.now() / 1000): string[] {
  const parts: string[] = [];
  const seconds = elapsedSec(job, now);
  if (seconds > 0 || job.status === "running") parts.push(durationLabel(seconds));
  if (job.steps > 0) parts.push(t("{0}걸음", job.steps));
  if (job.attempts > 1) parts.push(t("{0}번째 시도", job.attempts));
  return parts;
}

/** 예약: 아직 돌 것만 위에. 취소·완료된 예약은 목록을 채울 뿐이다. */
export function pendingSchedules(rows: ScheduleRow[], now = Date.now() / 1000): ScheduleRow[] {
  return rows.filter((row) => row.status === "pending" || row.status === "dispatching"
    // 한 번만 도는 루틴은 돌고 나면 「ran」이다. 결과(건수 · 깨짐)를 볼 자리가 여기뿐이라 하루는 남긴다.
    || (row.kind === "routine" && row.status === "ran" && now - row.updated_at < 86_400))
    .sort((a, b) => a.run_at - b.run_at);
}

/** 루틴 마지막 회차의 작은 줄. 백엔드 `routine.summary` 와 같은 모양. */
export interface RoutineResult {
  status: string;
  count: number;
  total_on_site?: number | null;
  problems?: string[];
  notes?: string[];
  out?: string;
  at?: number;
}

export function routineResult(row: ScheduleRow): RoutineResult | null {
  if (row.kind !== "routine" || !row.last_result) return null;
  try {
    const parsed = JSON.parse(row.last_result) as RoutineResult;
    return parsed && typeof parsed.status === "string" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * 루틴 줄의 결과 한 마디 (2026-10-23 · 전략안 §55-39 「루틴 카드 한 장」).
 *
 * 「0건」과 「깨짐」을 **다른 말로** 쓴다 — 깨진 회차를 0건처럼 보이면 사람은 「오늘은 새 공고가 없다」로 읽는다.
 */
export function routineLine(row: ScheduleRow, now = Date.now() / 1000): string {
  const result = routineResult(row);
  if (!result) return t("모델 없이 · 아직 안 돎");
  const at = result.at ? new Date(result.at * 1000) : null;
  const when = at
    ? (now - result.at! < 86_400
      ? at.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })
      : at.toLocaleDateString(locale(), { month: "short", day: "numeric" }))
    : "";
  const first = (result.problems ?? [])[0] ?? "";
  switch (result.status) {
    case "ok":
    case "empty":
      return t("모델 없이 · {0}건 · {1}", result.count, when);
    case "broken":
      return t("깨짐 · {0}", first);
    case "failed":
      return t("못 받음 · {0}", when);
    case "refused":
      return t("멈춤 · {0}", first);
    default:
      return result.status;
  }
}

export function routineFailed(row: ScheduleRow): boolean {
  const status = routineResult(row)?.status ?? "";
  return status === "broken" || status === "failed" || status === "refused";
}

/** 언제 도는가. 지났는데 아직 안 돌았으면 그렇게 말한다(숨기지 않는다). */
export function scheduleLabel(row: ScheduleRow, now = Date.now() / 1000): string {
  const seconds = Math.round(row.run_at - now);
  if (seconds <= 0) return t("곧 시작");
  if (seconds < 3600) return t("{0}분 뒤", Math.max(1, Math.round(seconds / 60)));
  if (seconds < 86_400) return t("{0}시간 뒤", Math.round(seconds / 3600));
  return t("{0}일 뒤", Math.round(seconds / 86_400));
}

/**
 * 정확히 몇 시. 위의 상대 표기와 **짝**이다.
 *
 * 여기가 `timeLabel`(오늘이면 시:분, 아니면 월/일)이었는데, 하루 넘게 남은 예약은
 * 두 칸이 똑같이 "8월 20일"로 나왔다 — 같은 말이 두 번 적히면 한 칸은 버려진 것이다.
 * 예약은 **시각이 요점**이므로 날짜를 줄이더라도 시:분은 남긴다.
 */
export function scheduleWhen(row: ScheduleRow, now = Date.now() / 1000): string {
  const date = new Date(row.run_at * 1000);
  const clock = date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (row.run_at - now < 86_400) return clock;
  return `${date.toLocaleDateString(locale(), { month: "short", day: "numeric" })} ${clock}`;
}

/**
 * 지금 화면이 따라가야 할 작업.
 *
 * ## 왜 필요한가 (2026-08-28)
 *
 * `activeJobId` 를 **이 화면에서 보낸 대기열의 맨 앞**에서만 가져왔다. 그래서
 * 이 창 밖에서 시작된 일은 영원히 안 보였다 — 오른쪽 작업공간이 `0 step`,
 * "저장소를 읽을 준비가 됐습니다" 로 멈춰 있는 동안 왼쪽에서는 같은 일이
 * **6분 58초째 일하는 중**이었다.
 *
 * 벤치만의 문제가 아니다. 이 창 밖에서 시작되는 일은 흔하다:
 *
 *   - 앱을 껐다 켰다 — 일하던 잡이 「준비됐다」로 보인다
 *   - MCP(클로드 데스크톱)로 시킨 일
 *   - 예약으로 도는 일 · 위성 노트북에서 넘어온 일
 *   - 관찰 초소가 스스로 시작한 일
 *
 * 맡겨 놓고 진행을 못 보면 맡길 수가 없다. 그래서 대기열이 비면 **서버에서
 * 실제로 도는 것**을 따라간다. 사람이 손대야 하는 것(승인·계속진행)이 먼저다 —
 * `LIVE_ORDER` 와 같은 규율이다.
 */
export function jobToFollow(pendingHead: string, jobs: JobSummary[]): string {
  if (pendingHead) return pendingHead;
  const live = jobs.filter(isLive).sort(
    (a, b) => (LIVE_ORDER[a.status] ?? 9) - (LIVE_ORDER[b.status] ?? 9) || b.created_at - a.created_at,
  );
  return live[0]?.id ?? "";
}

/** 이 창이 따라가는 판 하나 — 어느 방(대화)의 것인지만 본다. */
export interface FollowedJob {
  jobId: string;
  sessionId: string;
}

/**
 * 따라가는 판 가운데 **지금 보고 있는 방의 것**만 돌려준다. 다른 방의 판이면 빈 글 (2026-10-09 낮 · 대표가 본 화면).
 *
 * 창은 「지금 도는 판은 하나」로 알고, 그 판의 생각·진행·멈춤 단추·「덧붙일 말」 입력창을 **어느 대화를 보고 있든** 그렸다.
 * 사람의 판이 30초~몇 분일 때는 드러나지 않았다. 바깥 AI 가 맡긴 코드 판은 시간 제한 없이 돈다 — 그동안 대표가 자기 대화로
 * 돌아가 「오늘 뉴스 알아봐 줘」를 보냈더니, 그 대화에 맡긴 판의 생각(코드 상수 목록)이 흘렀고 「새 대화」는 눌리지 않았다.
 * 서버는 제대로 했다(맡긴 판이 비켜 주고 사람의 판이 먼저 돌았다) — 화면만 틀렸다.
 *
 * 방을 모르는 판(옛 서버 · 방 없이 만든 판)은 지금까지처럼 여기 것으로 친다.
 */
export function jobShownHere(activeJobId: string, viewedSession: string, pending: FollowedJob[], jobs: JobSummary[]): string {
  if (!activeJobId) return "";
  const room =
    pending.find((item) => item.jobId === activeJobId)?.sessionId
    || jobs.find((job) => job.id === activeJobId)?.session_id
    || "";
  return !room || room === viewedSession ? activeJobId : "";
}

/**
 * 방금 **돌기 시작한** 판을 줄 맨 앞으로 옮긴다. 줄에 없거나 이미 맨 앞이면 받은 것을 그대로 돌려준다(같은 배열).
 *
 * 줄의 맨 앞이 「지금 답하고 있는 판」이다(`syncPending`). 들어온 순서대로 돌 때는 늘 맞았다. 이제 서버는 사람의 판을 맡긴 판보다
 * 먼저 꺼내고, 돌던 맡긴 판은 비켜 줬다 다시 줄에 선다 — 들어온 순서와 도는 순서가 달라진다. 맨 앞을 안 바꾸면 사람은 자기 판이
 * 도는 동안 비켜 준 판의 멈춘 화면을 본다.
 */
export function withRunningFirst<T extends FollowedJob>(pending: T[], startedJobId: string): T[] {
  const at = pending.findIndex((item) => item.jobId === startedJobId);
  if (at <= 0) return pending;
  return [pending[at], ...pending.slice(0, at), ...pending.slice(at + 1)];
}

/** 비켜 준 판을 줄 맨 뒤로 보낸다. 줄에 없거나 혼자면 받은 것을 그대로 돌려준다. */
export function withYieldedLast<T extends FollowedJob>(pending: T[], yieldedJobId: string): T[] {
  const at = pending.findIndex((item) => item.jobId === yieldedJobId);
  if (at < 0 || at === pending.length - 1) return pending;
  return [...pending.slice(0, at), ...pending.slice(at + 1), pending[at]];
}

/** 왼쪽 목록의 대화 한 줄에 필요한 만큼. */
export interface RoomRow {
  session_id: string;
  title: string;
  preview: string;
  message_count: number;
  updated_at: number;
  has_summary: boolean;
  caller?: string;
}

/**
 * 대화 목록에 **지금 도는 판의 방**이 빠져 있으면 맨 위에 한 줄을 세운다 (2026-10-09 저녁 · 대표가 본 화면).
 *
 * 대화는 판이 끝나 글이 저장돼야 목록에 선다. 사람의 판은 몇십 초라 드러나지 않았다. 바깥 AI 가 맡긴 코드 판은 한 시간씩 돈다 —
 * 그동안 왼쪽 목록에 그 방이 없어서, 대표는 다른 대화에 있다가 「맡긴 일이 끝난 줄」 알았다(그 판은 40분째 돌고 있었다).
 * 「도는 중」 점은 목록의 줄에 붙는데 줄이 없으니 붙을 자리가 없었다.
 *
 * 세우는 줄은 그 판의 제목과 시작 시각만 쓴다. 판이 끝나 진짜 줄이 생기면 이 줄은 저절로 빠진다(같은 방이면 진짜 줄을 쓴다).
 * 맡긴 판(origin 이 mcp)은 맡긴 쪽 표시가 붙도록 caller 를 채운다.
 */
export function withLiveRooms<T extends RoomRow>(sessions: T[], jobs: JobSummary[], delegatedCaller = "mcp"): Array<T | RoomRow> {
  const known = new Set(sessions.map((row) => row.session_id));
  const added: RoomRow[] = [];
  for (const job of [...jobs].sort((a, b) => b.created_at - a.created_at)) {
    if (!isLive(job) || !job.session_id || known.has(job.session_id)) continue;
    // 앱 안 Claude 가 맡긴 판(via=app)은 맡긴 Claude 대화 안에 묶여 보인다 — 제 방을 따로 세우지 않는다(2026-10-26 대표).
    if (job.via === "app") continue;
    known.add(job.session_id);
    added.push({
      session_id: job.session_id,
      title: job.title || "",
      preview: "",
      message_count: 0,
      updated_at: job.started_at ?? job.created_at,
      has_summary: false,
      ...(job.origin === "mcp" ? { caller: delegatedCaller } : {}),
    });
  }
  return added.length ? [...added, ...sessions] : sessions;
}

/** 줄에 선 판 하나가 화면의 어디에 놓이나. */
export type QueuedLanding =
  /** 지금 보고 있는 대화에 놓는다 — 그 대화의 판이다. */
  | "here"
  /** 그 판의 방을 열어 화면을 그리로 옮긴다 — 바깥 AI 가 맡긴 판. */
  | "own-room"
  /** 화면은 그대로 두고 왼쪽 목록에만 올린다 — 사람이 자기 일을 기다리는 중. */
  | "listed"
  /** 이 화면의 일이 아니다. */
  | "elsewhere";

/**
 * 바깥 AI(Claude·Codex)가 맡긴 판은 **제 방으로 연다** (2026-10-09).
 *
 * 2026-09-16 부터 맡긴 판은 「대화가 달라도 따라간다」였다 — 그 전에는 통째로 안 보였기 때문이다. 그런데 따라가는 방법이
 * **사람이 보고 있던 대화에 그 과제 글을 끼워 넣는 것**이었다. 방은 따로 주면서(2026-09-29) 화면만 섞고 있었다.
 * 대표가 실제로 본 것: 자기 대화 한가운데에 Claude 가 보낸 긴 과제 글이 들어오고, 작업 폴더 표시는 자기가 보던 대화의 것이었다.
 * 「클로드가 시킨 일이면 딱 새 채팅으로 나와야 한다.」
 *
 * 다른 범용 에이전트들도 같은 쪽이다: 세션에 출처를 적어 두고 사람의 대화와 섞지 않는다(Codex · Hermes · Goose · Cline 의 소스에서 확인).
 *
 * 사람이 자기 일을 보내 놓고 기다리는 중이면 화면을 뺏지 않는다 — 그때는 왼쪽 목록에만 올린다.
 */
export function whereAQueuedJobLands(input: {
  delegated: boolean;
  queuedSession: string;
  viewedSession: string;
  /** 이 화면에서 답을 기다리는 판의 수. */
  waitingHere: number;
}): QueuedLanding {
  const sameRoom = !input.queuedSession || input.queuedSession === input.viewedSession;
  if (!input.delegated) return input.queuedSession === input.viewedSession ? "here" : "elsewhere";
  if (sameRoom) return "here";
  return input.waitingHere > 0 ? "listed" : "own-room";
}

/**
 * 오른쪽 작업 창이 보일 모드와 폴더 (2026-10-09).
 *
 * 작업 창은 「사람이 화면에서 고른」 모드와 폴더를 그렸다. 사람의 판이면 그게 그 판의 것이다. 바깥 AI 가 맡긴 판은 아니다 —
 * 대표가 본 것: Claude 가 다른 폴더의 코드 일을 맡겼는데 작업 창에는 자기가 골라 둔 폴더의 파일 목록이 떴다.
 * 맡긴 판을 보는 동안에는 **그 판의** 것을 보인다. 사람의 판은 지금까지와 똑같다.
 */
/**
 * 오른쪽 작업 창의 **폭** — 창 틀의 모드를 따른다 (2026-10-11).
 *
 * 대표 화면: Code 탭을 보는 중에 바깥 AI 가 맡긴 일반(Cowork) 일이 떴더니, 작업 창의 내용이 왼쪽 절반 폭에만 몰리고 오른쪽이
 * 텅 비었다. 창 틀(`mode-code`)은 사람이 고른 모드로 자리를 나누고(Code 는 화면 절반), 칸 자신은 `paneContext` 가 준 **그 일의**
 * 모드로 폭을 정해(Cowork 는 468) 둘이 어긋난 것이다. 자리를 나누는 쪽은 틀이다 — 폭은 틀을 따르고, **무엇을 보일지**만 일을 따른다.
 */
export function paneWidth(input: { frame: WorkspaceMode; stage: boolean; stageWidth?: number }): string | number {
  if (input.frame === "code") return "100%";
  return input.stage && input.stageWidth ? input.stageWidth : 468;
}

export function paneContext(
  job: JobSummary | undefined,
  person: { mode: WorkspaceMode; codeWorkspace: string },
): { mode: WorkspaceMode; codeWorkspace: string } {
  if (!job || job.origin !== "mcp" || job.workspace_mode === undefined) return person;
  return {
    mode: job.workspace_mode === "code" ? "code" : "cowork",
    codeWorkspace: job.code_workspace ?? "",
  };
}
