import { lang, t, type Lang } from "./i18n";
import { invoke } from "@tauri-apps/api/core";
import type { Observation, StepRow } from "./workspace/observation";
import type { HealthOllama } from "./workspace/readiness";
import type { ModelLoading } from "./workspace/ModelLoadLine";
import type { BackendBootstrap, BrowserFrame, BrowserStatus, LiveFrame, LiveInputEvent, LiveSelect, LiveState, Capabilities, ChatAttachment, ChatOrigin, CoworkTakeoverPrepared, JobOutput, UndoOffer, ConversationHistory, ConversationSummary, DiscoverPersonResult, ExternalActionPreview, GoogleStatus, JarvisEvent, JarvisPublicConfig, JobDetail, JobSummary, PeopleStatus, PermissionModes, ScheduleList, ScheduleRow, SelfCheckStatus, SelfHealResult, UpdateStatus, LearnedFacts, WorkspaceMode, HandoffDirection, SettingsView, SettingsPatchResult, SettingValue, SkillDomainsView, BackupSummary, PackInfo, PacksView, UnitySetupView, UnityDraft, UnityEditorView, UnityRecipeCard, UnityRoom, UnitySchedule, UnityStageFrame, DiscordStatus, DiscordStepResult, DiscordRequestsView, ModelAliasesView, DiscordAliasItem, SavingsReceipt } from "./types";

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

/**
 * 보낸 일이 크롬을 처음 띄우면, 화면 밖 크롬이 몇 초 앞창(키보드)을 쥔다(노트북 2.7~7.2초) — 그 사이 친 글자가 크롬으로 간다.
 * 앞창 잠금은 앞에 있는 프로그램만 걸 수 있고, 보내는 순간엔 온텔릭이 앞이다. 사람이 다른 창을 누르면 윈도우가 스스로 푼다.
 */
export const FOREGROUND_HOLD_MS = 15_000;

export function holdForeground(ms = FOREGROUND_HOLD_MS): void {
  if (isTauri()) void invoke("hold_foreground", { ms }).catch(() => undefined);
}

export async function releaseForeground(): Promise<void> {
  if (isTauri()) await invoke("release_foreground").catch(() => undefined);
}

/** 본체가 토큰을 아직 안 만든 것(파일·폴더 없음)인가 — 기다리면 풀리는 오류. */
export function tokenNotYetWritten(error: unknown): boolean {
  return /os error (2|3)\b/.test(String(error ?? ""));
}

/** 첫 실행에서 본체를 기다리는 최대 시간. 889MB 묶음을 백신이 처음 훑는 동안 1분 넘게 걸린다. */
export const BOOTSTRAP_WAIT_MS = 90_000;

/**
 * ★ 2026-10-01 베타 테스터 PC(새 설치 첫 실행): 「제어 토큰을 읽지 못했습니다 (…\Sonjari\data\control.token): 지정된 경로를 찾을 수
 *   없습니다 (os error 3)」. 화면이 본체보다 먼저 떠서 토큰을 **딱 한 번** 읽고 빨간 오류를 띄웠다 — 본체는 아직 그 폴더를 만들기
 *   전이었다. 「없음」 오류일 때만 잠깐씩 다시 읽고, 끝내 없으면 사람이 할 일을 말한다. 다른 오류(권한·빈 파일)는 바로 보인다.
 */
export async function loadBootstrap(waitMs = BOOTSTRAP_WAIT_MS, sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))): Promise<BackendBootstrap> {
  if (isTauri()) {
    const started = Date.now();
    for (;;) {
      try {
        const value = await invoke<{ base_url: string; control_token: string; mode?: "server" | "pilot" }>("backend_bootstrap");
        const bootstrap: BackendBootstrap = { baseUrl: value.base_url, controlToken: value.control_token, mode: value.mode ?? "server" };
        syncUiLanguage(bootstrap);
        return bootstrap;
      } catch (error) {
        if (!tokenNotYetWritten(error)) throw error;
        if (Date.now() - started >= waitMs) {
          throw new Error(
            t("Sonjari 본체가 아직 준비되지 않았습니다({0}초 기다림). 첫 실행이면 백신 검사로 더 걸릴 수 있습니다 — ", Math.round(waitMs / 1000))
            + t("잠시 뒤 「다시 시도」를 누르거나 앱을 닫았다가 다시 열어 주세요. ({0})", String(error)),
          );
        }
        await sleep(2000);
      }
    }
  }

  const bootstrap: BackendBootstrap = {
    baseUrl: import.meta.env.VITE_JARVIS_URL || "http://127.0.0.1:8091",
    controlToken: import.meta.env.VITE_JARVIS_TOKEN || "",
  };
  syncUiLanguage(bootstrap);
  return bootstrap;
}

/**
 * 화면 언어를 백엔드에 알린다 — 백엔드가 카드·진행 줄·답 끝 안내를 **나가는 순간** 그 언어로 바꾼다(ui_i18n.py).
 * 화면이 뜰 때 한 번. 실패해도 화면은 그대로 쓴다(백엔드 글만 한국어로 남는다).
 */
let uiLanguageSynced = false;
function syncUiLanguage(bootstrap: BackendBootstrap): void {
  if (uiLanguageSynced || !bootstrap.controlToken || import.meta.env?.MODE === "test") return;
  uiLanguageSynced = true;
  void pushUiLanguage(bootstrap, lang()).catch(() => { uiLanguageSynced = false; });
}

export async function pushUiLanguage(bootstrap: BackendBootstrap, value: Lang): Promise<void> {
  await fetch(`${bootstrap.baseUrl}/v1/ui-language`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-JARVIS-TOKEN": bootstrap.controlToken },
    body: JSON.stringify({ lang: value }),
  });
}

/**
 * 답 속 링크를 **온텔릭 브라우저의 새 탭**으로 열고 그 창을 앞으로 가져온다 (2026-09-29 대표 실사용).
 *
 * 데스크톱 앱 창 안에서 `<a target="_blank">` 는 **아무 데로도 안 간다** — 「AWS EC2 대시보드 열기」를 눌러도 반응이 없었다.
 * 기본 브라우저가 아니라 온텔릭 브라우저로 여는 이유: 거기서 로그인해야 온텔릭이 이어서 그 화면을 다룰 수 있다.
 * 사람이 직접 누른 것이라 창을 앞으로 가져온다(스스로는 앞으로 안 온다는 규칙과 같은 자리 — 「크롬 창 보기」).
 * 백엔드에 못 붙으면 false — 부르는 쪽이 예전 길(`window.open`)로 넘어간다.
 */
export async function openLinkInOntelicBrowser(url: string): Promise<boolean> {
  if (!/^https?:\/\//i.test(url)) return false;
  try {
    const bootstrap = await loadBootstrap(0);  // 링크 클릭은 기다리지 않는다
    if (!bootstrap.controlToken) return false;
    const post = (path: string, body: unknown) => fetch(`${bootstrap.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-JARVIS-TOKEN": bootstrap.controlToken },
      body: JSON.stringify(body),
    }).then((response) => (response.ok ? response.json() : { ok: false })).catch(() => ({ ok: false }));
    const opened = await post("/v1/browser/live/tab", { action: "new", url }) as { ok?: boolean };
    if (!opened?.ok) return false;
    await releaseForeground();  // 잠가 둔 채면 크롬이 앞으로 못 온다
    await post("/v1/browser/show", {});
    return true;
  } catch {
    return false;
  }
}

/**
 * 사람이 보려고 누른 바깥 주소(디스코드 개발자 포털 등)를 **기본 브라우저**로 연다.
 * 손자리 크롬이 아니라 기본 브라우저인 까닭: 디스코드 로그인은 사람이 평소 쓰는 브라우저에 있다(답 속 링크와 같은 길 · MarkdownView).
 */
export async function openExternalUrl(url: string): Promise<void> {
  if (!/^https?:\/\//i.test(url)) return;
  if (isTauri()) {
    try {
      await invoke("open_external_url", { url });
      return;
    } catch {
      // 아래 예전 길로 넘어간다.
    }
  }
  window.open(url, "_blank", "noreferrer");
}

export async function setNativeHudMode(mode: "orb" | "panel" | "approval" | "continuation" | "attention"): Promise<void> {
  if (isTauri()) await invoke("set_hud_mode", { mode });
}

export async function hideNativeHud(): Promise<void> {
  if (isTauri()) await invoke("hide_hud");
}

export async function startNativeHudDrag(): Promise<void> {
  if (isTauri()) await invoke("start_hud_drag");
}

export async function minimizeNativeWorkspace(): Promise<void> {
  if (isTauri()) await invoke("minimize_workspace");
}

export async function pickNativeCodeWorkspace(currentDir = ""): Promise<string | null> {
  if (!isTauri()) return null;
  return invoke<string | null>("pick_code_workspace", {
    currentDir: currentDir.trim() || null,
  });
}

// 사용자가 결정해야 하는 것이 생기면 창을 앞으로 가져온다. 승인은 놓치면 작업이
// 아무 말 없이 멈춰 있고, 5분 뒤 만료된다(실제로 그렇게 한 번 놓쳤다).
export async function focusWorkspaceWindow(): Promise<void> {
  if (isTauri()) {
    try {
      await invoke("focus_workspace");
    } catch {
      // 창을 못 띄워도 카드 자체는 화면에 있다. 이건 거들 뿐이다.
    }
  }
}

export class JarvisClient {
  private socket: WebSocket | null = null;
  private reconnectTimer = 0;
  private reconnectAttempt = 0;
  private closed = false;

  constructor(
    private readonly bootstrap: BackendBootstrap,
    private readonly onEvent: (event: JarvisEvent) => void,
    private readonly onConnection: (connected: boolean) => void,
  ) {}

  connect(): void {
    this.closed = false;
    const wsBase = this.bootstrap.baseUrl.replace(/^http/, "ws");
    const protocols = this.bootstrap.controlToken
      ? ["jarvis", this.bootstrap.controlToken]
      : ["jarvis"];
    this.socket = new WebSocket(`${wsBase}/v1/ws`, protocols);

    this.socket.onopen = () => {
      this.reconnectAttempt = 0;
      this.onConnection(true);
    };
    this.socket.onmessage = (event) => {
      try {
        this.onEvent(JSON.parse(event.data) as JarvisEvent);
      } catch {
        // A malformed diagnostic event must not take the HUD down.
      }
    };
    this.socket.onclose = () => {
      this.onConnection(false);
      if (!this.closed) this.scheduleReconnect();
    };
    this.socket.onerror = () => this.socket?.close();
  }

  disconnect(): void {
    this.closed = true;
    window.clearTimeout(this.reconnectTimer);
    this.socket?.close();
  }

  async getState(): Promise<{ state: string }> {
    return this.request("/v1/state", { method: "GET" }, false);
  }

  getConfig(): Promise<JarvisPublicConfig> {
    return this.request("/v1/config", { method: "GET" }, false);
  }

  getGoogleStatus(verify = false): Promise<GoogleStatus> {
    return this.request(`/v1/google/status?verify=${verify ? "true" : "false"}`, { method: "GET" });
  }

  startGoogleOAuth(): Promise<{ ok: boolean; opened_browser: boolean; authorization_url: string }> {
    return this.request("/v1/google/oauth/start", { method: "POST" });
  }

  /** 드라이브에서 파일 고르기 — Google 이 기본 브라우저에 고르는 화면을 띄운다(인수인계 H4). */
  startGooglePicker(): Promise<{ ok: boolean; opened_browser: boolean; authorization_url: string }> {
    return this.request("/v1/google/picker/start", { method: "POST" });
  }

  // The backend decides start-vs-stop under its state lock. Deciding it here
  // from the last WebSocket event is what let the orb and the F9 hotkey drift
  // apart and leave the mic unresponsive.
  // sessionId 를 함께 보내는 이유: 이걸 안 보내면 말한 내용이 기본 대화로 들어가고,
  // 지금 보고 있는 화면은 빈 채로 남는다. 오브(세션 개념이 없다)는 생략하고 부른다.
  togglePtt(sessionId = ""): Promise<{ action: "started" | "stopped" }> {
    return this.request("/v1/voice/ptt/toggle", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  }

  // 전체화면이 살아 있고 어느 대화를 보고 있는지 알린다. 음성으로 시킨 답이 이 화면에
  // 붙을지 구석 팝업으로 뜰지가 여기서 갈린다 — 백엔드가 판정하고 우리는 사실만 준다.
  // ★ 모드도 같이 알린다. 말로 시킨 것이 화면과 같은 모드로 가야 하기 때문이다 —
  // 이게 없던 동안 Code 탭에서 말한 판은 cowork 로 돌았다(2026-08-28 실측: 말한 판
  // 3/3 타임아웃, 타이핑한 판 3/3 완료).
  noteWorkspacePresence(
    sessionId: string,
    workspaceMode: WorkspaceMode | "" = "",
    codeWorkspace = "",
  ): Promise<{ ok: boolean; ttl_sec: number }> {
    return this.request("/v1/ui/presence", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        workspace_mode: workspaceMode,
        code_workspace: codeWorkspace,
      }),
    });
  }

  sendChat(
    prompt: string,
    // 빈 값 = "사용자가 지금 보고 있는 대화". 여기에 기본 대화 이름을 박아 두었더니
    // 작은 HUD 에 물어본 것과 전체화면에 물어본 것이 서로 다른 기억에 쌓였다 —
    // 같은 모델인데 사용자 눈에는 다른 자비스 둘이었다(2026-08-06, office-main 94개
    // 대 jarvis-* 14개). 어느 대화인지 정말 아는 쪽만 값을 준다.
    sessionId = "",
    attachments: ChatAttachment[] = [],
    delivery: "auto" | "screen" = "auto",
    origin: ChatOrigin = "chat",
    workspaceMode: WorkspaceMode = "cowork",
    codeWorkspace = "",
    displayPrompt = "",
    handoffDirection: HandoffDirection | "" = "",
    // 입력창 「추론」 칩(2026-09-28). 비면 설정 「생각 깊이」를 따른다.
    reasoning: "" | "auto" | "fast" | "normal" | "deep" = "",
    // 출처 도장의 「찾아보고 다시 답하기」(2026-09-30) — 갈래 추측 없이 에이전트로, 본 걸음이 있어야 답한다.
    observe = false,
  ): Promise<{ id: string; status: string }> {
    holdForeground();
    return this.request<{ id: string; status: string }>("/v1/chat", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        display_prompt: displayPrompt,
        session_id: sessionId,
        delivery,
        origin,
        agent_mode: "auto",
        workspace_mode: workspaceMode,
        code_workspace: codeWorkspace,
        attachments,
        ...(handoffDirection ? { handoff_direction: handoffDirection } : {}),
        ...(reasoning ? { reasoning } : {}),
        ...(observe ? { observe: true } : {}),
      }),
    });
  }

  /** 듣는 중 파형의 재료 — 지금 녹음 중인가와 소리 크기(0~1). 듣는 동안만 짧게 묻는다(2026-09-30). */
  voiceLevel(): Promise<{ recording: boolean; level: number }> {
    return this.request("/v1/voice/level", { method: "GET" });
  }

  getConversations(limit = 50): Promise<ConversationSummary[]> {
    return this.request(`/v1/conversations?limit=${limit}`, { method: "GET" });
  }

  /** 대화 하나를 지운다(목록·기록). 사실 서랍은 그대로 — 백엔드 `MemoryStore.delete_session`. */
  deleteConversation(sessionId: string): Promise<{ ok: boolean }> {
    return this.request(`/v1/conversations/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  }

  getConversation(sessionId: string, limit = 200): Promise<ConversationHistory> {
    return this.request(
      `/v1/conversations/${encodeURIComponent(sessionId)}/messages?limit=${limit}`,
      { method: "GET" },
    );
  }

  prepareCoworkTakeover(
    takeoverId: number,
    direction: HandoffDirection,
    custom = "",
  ): Promise<CoworkTakeoverPrepared> {
    return this.request(`/v1/takeover/${takeoverId}/cowork`, {
      method: "POST",
      body: JSON.stringify({ direction, custom }),
    });
  }

  /**
   * ★ 진짜 코드 이어받기 (2026-09-20). 따로 만든 가지(worktree)에서 **실제로 이어 작업**한다.
   *
   * 이 문이 UI 에 없어서, 백엔드에 기계가 다 있는데도 Code 모드 이어받기가 한 번도
   * 안 돌았다 — 「만들어 놓고 갈래가 없어서 안 쓰인다」 그 자리다.
   */
  acceptCodeTakeover(takeoverId: number): Promise<{
    kind: "started" | "card" | "missing";
    answer: string;
    takeover_id?: number;
    job_id?: string;
  }> {
    return this.request(`/v1/takeover/${takeoverId}/accept`, { method: "POST" });
  }

  dismissTakeover(takeoverId: number): Promise<{ ok: boolean; takeover_id?: number; error?: string }> {
    return this.request(`/v1/takeover/${takeoverId}/dismiss`, { method: "POST" });
  }

  // ── 권한 모드 (2026-09-21) ────────────────────────────────────────────
  // 사장님: 「계속 눌러야 되는 게 귀찮네」. 설정 화면까지 안 들어가고 **승인 카드에서
  // 바로** 풀 수 있어야 한다 — 귀찮은 그 순간에 손이 닿아야 사람이 실제로 바꾼다.
  permissionMode(): Promise<PermissionModes> {
    return this.request("/v1/permissions/mode", {});
  }

  setPermissionMode(mode: string): Promise<PermissionModes & { ok: boolean; error?: string }> {
    return this.request("/v1/permissions/mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  }

  cancelJob(jobId: string): Promise<{ ok: boolean; job_id: string }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  }

  /** 돌고 있는 작업에 한마디 덧붙인다 — 다음 걸음 앞에서 온텔릭이 읽는다. 끝난 작업이면 409(던짐). */
  steerJob(jobId: string, text: string): Promise<{ ok: boolean; job_id: string }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}/steer`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }

  // ── 일감 ──────────────────────────────────────────────────────────────
  // 백엔드에는 처음부터 있었는데 **화면이 한 번도 안 불렀다.** 이 창은 채팅만
  // 보여 주고 있었고, 그래서 작업 중앙값 143초짜리 일을 시켜 놓으면 대화를 옮기는
  // 순간 그 일이 화면에서 사라졌다(2026-08-19 실측: 50건 중 8건이 취소, 16%).
  //
  // `view=summary` 인 이유는 `types.ts` 의 JobSummary 주석에.
  listJobs(limit = 40): Promise<JobSummary[]> {
    return this.request(`/v1/jobs?view=summary&limit=${limit}`, { method: "GET" }, false);
  }

  /** 잡 하나의 전부 — 답변·도구 걸음·검증까지. 목록에는 안 싣는 것들이다.
   *  ★ 토큰을 들고 읽는다(2026-10-15): 토큰 없이 읽으면 바깥 AI 가 맡긴 일의 답은 정제한 판(바깥으로 나가는 것)이 온다 —
   *    이 PC 의 화면은 원문을 본다(`api.job` · `outbound.outbound_job_view`). */
  getJob(jobId: string): Promise<JobDetail> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
  }

  listSchedules(limit = 20): Promise<ScheduleList> {
    return this.request(`/v1/schedules?limit=${limit}`, { method: "GET" });
  }

  cancelSchedule(scheduleId: string): Promise<ScheduleRow> {
    return this.request(`/v1/schedules/${encodeURIComponent(scheduleId)}/cancel`, { method: "POST" });
  }

  // ── 할 수 있는 일 (R5) ─────────────────────────────────────────────────
  // 도구 102개·레시피·아는 사이트가 전부 코드 안에만 있었다. 쓸 수 있다는 걸
  // 모르면 없는 기능과 같다. 서랍을 **열었을 때만** 부른다.
  // ── 설정 화면 (W3) ─────────────────────────────────────────────────────
  getSettings(): Promise<SettingsView> {
    return this.request("/v1/settings", { method: "GET" });
  }

  patchSettings(values: Record<string, SettingValue>): Promise<SettingsPatchResult> {
    return this.request("/v1/settings", { method: "PATCH", body: JSON.stringify({ values }) });
  }

  resetSettings(keys: string[]): Promise<SettingsPatchResult> {
    return this.request("/v1/settings/reset", { method: "POST", body: JSON.stringify({ keys }) });
  }

  getGrantedPaths(): Promise<{ read: string[]; write: string[] }> {
    return this.request("/v1/settings/granted-paths", { method: "GET" });
  }

  revokeGrantedPath(path: string, mode: "read" | "write"): Promise<{ ok: boolean; granted_paths: { read: string[]; write: string[] } }> {
    return this.request("/v1/settings/granted-paths/revoke", { method: "POST", body: JSON.stringify({ path, mode }) });
  }

  exportDiagnostics(): Promise<{ ok: boolean; path: string; bytes: number }> {
    return this.request("/v1/diagnostics/export", { method: "POST", body: "{}" });
  }

  openFolder(which: "data" | "backup" | "diagnostics" | "guide_skill" | "skillpacks"): Promise<{ ok: boolean; path?: string; error?: string }> {
    return this.request("/v1/desktop/open-folder", { method: "POST", body: JSON.stringify({ which }) });
  }

  getBackup(): Promise<BackupSummary> {
    return this.request("/v1/backup", { method: "GET" });
  }

  backupNow(): Promise<{ ok: boolean; generation?: string; error?: string }> {
    return this.request("/v1/backup/now", { method: "POST", body: "{}" });
  }

  deleteBackups(confirmation: string): Promise<{ ok: boolean; removed?: string[]; error?: string }> {
    return this.request("/v1/backup/delete", { method: "POST", body: JSON.stringify({ confirmation }) });
  }

  resetSetupState(): Promise<{ completed: boolean }> {
    return this.request("/v1/setup/state/reset", { method: "POST", body: "{}" });
  }

  // ── 스킬 온보딩 (W4) ───────────────────────────────────────────────────
  getSkillDomains(): Promise<SkillDomainsView> {
    return this.request("/v1/skills/domains", { method: "GET" });
  }

  applySkillDomains(domains: string[]): Promise<SkillDomainsView & { ok: boolean }> {
    return this.request("/v1/skills/domains", { method: "POST", body: JSON.stringify({ domains }) });
  }

  // ── 분야 팩 (0판) — 켜고 끄는 것은 사람이 화면에서 누른 것이 동의다 ───────────────
  listPacks(): Promise<PacksView> {
    return this.request("/v1/packs", { method: "GET" });
  }

  /** 스킬팩 폴더에 넣거나 뺀 뒤 다시 읽는다. 경로를 보내지 않는다 — 읽는 자리는 백엔드가 정해 둔 폴더다. */
  rescanPacks(): Promise<PacksView> {
    return this.request("/v1/packs/rescan", { method: "POST", body: "{}" });
  }

  setPack(packId: string, on: boolean): Promise<PackInfo> {
    return this.request(`/v1/packs/${encodeURIComponent(packId)}/${on ? "enable" : "disable"}`, { method: "POST", body: "{}" });
  }

  unitySetup(): Promise<UnitySetupView> {
    return this.request("/v1/packs/game/unity", { method: "GET" });
  }

  unityPickProject(path: string): Promise<UnitySetupView> {
    return this.request("/v1/packs/game/unity/project", { method: "POST", body: JSON.stringify({ path }) });
  }

  unityOpenHub(): Promise<{ ok: boolean; opened: "hub" | "download_page" }> {
    return this.request("/v1/packs/game/unity/hub", { method: "POST", body: "{}" });
  }

  unityDrafts(): Promise<{ drafts: UnityDraft[]; recipes: string[]; recipe_cards?: UnityRecipeCard[] }> {
    return this.request("/v1/packs/game/unity/drafts", { method: "GET" });
  }

  unityDraftAction(name: string, action: "promote" | "discard"): Promise<{ ok: boolean }> {
    return this.request(`/v1/packs/game/unity/drafts/${encodeURIComponent(name)}/${action}`, { method: "POST", body: "{}" });
  }

  // ── 게임 팩 2단계: 열린 에디터 · 무대 · 정기 점검 (2026-09-27) ───────────────────
  unityEditor(): Promise<UnityEditorView> {
    return this.request("/v1/packs/game/unity/editor", { method: "GET" });
  }

  unityEditorLink(project: string, on: boolean): Promise<{ ok: boolean; next?: string; resolved_now?: boolean }> {
    return this.request(`/v1/packs/game/unity/editor/${on ? "install" : "uninstall"}`, { method: "POST", body: JSON.stringify({ project }) });
  }

  unityShareWithCoplay(on: boolean): Promise<Pick<UnityRoom, "share_with_coplay" | "install_id">> {
    return this.request("/v1/packs/game/unity/editor/share", { method: "POST", body: JSON.stringify({ on }) });
  }

  /** 유니티 창의 한 장(롱 폴). 브라우저 무대와 같이 던지지 않는다 — 못 받은 이유(`problem`)를 돌려준다. */
  async getUnityStageFrame(after: number, waitSec = 1, project = ""): Promise<UnityStageFrame> {
    const empty: UnityStageFrame = { blob: null, seq: after, width: 0, height: 0, title: "", problem: "" };
    if (!this.bootstrap.controlToken) return { ...empty, problem: "no_token" };
    try {
      const response = await fetch(
        `${this.bootstrap.baseUrl}/v1/packs/game/unity/stage?after=${after}&wait=${waitSec}&project=${encodeURIComponent(project)}`,
        { headers: { "X-JARVIS-TOKEN": this.bootstrap.controlToken }, cache: "no-store" },
      );
      const header = (name: string) => response.headers.get(name) ?? "";
      if (response.status !== 200) return { ...empty, problem: header("X-Stage-Problem") || (response.status === 204 ? "" : `http_${response.status}`) };
      return {
        blob: await response.blob(),
        seq: Number(header("X-Stage-Seq") || after),
        width: Number(header("X-Stage-Width") || 0),
        height: Number(header("X-Stage-Height") || 0),
        title: decodeURIComponent(header("X-Stage-Title")),
        problem: "",
      };
    } catch {
      return { ...empty, problem: "backend_unreachable" };
    }
  }

  unityTakeOver(project = ""): Promise<{ ok: boolean; title?: string; error?: string }> {
    return this.request("/v1/packs/game/unity/stage/takeover", { method: "POST", body: JSON.stringify({ project }) });
  }

  unitySchedules(): Promise<{ schedules: UnitySchedule[] }> {
    return this.request("/v1/packs/game/unity/schedules", { method: "GET" });
  }

  unityScheduleAdd(body: { recipe: string; project: string; at: string; days: "daily" | "weekday" | "weekly" }): Promise<UnitySchedule> {
    return this.request("/v1/packs/game/unity/schedules", { method: "POST", body: JSON.stringify(body) });
  }

  unityScheduleAction(id: string, action: "run" | "enable" | "disable" | "remove"): Promise<{ ok?: boolean }> {
    return this.request(`/v1/packs/game/unity/schedules/${encodeURIComponent(id)}/${action}`, { method: "POST", body: "{}" });
  }

  // ── 디스코드로 일 시키기 (2026-10-18) ─────────────────────────────────────────
  // 봇 토큰은 이 문들로 **들어오지도 나가지도 않는다** — 화면은 「복사했어요」만 누르고 본체가 클립보드를 직접 읽는다.
  // 단계 문은 실패해도 200 + {ok:false, error, message} 라 던지지 않는다. 화면은 status 모양 하나로 그린다.
  discordStatus(): Promise<DiscordStatus> {
    return this.request("/v1/discord/status", { method: "GET" });
  }

  discordTokenFromClipboard(): Promise<DiscordStepResult> {
    return this.request("/v1/discord/token/from-clipboard", { method: "POST", body: "{}" });
  }

  discordRecheck(): Promise<DiscordStepResult> {
    return this.request("/v1/discord/recheck", { method: "POST", body: "{}" });
  }

  discordFinish(): Promise<DiscordStepResult> {
    return this.request("/v1/discord/finish", { method: "POST", body: "{}" });
  }

  discordDisconnect(): Promise<DiscordStepResult> {
    return this.request("/v1/discord/disconnect", { method: "POST", body: "{}" });
  }

  /** 빈 별명 = 「PC 와 같음」. */
  discordSetDefaultModel(alias: string): Promise<DiscordStepResult> {
    return this.request("/v1/discord/settings", { method: "PUT", body: JSON.stringify({ default_model_alias: alias }) });
  }

  discordRequests(): Promise<DiscordRequestsView> {
    return this.request("/v1/discord/requests", { method: "GET" });
  }

  discordDecideRequest(userId: string, allow: boolean): Promise<DiscordStepResult & Partial<DiscordRequestsView>> {
    // 주소를 두 갈래로 다 적는다 — 화면 ↔ 백엔드 주소 대조 시험이 글자 그대로 읽는다(`test_ui_backend_wiring`).
    const id = encodeURIComponent(userId);
    return allow
      ? this.request(`/v1/discord/requests/${id}/allow`, { method: "POST", body: "{}" })
      : this.request(`/v1/discord/requests/${id}/ignore`, { method: "POST", body: "{}" });
  }

  getModelAliases(): Promise<ModelAliasesView> {
    return this.request("/v1/models/aliases", { method: "GET" });
  }

  /** 바깥 AI 가 맡긴 판에서 손자리가 대신 읽은 양 — **하한**과 그 근거(2026-10-19). 읽기만 한다. */
  getSavings(days = 7): Promise<SavingsReceipt> {
    return this.request(`/v1/savings?days=${encodeURIComponent(String(days))}`, { method: "GET" });
  }

  /** 표를 통째로 바꾼다. 틀리면 400 — 던지는 오류 문장이 까닭 코드(invalid_alias · invalid_tag · duplicate_alias · too_many_aliases)다. */
  putModelAliases(aliases: DiscordAliasItem[]): Promise<ModelAliasesView & { ok: boolean }> {
    return this.request("/v1/models/aliases", { method: "PUT", body: JSON.stringify({ aliases }) });
  }

  getCapabilities(): Promise<Capabilities> {
    return this.request("/v1/capabilities", { method: "GET" }, false);
  }

  // ── 만든 것 · 되돌리기 (R4) ────────────────────────────────────────────
  // 둘 다 백엔드에는 있었다. `outputs/` 는 목록 경로가 없었고, undo 는 **모델만**
  // 부를 수 있었다 — 사람은 "방금 거 취소해줘"라고 말로 해야 했다.
  listOutputs(jobId: string): Promise<{ job_id: string; count: number; items: JobOutput[] }> {
    return this.request(`/v1/outputs?job_id=${encodeURIComponent(jobId)}`, { method: "GET" });
  }

  /** 사람이 직접 해야 하는 순간 — 뒤에 떠 있는 크롬 창을 앞으로 가져온다. */
  async showBrowser(): Promise<{ ok: boolean; windows?: number; error?: string }> {
    await releaseForeground();  // 잠가 둔 채면 크롬이 앞으로 못 온다
    return this.request("/v1/browser/show", { method: "POST", body: "{}" });
  }

  /** 만든 파일을 이 PC 의 기본 앱(워드·한글·엑셀…)으로 연다. reveal 이면 탐색기에서 그 파일을 짚는다. */
  openOutputOnPc(jobId: string, path: string, reveal = false): Promise<{ ok: boolean; error?: string; path?: string }> {
    return this.request("/v1/outputs/open", { method: "POST", body: JSON.stringify({ job_id: jobId, path, reveal }) });
  }

  /** 그림을 화면에 걸 주소. 토큰이 필요해 `<img src>` 로는 못 쓰고 fetch 로 가져온다. */
  async fetchOutput(jobId: string, path: string): Promise<Blob | null> {
    const headers = new Headers();
    if (this.bootstrap.controlToken) headers.set("X-JARVIS-TOKEN", this.bootstrap.controlToken);
    const query = `job_id=${encodeURIComponent(jobId)}&path=${encodeURIComponent(path)}`;
    const response = await fetch(`${this.bootstrap.baseUrl}/v1/outputs/file?${query}`, { headers });
    return response.ok ? response.blob() : null;
  }

  /**
   * 답이 기댄 페이지의 사진 한 장(2026-10-18). 그 판 result.showcase 의 index 번째 — 경로는 안 보낸다(백엔드가 기록에서 찾는다).
   * 화면 CSP 가 `img-src 'self' data: blob:` 라 `<img src>` 로 못 걸고, 토큰도 붙여야 해서 받아서 blob 으로 건다.
   */
  async fetchShowcaseShot(jobId: string, index: number): Promise<Blob | null> {
    const headers = new Headers();
    if (this.bootstrap.controlToken) headers.set("X-JARVIS-TOKEN", this.bootstrap.controlToken);
    const response = await fetch(
      `${this.bootstrap.baseUrl}/v1/jobs/${encodeURIComponent(jobId)}/showcase/${Math.trunc(index)}`,
      { headers },
    );
    return response.ok ? response.blob() : null;
  }

  /**
   * 만든 문서의 **속**을 글로 가져온다.
   *
   * `fetchOutput` 은 바이트를 준다. hwpx·docx·xlsx 는 브라우저가 못 그려서
   * 그걸 창에 띄우면 다운로드가 될 뿐이다 — 사용자가 본 그 화면이다.
   * 여기서는 글을 받아 화면 안에 그대로 편다.
   */
  previewOutput(jobId: string, path: string): Promise<{
    name: string; path: string; format: string; text: string; readable: boolean;
  }> {
    const query = `job_id=${encodeURIComponent(jobId)}&path=${encodeURIComponent(path)}`;
    return this.request(`/v1/outputs/preview?${query}`, { method: "GET" });
  }

  // ── 걸음이 본 것 (2026-08-19) ──────────────────────────────────────────
  // 이벤트로 오는 장부는 200자에서 잘린다(`agent._step_evidence`). 그건 옳은
  // 판단이지만 — 걸음마다 8,000자를 웹소켓으로 쏠 수는 없다 — 그래서 원문은
  // **누를 때만** 가져온다. 목록은 가볍고(본문 없음), 본문은 한 걸음씩.
  listSteps(jobId: string): Promise<{ job_id: string; count: number; items: StepRow[] }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}/steps`, { method: "GET" });
  }

  /** 그 걸음의 원문. 없으면 `null` — 오래돼 버려진 것과 실패를 구별해서 화면이 말한다. */
  async getStep(jobId: string, step: number): Promise<Observation | null> {
    try {
      return await this.request<Observation>(
        `/v1/jobs/${encodeURIComponent(jobId)}/steps/${step}`,
        { method: "GET" },
      );
    } catch {
      return null;
    }
  }

  // ── 「문제 보내기」 (2026-09-29) — 미리보기 번호의 내용만 보낸다(problem_report.py). ──
  reportPreview(jobId = ""): Promise<{ id: string; text: string; to: string }> {
    return this.request(`/v1/report/preview?job_id=${encodeURIComponent(jobId)}`, { method: "GET" });
  }

  reportSend(id: string, note: string, consent: boolean): Promise<{ ok: boolean; id?: string; error?: string }> {
    return this.request("/v1/report/send", { method: "POST", body: JSON.stringify({ id, note, consent }) });
  }

  listUndo(): Promise<{ count: number; items: UndoOffer[] }> {
    return this.request("/v1/undo", { method: "GET" });
  }

  /** 되돌린다. **못 되돌려도 던지지 않는다** — 왜 못 되돌렸는지가 답이다. */
  runUndo(undoId: string): Promise<{ ok: boolean; error?: string; verified?: boolean; hint?: string }> {
    return this.request(`/v1/undo/${encodeURIComponent(undoId)}`, { method: "POST" });
  }

  // ── 자비스가 보는 화면 (R2) ────────────────────────────────────────────
  /**
   * 받을 게 있나 (위성 전용).
   *
   * **아무것도 안 바꾼다** — 물어만 본다. 본체에 못 닿으면 `ok:false` 와 이유를
   * 준다. 던지지 않는 이유: 본체가 꺼져 있는 것은 흔한 일이고, 그때마다 화면에
   * 빨간 것이 뜨면 사람이 무시하는 법을 배운다.
   */
  /** 자비스가 배운 사실 + **그 근거가 된 말.** 근거 없이는 사람이 못 고친다. */
  listFacts(): Promise<LearnedFacts> {
    return this.request("/v1/memory/facts", { method: "GET" }, true);
  }

  /** 틀린 사실을 덮는다. 지우지 않는다 — 왜 바뀌었는지가 남아야 한다. */
  forgetFact(factId: number): Promise<{ ok: boolean }> {
    return this.request("/v1/memory/facts/forget", {
      method: "POST",
      body: JSON.stringify({ fact_id: factId }),
    }, true);
  }

  /** 지금 도는 판. 갱신이 **먹었는지**를 확인하는 유일한 값이다. */
  getHealth(): Promise<{
    ok: boolean;
    build?: string;
    state?: string;
    ollama?: HealthOllama;
    thinking_translation?: "live" | "after";
  }> {
    return this.request("/health", { method: "GET" }, false);
  }

  /** 모델을 카드에 올리는 동안의 실측 진행률. 콜드 적재 중일 때만 부른다(백엔드가 nvidia-smi 를 한 번 돈다). */
  getModelLoading(): Promise<ModelLoading> {
    return this.request("/v1/model/loading", { method: "GET" }, true);
  }

  /** 판이 끝난 생각 원문을 한국어로(그래픽카드 한 장 PC, 인수인계 H3). 일하는 중이면 409 `busy`. */
  translateThinking(text: string, mode: WorkspaceMode): Promise<{ ok: boolean; text: string }> {
    return this.request("/v1/thinking/translate", { method: "POST", body: JSON.stringify({ text, mode }) }, true);
  }

  /** 켤 때 돈 자가 점검의 결과. 아직 안 돌았으면 `{pending: true}`. */
  getSelfCheck(): Promise<SelfCheckStatus> {
    return this.request("/v1/self-check", {}, true);
  }

  /** 백엔드가 「이 버튼으로 고칠 수 있다」고 한 것만 누른다. 고장일 때만 돌고, 고친 뒤 다시 읽는다. */
  healSelf(action: string): Promise<SelfHealResult> {
    return this.request("/v1/self-check/heal", { method: "POST", body: JSON.stringify({ action }) }, true);
  }

  checkUpdate(): Promise<UpdateStatus> {
    return this.request("/v1/update/check", { method: "POST" }, true);
  }

  /**
   * 사람이 눌렀다. 받아서 갈아치우고 재기동한다.
   *
   * ★ 응답은 「시작했다」이지 「됐다」가 아니다. 백엔드가 곧 죽기 때문에
   *   거기서 성공을 말할 수가 없다. 성공은 재기동 뒤 `/health` 의 `build` 로만
   *   확인한다 — 화면도 그렇게 기다린다.
   */
  applyUpdate(): Promise<{ ok: boolean; applied: boolean; build?: string; reason?: string }> {
    return this.request("/v1/update/apply", { method: "POST" }, true);
  }

  getBrowserStatus(): Promise<BrowserStatus> {
    return this.request("/v1/browser/status", { method: "GET" }, false);
  }

  /**
   * 지금 화면 한 장. **못 찍어도 던지지 않는다** — 왜 못 찍었는지가 답이다.
   *
   * 이 경로만 `request()` 를 안 쓴다. 그건 json 만 다루고 실패를 예외로 만드는데,
   * 여기서는 503 자체가 화면이 그려야 할 정보이기 때문이다("브라우저가 안 떠
   * 있습니다"와 "앞 동작에 물려 있습니다"는 사람이 할 일이 다르다).
   */
  async getBrowserFrame(): Promise<BrowserFrame> {
    const read = (response: Response, name: string) => decodeURIComponent(response.headers.get(name) ?? "");
    try {
      const response = await fetch(`${this.bootstrap.baseUrl}/v1/browser/frame.jpg`, {
        method: "GET",
        cache: "no-store",
      });
      const frame: BrowserFrame = {
        ok: response.ok,
        blob: response.ok ? await response.blob() : null,
        pageUrl: read(response, "X-Jarvis-Frame-Url"),
        title: read(response, "X-Jarvis-Frame-Title"),
        ageSec: Number(response.headers.get("X-Jarvis-Frame-Age") ?? 0),
        fresh: response.headers.get("X-Jarvis-Frame-Fresh") === "1",
        reason: read(response, "X-Jarvis-Frame-Reason"),
      };
      return frame;
    } catch (reason) {
      // 여기까지 오면 자비스 자체에 못 닿은 것이다. 브라우저 이야기가 아니다.
      return {
        ok: false, blob: null, pageUrl: "", title: "", ageSec: 0, fresh: false,
        reason: `backend_unreachable: ${reason instanceof Error ? reason.message : String(reason)}`,
      };
    }
  }

  continueAgent(jobId: string, action: "extend_3m" | "continue_task" | "finish"): Promise<{ ok: boolean }> {
    return this.request(`/v1/agents/${encodeURIComponent(jobId)}/continue`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  }

  /** `answer` 는 질문 카드에서 고른 선택지(또는 직접 적은 말). 승인 카드는 비운다. */
  decideApproval(nonce: string, approve: boolean, answer?: string): Promise<unknown> {
    return this.request(`/v1/approvals/${encodeURIComponent(nonce)}`, {
      method: "POST",
      body: JSON.stringify(answer === undefined ? { approve } : { approve, answer }),
    });
  }

  listPeople(): Promise<PeopleStatus> {
    return this.request("/v1/people", { method: "GET" });
  }

  // Sweeps the room looking for a face that matches nobody on file. Slow by
  // nature -- the gimbal physically turns and stops to look -- so callers must
  // keep the UI honest about that rather than showing a spinner that looks
  // stuck.
  discoverPerson(name: string): Promise<DiscoverPersonResult> {
    return this.request("/v1/people/discover", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  forgetPerson(name: string): Promise<{ ok: boolean; remaining: string[] }> {
    return this.request(`/v1/people/${encodeURIComponent(name)}`, { method: "DELETE" });
  }

  /**
   * 브라우저 무대 — `after` 보다 새 장을 **기다렸다가** 받는다(롱 폴). 새 장이 없으면 `blob: null`.
   * 던지지 않는다: 무대는 못 받은 이유(`status`)를 보고 예전 스크린샷 길로 돌아간다.
   */
  async getLiveFrame(after: number, waitSec = 1): Promise<LiveFrame> {
    const empty: LiveFrame = { blob: null, seq: after, width: 0, height: 0, url: "", status: "", control: false, releaseIn: 0 };
    if (!this.bootstrap.controlToken) return { ...empty, status: "no_token" };
    try {
      const response = await fetch(`${this.bootstrap.baseUrl}/v1/browser/live?after=${after}&wait=${waitSec}`, {
        headers: { "X-JARVIS-TOKEN": this.bootstrap.controlToken },
        cache: "no-store",
      });
      const header = (name: string) => response.headers.get(name) ?? "";
      const base = {
        ...empty,
        status: header("X-Live-Status"),
        control: header("X-Live-Control") === "1",
        releaseIn: Number(header("X-Live-Release-In") || 0),
      };
      if (response.status !== 200) return base;
      return {
        ...base,
        blob: await response.blob(),
        seq: Number(header("X-Live-Seq") || after),
        width: Number(header("X-Live-Width") || 0),
        height: Number(header("X-Live-Height") || 0),
        url: decodeURIComponent(header("X-Live-Url")),
      };
    } catch {
      return { ...empty, status: "backend_unreachable" };
    }
  }

  sendLiveInput(events: LiveInputEvent[]): Promise<{ ok: boolean; errors?: string[]; select?: LiveSelect }> {
    return this.request("/v1/browser/live/input", { method: "POST", body: JSON.stringify({ events }) });
  }

  getLiveState(): Promise<LiveState> {
    return this.request("/v1/browser/live/state", { method: "GET" });
  }

  liveNav(action: "back" | "forward" | "reload" | "stop" | "go", url = ""): Promise<{ ok: boolean; error?: string }> {
    return this.request("/v1/browser/live/nav", { method: "POST", body: JSON.stringify({ action, url }) });
  }

  liveTab(action: "switch" | "new", id = "", url = ""): Promise<{ ok: boolean; error?: string }> {
    return this.request("/v1/browser/live/tab", { method: "POST", body: JSON.stringify({ action, id, url }) });
  }

  liveDialog(accept: boolean, text = ""): Promise<{ ok: boolean }> {
    return this.request("/v1/browser/live/dialog", { method: "POST", body: JSON.stringify({ accept, text }) });
  }

  liveFiles(paths: string[]): Promise<{ ok: boolean; cancelled?: boolean }> {
    return this.request("/v1/browser/live/files", { method: "POST", body: JSON.stringify({ paths }) });
  }

  liveControl(action: "take" | "release", reason = "button"): Promise<{ ok: boolean; active: boolean }> {
    return this.request("/v1/browser/live/control", { method: "POST", body: JSON.stringify({ action, reason }) });
  }

  liveFit(width: number, height: number): Promise<{ ok: boolean }> {
    return this.request("/v1/browser/live/fit", { method: "POST", body: JSON.stringify({ width, height }) });
  }

  getExternalAction(actionId: string): Promise<ExternalActionPreview> {
    return this.request(`/v1/external-actions/${encodeURIComponent(actionId)}`, { method: "GET" });
  }

  private async request<T>(path: string, init: RequestInit, authenticated = true): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    if (authenticated) {
      if (!this.bootstrap.controlToken) throw new Error(t("Sonjari에 연결하지 못했습니다. 앱 백엔드를 다시 시작해 주세요."));
      headers.set("X-JARVIS-TOKEN", this.bootstrap.controlToken);
    }
    const response = await fetch(`${this.bootstrap.baseUrl}${path}`, { ...init, headers });
    if (!response.ok) {
      throw new Error(readableError(response.status, await response.text()));
    }
    return response.json() as Promise<T>;
  }

  private scheduleReconnect(): void {
    const delay = Math.min(10_000, 600 * 2 ** this.reconnectAttempt++);
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }
}

/**
 * 화면이 붙을 백엔드를 고른다.
 *
 * `?fixture=` 가 붙은 **개발 빌드**에서만 리허설용 가짜 백엔드를 쓴다. 그 모듈은
 * 여기서 동적으로만 불러오므로, 릴리스 빌드에서는 이 갈래가 `if (false)` 가 되어
 * 시나리오 데이터와 조종대 CSS 가 번들에 아예 들어가지 않는다.
 * (정적 import 로 뒀더니 시나리오 원문이 릴리스 번들에서 발견됐다 — 2026-08-19 실측.)
 */
export async function createBackendClient(
  bootstrap: BackendBootstrap,
  onEvent: (event: JarvisEvent) => void,
  onConnection: (connected: boolean) => void,
): Promise<JarvisClient> {
  if (bootstrap.mode === "pilot") {
    const pilot = await import("./pilot/PilotClient");
    return new pilot.PilotClient(bootstrap, onEvent, onConnection);
  }

  if (import.meta.env.DEV) {
    const name = new URLSearchParams(window.location.search).get("fixture") ?? "";
    if (name) {
      const fixtures = await import("./fixtures");
      const client = fixtures.createFixtureClient(name, onEvent, onConnection);
      if (client) return client;
    }
  }
  return new JarvisClient(bootstrap, onEvent, onConnection);
}

/**
 * 서버 오류를 **사람이 읽을 문장**으로 (2026-09-16 밤 스크린샷).
 *
 * 전에는 `400 {"detail":"path_outside_allowed_roots: …"}` 를 날것으로 채팅 칸 밑에 찍었다. 사람이
 * 읽어야 할 것은 `detail` 안의 문장이다. 앞의 코드 이름(`path_outside_allowed_roots:`)은 떼고,
 * 문장이 없으면 상태 코드만이라도 알린다. 원문은 개발자 도구에서 볼 수 있게 남긴다.
 */
export function readableError(status: number, body: string): string {
  let detail: unknown = body;
  try {
    detail = (JSON.parse(body) as { detail?: unknown }).detail ?? body;
  } catch {
    // 본문이 JSON 이 아니면 그대로 쓴다.
  }
  let text = "";
  if (typeof detail === "string") text = detail;
  else if (detail && typeof detail === "object" && "message" in (detail as Record<string, unknown>)) {
    text = String((detail as Record<string, unknown>).message ?? "");
  } else if (detail && typeof detail === "object" && "code" in (detail as Record<string, unknown>)) {
    text = String((detail as Record<string, unknown>).code ?? "");
  }
  // `code_name: 사람 문장` 모양이면 사람 문장만 보여 준다.
  const human = text.replace(/^[a-z][a-z0-9_]*:\s*/i, "").trim();
  if (text !== human) console.warn(t("Sonjari 서버 오류 {0}: {1}", status, text));
  return human || t("Sonjari가 요청을 처리하지 못했습니다 (오류 {0}).", status);
}
