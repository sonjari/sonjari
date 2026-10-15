import { t } from "../i18n";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { JarvisClient } from "../backend";
import { pilotModel, savedPilotModel } from "./PilotModelPicker";
import type {
  BackendBootstrap, BrowserFrame, BrowserStatus, Capabilities, ChatAttachment,
  ConversationHistory, ConversationMessage, ConversationSummary, DiscoverPersonResult,
  ExternalActionPreview, GoogleStatus, JarvisEvent, JarvisPublicConfig, JobDetail,
  JobOutput, JobSummary, LearnedFacts, PeopleStatus, PilotChatResult, ScheduleList,
  ScheduleRow, UndoOffer, UpdateStatus, WorkspaceMode,
} from "../types";
import type { Observation, StepRow } from "../workspace/observation";

const STORE_KEY = "jarvis.pilot.store.v1";

type StoredJob = JobSummary & {
  answer?: string;
  trace?: Observation[];
  outputs?: JobOutput[];
  claude_session_id?: string;
  model?: string;
};
type PilotStore = {
  messages: Record<string, ConversationMessage[]>;
  jobs: StoredJob[];
};

function emptyStore(): PilotStore {
  return { messages: {}, jobs: [] };
}

function readStore(): PilotStore {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORE_KEY) ?? "") as PilotStore;
    return value && value.messages && Array.isArray(value.jobs) ? value : emptyStore();
  } catch {
    return emptyStore();
  }
}

function writeStore(value: PilotStore) {
  window.localStorage.setItem(STORE_KEY, JSON.stringify(value));
}

function now() {
  return Date.now() / 1000;
}

function nextMessageId() {
  return Date.now() * 1000 + Math.floor(Math.random() * 1000);
}

function firstUrl(prompt: string) {
  return prompt.match(/https?:\/\/[^\s)\]}>,]+/i)?.[0] ?? "";
}

function traceFor(_prompt: string, jobId: string): Observation[] {
  const at = now();
  return [{
    job_id: jobId, step: 1, tool: "claude-code", ok: true, status: "running",
    error: "", kind: "note", title: t("Claude Code와 공개 도구 준비"), at, took_ms: 0,
    truncated: false, arguments: {}, payload: { text: t("요청과 연결된 공개 도구를 확인했습니다.") }, truncation: {},
  }];
}

function completedTrace(result: PilotChatResult, jobId: string, fallback: Observation[], finished: number): Observation[] {
  const actual = (result.trace ?? []).map((row, index) => ({
    ...row,
    job_id: jobId,
    step: index + 1,
    status: row.status || "completed",
    at: row.at || finished,
    arguments: row.arguments ?? {},
    payload: row.payload ?? {},
    truncation: row.truncation ?? {},
  }));
  if (actual.length) return actual;
  return fallback.map((row) => ({
    ...row, status: "completed", at: finished,
    took_ms: Math.max(1, Math.round((finished - (row.at || finished)) * 1000)),
  }));
}

const GOOGLE_DISABLED: GoogleStatus = {
  enabled: false, configured: false, connected: false, pending: false,
  project_id: "", email: "", name: "", scopes: [], mode: "read_only", last_error: "",
};

const BROWSER_IDLE: BrowserStatus = {
  enabled: true, started: false, liveness: "probed", headless: false, read_only: false,
  connect_mode: "Browser Use MCP", automation_flag: null, attach_error: "", last_error: "",
  stuck: false, circuit_open: false, recoveries: 0,
};

function capabilities(): Capabilities {
  const rows = [
    ["browser-use", t("공개 Browser Use로 웹을 탐색하고 화면을 조작합니다."), "L1"],
    ["markitdown", t("DOCX·XLSX·PPTX·PDF를 Markdown으로 읽습니다."), "L0"],
    ["document-runtime", t("DOCX·XLSX·PPTX·PDF 문서를 만들고 검사합니다."), "L1"],
    ["github-readonly", t("GitHub 공개 저장소와 문서를 읽기 전용으로 조사합니다."), "L0"],
    ["blender", t("설치된 Blender를 안전 모드로 연결합니다."), "L1"],
    ["unity", t("설치된 Unity 프로젝트 도구를 연결합니다."), "L1"],
    ["unreal", t("설치된 Unreal Engine의 공식 Claude 플러그인을 사용합니다."), "L1"],
    ["godot", t("설치된 Godot 프로젝트를 연결합니다."), "L1"],
    ["maya", t("설치된 Maya를 사용자 확인 후 조작합니다."), "L2"],
    ["after-effects", t("설치된 After Effects를 사용자 확인 후 조작합니다."), "L2"],
    ["davinci-resolve", t("설치된 DaVinci Resolve를 사용자 확인 후 조작합니다."), "L2"],
  ] as const;
  const tools = rows.map(([name, description, risk_level]) => ({ name, description, risk_level, enabled: true }));
  const by_risk: Record<string, number> = {};
  for (const row of tools) by_risk[row.risk_level] = (by_risk[row.risk_level] ?? 0) + 1;
  return { tools, tool_count: tools.length, by_risk, recipes: [], sites: [] };
}

export class PilotClient extends JarvisClient {
  private store = readStore();
  private pilotClosed = false;
  private unlistenPilotStream: UnlistenFn | null = null;
  private thinkingTranslationBuffers = new Map<string, string>();
  private thinkingTranslationTimers = new Map<string, number>();
  private thinkingTranslationBusy = new Set<string>();

  constructor(
    bootstrap: BackendBootstrap,
    private readonly emit: (event: JarvisEvent) => void,
    private readonly setConnected: (connected: boolean) => void,
  ) {
    super(bootstrap, emit, setConnected);
  }

  override connect(): void {
    this.pilotClosed = false;
    void listen<{
      job_id: string;
      kind: "thinking" | "tool";
      delta?: string;
      step?: number;
      tool?: string;
      message?: string;
      evidence?: Record<string, unknown>;
    }>("pilot-stream", ({ payload }) => {
      if (payload.kind === "thinking" && payload.delta) {
        this.emit({ event: "agent_thinking", payload: { job_id: payload.job_id } });
        this.emit({ event: "agent_thinking_text", payload: { job_id: payload.job_id, delta: payload.delta } });
        this.queueThinkingTranslation(payload.job_id, payload.delta);
      } else if (payload.kind === "tool") {
        this.emit({ event: "agent_progress", payload: {
          job_id: payload.job_id,
          step: payload.step ?? 1,
          phase: "research",
          tool: payload.tool ?? "claude-code",
          message: payload.message ?? t("도구를 실행하는 중"),
          status: "running",
          evidence: payload.evidence ?? {},
        } });
      }
    }).then((unlisten) => {
      if (this.pilotClosed) unlisten();
      else this.unlistenPilotStream = unlisten;
    }).catch(() => undefined);
    window.setTimeout(() => !this.pilotClosed && this.setConnected(true), 20);
  }

  override disconnect(): void {
    this.pilotClosed = true;
    this.unlistenPilotStream?.();
    this.unlistenPilotStream = null;
    for (const timer of this.thinkingTranslationTimers.values()) window.clearTimeout(timer);
    this.thinkingTranslationTimers.clear();
    this.thinkingTranslationBuffers.clear();
    this.setConnected(false);
  }

  private queueThinkingTranslation(jobId: string, delta: string) {
    const buffered = (this.thinkingTranslationBuffers.get(jobId) ?? "") + delta;
    this.thinkingTranslationBuffers.set(jobId, buffered);
    const prior = this.thinkingTranslationTimers.get(jobId);
    if (prior) window.clearTimeout(prior);
    const delay = buffered.length >= 1_600 || buffered.includes("\n\n") ? 40 : 650;
    this.thinkingTranslationTimers.set(jobId, window.setTimeout(() => {
      this.thinkingTranslationTimers.delete(jobId);
      void this.flushThinkingTranslation(jobId);
    }, delay));
  }

  private async flushThinkingTranslation(jobId: string) {
    if (this.thinkingTranslationBusy.has(jobId)) return;
    const text = this.thinkingTranslationBuffers.get(jobId) ?? "";
    if (!text.trim()) return;
    this.thinkingTranslationBuffers.set(jobId, "");
    this.thinkingTranslationBusy.add(jobId);
    try {
      const translated = await invoke<string>("pilot_translate_thinking", { text });
      if (translated.trim()) {
        await this.revealThinkingTranslation(jobId, `${translated.trim()}\n`);
      }
    } catch {
      // Ollama 또는 번역 모델이 회사 정책에 막혀도 Claude 작업과 원문 thinking은 유지한다.
    } finally {
      this.thinkingTranslationBusy.delete(jobId);
      if ((this.thinkingTranslationBuffers.get(jobId) ?? "").trim()) {
        this.thinkingTranslationTimers.set(jobId, window.setTimeout(() => {
          this.thinkingTranslationTimers.delete(jobId);
          void this.flushThinkingTranslation(jobId);
        }, 80));
      }
    }
  }

  private async revealThinkingTranslation(jobId: string, translated: string) {
    const characters = Array.from(translated);
    // 짧은 번역은 약 1초, 긴 번역은 2초 안팎으로 뒤따른다. 원문 스트림과 본 답은
    // 기다리지 않고, 한국어 레이어만 자비스처럼 부드럽게 채운다.
    const chunkSize = Math.max(2, Math.ceil(characters.length / 80));
    for (let offset = 0; offset < characters.length; offset += chunkSize) {
      if (this.pilotClosed) return;
      this.emit({ event: "agent_thinking_ko", payload: {
        job_id: jobId,
        delta: characters.slice(offset, offset + chunkSize).join(""),
      } });
      await new Promise((resolve) => window.setTimeout(resolve, 18));
    }
  }

  override async getState() {
    return { state: this.store.jobs.some((job) => job.status === "running" || job.status === "queued") ? "working" : "idle" };
  }

  override async getConfig(): Promise<JarvisPublicConfig> {
    const selected = pilotModel(savedPilotModel());
    return {
      ollama_model: selected.label, ollama_num_ctx: selected.context,
      model_roles: { chat: selected.label, code: selected.label },
      model_num_ctx: { chat: selected.context, code: selected.context },
      memory_retrieval_enabled: false, memory_retrieval_limit: 0,
    };
  }

  override async getGoogleStatus(): Promise<GoogleStatus> {
    return { ...GOOGLE_DISABLED };
  }

  override async startGoogleOAuth(): Promise<{ ok: boolean; opened_browser: boolean; authorization_url: string }> {
    throw new Error(t("파일럿에서는 Google 계정 연결을 제공하지 않습니다."));
  }

  override async togglePtt(): Promise<{ action: "started" | "stopped" }> {
    throw new Error(t("파일럿 음성 입력은 아직 연결되지 않았습니다. 입력창을 사용해 주세요."));
  }

  override async noteWorkspacePresence() {
    return { ok: true, ttl_sec: 45 };
  }

  override async getConversations(limit = 50): Promise<ConversationSummary[]> {
    return Object.entries(this.store.messages)
      .map(([session_id, messages]) => {
        const first = messages.find((row) => row.role === "user")?.content.trim() || t("새 대화");
        const last = messages[messages.length - 1];
        return {
          session_id,
          title: first.slice(0, 34),
          preview: last?.content.slice(0, 80) ?? "",
          message_count: messages.length,
          updated_at: last?.created_at ?? 0,
          has_summary: false,
        };
      })
      .sort((a, b) => b.updated_at - a.updated_at)
      .slice(0, limit);
  }

  override async getConversation(sessionId: string, limit = 200): Promise<ConversationHistory> {
    return {
      session_id: sessionId, summary: "", has_summary: false,
      context_window: 1_000_000, retrieval_enabled: false,
      messages: structuredClone((this.store.messages[sessionId] ?? []).slice(-limit)),
    };
  }

  override async sendChat(
    prompt: string,
    sessionId = "",
    attachments: ChatAttachment[] = [],
    _delivery: "auto" | "screen" = "auto",
    origin: "chat" | "voice" | "workspace" = "chat",
    workspaceMode: WorkspaceMode = "cowork",
    codeWorkspace = "",
  ) {
    const target = sessionId || `jarvis-${Date.now().toString(36)}`;
    const jobId = `pilot-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    const created = now();
    const message: ConversationMessage = {
      id: nextMessageId(), session_id: target, role: "user", content: prompt,
      kind: "chat", metadata: attachments.length ? { attachments: attachments.map(({ name, mime_type }) => ({ name, mime_type })) } : {},
      created_at: created,
    };
    this.store.messages[target] = [...(this.store.messages[target] ?? []), message];
    this.store.jobs.unshift({
      id: jobId, kind: "chat", title: prompt.slice(0, 80), status: "queued", risk_level: "L1", error: "",
      created_at: created, updated_at: created, started_at: null, finished_at: null, attempts: 1,
      build: "pilot-ui", session_id: target, origin, steps: 0, completion_state: "queued", trace: traceFor(prompt, jobId),
    });
    this.store.jobs = this.store.jobs.slice(0, 100);
    writeStore(this.store);
    window.setTimeout(() => void this.runJob(jobId, target, prompt, attachments, workspaceMode, codeWorkspace), 0);
    return { id: jobId, status: "queued" };
  }

  private async runJob(
    jobId: string, sessionId: string, prompt: string, attachments: ChatAttachment[],
    workspaceMode: WorkspaceMode, codeWorkspace: string,
  ) {
    const trace = this.store.jobs.find((row) => row.id === jobId)?.trace ?? traceFor(prompt, jobId);
    const url = firstUrl(prompt);
    this.emit({ event: "job_queued", payload: { job_id: jobId, session_id: sessionId, kind: "chat", prompt, origin: "workspace" } });
    this.updateJob(jobId, { status: "running", started_at: now(), completion_state: "running", steps: trace.length, trace });
    this.emit({ event: "state_changed", payload: { to: "working" } });
    this.emit({ event: "agent_started", payload: { job_id: jobId } });
    if (url) this.emit({ event: "agent_plan", payload: { job_id: jobId, items: [{ kind: "site", label: url, met: false, saw: t("원문을 여는 중") }] } });
    for (const row of trace) this.emit({ event: "agent_progress", payload: {
      job_id: jobId, step: row.step, phase: row.step === 1 ? "prepare" : "research", tool: row.tool,
      message: row.step === 1 ? t("Claude Code와 공개 도구를 준비하는 중") : t("Browser Use로 원문 사이트를 조사하는 중"),
      status: "running", evidence: row.arguments,
    } });
    try {
      const resumeSessionId = this.store.jobs.find((job) => (
        job.id !== jobId && job.session_id === sessionId && job.status === "completed" && job.claude_session_id
      ))?.claude_session_id ?? "";
      // Claude 자체 세션이 있으면 이전 대화는 디스크 세션에서 이어 받는다. 브라우저
      // 저장소의 200개 메시지를 매번 다시 보내지 않아 캐시 경계를 안정적으로 유지한다.
      const history = resumeSessionId ? [] : (this.store.messages[sessionId] ?? [])
        .slice(0, -1).slice(-200).map(({ role, content }) => ({ role, content }));
      const model = savedPilotModel();
      const result = await invoke<PilotChatResult>("pilot_chat", { request: {
        job_id: jobId, prompt, session_id: sessionId, history, attachments,
        workspace_mode: workspaceMode, code_workspace: codeWorkspace,
        resume_session_id: resumeSessionId, model,
      } });
      const finished = now();
      const observedTrace = completedTrace(result, jobId, trace, finished);
      this.store.messages[sessionId] = [...(this.store.messages[sessionId] ?? []), {
        id: nextMessageId(), session_id: sessionId, role: "assistant", content: result.answer,
        kind: "chat", metadata: {
          cost_usd: result.cost_usd,
          duration_ms: result.duration_ms,
          model: result.model ?? model,
          thinking_tokens: result.thinking_tokens,
          cache_read_tokens: result.cache_read_tokens,
          cache_creation_tokens: result.cache_creation_tokens,
        }, created_at: finished,
      }];
      this.updateJob(jobId, {
        status: "completed", updated_at: finished, finished_at: finished,
        completion_state: "completed", steps: observedTrace.length, answer: result.answer, trace: observedTrace,
        outputs: result.outputs ?? [], claude_session_id: result.session_id, model: result.model ?? model,
      });
      writeStore(this.store);
      await this.revealAnswer(jobId, result.answer);
      const browserObserved = observedTrace.some((row) => row.tool.toLowerCase().includes("browser"));
      if (url) this.emit({ event: "agent_plan", payload: { job_id: jobId, items: [{ kind: "site", label: url, met: browserObserved, saw: browserObserved ? t("Browser Use 원문 확인 완료") : t("Browser Use 호출 기록 없음") }] } });
      this.emit({ event: "agent_progress", payload: {
        job_id: jobId, step: 1, phase: "complete", tool: "claude-code",
        message: t("Claude Code 작업 완료"), status: "completed",
      } });
      this.emit({ event: "job_completed", payload: { job_id: jobId, session_id: sessionId } });
    } catch (reason) {
      const error = reason instanceof Error ? reason.message : String(reason);
      const finished = now();
      this.updateJob(jobId, { status: "failed", error, updated_at: finished, finished_at: finished, completion_state: "failed" });
      writeStore(this.store);
      this.emit({ event: "job_failed", payload: { job_id: jobId, session_id: sessionId, error } });
    } finally {
      this.emit({ event: "state_changed", payload: { to: "idle" } });
    }
  }

  /**
   * Claude CLI는 JSON 응답을 끝까지 받은 뒤 돌려준다. 완성된 답을 한 프레임에
   * 꽂으면 자동 스크롤도 한 번에 튀므로, JARVIS 화면에서만 짧게 나눠 펼친다.
   * 실제 모델 출력을 늦추지 않고 긴 답도 약 2초 안에 전부 보이게 한다.
   */
  private async revealAnswer(jobId: string, answer: string) {
    const characters = Array.from(answer);
    const chunkSize = Math.max(8, Math.ceil(characters.length / 120));
    for (let offset = 0; offset < characters.length; offset += chunkSize) {
      this.emit({ event: "agent_answer_delta", payload: {
        job_id: jobId,
        delta: characters.slice(offset, offset + chunkSize).join(""),
      } });
      await new Promise((resolve) => window.setTimeout(resolve, 16));
    }
  }

  private updateJob(jobId: string, patch: Partial<StoredJob>) {
    this.store.jobs = this.store.jobs.map((job) => job.id === jobId ? { ...job, ...patch } : job);
    writeStore(this.store);
  }

  override async cancelJob(jobId: string) {
    await invoke<boolean>("pilot_cancel", { jobId });
    this.updateJob(jobId, { status: "cancelled", finished_at: now(), completion_state: "cancelled" });
    this.emit({ event: "job_cancelled", payload: { job_id: jobId } });
    return { ok: true, job_id: jobId };
  }

  override async listJobs(limit = 40): Promise<JobSummary[]> {
    return structuredClone(this.store.jobs.slice(0, limit));
  }

  override async getJob(jobId: string): Promise<JobDetail> {
    const job = this.store.jobs.find((row) => row.id === jobId);
    if (!job) throw new Error(t("작업 기록을 찾지 못했습니다."));
    const { answer, ...summary } = job;
    return { ...structuredClone(summary), result: { answer, completion_state: job.completion_state, session_id: job.session_id, agent_trace: null } };
  }

  override async listSchedules(): Promise<ScheduleList> {
    return { action: "schedule_list", count: 0, schedules: [] };
  }

  override async cancelSchedule(_scheduleId: string): Promise<ScheduleRow> {
    throw new Error(t("파일럿에서는 예약 작업을 제공하지 않습니다."));
  }

  override async getCapabilities(): Promise<Capabilities> { return capabilities(); }
  override async listOutputs(jobId: string): Promise<{ job_id: string; count: number; items: JobOutput[] }> {
    const items = this.store.jobs.find((row) => row.id === jobId)?.outputs ?? [];
    return { job_id: jobId, count: items.length, items: structuredClone(items) };
  }
  override async fetchOutput(_jobId: string, path: string): Promise<Blob | null> {
    const result = await invoke<{ data_base64: string; mime_type: string }>("pilot_read_output", { path });
    const binary = atob(result.data_base64);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return new Blob([bytes], { type: result.mime_type });
  }
  override async previewOutput(_jobId: string, path: string) {
    return invoke<{ name: string; path: string; format: string; text: string; readable: boolean }>("pilot_preview_output", { path });
  }
  override async listSteps(jobId: string): Promise<{ job_id: string; count: number; items: StepRow[] }> {
    const trace = this.store.jobs.find((row) => row.id === jobId)?.trace ?? [];
    const items = trace.map(({ job_id: _job, arguments: _args, payload: _payload, truncation: _truncation, ...row }) => row);
    return { job_id: jobId, count: items.length, items: structuredClone(items) };
  }
  override async getStep(jobId: string, step: number): Promise<Observation | null> {
    return structuredClone(this.store.jobs.find((row) => row.id === jobId)?.trace?.find((row) => row.step === step) ?? null);
  }
  override async listUndo(): Promise<{ count: number; items: UndoOffer[] }> { return { count: 0, items: [] }; }
  override async runUndo() { return { ok: false, error: t("파일럿 작업은 Sonjari 화면에서 자동 되돌리기를 제공하지 않습니다.") }; }
  override async listFacts(): Promise<LearnedFacts> { return { count: 0, items: [], always_on_chars: 0, always_on_cap: 0 }; }
  override async forgetFact() { return { ok: false }; }
  override async getHealth() { return { ok: true, build: "pilot-ui", state: "idle" }; }
  override async checkUpdate(): Promise<UpdateStatus> { return { ok: true, mine: "pilot-ui", available: false }; }
  override async applyUpdate() { return { ok: false, applied: false, reason: t("설치 파일로 업데이트해 주세요.") }; }
  private latestPage(): Observation | null {
    const newest = this.store.jobs[0];
    return [...(newest?.trace ?? [])].reverse().find((row) => row.kind === "page") ?? null;
  }
  override async getBrowserStatus(): Promise<BrowserStatus> {
    const page = this.latestPage();
    return page ? { ...BROWSER_IDLE, started: true, connect_mode: "attached", liveness: "cached" } : { ...BROWSER_IDLE };
  }
  override async getBrowserFrame(): Promise<BrowserFrame> {
    const page = this.latestPage();
    const pageUrl = String(page?.payload?.url ?? page?.arguments?.url ?? "");
    const title = String(page?.payload?.title ?? page?.title ?? "");
    return {
      ok: false, blob: null,
      pageUrl, title,
      ageSec: page ? Math.max(0, now() - page.at) : 0, fresh: false,
      reason: page ? t("실제 페이지는 별도 Browser Use 창에서 열립니다. 파일럿 UI에는 URL과 조사 기록만 보존합니다.") : "browser_not_started",
    };
  }
  override async continueAgent() { return { ok: false }; }
  override async decideApproval() { return { ok: false }; }
  override async listPeople(): Promise<PeopleStatus> { return { enabled: false, ok: false, registered: [] }; }
  override async discoverPerson(_name: string): Promise<DiscoverPersonResult> { return { ok: false, registered: false, reason: t("파일럿에서는 카메라 인식 기능을 제공하지 않습니다.") }; }
  override async forgetPerson() { return { ok: false, remaining: [] }; }
  override async getExternalAction(_actionId: string): Promise<ExternalActionPreview> { throw new Error(t("외부 작업 미리보기가 없습니다.")); }
}
