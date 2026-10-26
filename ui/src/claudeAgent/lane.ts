/**
 * **Claude 갈래** — 모델 칸에서 「Claude Agent」를 고른 대화의 일을 맡는다 (2026-10-26 · ADR 고침 4 · 구현 1판).
 *
 * 일하는 것은 앤트로픽의 CLI(Rust `claude_agent.rs`)이고, 여기서는 그 흐름을 손자리 화면이 아는 사건으로 바꿀 뿐이다
 * (파일럿 `PilotClient` 와 같은 사건 순서). 다른 점은 하나 — **클로드가 손자리에게 맡긴 판**을 같은 컴퓨터 칸 · 같은 눈금자에 잇는다.
 *
 * ## 걸음 잇기
 *
 * 눈금자의 칸(`Slot`)은 「누가(actor) · 어느 판의 · 몇 번째 걸음」이다. 클로드 걸음은 흐름에서, 손자리 걸음은 맡긴 판(origin=mcp)의
 * 진행 사건과 서버 걸음 기록에서 온다. 번호는 **시간순 자리**다 — 클로드가 결과를 기다리는 사이 손자리 걸음이 끼어드는 그대로.
 * 맡긴 판 번호를 알기 전에 지나간 손자리 걸음은 서버 기록으로 채운다(`pull`).
 *
 * ## 지키는 것
 * - 영수증 숫자는 CLI 의 `result` 줄에 있는 값만(`cost_usd` 없으면 null). 손자리 쪽은 「0원 · 내 PC N걸음」 — N 은 눈금자에 실제로 선 칸 수.
 * - 키는 여기로 오지 않는다(Rust 가 DPAPI 파일에서 직접 꺼낸다).
 */
import { t } from "../i18n";
import { toolLabel } from "../trajectory";
import type {
  AgentChatResult, AgentStreamEvent, ChatAttachment, ClaudeAgentStatus, ClaudeHandoff, ConversationHistory,
  ConversationMessage, ConversationSummary, DelegationSummary, JarvisEvent, JobDetail, JobOutput, JobSummary, StepActor,
  WorkspaceMode,
} from "../types";
import type { Observation, ObservationKind, StepRow } from "../workspace/observation";
import type { PilotModelId } from "../pilot/PilotModelPicker";

export const CLAUDE_JOB_PREFIX = "claude-";
const STORE_KEY = "sonjari.claude-agent.store.v1";
/** 맡긴 판 번호를 알기 전에 온 손자리 사건을 잠시 쥐고 있는 시간 — 맡기기 결과는 보통 1초 안에 돌아온다. */
const BUFFER_SEC = 120;

export interface AgentRunRequest {
  job_id: string;
  prompt: string;
  history: Array<{ role: string; content: string }>;
  attachments: ChatAttachment[];
  workspace_mode: WorkspaceMode;
  code_workspace: string;
  resume_session_id: string;
  model: PilotModelId;
  lang: string;
  /** 손자리 권한 메뉴 값 — 코드 모드에서 클로드 코드 권한 모드로(Rust `claude_permission`). */
  permission_mode?: string;
  /** 입력창 생각 깊이 칩 — `--effort` 로(Rust `claude_effort`). */
  effort?: string;
}

/** 클로드를 돌리는 손 — 앱에서는 Tauri(`tauriRunner.ts`), 리허설에서는 손으로 만든 흐름(`fixtures/claudeHands.ts`). */
export interface ClaudeRunner {
  status(): Promise<ClaudeAgentStatus>;
  /** 옆에 끼울 파일(손자리 MCP · 「앱 안」 지침)을 본체가 쓰게 한다. */
  prepare(lang: string): Promise<void>;
  run(request: AgentRunRequest, onStream: (event: AgentStreamEvent) => void): Promise<AgentChatResult>;
  cancel(jobId: string): Promise<void>;
  /** 「키 넣기」 — 복사해 둔 키를 본체가 클립보드에서 직접 읽는다. 실패는 까닭 코드(`not_an_api_key` · `subscription_token` …). */
  keyFromClipboard(): Promise<{ ok: boolean; error?: string }>;
}

/** 손자리 판의 기록을 읽는 문 — 보통은 원래 클라이언트(서버). */
export interface LocalSource {
  listSteps(jobId: string): Promise<{ items: StepRow[] }>;
  getStep(jobId: string, step: number): Promise<Observation | null>;
  listOutputs(jobId: string): Promise<{ items: JobOutput[] }>;
  cancelJob(jobId: string): Promise<unknown>;
}

interface Slot { actor: StepActor; jobId: string; step: number; at: number }
interface Link { localJobId: string; toolUseId: string; task: string }

type StoredJob = JobSummary & {
  answer?: string;
  /** 클로드 자신의 걸음(클로드 걸음 번호 = `step`). */
  trace: Observation[];
  slots: Slot[];
  links: Link[];
  handoffs: ClaudeHandoff[];
  claude_session_id?: string;
  model?: string;
};

interface Store { messages: Record<string, ConversationMessage[]>; jobs: StoredJob[] }

function emptyStore(): Store {
  return { messages: {}, jobs: [] };
}

const now = () => Date.now() / 1000;
let messageSeq = 0;
const nextMessageId = () => Date.now() * 1000 + (++messageSeq % 1000);

/** 화면 「지금」 줄의 말 — 도구 이름이 아니라 하는 일. */
export function agentToolMessage(tool: string): string {
  const name = tool.replace(/^mcp__.+?__/, "");
  if (name === "sonjari_task") return t("손자리에게 맡기는 중");
  if (name === "sonjari_task_status") return t("손자리가 하는 일을 기다리는 중");
  if (name === "sonjari_guide") return t("손자리 사용법을 읽는 중");
  switch (tool) {
    case "Read": return t("파일을 읽는 중");
    case "Edit": case "MultiEdit": case "Write": case "NotebookEdit": return t("파일을 고치는 중");
    case "Glob": case "Grep": return t("파일을 찾는 중");
    case "Bash": case "PowerShell": return t("명령을 실행하는 중");
    default: return t("{0} 실행 중", toolLabel(tool));
  }
}

export function agentToolKind(tool: string, args: Record<string, unknown>): ObservationKind {
  if (tool === "Read") {
    const path = String(args.file_path ?? args.path ?? "").toLowerCase();
    return /\.(md|txt|pdf|docx|xlsx|pptx|hwp|hwpx)$/.test(path) ? "document" : "code";
  }
  if (["Edit", "MultiEdit", "Write", "NotebookEdit"].includes(tool)) return "artifact";
  if (tool === "Glob" || tool === "Grep") return "files";
  if (tool === "Bash" || tool === "PowerShell") return "code";
  return "note";
}

/** 명령 걸음이 도는 동안의 본문 — 명령 한 줄(출력은 끝나면 Rust 가 만든 본문으로 바뀐다 · `claude_agent.rs::command_payload`). */
function liveCommand(tool: string, args: Record<string, unknown>): Record<string, unknown> | null {
  if (tool !== "Bash" && tool !== "PowerShell") return null;
  const command = String(args.command ?? "").trim();
  if (!command) return null;
  return { command, text: `${tool === "PowerShell" ? "PS>" : "$"} ${command}`, language: tool === "PowerShell" ? "powershell" : "bash" };
}

function stringArgs(value: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, item] of Object.entries(value ?? {})) {
    out[key] = typeof item === "string" ? item : JSON.stringify(item);
  }
  return out;
}

/**
 * 코드 모드에서 클로드가 고치는 동안의 「바뀐 줄」 — 인자에 든 글만으로(EditReplay 꼴). 몇 번째 줄인지는 아직 모르니 0(번호 안 그림).
 * 끝난 뒤 Rust 가 파일에서 자리를 찾아 줄 번호를 붙인 걸음 기록으로 바꿔 끼운다(`claude_agent.rs::edit_preview`).
 */
export function livePreview(tool: string, args: Record<string, unknown>): Record<string, unknown> {
  const command = liveCommand(tool, args);
  if (command) return command;
  const path = String(args.file_path ?? "");
  if (!path || (tool !== "Edit" && tool !== "Write")) return { text: "" };
  const before = tool === "Edit" ? String(args.old_string ?? "") : "";
  const after = String((tool === "Edit" ? args.new_string : args.content) ?? "");
  const lines = (text: string) => (text ? text.split(/\r?\n/).slice(0, 200) : []);
  return {
    path, text: "",
    edit_preview: { start_line: tool === "Write" ? 1 : 0, removed: lines(before), added: lines(after), added_count: after ? after.split(/\r?\n/).length : 0 },
  };
}

function handoffState(summary: DelegationSummary | null): ClaudeHandoff["state"] {
  const status = summary?.status ?? "";
  if (status === "done" || status === "needs_review" || status === "completed") return "done";
  if (status === "failed" || status === "cancelled") return "failed";
  return "working";
}

export class ClaudeLane {
  private store: Store;
  private chain: Promise<unknown> = Promise.resolve();
  private textBuffer = new Map<string, string>();
  /** 맡긴 판 번호 → 클로드 판 번호. */
  private linked = new Map<string, string>();
  /** 클로드 판 → 장표를 그리는 손자리 판(사건을 클로드 판 번호로 옮겨 보이므로, 답은 이 번호로 되돌려 보낸다). */
  private deckSource = new Map<string, string>();
  /** 아직 이어지지 않은 손자리 판의 사건(맡기기 결과보다 먼저 온 것). */
  private buffered = new Map<string, Array<{ at: number; event: JarvisEvent }>>();
  private prepared = "";
  /** 대화의 첫 판(앞선 대화가 없던 판). 끝나면 제목을 짓게 한다(`onFirstAnswer`). */
  private firstTurns = new Set<string>();
  local: LocalSource | null;
  /** 대화의 첫 답이 끝났을 때 — 제목 짓기(내 PC 모델 · `withClaudeLane` 이 본체 문을 단다). 실패해도 판과 상관없다. */
  onFirstAnswer: ((sessionId: string, prompt: string, answer: string) => void) | null = null;

  constructor(private readonly options: {
    emit: (event: JarvisEvent) => void;
    runner: ClaudeRunner;
    local?: LocalSource | null;
    lang?: () => string;
    storage?: Pick<Storage, "getItem" | "setItem"> | null;
  }) {
    this.local = options.local ?? null;
    this.store = this.read();
    for (const job of this.store.jobs) {
      for (const link of job.links ?? []) this.linked.set(link.localJobId, job.id);
      // 앱이 꺼진 사이 돌던 판은 끝을 모른다 — 「멈춤」으로 남긴다(돌고 있다고 거짓말하지 않는다).
      if (job.status === "running" || job.status === "queued") {
        Object.assign(job, { status: "cancelled", completion_state: "cancelled", finished_at: job.updated_at });
      }
    }
  }

  get runner(): ClaudeRunner {
    return this.options.runner;
  }

  owns(jobId: string): boolean {
    return jobId.startsWith(CLAUDE_JOB_PREFIX);
  }

  /** 클로드 판 화면에서 고른 결 · 이야기판 · 사진을 보낼 손자리 판 번호(장표를 실제로 그리는 판). 모르면 마지막으로 맡긴 판. */
  deckJobOf(claudeJobId: string): string {
    const known = this.deckSource.get(claudeJobId);
    if (known) return known;
    const links = this.job(claudeJobId)?.links ?? [];
    return links.length ? links[links.length - 1].localJobId : "";
  }

  /** 이 손자리 판이 클로드가 맡긴 것이면 그 클로드 판 번호. */
  claudeJobOf(localJobId: string): string {
    return this.linked.get(localJobId) ?? "";
  }

  // ── 저장 ─────────────────────────────────────────────────────────────
  private storage() {
    if (this.options.storage !== undefined) return this.options.storage;
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  private read(): Store {
    try {
      const value = JSON.parse(this.storage()?.getItem(STORE_KEY) ?? "") as Store;
      return value && value.messages && Array.isArray(value.jobs) ? value : emptyStore();
    } catch {
      return emptyStore();
    }
  }

  private write() {
    this.store.jobs = this.store.jobs.slice(0, 100);
    try {
      this.storage()?.setItem(STORE_KEY, JSON.stringify(this.store));
    } catch {
      // 저장소가 가득 찼어도 이번 화면은 돈다.
    }
  }

  private job(jobId: string): StoredJob | undefined {
    return this.store.jobs.find((row) => row.id === jobId);
  }

  private update(jobId: string, patch: Partial<StoredJob>) {
    const job = this.job(jobId);
    if (job) Object.assign(job, patch);
    this.write();
  }

  // ── 대화 · 일감 (원래 클라이언트의 것과 합친다 · `withClaudeLane`) ─────────────
  sessions(): ConversationSummary[] {
    return Object.entries(this.store.messages).map(([session_id, messages]) => {
      const first = messages.find((row) => row.role === "user")?.content.trim() || t("새 대화");
      const last = messages[messages.length - 1];
      return {
        session_id, title: first.slice(0, 34), preview: last?.content.slice(0, 80) ?? "",
        message_count: messages.length, updated_at: last?.created_at ?? 0, has_summary: false,
      };
    });
  }

  messages(sessionId: string): ConversationMessage[] {
    return structuredClone(this.store.messages[sessionId] ?? []);
  }

  deleteSession(sessionId: string) {
    delete this.store.messages[sessionId];
    this.store.jobs = this.store.jobs.filter((job) => job.session_id !== sessionId);
    this.write();
  }

  jobs(): JobSummary[] {
    return this.store.jobs.map(({ answer: _a, trace: _t, slots: _s, links: _l, handoffs: _h, claude_session_id: _c, model: _m, ...summary }) => structuredClone(summary));
  }

  getJob(jobId: string): JobDetail {
    const job = this.job(jobId);
    if (!job) throw new Error(t("작업 기록을 찾지 못했습니다."));
    const { answer, trace: _t, slots: _s, links: _l, handoffs: _h, claude_session_id: _c, model: _m, ...summary } = job;
    return { ...structuredClone(summary), result: { answer, completion_state: job.completion_state, session_id: job.session_id, agent_trace: null } } as JobDetail;
  }

  handoffs(jobId: string): ClaudeHandoff[] {
    return structuredClone(this.job(jobId)?.handoffs ?? []);
  }

  // ── 보내기 ───────────────────────────────────────────────────────────
  send(input: {
    prompt: string; sessionId: string; attachments: ChatAttachment[]; workspaceMode: WorkspaceMode;
    codeWorkspace: string; model: PilotModelId; history: ConversationMessage[];
    permissionMode?: string; effort?: string;
  }): { id: string; status: string } {
    const sessionId = input.sessionId || `jarvis-${Date.now().toString(36)}`;
    const jobId = `${CLAUDE_JOB_PREFIX}${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    const created = now();
    // 앞선 대화: 마지막 말이 클로드 판의 답이면 그 클로드 대화를 이어받는다(--resume). 그 뒤에 내 PC 모델과 말한 것이 있으면 글로 넘긴다.
    const prior = input.history.filter((row) => row.role === "user" || row.role === "assistant");
    const last = prior[prior.length - 1];
    const resume = last?.role === "assistant" && last.metadata?.brain === "claude" ? String(last.metadata?.claude_session_id ?? "") : "";
    this.store.messages[sessionId] = [...(this.store.messages[sessionId] ?? []), {
      id: nextMessageId(), session_id: sessionId, role: "user", content: input.prompt, kind: "chat",
      metadata: { job_id: jobId, ...(input.attachments.length ? { attachments: input.attachments.map(({ name, mime_type }) => ({ name, mime_type })) } : {}) },
      created_at: created,
    }];
    this.store.jobs.unshift({
      id: jobId, kind: "chat", title: input.prompt.slice(0, 80), status: "queued", risk_level: "L1", error: "",
      created_at: created, updated_at: created, started_at: null, finished_at: null, attempts: 1,
      build: "claude-agent", session_id: sessionId, origin: "workspace", steps: 0, completion_state: "queued",
      trace: [], slots: [], links: [], handoffs: [], model: input.model,
    });
    this.write();
    if (!prior.length) this.firstTurns.add(jobId);
    const request: AgentRunRequest = {
      job_id: jobId, prompt: input.prompt,
      history: resume ? [] : prior.slice(-40).map(({ role, content }) => ({ role, content })),
      attachments: input.attachments, workspace_mode: input.workspaceMode, code_workspace: input.codeWorkspace,
      resume_session_id: resume, model: input.model, lang: this.options.lang?.() ?? "ko",
      permission_mode: input.permissionMode ?? "", effort: input.effort ?? "",
    };
    // 한 번에 한 판 — 같은 대화를 두 클로드가 동시에 이어받지 않게.
    this.chain = this.chain.then(() => this.run(jobId, sessionId, request)).catch(() => undefined);
    return { id: jobId, status: "queued" };
  }

  private emit(event: string, payload: Record<string, unknown>) {
    this.options.emit({ event, payload });
  }

  private async run(jobId: string, sessionId: string, request: AgentRunRequest) {
    const job = this.job(jobId);
    if (!job || job.status === "cancelled") return;
    this.emit("job_queued", { job_id: jobId, session_id: sessionId, kind: "chat", prompt: request.prompt, origin: "workspace" });
    this.update(jobId, { status: "running", started_at: now(), completion_state: "running" });
    this.emit("state_changed", { to: "working" });
    this.emit("agent_started", { job_id: jobId });
    try {
      if (this.prepared !== request.lang) {
        await this.runner.prepare(request.lang);
        this.prepared = request.lang;
      }
      const result = await this.runner.run(request, (event) => this.onStream(jobId, event));
      if (this.job(jobId)?.status === "cancelled") return;
      this.finish(jobId, sessionId, result);
      await this.reveal(jobId, result.answer);
      this.emit("job_completed", { job_id: jobId, session_id: sessionId });
      if (this.firstTurns.delete(jobId)) {
        try {
          this.onFirstAnswer?.(sessionId, request.prompt, result.answer);
        } catch {
          // 제목은 덤이다 — 못 지으면 첫 말 앞부분이 그대로 남는다.
        }
      }
    } catch (reason) {
      this.firstTurns.delete(jobId);
      if (this.job(jobId)?.status === "cancelled") return;
      const error = reason instanceof Error ? reason.message : String(reason);
      this.update(jobId, { status: "failed", error, updated_at: now(), finished_at: now(), completion_state: "failed" });
      this.emit("job_failed", { job_id: jobId, session_id: sessionId, error });
    } finally {
      this.emit("state_changed", { to: "idle" });
    }
  }

  private finish(jobId: string, sessionId: string, result: AgentChatResult) {
    const job = this.job(jobId);
    if (!job) return;
    const finished = now();
    // 끝난 판의 걸음 기록(Rust 가 흐름 전체에서 다시 센 것)으로 클로드 걸음을 바꿔 끼운다 — 같은 순서 · 같은 번호.
    const trace = (result.trace ?? []).map((row, index): Observation => {
      const live = job.trace.find((item) => item.step === index + 1);
      return {
        ...row, job_id: jobId, step: index + 1, actor: "claude",
        kind: agentToolKind(row.tool, (row.arguments ?? {}) as Record<string, unknown>),
        title: toolLabel(row.tool), at: live?.at ?? row.at ?? finished,
        took_ms: live?.took_ms ?? row.took_ms ?? 0,
        arguments: stringArgs((row.arguments ?? {}) as Record<string, unknown>),
        payload: (row.payload ?? {}) as Record<string, unknown>, truncation: row.truncation ?? {},
      };
    });
    const localSteps = job.slots.filter((slot) => slot.actor === "local").length;
    this.store.messages[sessionId] = [...(this.store.messages[sessionId] ?? []), {
      id: nextMessageId(), session_id: sessionId, role: "assistant", content: result.answer, kind: "chat",
      metadata: {
        job_id: jobId, brain: "claude", model: result.model, claude_session_id: result.session_id,
        cost_usd: result.cost_usd, input_tokens: result.input_tokens, output_tokens: result.output_tokens,
        cache_read_tokens: result.cache_read_tokens, num_turns: result.num_turns, duration_ms: result.duration_ms,
        local_steps: localSteps, local_jobs: job.links.length,
      },
      created_at: finished,
    }];
    this.update(jobId, {
      status: "completed", completion_state: "completed", updated_at: finished, finished_at: finished,
      answer: result.answer, trace: trace.length ? trace : job.trace, steps: job.slots.length,
      claude_session_id: result.session_id, model: result.model,
    });
    // 「끝났다」는 job_completed 가 말한다 — 여기서 진행 사건을 하나 더 보내면 궤적이 그것을 걸음 하나로 센다(10걸음이 11걸음으로 보였다).
  }

  /** 답은 CLI 가 끝에 한 번에 준다 — 화면에서만 짧게 나눠 펼친다(파일럿과 같다). */
  private async reveal(jobId: string, answer: string) {
    const characters = Array.from(answer);
    const size = Math.max(8, Math.ceil(characters.length / 120));
    for (let offset = 0; offset < characters.length; offset += size) {
      this.emit("agent_answer_delta", { job_id: jobId, delta: characters.slice(offset, offset + size).join("") });
      await new Promise((resolve) => window.setTimeout(resolve, 16));
    }
  }

  async cancel(jobId: string) {
    const job = this.job(jobId);
    await this.runner.cancel(jobId).catch(() => undefined);
    // 멈춤은 맡긴 판까지 — 클로드만 멈추고 손자리가 계속 돌면 「멈췄다」가 거짓말이다.
    for (const link of job?.links ?? []) {
      const handoff = job?.handoffs.find((row) => row.localJobId === link.localJobId);
      if (handoff && handoff.state !== "done" && handoff.state !== "failed") {
        await this.local?.cancelJob(link.localJobId).catch(() => undefined);
      }
    }
    this.update(jobId, { status: "cancelled", completion_state: "cancelled", finished_at: now(), updated_at: now() });
    this.emit("job_cancelled", { job_id: jobId });
    return { ok: true, job_id: jobId };
  }

  // ── 흐름 → 사건 ──────────────────────────────────────────────────────
  private flushText(jobId: string) {
    const text = (this.textBuffer.get(jobId) ?? "").trim();
    this.textBuffer.delete(jobId);
    const job = this.job(jobId);
    if (text && job) this.emit("agent_says", { job_id: jobId, step: job.slots.length + 1, text });
  }

  private slotIndex(job: StoredJob, actor: StepActor, sourceJob: string, step: number): number {
    return job.slots.findIndex((slot) => slot.actor === actor && slot.jobId === sourceJob && slot.step === step);
  }

  onStream(jobId: string, event: AgentStreamEvent) {
    const job = this.job(jobId);
    if (!job || job.status === "cancelled") return;
    switch (event.kind) {
      case "thinking":
        this.emit("agent_thinking", { job_id: jobId });
        this.emit("agent_thinking_text", { job_id: jobId, delta: event.delta });
        return;
      case "text":
        this.textBuffer.set(jobId, (this.textBuffer.get(jobId) ?? "") + event.delta);
        return;
      case "tool": {
        this.flushText(jobId);
        const at = now();
        if (this.slotIndex(job, "claude", jobId, event.step) < 0) job.slots.push({ actor: "claude", jobId, step: event.step, at });
        const args = (event.evidence ?? {}) as Record<string, unknown>;
        job.trace = [...job.trace.filter((row) => row.step !== event.step), {
          job_id: jobId, step: event.step, tool: event.tool, ok: true, status: "running", error: "",
          kind: agentToolKind(event.tool, args), title: toolLabel(event.tool), at, took_ms: 0, truncated: false,
          arguments: stringArgs(args), payload: livePreview(event.tool, args), truncation: {}, actor: "claude",
        }];
        this.update(jobId, { steps: job.slots.length });
        this.emit("agent_progress", {
          job_id: jobId, step: this.slotIndex(job, "claude", jobId, event.step) + 1, phase: "research", tool: event.tool,
          message: agentToolMessage(event.tool), status: "running", evidence: args, actor: "claude",
        });
        return;
      }
      case "tool_done": {
        const row = job.trace.find((item) => item.step === event.step);
        if (row) {
          row.status = event.ok ? "completed" : "failed";
          row.ok = event.ok;
          row.error = event.ok ? "" : event.message.slice(0, 2_000);
          // 끝난 걸음의 본문은 Rust 가 한 번 만든 것(`agent_tool_payload` — 명령 · 출력, 바뀐 줄)을 그대로 쓴다. 옛 판(본문 없음)은 결과 글만.
          const shaped = event.evidence && typeof event.evidence === "object" && Object.keys(event.evidence).length > 0;
          row.payload = shaped ? { ...event.evidence } : { ...row.payload, text: event.message };
          row.took_ms = Math.max(1, Math.round((now() - row.at) * 1000));
        }
        this.write();
        this.emit("agent_progress", {
          job_id: jobId, step: this.slotIndex(job, "claude", jobId, event.step) + 1, phase: "research", tool: event.tool,
          message: agentToolMessage(event.tool), status: event.ok ? "completed" : "failed", actor: "claude",
        });
        return;
      }
      case "delegated": {
        if (!event.local_job_id || job.links.some((link) => link.localJobId === event.local_job_id)) return;
        const task = String(job.trace.find((row) => row.step === event.step)?.arguments?.task ?? "");
        job.links.push({ localJobId: event.local_job_id, toolUseId: event.tool_use_id, task });
        job.handoffs.push({ localJobId: event.local_job_id, task, state: "received", summary: null, steps: 0 });
        this.linked.set(event.local_job_id, jobId);
        this.write();
        this.emitHandoff(jobId);
        // 이어지기 전에 온 손자리 사건을 다시 흘리고, 지나간 걸음은 서버 기록으로 채운다.
        for (const held of this.buffered.get(event.local_job_id) ?? []) this.observe(held.event);
        this.buffered.delete(event.local_job_id);
        void this.pull(jobId);
        return;
      }
      case "delegation_status": {
        const handoff = job.handoffs.find((row) => row.localJobId === event.local_job_id) ?? job.handoffs[job.handoffs.length - 1];
        if (!handoff || !event.summary) return;
        handoff.summary = event.summary;
        const state = handoffState(event.summary);
        // 「끝남」은 서버 사건(job_completed)이 먼저 말했을 수 있다 — 되돌리지 않는다.
        if (!(handoff.state === "done" || handoff.state === "failed") || state !== "working") handoff.state = state;
        this.write();
        this.emitHandoff(jobId);
        return;
      }
    }
  }

  private emitHandoff(jobId: string) {
    const job = this.job(jobId);
    if (!job) return;
    for (const handoff of job.handoffs) {
      handoff.steps = job.slots.filter((slot) => slot.actor === "local" && slot.jobId === handoff.localJobId).length;
    }
    this.emit("claude_handoff", { job_id: jobId, handoffs: structuredClone(job.handoffs) });
  }

  /**
   * 원래 클라이언트로 들어온 사건을 본다. 클로드가 맡긴 손자리 판의 사건이면 클로드 판의 사건으로 바꿔 한 번 더 흘린다 —
   * 원래 사건은 그대로 흐른다(그 판은 사이드바의 「클로드가 맡긴 방」에도 그대로 보인다).
   */
  observe(event: JarvisEvent) {
    const payload = event.payload ?? {};
    const localJobId = String(payload.job_id ?? "");
    if (!localJobId || this.owns(localJobId)) return;
    const claudeJobId = this.linked.get(localJobId);
    if (!claudeJobId) {
      if (event.event === "agent_progress" || event.event === "agent_plan" || event.event === "agent_started"
        || event.event.startsWith("deck_") || event.event.startsWith("job_")) {
        const cut = now() - BUFFER_SEC;
        const rows = (this.buffered.get(localJobId) ?? []).filter((row) => row.at >= cut);
        rows.push({ at: now(), event });
        this.buffered.set(localJobId, rows.slice(-60));
        if (this.buffered.size > 20) this.buffered.delete(this.buffered.keys().next().value as string);
      }
      return;
    }
    const job = this.job(claudeJobId);
    if (!job) return;
    const handoff = job.handoffs.find((row) => row.localJobId === localJobId);
    if (event.event === "agent_progress") {
      const step = Number(payload.step ?? 0);
      if (step > 0 && String(payload.phase ?? "") !== "complete") {
        if (this.slotIndex(job, "local", localJobId, step) < 0) job.slots.push({ actor: "local", jobId: localJobId, step, at: now() });
        if (handoff && handoff.state === "received") handoff.state = "working";
        this.update(claudeJobId, { steps: job.slots.length });
        this.emit("agent_progress", { ...payload, job_id: claudeJobId, step: this.slotIndex(job, "local", localJobId, step) + 1, actor: "local" });
        this.emitHandoff(claudeJobId);
      }
      return;
    }
    if (event.event === "agent_plan" || event.event.startsWith("deck_")) {
      if (event.event.startsWith("deck_")) this.deckSource.set(claudeJobId, localJobId);
      this.emit(event.event, { ...payload, job_id: claudeJobId });
      return;
    }
    if (handoff && (event.event === "job_completed" || event.event === "job_failed" || event.event === "job_cancelled")) {
      handoff.state = event.event === "job_completed" ? "done" : "failed";
      this.write();
      this.emitHandoff(claudeJobId);
      void this.pull(claudeJobId);
    }
  }

  /** 맡긴 판의 서버 걸음 기록으로 칸을 채운다 · 시각을 서버 것으로 맞춘다. 돌려주는 것은 판마다 걸음 줄. */
  private async pull(jobId: string): Promise<Map<string, StepRow[]>> {
    const job = this.job(jobId);
    const out = new Map<string, StepRow[]>();
    if (!job || !this.local) return out;
    for (const link of job.links) {
      try {
        const rows = (await this.local.listSteps(link.localJobId)).items ?? [];
        out.set(link.localJobId, rows);
        for (const row of rows) {
          const index = this.slotIndex(job, "local", link.localJobId, row.step);
          if (index < 0) job.slots.push({ actor: "local", jobId: link.localJobId, step: row.step, at: row.at || now() });
          else if (row.at) job.slots[index].at = row.at;
        }
      } catch {
        // 못 읽은 판은 사건으로 받은 칸만 둔다.
      }
    }
    // 시간순 — 클로드가 결과를 기다리는 사이 손자리 걸음이 끼어든 그대로. 같은 시각이면 들어온 차례를 지킨다.
    job.slots = job.slots.map((slot, order) => ({ slot, order }))
      .sort((a, b) => a.slot.at - b.slot.at || a.order - b.order).map(({ slot }) => slot);
    this.update(jobId, { steps: job.slots.length });
    return out;
  }

  async listSteps(jobId: string): Promise<{ job_id: string; count: number; items: StepRow[] }> {
    const job = this.job(jobId);
    if (!job) return { job_id: jobId, count: 0, items: [] };
    const localRows = job.links.length ? await this.pull(jobId) : new Map<string, StepRow[]>();
    const items = job.slots.map((slot, index): StepRow => {
      if (slot.actor === "claude") {
        const row = job.trace.find((item) => item.step === slot.step);
        const { job_id: _j, arguments: _a, payload: _p, truncation: _t, ...shown } = row ?? {
          job_id: jobId, step: slot.step, tool: "", ok: true, status: "running", error: "", kind: "note" as ObservationKind,
          title: "", at: slot.at, took_ms: 0, truncated: false, arguments: {}, payload: {}, truncation: {},
        };
        return { ...shown, step: index + 1, actor: "claude" };
      }
      const row = localRows.get(slot.jobId)?.find((item) => item.step === slot.step);
      return row
        ? { ...row, step: index + 1, actor: "local" }
        : { step: index + 1, tool: "", ok: true, status: "running", error: "", kind: "note", title: t("손자리 걸음"), at: slot.at, took_ms: 0, truncated: false, actor: "local" };
    });
    return { job_id: jobId, count: items.length, items };
  }

  async getStep(jobId: string, step: number): Promise<Observation | null> {
    const job = this.job(jobId);
    const slot = job?.slots[step - 1];
    if (!job || !slot) return null;
    if (slot.actor === "claude") {
      const row = job.trace.find((item) => item.step === slot.step);
      return row ? { ...structuredClone(row), step, job_id: jobId, actor: "claude" } : null;
    }
    const row = await this.local?.getStep(slot.jobId, slot.step).catch(() => null);
    return row ? { ...row, step, job_id: jobId, actor: "local" } : null;
  }

  /** 클로드 판이 만든 파일 = 맡긴 손자리 판들이 만든 파일. */
  async listOutputs(jobId: string): Promise<{ job_id: string; count: number; items: JobOutput[] }> {
    const job = this.job(jobId);
    const items: JobOutput[] = [];
    for (const link of job?.links ?? []) {
      try {
        items.push(...((await this.local?.listOutputs(link.localJobId))?.items ?? []));
      } catch {
        // 못 읽은 판은 건너뛴다.
      }
    }
    return { job_id: jobId, count: items.length, items };
  }

  /** 파일 하나가 어느 손자리 판의 것인지 — 열기 · 미리보기를 그 판으로 보낸다. */
  async ownerOf(jobId: string, path: string): Promise<string> {
    for (const link of this.job(jobId)?.links ?? []) {
      try {
        const rows = (await this.local?.listOutputs(link.localJobId))?.items ?? [];
        if (rows.some((row) => row.path === path)) return link.localJobId;
      } catch {
        // 다음 판을 본다.
      }
    }
    return this.job(jobId)?.links[0]?.localJobId ?? "";
  }
}
