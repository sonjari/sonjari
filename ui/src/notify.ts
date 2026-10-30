// 윈도우 알림 — 언제 띄우고 무엇을 적을지 (2026-10-27 · 그룹장 피드백: 일을 던져 두고 다른 일을 하다 나중에 본다).
//
// 띄우는 것은 Rust(`src-tauri/src/notify.rs` · `notify_user`)이고, 여기는 **판단**만 한다. 새 사건을 만들지 않고 백엔드가 이미 내보내는
// 사건(`job_completed` · `job_failed` · `approval_requested` · `attention_required` · `agent_waiting_for_human` ·
// `agent_continuation_requested`)을 작업 화면이 받는 자리(`WorkspaceApp.onEvent`)에서 그대로 듣는다.
//
// 세 때(그룹장 요청):
//   ① finished — 판이 끝났을 때(완료 · 일부만 · 실패). 제목은 요청 앞부분, 본문은 결과 한 줄.
//   ② waiting  — 손자리가 사람을 기다릴 때(승인 카드 · 질문 · 로그인/보안 문자 넘겨받기 · 계속할지 묻기).
//   ③ stuck    — 막혀서 끝났을 때(모델 제한 시간 · 같은 자리에서 헛돔). 까닭은 끝맺음 문장(`delegation.timeout_detail`)과 같은 말 한 줄.
//
// 모양(대표 요청): 앱 아이콘 · 위쪽 큰 그림(종류별) · 「열기」 단추 · 끝났고 산출물이 있으면 「결과 폴더」 단추 · 출처 줄(대화 · 코드 · 조사). 소리는 윈도우 기본.
//
// 띄우지 않는 때:
//   · 설정 「알림 받기」가 꺼져 있을 때.
//   · 손자리 창이 **앞에서 사용자가 보는 중**일 때(보이고 · 안 접히고 · 포커스가 있음) — 방해일 뿐이다.
//   · 바깥 AI(Claude · Codex · 디스코드)가 맡긴 판의 ① — 그쪽이 결과를 받아 사용자에게 말한다. 알림까지 띄우면 같은 소식이 두 번 온다.
//     바깥 AI 판도 ②(사람을 기다림)와 ③(막힘)은 띄운다(2026-10-27 대표 결정): 로그인 · 보안 문자 · 결제 · 승인 카드 · 질문은 바깥 AI 가
//     대신 할 수 없고 이 PC 앞의 사람만 풀 수 있으며, 막힌 판도 바깥 AI 는 「안 됐다」만 알 뿐 프로그램 닫기 같은 할 일을 못 한다.
//     바뀌는 곳은 아래 EXTERNAL_KINDS 한 줄이다.
import { lang, t } from "./i18n";
import { GATE_TITLES } from "./workspace/humanGate";
import type { JarvisEvent, JobDetail } from "./types";

export type NotifyKind = "finished" | "waiting" | "stuck";

/** 바깥 AI 가 맡긴 판에서도 띄우는 때. */
export const EXTERNAL_KINDS: ReadonlySet<NotifyKind> = new Set<NotifyKind>(["stuck", "waiting"]);

/** 알림 설정(화면 이 PC 에만 — 화면 언어와 같은 자리). 기본 켬. */
export const NOTIFY_ENABLED_KEY = "sonjari.notify_enabled";

export function readNotifyEnabled(): boolean {
  try {
    return window.localStorage.getItem(NOTIFY_ENABLED_KEY) !== "off";
  } catch {
    return true; // 저장소를 못 읽어도 기본값(켬)
  }
}

export function writeNotifyEnabled(on: boolean): void {
  try {
    window.localStorage.setItem(NOTIFY_ENABLED_KEY, on ? "on" : "off");
  } catch {
    // 못 저장해도 이번 화면에서는 바뀐 대로 둔다(읽기는 기본값으로 돌아간다)
  }
}

/** 알림의 종류 — 위쪽 큰 그림(끝났어요 · 기다려요 · 막혔어요)을 고른다. */
export type NotifyTone = "done" | "waiting" | "stuck";

export interface ToastRequest {
  title: string;
  body: string;
  sessionId: string;
  jobId: string;
  tone: NotifyTone;
  /** 제목 아래 작은 출처 줄 — 어떤 판인가(대화 · 코드 · 조사). */
  attribution: string;
  /** 「열기」 단추 글자 · 「결과 폴더」 단추 글자(없으면 단추를 안 둔다 — 끝났고 산출물이 있을 때만). */
  openLabel: string;
  folderLabel: string | null;
  /** 큰 그림의 언어. */
  lang: "ko" | "en";
}

export interface NotifyDeps {
  /** 설정 「알림 받기」. */
  enabled: () => boolean;
  /** 손자리 창이 앞에서 사용자가 보는 중인가. */
  inFront: () => Promise<boolean>;
  /** 윈도우 알림을 띄운다. */
  show: (toast: ToastRequest) => Promise<void>;
  /** 일감 하나를 읽는다(제목 · 어디서 온 판인지 · 결과). 실패하면 null — 모르는 판으로 다룬다. */
  loadJob: (jobId: string) => Promise<JobDetail | null>;
  /** 이 판이 만든 파일이 디스크에 있는가 — 「결과 폴더」 단추를 둘지. 없으면(또는 못 읽으면) 단추를 안 둔다. */
  hasOutputs?: (jobId: string) => Promise<boolean>;
}

export interface JobFacts {
  id: string;
  kind: string;
  title: string;
  status: string;
  error: string;
  origin: string;
  via: string;
  sessionId: string;
  answer: string;
  completionState: string;
  diagnosis: Record<string, unknown> | null;
  /** 그 판이 도는 모드(code · cowork). */
  mode: string;
}

export function factsOf(job: JobDetail): JobFacts {
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const result = (job.result ?? {}) as Record<string, unknown>;
  const diagnosis = result.diagnosis && typeof result.diagnosis === "object" ? (result.diagnosis as Record<string, unknown>) : null;
  return {
    id: job.id,
    kind: String(job.kind ?? ""),
    title: String(job.title || payload.prompt || ""),
    status: String(job.status ?? ""),
    error: String(job.error || result.error || ""),
    origin: String(payload.origin ?? ""),
    via: String(payload.via ?? job.via ?? ""),
    sessionId: String(payload.session_id ?? result.session_id ?? ""),
    answer: typeof result.answer === "string" ? result.answer : "",
    completionState: String(result.completion_state ?? ""),
    diagnosis,
    mode: String(payload.workspace_mode ?? job.workspace_mode ?? ""),
  };
}

/** 바깥 AI 가 맡긴 판인가 — MCP 로 들어온 판(Claude · Codex · 디스코드)과 앱 안 Claude 가 맡긴 판(via=app)·원격(via=remote). */
export function isExternalJob(facts: JobFacts | null): boolean {
  if (!facts) return false; // 모르면 사람의 판으로 본다 — 알림을 빼먹는 쪽이 더 나쁘다
  return facts.origin === "mcp" || facts.via === "app" || facts.via === "remote";
}

const TITLE_MAX = 30;
const LINE_MAX = 90;

/** 알림 한 줄로 — 마크다운 기호 · 링크 · 줄바꿈을 걷어 낸다. */
export function oneLine(text: string, max = LINE_MAX): string {
  const plain = String(text ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^[#>\-*\s|]+/gm, "")
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > max ? `${plain.slice(0, max).trimEnd()}…` : plain;
}

function firstSentence(text: string): string {
  const line = oneLine(text, 400);
  const cut = line.search(/(?<=[.!?。다요])\s/);
  return oneLine(cut > 12 ? line.slice(0, cut) : line);
}

function requestTitle(facts: JobFacts | null): string {
  const asked = oneLine(facts?.title ?? "", TITLE_MAX);
  return asked || t("손자리");
}

/** 막혀서 끝난 판인가 — 모델이 제한 시간에 막혔거나(`timed out`) 판 기록에 모델 대기 진단이 달려 있을 때. */
export function isStuckFailure(facts: JobFacts): boolean {
  const waited = facts.diagnosis && typeof facts.diagnosis.model_wait === "object" && facts.diagnosis.model_wait;
  return Boolean(waited) || /timed out|timeout|제한 시간/i.test(facts.error);
}

/**
 * 막힌 까닭 한 줄 — 끝맺음 문장(`delegation.timeout_detail`)과 **같은 말**을 짧게. 판 기록에 달린 모델 대기 진단만 읽는다(지어내지 않는다).
 */
export function stuckReason(facts: Pick<JobFacts, "diagnosis">): string {
  const wait = (facts.diagnosis?.model_wait ?? {}) as Record<string, unknown>;
  const limit = Math.round(Number(wait.limit_sec ?? 0)) || 0;
  const phase = String(wait.phase ?? "");
  if (wait.resume_skipped === "card_full") {
    return t("그래픽카드가 가득 차 있어 다시 불러도 같은 자리에서 멈출 가능성이 큽니다 — 다른 프로그램을 닫은 뒤 「이어서 해줘」라고 보내 주세요");
  }
  if (phase === "connect") return t("모델 프로그램(Ollama)에 연결하지 못했습니다 — Ollama 가 실행 중인지 확인해 주세요");
  if (phase === "no_first_token" && limit) {
    return t("모델이 첫 글자를 {0}초 동안 내놓지 못했습니다 — 그래픽카드를 쓰는 다른 프로그램을 닫고 「이어서 해줘」라고 보내 주세요", limit);
  }
  if (phase === "mid_stream" && limit) {
    return t("답을 쓰던 도중 {0}초 동안 새 글자가 오지 않았습니다 — 「이어서 해줘」라고 보내면 이어갑니다", limit);
  }
  return t("모델이 제한 시간 안에 답하지 못해 멈췄습니다 — 「이어서 해줘」라고 보내면 이어갑니다");
}

export interface Candidate {
  kind: NotifyKind;
  jobId: string;
  /** 같은 일로 알림이 두 번 뜨지 않게(승인 카드와 안내 카드가 같은 순간 오는 경우). */
  dedupeKey: string;
  title: string;
  body: string;
  sessionId: string;
  external: boolean;
  /** 위쪽 큰 그림의 종류. */
  tone: NotifyTone;
  /** 출처 줄(대화 · 코드 · 조사). */
  attribution: string;
  /** 끝났을 때만 — 산출물이 있으면 「결과 폴더」 단추를 둘 수 있는 알림인가. */
  mayHaveFolder: boolean;
}

/** 어떤 판인가 — 알림 출처 줄. */
export function attributionOf(facts: JobFacts | null): string {
  if (facts?.kind === "research") return t("조사");
  if (facts?.mode === "code") return t("코드");
  return t("대화");
}

/** 판이 끝난 사건(`job_completed` · `job_failed`)의 알림. 대화·조사가 아닌 판(음성 · 받아쓰기)은 안 띄운다. */
export function candidateForFinished(event: "job_completed" | "job_failed", jobId: string, facts: JobFacts | null, fallbackError = ""): Candidate | null {
  if (facts && facts.kind && facts.kind !== "chat" && facts.kind !== "research") return null;
  const external = isExternalJob(facts);
  const base = { jobId, title: requestTitle(facts), sessionId: facts?.sessionId ?? "", external, attribution: attributionOf(facts) };
  if (event === "job_completed") {
    const answer = facts?.answer ? firstSentence(facts.answer) : "";
    const partial = facts?.completionState === "partial";
    const lead = partial ? t("일부만 끝났습니다") : t("끝났습니다");
    return { ...base, kind: "finished", tone: "done", mayHaveFolder: true, dedupeKey: `finished:${jobId}`, body: answer ? `${lead} — ${answer}` : lead };
  }
  const merged: JobFacts = facts ?? { id: jobId, kind: "", title: "", status: "failed", error: fallbackError, origin: "", via: "", sessionId: "", answer: "", completionState: "", diagnosis: null, mode: "" };
  const withError = merged.error ? merged : { ...merged, error: fallbackError };
  if (isStuckFailure(withError)) {
    return { ...base, kind: "stuck", tone: "stuck", mayHaveFolder: false, dedupeKey: `stuck:${jobId}`, body: stuckReason(withError) };
  }
  const why = oneLine(withError.error.replace(/^[a-z_]+:\s*/i, ""));
  return { ...base, kind: "finished", tone: "stuck", mayHaveFolder: false, dedupeKey: `finished:${jobId}`, body: why ? t("끝내지 못했습니다 — {0}", why) : t("끝내지 못했습니다") };
}

/** 사람을 기다리는 사건(승인 · 질문 · 사람이 해야 하는 화면 · 계속할지 묻기)의 알림. 모르는 사건이면 null. */
export function candidateForWaiting(event: JarvisEvent, facts: JobFacts | null): Candidate | null {
  const payload = (event.payload ?? {}) as Record<string, unknown>;
  const jobId = String(payload.job_id ?? "");
  const external = isExternalJob(facts);
  const base = { jobId, title: requestTitle(facts), sessionId: facts?.sessionId ?? "", external, attribution: attributionOf(facts), mayHaveFolder: false };
  const waiting = { ...base, kind: "waiting" as const, tone: "waiting" as const };
  switch (event.event) {
    case "approval_requested": {
      const target = (payload.target ?? {}) as Record<string, unknown>;
      const question = oneLine(String(target.question ?? ""));
      const nonce = String(payload.nonce ?? jobId);
      if (question) return { ...waiting, dedupeKey: `approval:${nonce}`, body: t("질문이 있습니다 — {0}", question) };
      const what = oneLine(String(target.label || target.place || target.path || payload.tool_name || ""), 60);
      return { ...waiting, dedupeKey: `approval:${nonce}`, body: what ? t("승인이 필요합니다 — {0}", what) : t("승인이 필요합니다") };
    }
    case "attention_required": {
      const title = oneLine(String(payload.title ?? ""), 50);
      if (!title) return null;
      const message = oneLine(String(payload.message ?? ""), 80);
      return { ...waiting, dedupeKey: `gate:${jobId}`, body: message ? `${title} — ${message}` : title };
    }
    case "agent_waiting_for_human": {
      const code = String(payload.code ?? "");
      const title = GATE_TITLES[code] ?? t("사람이 해 주셔야 하는 화면이에요");
      const message = oneLine(String(payload.message ?? "").replace(/\*\*/g, "").split("\n\n")[0], 80);
      return { ...waiting, dedupeKey: `gate:${jobId}`, body: message ? `${title} — ${message}` : title };
    }
    case "agent_continuation_requested": {
      const reason = String(payload.reason ?? "");
      const report = (payload.report ?? {}) as Record<string, unknown>;
      if (reason === "stuck") {
        const said = oneLine(String(report.message || report.blocked || ""));
        return { ...base, kind: "stuck", tone: "stuck" as const, dedupeKey: `continue:${jobId}`, body: said ? t("같은 자리에서 막혔습니다 — {0}", said) : t("같은 자리에서 막혔습니다") };
      }
      if (reason.startsWith("human_gate")) {
        return { ...waiting, dedupeKey: `gate:${jobId}`, body: t("사람이 해 주셔야 하는 화면이 있습니다") };
      }
      return { ...waiting, dedupeKey: `continue:${jobId}`, body: t("시간이 다 되어 계속할지 묻고 있습니다") };
    }
    default:
      return null;
  }
}

const WAITING_EVENTS = new Set(["approval_requested", "attention_required", "agent_waiting_for_human", "agent_continuation_requested"]);

export type NotifyOutcome =
  | "shown"
  | "ignored" // 알림 대상 사건이 아님
  | "disabled" // 설정이 꺼짐
  | "in_front" // 창이 앞에 있음
  | "external" // 바깥 AI 가 맡긴 판의 ①(끝남 — 그쪽이 결과를 말한다)
  | "duplicate";

export function createNotifier(deps: NotifyDeps) {
  const seen: string[] = [];

  async function decide(candidate: Candidate | null): Promise<NotifyOutcome> {
    if (!candidate) return "ignored";
    if (!deps.enabled()) return "disabled";
    if (candidate.external && !EXTERNAL_KINDS.has(candidate.kind)) return "external";
    if (seen.includes(candidate.dedupeKey)) return "duplicate";
    let front = false;
    try {
      front = await deps.inFront();
    } catch {
      front = false; // 못 알아내면 띄운다 — 알림을 놓치는 쪽이 더 나쁘다
    }
    if (front) return "in_front";
    seen.push(candidate.dedupeKey);
    if (seen.length > 60) seen.shift();
    // 「결과 폴더」 단추 — 끝났고(완료·일부만) 만든 파일이 디스크에 있을 때만. 못 읽으면 없는 것으로(단추 없이 띄운다).
    let folder = false;
    if (candidate.mayHaveFolder && deps.hasOutputs) {
      folder = await deps.hasOutputs(candidate.jobId).catch(() => false);
    }
    await deps.show({
      title: candidate.title, body: candidate.body, sessionId: candidate.sessionId, jobId: candidate.jobId,
      tone: candidate.tone, attribution: candidate.attribution, openLabel: t("열기"),
      folderLabel: folder ? t("결과 폴더") : null, lang: lang(),
    });
    return "shown";
  }

  /** 백엔드 사건 하나를 듣는다. 늘 끝까지 조용히 — 알림이 안 떠도 화면은 멀쩡해야 한다. */
  async function onEvent(event: JarvisEvent): Promise<NotifyOutcome> {
    try {
      const payload = (event.payload ?? {}) as Record<string, unknown>;
      const jobId = String(payload.job_id ?? "");
      if (!jobId) return "ignored";
      const isFinish = event.event === "job_completed" || event.event === "job_failed";
      if (!isFinish && !WAITING_EVENTS.has(event.event)) return "ignored";
      if (!deps.enabled()) return "disabled";
      const job = await deps.loadJob(jobId).catch(() => null);
      const facts = job ? factsOf(job) : null;
      const candidate = isFinish
        ? candidateForFinished(event.event as "job_completed" | "job_failed", jobId, facts, String(payload.error ?? ""))
        : candidateForWaiting(event, facts);
      return await decide(candidate);
    } catch {
      return "ignored";
    }
  }

  return { onEvent };
}

// --- Tauri 쪽 연결 ------------------------------------------------------------------------------

/** 손자리 창이 앞에 있는가. Tauri 면 Rust(`window_in_front`: 보임 · 안 접힘 · 포커스), 아니면(브라우저 · 개발) 문서 포커스. */
export async function windowInFront(): Promise<boolean> {
  if (typeof window !== "undefined" && (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<boolean>("window_in_front");
  }
  return typeof document !== "undefined" && document.visibilityState === "visible" && document.hasFocus();
}

/** 윈도우 알림을 띄운다. Tauri 가 아니면(브라우저) 아무것도 안 한다. */
export async function showToast(toast: ToastRequest): Promise<void> {
  if (typeof window === "undefined" || !(window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("notify_user", {
    title: toast.title, body: toast.body, sessionId: toast.sessionId, jobId: toast.jobId,
    tone: toast.tone, lang: toast.lang, attribution: toast.attribution, openLabel: toast.openLabel, folderLabel: toast.folderLabel,
  });
}
