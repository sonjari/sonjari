/**
 * 백엔드 없이 화면을 돌리는 가짜 클라이언트.
 *
 * 상태를 컴포넌트에 직접 꽂지 않는다. **진짜와 같은 문으로** 들여보낸다 —
 * 같은 `onEvent`, 같은 REST 메서드. 그래야 리허설에서 본 것이 실제 화면과 같다.
 * (상태를 직접 심으면 화면은 예쁘게 나오지만 실제 배선이 깨진 걸 못 잡는다.)
 *
 * 개발 빌드 전용. `fixtures/index.ts` 가 DEV 에서만 가져온다.
 */
import { JarvisClient } from "../backend";
import settingsFixture from "./settingsFixture.json";
import whatsNewFixture from "./whatsNewFixture.json";
import { FIXTURE_STEPS } from "./observations";
import type { Observation, StepRow } from "../workspace/observation";
import type {
  BrowserFrame, BrowserStatus, LiveFrame, ChatAttachment, ConversationHistory, ConversationSummary,
  CoworkTakeoverPrepared, DiscoverPersonResult, ExternalActionPreview, GoogleStatus, JarvisEvent, JarvisPublicConfig,
  Capabilities, JobDetail, JobOutput, JobSummary, PeopleStatus, ScheduleList, ScheduleRow, UndoOffer,
  WorkspaceMode, ChatOrigin, HandoffDirection, SelfCheckStatus, SelfHealResult, UpdateStatus, SettingsView, SettingsPatchResult, SettingValue, SkillDomainsView, BackupSummary,
  PermissionModes, PackInfo, PacksView, UsageShowStatus, WhatsNewStatus, WeeklyReceipt, ReceiptImageSaved,
} from "../types";
import type { Scenario, ScriptStep } from "./scenarios";
import type { Lang } from "../i18n";

const JOB_ID = "fixture-job";

const DEFAULT_GOOGLE: GoogleStatus = {
  enabled: true, configured: true, connected: false, pending: false,
  project_id: "fixture", email: "", name: "", scopes: [], mode: "read_only", last_error: "",
};

const DEFAULT_BROWSER: BrowserStatus = {
  enabled: true, started: false, liveness: "probed", headless: false, read_only: false,
  connect_mode: "", automation_flag: null, attach_error: "", last_error: "",
  stuck: false, circuit_open: false, recoveries: 0,
};

/**
 * 리허설용 가짜 페이지 한 장.
 *
 * SVG 로 만드는 이유: 진짜 JPEG 을 base64 로 박아 두면 개발 번들이 무거워지고,
 * 무엇보다 **무엇이 그려졌는지 코드에서 안 보인다.** 여기서 확인하려는 것은 그림의
 * 화질이 아니라 배선(패널이 뜨는가·주소가 붙는가·낡으면 표시가 뜨는가)이다.
 */
function fakePage(title: string, url: string): Blob {
  // ★ SVG 는 XML 이다. 주소에 흔한 `&`(`?type=gigs&keyword=RAG`) 를 그대로 넣으면
  //   문서가 통째로 파싱에 실패하고 <img> 는 **조용히 아무것도 안 그린다**
  //   (실측: naturalWidth 0, onerror). 에러가 화면에 안 뜨는 종류라 더 나쁘다.
  const xml = (value: string) => value.replace(/[<>&"']/g, (ch) => (
    { "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" }[ch] as string
  ));
  const rows = [0, 1, 2, 3].map((index) => `
    <rect x="40" y="${170 + index * 96}" width="1360" height="76" rx="8" fill="#12151d" stroke="#252a36"/>
    <rect x="60" y="${192 + index * 96}" width="${420 - index * 40}" height="14" rx="4" fill="#3b4252"/>
    <rect x="60" y="${216 + index * 96}" width="${260 + index * 30}" height="11" rx="4" fill="#2b303c"/>
    <rect x="1240" y="${196 + index * 96}" width="120" height="26" rx="6" fill="#1d2230" stroke="#2f3646"/>`).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 620" width="1440" height="620">
    <rect width="1440" height="620" fill="#0b0d13"/>
    <rect x="0" y="0" width="1440" height="56" fill="#141821"/>
    <rect x="24" y="18" width="220" height="20" rx="6" fill="#2a3140"/>
    <text x="270" y="34" fill="#7c8496" font-family="monospace" font-size="15">${xml(url)}</text>
    <text x="40" y="120" fill="#c9d1e0" font-family="sans-serif" font-size="26">${xml(title)}</text>
    ${rows}
  </svg>`;
  return new Blob([svg], { type: "image/svg+xml" });
}

/**
 * 리허설용 능력 목록 (R5).
 *
 * 실제 `/v1/capabilities` 는 102개를 준다. 여기서 확인하려는 것은 개수가 아니라
 * **묶음이 서고 등급 거르기가 도는가**라, 묶음마다 몇 개씩만 둔다. 이름은 전부
 * 실제로 있는 도구 이름이다 — 지어낸 이름을 두면 분류표가 틀려도 안 보인다.
 */
function fakeCapabilities(): Capabilities {
  const tool = (name: string, description: string, risk_level: string, enabled = true) =>
    ({ name, description, risk_level, enabled });
  const tools = [
    tool("browser_open", "주소를 연다", "L0"),
    tool("browser_site_search", "그 사이트의 검색칸에 직접 친다", "L0"),
    tool("browser_extract", "본문을 끝까지 읽는다", "L0"),
    tool("browser_fill", "입력칸을 채운다", "L1"),
    tool("browser_form_submit", "양식을 보낸다", "L2"),
    tool("site_run", "검토된 사이트 절차를 돌린다", "L1"),
    tool("google_calendar_create", "일정을 만든다", "L2"),
    tool("google_gmail_send", "메일을 보낸다", "L2"),
    tool("naver_blog_publish", "블로그에 발행한다", "L2"),
    tool("inhouse_lookup", "우리 학원 데이터를 조회한다", "L0"),
    tool("windows_focus_window", "창을 앞으로 가져온다", "L1"),
    tool("local_read_document", "이 PC 문서를 읽는다", "L0"),
    tool("camera_look", "카메라를 돌려 본다", "L1", false),
    tool("ui_find_target", "화면을 보고 누를 것을 고른다", "L0"),
    tool("undo_action", "방금 한 일을 되돌린다", "L1"),
    tool("schedule_create", "나중에 하도록 걸어 둔다", "L1"),
    tool("mystery_tool", "분류표에 없는 도구", "L0"),
  ];
  const by_risk: Record<string, number> = {};
  for (const row of tools) by_risk[row.risk_level] = (by_risk[row.risk_level] ?? 0) + 1;
  return {
    tools,
    tool_count: tools.length,
    by_risk,
    recipes: [
      {
        site: "saramin",
        description: "사람인 채용 검색 + 관심공고 + 관심기업. 바꾸는 절차에는 전부 undo 가 걸려 있다.",
        hosts: ["saramin.co.kr", "www.saramin.co.kr"],
        actions: [
          { action: "search_jobs", risk: "L0", params: ["query"], description: "공고를 검색한다" },
          { action: "scrap", risk: "L1", params: ["job_id"], description: "관심공고에 담는다" },
          { action: "unscrap", risk: "L1", params: ["job_id"], description: "관심공고에서 뺀다" },
        ],
      },
      {
        site: "naver_blog",
        description: "네이버 블로그 임시저장·발행. 발행은 되돌릴 수 없다.",
        hosts: ["blog.naver.com"],
        actions: [
          { action: "save_draft", risk: "L1", params: ["title", "body"], description: "임시저장한다" },
          { action: "publish", risk: "L2", params: ["title", "body"], description: "발행한다" },
        ],
      },
    ],
    sites: [
      { name: "위시켓", host: "wishket.com", seeded: true },
      { name: "크몽", host: "kmong.com", seeded: true },
      { name: "사람인", host: "saramin.co.kr", seeded: true },
      { name: "다나와", host: "danawa.com", seeded: false },
      { name: "교보문고", host: "kyobobook.co.kr", seeded: false },
    ],
  };
}

const DEFAULT_PEOPLE: PeopleStatus = { enabled: true, ok: true, models_present: true, registered: [], threshold: 0.42 };

const EXTERNAL_ACTIONS: Record<string, ExternalActionPreview> = {
  "fixture-action-1": {
    action_id: "fixture-action-1",
    kind: "google_gmail_send",
    status: "pending",
    created_at: Date.now() / 1000,
    expires_at: Date.now() / 1000 + 1800,
    preview: {
      to: ["someone@example.com"],
      subject: "여수 사무실 이전 — 네트워크 확인 사항",
      body_preview: "공유기를 안 가져가면 NAS 가 고립됩니다. NAS 는 자체 고정 IP 라 대역이 바뀌면 내부에서도 못 찾습니다. 젯슨은 Wi-Fi 에 물려 있어 같은 문제를 한 번 더 겪습니다.",
      attachments: [{ name: "이전_체크리스트.pdf" }],
    },
  },
};

/** 배속을 아는 시계. 연출은 느리게 돌려 보지 않으면 다듬을 수 없다. */
class Clock {
  private timers: number[] = [];
  constructor(private speed: number) {}

  setSpeed(value: number) {
    this.speed = value;
  }

  run(steps: ScriptStep[], fire: (step: ScriptStep) => void) {
    for (const step of steps) {
      this.timers.push(window.setTimeout(() => fire(step), step.at / this.speed));
    }
  }

  stop() {
    for (const timer of this.timers) window.clearTimeout(timer);
    this.timers = [];
  }
}

export class FixtureClient extends JarvisClient {
  private readonly clock: Clock;
  private history: ConversationHistory;
  private jobs: JobSummary[];
  private schedules: ScheduleRow[];
  private lastPrompt = "";
  private lastHandoffDirection: HandoffDirection | "" = "";
  private sendCount = 0;
  /** 이미 되돌린 것. 눌렀는데 목록에 그대로 남아 있으면 배선이 깨진 걸 못 잡는다. */
  private readonly undone = new Set<string>();

  constructor(
    private readonly scenario: Scenario,
    private readonly emit: (event: JarvisEvent) => void,
    private readonly setConnected: (connected: boolean) => void,
    speed = 1,
  ) {
    super({ baseUrl: "fixture://", controlToken: "fixture" }, emit, setConnected);
    this.clock = new Clock(speed);
    this.history = structuredClone(scenario.history);
    this.jobs = structuredClone(scenario.jobs ?? []);
    this.schedules = structuredClone(scenario.schedules ?? []);
  }

  // ── 재생 제어 (FixtureBar 가 쓴다) ────────────────────────────────────
  setSpeed(value: number) {
    this.clock.setSpeed(value);
  }

  /** 처음 상태로 되돌린다. 같은 장면을 여러 번 봐야 연출을 고칠 수 있다. */
  replayAmbient() {
    this.clock.stop();
    this.history = structuredClone(this.scenario.history);
    this.jobs = structuredClone(this.scenario.jobs ?? []);
    this.schedules = structuredClone(this.scenario.schedules ?? []);
    this.undone.clear();
    this.emit({ event: "approval_denied", payload: {} });
    this.emit({ event: "state_changed", payload: { to: "idle" } });
    this.playAmbient();
  }

  private playAmbient() {
    this.clock.run(this.scenario.ambient ?? [], (step) => {
      this.emit({ event: step.event, payload: step.payload ?? {} });
    });
  }

  // ── JarvisClient 대체 ────────────────────────────────────────────────
  override connect(): void {
    window.setTimeout(() => {
      this.setConnected(true);
      this.playAmbient();
    }, 40);
  }

  override disconnect(): void {
    this.clock.stop();
    this.setConnected(false);
  }

  // ── 설정·스킬 분야 리허설 (W3·W4) — 표본은 진짜 백엔드 함수에서 뽑았다(settingsFixture.json) ──
  private settingsView: SettingsView = structuredClone(settingsFixture.settings) as SettingsView;
  private domainsView: SkillDomainsView = structuredClone(settingsFixture.domains) as SkillDomainsView;

  // 권한 모드 단추 리허설(2026-09-23). 이름·설명은 서버 `permissions.MODES` 를 옮긴 시험 데이터다.
  private permission = "reversible";

  override async permissionMode(): Promise<PermissionModes> {
    return {
      mode: this.permission,
      modes: [
        { id: "workspace", label: "자동", help: "허락한 폴더 안의 파일은 알아서 만들고 고칩니다. 명령도 묻지 않고 실행합니다 — 명령은 그 폴더 밖의 파일도 바꿀 수 있습니다. 폴더 밖 파일 고치기와 메일·발행·삭제·결제는 물어봅니다." },
        { id: "ask", label: "수동", help: "바꾸기 전에 항상 확인합니다. 가장 안전합니다." },
        { id: "reversible", label: "편집 자동 수락", help: "되돌릴 수 있는 편집은 묻지 않고 합니다. 명령 실행·메일·발행·삭제는 물어봅니다." },
        { id: "read_only", label: "계획", help: "아무것도 바꾸지 않습니다. 읽고, 보고, 무엇을 할지 계획만 세웁니다." },
        { id: "bypass", label: "권한 무시", help: "묻지 않고 다 합니다(지우기·폴더 권한·PC 설정 포함). 결제·메일 보내기·블로그 발행만 확인합니다." },
      ],
      always_ask: ["google_gmail_send", "naver_blog_publish", "payment_confirm"],
      never_bypass: ["google_gmail_send", "naver_blog_publish", "payment_confirm"],
    };
  }

  override async setPermissionMode(mode: string): Promise<PermissionModes & { ok: boolean; error?: string }> {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    this.permission = mode;
    return { ok: true, ...(await this.permissionMode()) };
  }

  override async getSettings(): Promise<SettingsView> {
    return structuredClone(this.settingsView);
  }

  override async patchSettings(values: Record<string, SettingValue>): Promise<SettingsPatchResult> {
    this.settingsView = {
      ...this.settingsView,
      settings: this.settingsView.settings.map((row) => (row.key in values
        ? { ...row, value: values[row.key], source: "user" as const, restart_required: !row.live }
        : row)),
    };
    return { ok: true, ...structuredClone(this.settingsView) };
  }

  override async resetSettings(keys: string[]): Promise<SettingsPatchResult> {
    const base = settingsFixture.settings as SettingsView;
    this.settingsView = {
      ...this.settingsView,
      settings: this.settingsView.settings.map((row) => (keys.includes(row.key)
        ? base.settings.find((item) => item.key === row.key) ?? row
        : row)),
    };
    return { ok: true, ...structuredClone(this.settingsView) };
  }

  override async getSkillDomains(): Promise<SkillDomainsView> {
    return structuredClone(this.domainsView);
  }

  override async applySkillDomains(domains: string[]): Promise<SkillDomainsView & { ok: boolean }> {
    this.domainsView = {
      ...this.domainsView, selected: domains, route_enabled: domains.length > 0,
      domains: this.domainsView.domains.map((row) => ({ ...row, selected: domains.includes(row.id) })),
    };
    return { ok: true, ...structuredClone(this.domainsView) };
  }

  override async getBackup(): Promise<BackupSummary> {
    return {
      enabled: true, root: "C:\\Users\\me\\Ontelic\\backup", keep: 3, memory_empty: false,
      delete_confirmation: "delete-backups",
      generations: [
        { generation: "20260915-042640", created_at: 1789414000, reason: "shutdown", tables: { conversation_messages: 184, facts: 12 } },
        { generation: "20260914-090000", created_at: 1789344000, reason: "daily", tables: { conversation_messages: 160, facts: 11 } },
      ],
    };
  }

  override async getState(): Promise<{ state: string }> {
    return { state: "idle" };
  }

  override async getConfig(): Promise<JarvisPublicConfig> {
    return {
      ollama_model: "gemma4:26b-a4b-it-qat", ollama_num_ctx: 131_072,
      model_roles: { chat: "gemma4:26b-a4b-it-qat", code: "qwen3.8:27b-mtp-q4_K_M" },
      model_num_ctx: { code: 102_400 },
      memory_retrieval_enabled: true, memory_retrieval_limit: 4,
    };
  }

  /**
   * 업데이트 뒤 「바뀐 것」 리허설(2026-10-21) — `?fixture=…&whatsnew=0.4.30.0` 일 때만 띄운다(없으면 다른 리허설을 가리지 않게 조용히).
   * 글은 진짜 백엔드 `whats_new.notes_for` 의 출력이다(whatsNewFixture.json · 시험 `test_ui_fixture_matches_the_backend` 가 맞춰 본다).
   */
  override async getWhatsNew(language: Lang): Promise<WhatsNewStatus> {
    const version = new URLSearchParams(window.location.search).get("whatsnew") ?? "";
    const byVersion = (whatsNewFixture as Record<string, Record<string, WhatsNewStatus>>)[version];
    if (!byVersion) return { show: false, version: "" };
    return structuredClone(byVersion[language === "en" ? "en" : "ko"]);
  }

  override async markWhatsNewSeen(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  /** 「쓰는 법」 쇼 리허설(2026-10-27) — `?fixture=…&usageshow=1` 일 때만 띄운다. */
  override async getUsageShow(): Promise<UsageShowStatus> {
    return { show: new URLSearchParams(window.location.search).get("usageshow") === "1" };
  }

  override async markUsageShowSeen(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  override async checkUpdate(): Promise<UpdateStatus> {
    return structuredClone(this.scenario.update ?? { ok: true, mine: "", available: false });
  }

  override async applyUpdate(): Promise<{ ok: boolean; applied: boolean }> {
    // 리허설은 앱이 안 꺼진다 — 덮개가 남는 것이 맞는 모습이다.
    return { ok: true, applied: true };
  }

  override async getSelfCheck(): Promise<SelfCheckStatus> {
    // 진짜처럼 조금 늦게 답한다. 즉답하면 요청이 요청을 부르는 고리가 있을 때 화면이 통째로 얼어
    // 「무엇이 몇 번 불렸나」를 못 센다(2026-09-18 — 점검 줄이 결과마다 다시 묻는 고리를 이렇게 찾았다).
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    return structuredClone(this.scenario.selfCheck ?? { pending: false, organs: [] });
  }

  override async healSelf(): Promise<SelfHealResult> {
    // 리허설은 「눌렀는데 그대로」를 보여 준다 — 그 경우가 화면이 가장 많이 말해야 하는 경우다.
    return { ran: true, fixed: false, why: "다시 올려도 속도가 그대로입니다." };
  }

  override async exportDiagnostics(): Promise<{ ok: boolean; path: string; bytes: number }> {
    return { ok: true, path: "fixture-diagnostics.json", bytes: 1 };
  }

  override async openFolder(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  // ── 첫 화면 「이번 주 영수증」 리허설 (2026-10-21) — 시나리오에 없으면 셀 것이 없는 판(카드가 숨는다) ──
  override async getReceipt(days = 7): Promise<WeeklyReceipt> {
    const base: WeeklyReceipt = {
      days, delegated: { jobs: 0, pages: 0, tokens_at_least: 0, chars: 0, flagged_numbers_jobs: 0 },
      direct: { jobs: 0, pages: 0 }, callers: {}, measurement_jobs_skipped: 0, basis: "",
    };
    const until = Date.now() / 1000;
    return { ...base, since: until - days * 86400, until, ...structuredClone(this.scenario.receipt ?? {}) };
  }

  /** 저장한 그림을 개발 창에 남긴다 — 리허설에서 그림을 꺼내 눈으로 보려고(개발 빌드에서만 이 모듈이 실린다). */
  override async saveReceiptImage(pngBase64: string): Promise<ReceiptImageSaved> {
    (window as unknown as { __sonjariReceiptPng?: string }).__sonjariReceiptPng = pngBase64;
    return { ok: true, name: "sonjari-receipt-2026-10-21.png", short: "Sonjari\\receipts\\sonjari-receipt-2026-10-21.png" };
  }

  // ── 설정 › 팩 리허설 (2026-10-11) — 「다시 읽기」를 눌러야 넣은 스킬팩이 나타난다(진짜도 그렇다) ──
  private packRows: PackInfo[] = [{
    id: "game", name: "게임 팩", version: "0.2.0", kind: "code",
    summary: "유니티 프로젝트를 점검하고, 열려 있는 에디터를 같이 보며 승인을 받아 만진다.", description: "",
    tools: ["unity_project_info", "unity_list_recipes", "unity_run_recipe"], skills: ["game-unity"], domains: ["game"],
    permissions: { reads: ["허락한 유니티 프로젝트 폴더"], writes: ["프로젝트의 Assets/Editor/SonjariRecipes — 도는 동안만"], runs: ["Unity.exe — 배치 모드"], network: "쓰지 않는다" },
    bench: "bench/game_pack", enabled: false, origin: "builtin", triggers: {},
  }];
  private static readonly DROPPED: PackInfo = {
    id: "price-watch-demo", name: "가격 조사 스킬팩", version: "1.0.0", kind: "content",
    summary: "정해 둔 가게 다섯 곳의 같은 상품 가격을 모아 엑셀로 정리한다.", description: "",
    tools: [], skills: ["price-watch"], domains: [],
    permissions: { reads: ["손자리가 여는 가게 페이지"], writes: ["결과 엑셀 파일"], runs: [], network: "손자리가 여는 페이지만" },
    bench: "", enabled: false, origin: "user", triggers: { "price-watch": ["가격 조사", "가격조사", "가격 비교"] },
    asks: { "price-watch": "말한 상품을 스킬에 적힌 가게마다 찾아 판매 가격과 배송비를 엑셀 파일로 정리해 줘" },
  };

  private packsView(): PacksView {
    return { packs: structuredClone(this.packRows), problems: [], user_dir: "C:\\Users\\me\\Documents\\Sonjari\\skillpacks" };
  }

  override async listPacks(): Promise<PacksView> {
    return this.packsView();
  }

  override async rescanPacks(): Promise<PacksView> {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    if (!this.packRows.some((row) => row.id === FixtureClient.DROPPED.id)) this.packRows.push(structuredClone(FixtureClient.DROPPED));
    return this.packsView();
  }

  override async setPack(packId: string, on: boolean): Promise<PackInfo> {
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    const row = this.packRows.find((item) => item.id === packId);
    if (!row) throw new Error("unknown_pack");
    row.enabled = on;
    return structuredClone(row);
  }

  override async getGoogleStatus(): Promise<GoogleStatus> {
    return { ...DEFAULT_GOOGLE, ...this.scenario.google };
  }

  override async startGoogleOAuth() {
    return { ok: true, opened_browser: true, authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?fixture=1" };
  }

  override async togglePtt(): Promise<{ action: "started" | "stopped" }> {
    return { action: "started" };
  }

  override async noteWorkspacePresence() {
    return { ok: true, ttl_sec: 45 };
  }

  override async getConversations(): Promise<ConversationSummary[]> {
    // 화면은 목록의 맨 앞 대화를 연다. 시나리오가 준비한 기록이 그 자리에 없으면
    // 빈 대화가 열려 리허설이 통째로 헛돈다 — 그래서 앞으로 끌어온다.
    const rows = structuredClone(this.scenario.sessions);
    const target = this.history.session_id;
    const found = rows.findIndex((row) => row.session_id === target);
    if (found > 0) rows.unshift(...rows.splice(found, 1));
    if (found < 0 && target !== this.scenario.history.session_id) {
      rows.unshift({
        session_id: target,
        title: "Claude Code에서 이어온 · 결제 모듈 리팩터링",
        preview: this.lastPrompt,
        message_count: this.history.messages.length,
        updated_at: Date.now() / 1000,
        has_summary: false,
      });
    }
    return rows;
  }

  /** 내 PC 모델이 지은 대화 제목(리허설: 이 PC 의 모델이 10-26 에 실제로 지은 것 · `generated_reports/claude_agent_fixes_1026`). */
  override async conversationTitles(): Promise<{ items: Record<string, { title: string; source: string }> }> {
    return this.scenario.id === "claude-hands"
      ? { items: { "claude-room": { title: "국내 AI 에이전트 소식 장표", source: "model" } } }
      : { items: {} };
  }

  override async nameConversation(): Promise<{ scheduled: boolean; title: string }> {
    return { scheduled: false, title: "" };
  }

  override async getConversation(sessionId: string): Promise<ConversationHistory> {
    if (sessionId === this.history.session_id) return structuredClone(this.history);
    return { session_id: sessionId, summary: "", has_summary: false, messages: [], context_window: 131_072, retrieval_enabled: true };
  }

  override async sendChat(
    prompt: string,
    sessionId = "",
    attachments: ChatAttachment[] = [],
    _delivery: "auto" | "screen" = "auto",
    _origin: ChatOrigin = "chat",
    _workspaceMode: WorkspaceMode = "cowork",
    _codeWorkspace = "",
    displayPrompt = "",
    handoffDirection: HandoffDirection | "" = "",
  ) {
    this.lastPrompt = prompt;
    this.lastHandoffDirection = handoffDirection;
    const jobId = `${JOB_ID}-${++this.sendCount}`;
    // 사용자 발화는 컴포넌트가 이미 낙관적으로 얹었다. 여기서는 "끝난 뒤 다시
    // 불러올 기록"에만 넣는다 — 실제 백엔드와 같은 순서다.
    this.history = {
      ...this.history,
      session_id: sessionId || this.history.session_id,
      messages: [
        ...this.history.messages,
        {
          id: Date.now(), session_id: sessionId || this.history.session_id, role: "user",
          content: displayPrompt || prompt, kind: "chat",
          metadata: attachments.length ? { attachments: attachments.map(({ name, mime_type }) => ({ name, mime_type })) } : {},
          created_at: Date.now() / 1000,
        },
      ],
    };
    this.clock.run(this.scenario.onSend ?? [], (step) => {
      if (step.event === "job_completed") this.settle(jobId);
      this.emit({ event: step.event, payload: { job_id: jobId, ...(step.payload ?? {}) } });
    });
    return { id: jobId, status: "queued" };
  }

  override async prepareCoworkTakeover(
    takeoverId: number,
    direction: HandoffDirection,
    custom = "",
  ): Promise<CoworkTakeoverPrepared> {
    const chosen = direction === "custom" ? custom : {
      continue: "멈춘 자리부터 이어가기",
      review: "지금까지 한 일과 근거부터 검토하기",
      tasks: "남은 일만 체크리스트로 정리하기",
    }[direction];
    return {
      ok: true, takeover_id: takeoverId, tool: "claude_code", tool_name: "Claude Code",
      title: "Claude Code에서 이어온 · 결제 모듈 리팩터링",
      prompt: `Claude Code에서 이어온 작업 · 결제 모듈 리팩터링\n\n마지막 요청: 결제 실패 회귀 테스트도 붙여 줘\n\n사용자 선택: ${chosen}`,
      direction,
    };
  }

  override async dismissTakeover(takeoverId: number) {
    return { ok: true, takeover_id: takeoverId };
  }

  /** 작업이 끝나면 답이 대화 기록으로 안착한다 — 여기가 실제 배선의 마지막 한 걸음이다. */
  private settle(jobId: string) {
    const answer = this.scenario.settledAnswer;
    if (!answer) return;
    this.history = {
      ...this.history,
      messages: [
        ...this.history.messages,
        {
          id: Date.now() + 1, session_id: this.history.session_id, role: "assistant",
          // 실제 백엔드처럼 답에 그 판 번호를 단다 — 답 아래 「답이 기댄 페이지」가 이 번호로 판 결과를 묻는다.
          content: answer, kind: "chat", metadata: { job_id: jobId }, created_at: Date.now() / 1000,
        },
      ],
    };
  }

  // ── 할 수 있는 일 (R5) ───────────────────────────────────────────────
  override async getCapabilities(): Promise<Capabilities> {
    return fakeCapabilities();
  }

  // ── 걸음이 본 것 (P10·P11) ───────────────────────────────────────────
  // 리허설에서도 **진짜로 열린다.** 못 여는 눈금은 나머지 눈금까지 못 믿게 만든다.
  private steps(): Observation[] {
    return (this.scenario.steps ?? FIXTURE_STEPS) as Observation[];
  }

  override async listSteps(jobId: string) {
    const items = this.steps().map(({ payload, arguments: args, truncation, job_id, ...row }) => row);
    return { job_id: jobId, count: items.length, items: items as StepRow[] };
  }

  override async getStep(jobId: string, step: number): Promise<Observation | null> {
    const found = this.steps().find((row) => row.step === step);
    return found ? { ...structuredClone(found), job_id: jobId } : null;
  }

  // ── 만든 것 · 되돌리기 (R4) ──────────────────────────────────────────
  override async listOutputs(jobId: string) {
    const items = structuredClone(this.scenario.outputs ?? []) as JobOutput[];
    return { job_id: jobId, count: items.length, items };
  }

  // ── 답이 기댄 페이지 (2026-10-18) ──────────────────────────────────
  override async getJob(jobId: string): Promise<JobDetail> {
    const finished = Math.floor(Date.now() / 1000);
    return {
      id: jobId, kind: "chat", title: this.lastPrompt, status: "completed", risk_level: "L0", error: "", build: "",
      created_at: finished - 60, updated_at: finished, started_at: finished - 59, finished_at: finished, attempts: 1,
      result: { answer: this.scenario.settledAnswer ?? "", showcase: structuredClone(this.scenario.showcase ?? []) },
    } as JobDetail;
  }

  override async fetchShowcaseShot(_jobId: string, index: number): Promise<Blob | null> {
    const shot = (this.scenario.showcase ?? [])[index];
    return shot ? fakePage(shot.title, shot.url) : null;
  }

  override async fetchOutput(_jobId: string, path: string): Promise<Blob | null> {
    // 리허설에서도 진짜로 열린다. 못 여는 버튼은 나머지 버튼까지 못 믿게 만든다.
    return fakePage(path.split("/").pop() ?? "산출물", path);
  }

  override async listUndo(): Promise<{ count: number; items: UndoOffer[] }> {
    // 되돌리기는 **잡에 매여 있다.** 시나리오는 job_id 를 모르므로 방금 만든
    // 잡으로 갈아 끼운다 — 안 그러면 목록에는 있는데 어느 궤적에도 안 붙는다.
    const jobId = `${JOB_ID}-${this.sendCount}`;
    const items = (this.scenario.undo ?? [])
      .filter((row) => !this.undone.has(row.undo_id))
      .map((row) => ({ ...structuredClone(row), job_id: jobId }));
    return { count: items.length, items };
  }

  override async runUndo(undoId: string) {
    this.undone.add(undoId);
    this.emit({ event: "undo_done", payload: { undo_id: undoId } });
    return { ok: true, verified: true };
  }

  // ── 자비스가 보는 화면 (R2) ──────────────────────────────────────────
  override async getBrowserStatus(): Promise<BrowserStatus> {
    return { ...DEFAULT_BROWSER, ...this.scenario.browser };
  }

  override async getBrowserFrame(): Promise<BrowserFrame> {
    const page = this.scenario.browserFrame;
    if (!page) {
      // 상태가 이유를 갖고 있으면 그것을, 없으면 안 떠 있다고. 실제 백엔드와 같다.
      const status = { ...DEFAULT_BROWSER, ...this.scenario.browser };
      return {
        ok: false, blob: null, pageUrl: "", title: "", ageSec: 0, fresh: false,
        reason: status.attach_error || "browser_not_started",
      };
    }
    return {
      ok: true, blob: fakePage(page.title, page.url), pageUrl: page.url, title: page.title,
      ageSec: 0, fresh: true, reason: "",
    };
  }

  // ── 브라우저 무대 (2026-09-24) — 스트림을 흉내 낸다: 첫 장을 주고, 그 뒤엔 새 장 없이 1초씩 기다린다(정적 페이지와 같다) ──
  private liveSeq = 0;
  private liveControlOn = false;

  override async getLiveFrame(after: number): Promise<LiveFrame> {
    const page = this.scenario.browserFrame;
    const base = { blob: null, seq: after, width: 1440, height: 620, url: page?.url ?? "", status: page ? "streaming" : "no_page",
      control: this.liveControlOn, releaseIn: this.liveControlOn ? 118 : 0 };
    if (!page) { await new Promise((resolve) => window.setTimeout(resolve, 300)); return base; }
    if (after >= this.liveSeq && this.liveSeq > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, 1_000));
      // 실제 서버처럼 **기다린 뒤의** 상태를 준다.
      return { ...base, control: this.liveControlOn, releaseIn: this.liveControlOn ? 118 : 0 };
    }
    this.liveSeq += 1;
    return { ...base, blob: fakePage(page.title, page.url), seq: this.liveSeq };
  }

  override async sendLiveInput(): Promise<{ ok: boolean }> {
    this.liveControlOn = true;
    return { ok: true };
  }

  override async liveControl(action: "take" | "release"): Promise<{ ok: boolean; active: boolean }> {
    this.liveControlOn = action === "take";
    return { ok: true, active: this.liveControlOn };
  }

  override async liveFit(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  // ── 일감 (R1) ────────────────────────────────────────────────────────
  // 시나리오가 준 목록을 그대로 돌려준다. 취소는 **정말 상태를 바꾼다** — 눌러도
  // 아무 일 없는 리허설은 배선이 깨진 걸 못 잡는다.
  override async listJobs(): Promise<JobSummary[]> {
    return structuredClone(this.jobs);
  }

  override async listSchedules(): Promise<ScheduleList> {
    const rows = structuredClone(this.schedules);
    return { action: "schedule_list", count: rows.length, schedules: rows };
  }

  override async cancelSchedule(scheduleId: string): Promise<ScheduleRow> {
    const found = this.schedules.find((row) => row.id === scheduleId);
    this.schedules = this.schedules.map((row) => (row.id === scheduleId ? { ...row, status: "cancelled" } : row));
    this.emit({ event: "schedule_cancelled", payload: { schedule_id: scheduleId } });
    return { ...(found ?? this.schedules[0]), status: "cancelled" };
  }

  override async cancelJob(jobId: string) {
    this.jobs = this.jobs.map((row) => (
      row.id === jobId ? { ...row, status: "cancelled", finished_at: Date.now() / 1000 } : row
    ));
    this.clock.stop();
    this.emit({ event: "job_cancelled", payload: { job_id: jobId } });
    return { ok: true, job_id: jobId };
  }

  override async continueAgent(jobId: string) {
    this.emit({ event: "agent_continuation_resumed", payload: { job_id: jobId } });
    return { ok: true };
  }

  override async decideApproval(nonce: string, approve: boolean, answer?: string) {
    this.emit({ event: approve ? "approval_approved" : "approval_denied", payload: { nonce, answer } });
    this.emit({ event: "state_changed", payload: { to: "idle" } });
    return { ok: true };
  }

  override async listPeople(): Promise<PeopleStatus> {
    return { ...DEFAULT_PEOPLE, ...this.scenario.people };
  }

  override async discoverPerson(name: string): Promise<DiscoverPersonResult> {
    return { ok: true, registered: true, name, similarity_to_known: 0.21, threshold: 0.42, steps: 6, embeddings: 4 };
  }

  override async forgetPerson(name: string) {
    const registered = (this.scenario.people?.registered ?? []).filter((row) => row !== name);
    return { ok: true, remaining: registered };
  }

  override async getExternalAction(actionId: string): Promise<ExternalActionPreview> {
    const found = EXTERNAL_ACTIONS[actionId];
    if (!found) throw new Error(`미리보기가 없습니다: ${actionId}`);
    return structuredClone(found);
  }

  /** 마지막으로 보낸 문장 — FixtureBar 가 다시 보낼 때 쓴다. */
  get prompt(): string {
    return this.lastPrompt;
  }

  /** 마지막 채팅 요청에 실린 인계 방향 — 캡슐 선택이 계약으로 실리는지 시험이 본다. */
  get handoffDirection(): HandoffDirection | "" {
    return this.lastHandoffDirection;
  }
}
