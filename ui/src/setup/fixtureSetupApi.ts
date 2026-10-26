/**
 * 첫 실행 화면 리허설 — **개발 빌드 전용**, 동적 import 로만 불린다.
 *
 * `fixturePcs.json` 은 화면용으로 지어낸 값이 아니다. 진짜 백엔드 추천 함수
 * (`setup_profile.recommend` · `catalog_view`)에 PC 일곱 대 사양을 넣어 뽑은 출력이다
 * (`python scripts/make_setup_fixtures.py`). 화면이 보는 추천과 실제 추천이 갈리지 않게 하려는 것이다.
 *
 *     ?mode=setup&setupFixture=3090 | 4080-laptop | 4060-8gb | 3050-laptop | rx7800xt | gtx1650 | no-gpu
 */
import connectFixture from "./fixtureConnect.json";
import imports from "./fixtureImport.json";
import pcs from "./fixturePcs.json";
import type {
  ConnectScan,
  OllamaStatus,
  SetupStateView,
  AboutMeAnswers,
  AboutMeView,
  ApplyResult,
  CatalogModel,
  ContextCeiling,
  ContextRung,
  ContextView,
  HfCheck,
  ImportedItem,
  ImportPreviewItem,
  ImportScan,
  InstalledModel,
  ModelPick,
  ModelsView,
  PcProfile,
  PullState,
  Recommendation,
  SetupApi,
} from "./setupApi";
import type { SkillDomainsView } from "../types";

type Bundle = {
  profile: PcProfile;
  recommendation: Recommendation;
  models: ModelsView["models"];
  installed_models: InstalledModel[];
};

/**
 * 같은 모델의 크기 둘 + 조건 없는 대안 하나 (2026-10-08) — 「크기 고르기」 줄 · 라이선스 줄 · 대안 배지를 리허설에서 보려는 표본.
 *
 * `fixturePcs.json` 은 이 모델들이 목록에 들어오기 전에 뽑은 것이라 여기서 덧붙인다. 그 파일을 다시 뽑아 같은 key 가
 * 생기면 **그쪽이 이긴다**(아래 `withSizeDemo`). 받는 크기·메모리는 RTX 3090 에서 잰 값이고, 글은 백엔드 목록
 * (`model_catalog.py`)의 것을 옮겼다 — 값을 고칠 때는 그 목록부터 고치고 여기를 맞춘다(그림 부속을 붙이고 nvidia-smi 로 잰 값).
 * 들어가는지(`fits`)는 진짜 백엔드가 재서 주는 값이다 — 여기서는 카드의 쓸 수 있는 메모리로 흉내만 낸다.
 */
type DemoModel = Omit<CatalogModel, "installed" | "fits" | "largest_fitting_ctx">;
const SWIFT: DemoModel = {
  key: "qwen3.8-27b-swift",
  name: "Swift 1.5 · Qwen 3.8 27B (3비트)",
  vendor: "UkisAI",
  ollama_tag: "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf",
  download_gb: 13.05,
  vram_gb: { "32768": 14.8, "65536": 16.1, "131072": 18.9 },
  chain: null,
  roles: ["chat", "vision"],
  vision: true,
  blurb: "Qwen 3.8 27B 를 손본 판입니다. 그래픽카드 24GB 급에서 128K 창까지 다 올라가는 것을 이 PC 에서 쟀습니다.",
  good_at: "코드 과제 12개 중 12개(창 64K · 과제마다 한 판) · 웹 조사 두 판에서 답의 값 53개 중 52개가 읽은 글과 일치",
  status: "verified",
  license: "Swift Open License v1.0",
  license_open: false,
  license_url: "https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/blob/main/LICENSE",
  evidence: [],
  caution: "",
  links: [{ label: "모델 카드", url: "https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF" }],
  checked_at: "2026-10-08",
  vram_measured: true,
  memory_device: "RTX 3090 24GB",
  minimum_vram_gb: 22,
  family: "swift-27b",
  family_name: "Swift 1.5 · Qwen 3.8 27B",
  quant: "IQ3_S",
  quant_label: "3비트",
  // 그림 부속을 따로 붙이는 모델 — 「그림 읽기」 줄이 보인다(백엔드 `model_catalog.public`).
  pictures_optional: true,
  text_only_tag: "sonjari-text-qwen3.8-27b-swift",
  text_only_saves_gb: 1.1,
};
const SIZE_DEMO: DemoModel[] = [
  SWIFT,
  {
    ...SWIFT,
    key: "qwen3.8-27b-swift-iq3xxs",
    text_only_tag: "sonjari-text-qwen3.8-27b-swift-iq3xxs",
    name: "Swift 1.5 · Qwen 3.8 27B (3비트 작게)",
    ollama_tag: "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf",
    download_gb: 11.37,
    vram_gb: { "32768": 13.5, "65536": 14.6, "131072": 17.3 },
    blurb: "같은 모델을 더 작게 눌러 담은 크기입니다. 받는 크기와 메모리가 조금 줄어듭니다.",
    good_at: "코드 과제 12개 중 12개(창 64K · 과제마다 한 판)",
    weak_at: "같은 과제에서 3비트 크기보다 걸음이 많고(116 대 85) 시간이 1.3배 들었습니다",
    quant: "IQ3_XXS",
    quant_label: "3비트 작게",
  },
  {
    key: "qwen3.8-27b-gsq",
    name: "Qwen 3.8 27B (압축 3비트)",
    vendor: "Alibaba · ISTA-DASLab 압축",
    ollama_tag: "hf.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf",
    download_gb: 13.05,
    vram_gb: { "32768": 14.8, "65536": 16.1, "131072": 18.9 },
    chain: null,
    roles: ["chat", "vision"],
    vision: true,
    blurb: "Qwen 3.8 27B 를 3비트로 눌러 담은 판입니다. 화면 읽기까지 한 모델로 됩니다.",
    good_at: "코드 과제 12개 중 11개(창 64K · 과제마다 한 판)",
    weak_at: "같은 과제에서 두 판이 600초 상한에 걸렸습니다(한 판은 답을 맞히고도 못 끝냄)",
    status: "verified",
    license: "Apache 2.0",
    license_open: true,
    license_url: "",
    evidence: [],
    caution: "",
    links: [{ label: "모델 카드", url: "https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF" }],
    checked_at: "2026-10-08",
    vram_measured: true,
    memory_device: "RTX 3090 24GB",
    minimum_vram_gb: 22,
    family: "",
    family_name: "",
    quant: "IQ3_S",
    quant_label: "3비트",
  },
];
const OPEN_ALTERNATIVE_KEY = "qwen3.8-27b-gsq";

function pickOf(model: CatalogModel, kind: ModelPick["kind"]): ModelPick {
  const ctx = model.largest_fitting_ctx ?? 0;
  return { kind, model_key: model.key, name: model.name, ollama_tag: model.ollama_tag, num_ctx: ctx,
    vram_gb: model.vram_gb[String(ctx)], download_gb: model.download_gb, installed: model.installed,
    confidence: "measured", license: model.license, chain: model.chain };
}

/**
 * 표본 묶음을 PC 표본에 덧붙인다. 대안은 그 PC 에 들어갈 때만 추천(`picks`)에 `open_alternative` 로 넣는다.
 *
 * `&setupPick=qwen3.8-27b-swift` — 검증 추천을 그 모델로 바꿔 「이 PC 추천」 칩과 강조를 본다. **추천의 까닭(reasons)은
 * 원래 표본의 글 그대로다**(지어내지 않는다) — 이 인자는 오른쪽 카드 모양을 보는 용도다.
 */
function withSizeDemo(bundle: Bundle, forcedPick: string | null): Bundle {
  const usable = Math.max(0, ...bundle.profile.gpus.filter((gpu) => !gpu.integrated).map((gpu) => Number(gpu.usable_gb) || 0));
  const have = new Set(bundle.models.map((model) => model.key));
  const extra: CatalogModel[] = SIZE_DEMO.filter((model) => !have.has(model.key)).map((model) => {
    const fitting = Object.entries(model.vram_gb).filter(([, gb]) => gb <= usable).map(([ctx]) => Number(ctx));
    return { ...model, installed: false, fits: fitting.length > 0, largest_fitting_ctx: fitting.length ? Math.max(...fitting) : null };
  });
  const models = [...bundle.models, ...extra];
  let recommendation = bundle.recommendation;
  let picks = [...(recommendation.picks ?? [])];
  const alternative = models.find((model) => model.key === OPEN_ALTERNATIVE_KEY);
  if (alternative?.fits && !picks.some((pick) => pick.model_key === alternative.key)) {
    picks.push(pickOf(alternative, "open_alternative"));
  }
  const forced = forcedPick ? models.find((model) => model.key === forcedPick && model.fits) : undefined;
  if (forced) {
    picks = [pickOf(forced, "verified"), ...picks.filter((pick) => pick.kind !== "verified" && pick.model_key !== forced.key)];
    recommendation = { ...recommendation, model_key: forced.key, ollama_tag: forced.ollama_tag,
      num_ctx: forced.largest_fitting_ctx, installed: forced.installed };
  }
  return { ...bundle, models, recommendation: { ...recommendation, picks } };
}

/**
 * `fixtureImport.json` 도 진짜 백엔드(`InstructionImportService` · `secret_scrub`)에 **지어낸
 * 가상의 지침 파일**을 넣어 뽑은 출력이다. 키는 전부 가짜이고, 걷은 결과만 담겨 가짜 키조차
 * 들어 있지 않다. 리허설에서 붙여 넣은 글은 무엇을 넣든 표본 하나로 답한다 — 화면이 비밀을
 * 판단하지 않게 하려는 것이다.
 */
type ImportFixture = {
  project_path: string;
  global: ImportScan;
  project: ImportScan;
  preview: { plain: ImportPreviewItem[]; contacts: ImportPreviewItem[] };
  paste_example: ImportPreviewItem;
  imported: Record<string, ImportedItem>;
};

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function fixtureSetupNames(): string[] {
  return Object.keys(pcs);
}

export function createFixtureSetupApi(name: string): SetupApi | null {
  const sample = (pcs as unknown as Record<string, Bundle>)[name];
  if (!sample) return null;
  const bundle = withSizeDemo(sample, new URLSearchParams(window.location.search).get("setupPick"));
  const pulls: Record<string, PullState> = {};
  const installed = new Set(bundle.profile.ollama.installed);
  const ceilings: Record<string, ContextCeiling> = {};
  const contextState: ContextView = { chat_model: bundle.models[0]?.ollama_tag ?? "", num_ctx: 32768, ceilings,
    measuring: false, live: null, global: { value: "", ours: false },
    // 리허설: 잰 뒤 뱀부 스튜디오가 카드에서 빠진 상황(2026-09-23 이 PC 에서 실제로 있었던 일).
    watch: { state: "changed", left: ["bambu-studio"], joined: [], measured_at: "2026-09-23T05:26:43" } };
  const imp = imports as unknown as ImportFixture;
  // 연결 칸 — 진짜 ConnectService 에 가상 홈을 넣어 뽑은 상태. 「실제로 띄워 확인」 값만 개발 PC 에서 실제로 띄운 것.
  const cx = connectFixture as unknown as {
    scan: ConnectScan;
    manual_claude_code: string;
    verify: { ok: boolean; tool_count?: number; error?: string };
  };
  const connected = new Set<string>();
  let desktopWaiting = false;
  let hookOn = false;
  let guideInstalled = false;
  let guideZip = false;
  let guideNote = false;
  const connectView = (): ConnectScan => ({
    ...cx.scan,
    clients: cx.scan.clients.map((c) => ({
      ...c,
      registered: connected.has(c.id),
      // 실제 백엔드는 켜져 있어도 누를 수 있게 준다(`_scan_desktop` — 누르면 닫히는 순간 잇는다).
      ...(c.id === "claude_desktop" && c.running
        ? { can_apply: true, waiting_for_close: desktopWaiting && !connected.has(c.id) } : {}),
    })),
    hooks: { ...cx.scan.hooks, claude_code_session_start: hookOn },
  });
  const stored = new Map<string, ImportedItem>();
  let nextImportId = 1;
  const withImported = (scan: ImportScan): ImportScan => ({
    ...scan,
    candidates: scan.candidates.map((c) => {
      const row = stored.get(c.id);
      return row ? { ...c, imported: { import_id: row.import_id, status: row.status } } : c;
    }),
  });

  // 「나에 대한 지침」 리허설(2026-10-18) — 화면 모양만 보려는 것이다. 줄을 만드는 진짜 규칙은 백엔드 `about_me.card_lines`
  // 한 곳이고, 여기 줄은 그 모양을 흉내 낸 고정 글이다(시험은 이 가짜를 쓰지 않는다).
  let aboutText = "";
  let aboutAnswers: AboutMeAnswers = { user_label: "", work_text: "", length: "", tone: "", sites: [], avoid_text: "" };
  const fakeLines = (a: AboutMeAnswers): string[] => [
    ...(a.work_text ? [`- 하는 일: ${a.work_text}`] : []),
    ...(a.length === "short" ? ["- 답은 짧게, 핵심부터."] : a.length === "long" ? ["- 답은 자세히, 까닭과 예를 들어."] : []),
    ...(a.tone === "casual" ? ["- 말투는 편하게, 딱딱하지 않게."] : a.tone === "polite" ? ["- 말투는 정중하게, 존댓말로."] : []),
    ...(a.sites.length ? [`- 자주 쓰는 사이트: ${a.sites.join(", ")}`] : []),
    ...(a.avoid_text ? [`- 하지 말 것: ${a.avoid_text}`] : []),
  ];
  const asAnswers = (raw: { sites: string[] | string } & Omit<AboutMeAnswers, "sites">): AboutMeAnswers => ({
    ...raw, sites: (Array.isArray(raw.sites) ? raw.sites : raw.sites.split(",")).map((x) => x.trim()).filter(Boolean),
  });
  const aboutView = (extra: Partial<AboutMeView> = {}): AboutMeView => {
    const tokens = aboutText ? Math.ceil((aboutText.length + 120) / 2) : 0;
    return {
      ok: true, path: "C:\\Users\\you\\AppData\\Local\\Ontelic\\data\\JARVIS_PROFILE.md", exists: Boolean(aboutText),
      content_raw: aboutText, chars: aboutText.trim().length, max_chars: 6000, truncated: false, has_card: aboutText.includes("sonjari:card"),
      answers: aboutAnswers, sent_chars: aboutText.length, tokens, num_ctx: 32768,
      share: tokens / 32768, share_pct: Math.round((tokens / 32768) * 1000) / 10,
      warn: tokens / 32768 > 0.1, warn_share: 0.1, chars_per_token: 2, ...extra,
    };
  };
  const withCard = (lines: string[]) => {
    const rest = aboutText.replace(/<!-- sonjari:card[\s\S]*?<!-- \/sonjari:card -->\n?/, "").trim();
    const card = lines.length ? `<!-- sonjari:card -->\n${lines.join("\n")}\n<!-- /sonjari:card -->\n` : "";
    return card + (rest ? `${rest}\n` : "");
  };

  // 첫 실행 칸(W2) 리허설 — Ollama 가 이미 있으면 그대로, 없으면 받기→해시 대조→켜기를 흉내 낸다.
  // `&setupOllama=missing` — 다섯 PC 표본이 전부 Ollama 가 있어 버튼 흐름을 볼 표본을 따로 연다.
  const ollamaRunning = bundle.profile.ollama.reachable
    && new URLSearchParams(window.location.search).get("setupOllama") !== "missing";
  let ollama: OllamaStatus = {
    running: ollamaRunning, version: bundle.profile.ollama.version, bundled: "", managed: false,
    can_install: !ollamaRunning, source: "https://github.com/ollama/ollama/releases", install: { phase: "idle" },
  };
  let setupDone: SetupStateView = { completed: false, steps: [] };
  // 쓰임 칸 리허설 — 이름은 실제 수확물(skills/vendor)의 스킬 이름에서 몇 개만 옮겼다.
  let domainView: SkillDomainsView = {
    selected: [], route_enabled: false, active_count: 96, total_served: 96,
    domains: [
      { id: "office", label: "사무·문서", blurb: "보고서·엑셀·공지문·메일 문장 다듬기", selected: false, missing: [],
        skills: [{ name: "document-craft", what: "", triggers: ["문서로", "보고서로", "엑셀로"] }, { name: "internal-comms", what: "", triggers: ["공지", "안내문", "주간 보고"] }] },
      { id: "research", label: "조사·리서치", blurb: "시장·경쟁사·고객 조사, 근거 있는 비교 정리", selected: false, missing: [],
        skills: [{ name: "competitors", what: "", triggers: ["경쟁사", "경쟁 분석"] }, { name: "customer-research", what: "", triggers: ["고객 조사", "니즈 파악"] }] },
      { id: "career", label: "취업·이직", blurb: "공고 찾기·이력서 첨삭·지원서 맞추기", selected: false, missing: [],
        skills: [{ name: "career-job-search", what: "", triggers: ["공고", "채용", "이직"] }, { name: "career-resume-review", what: "", triggers: ["이력서", "자소서"] }] },
    ],
  };

  return {
    async setupState() {
      return setupDone;
    },
    async finishSetup(steps) {
      setupDone = { completed: true, steps, completed_at: Date.now() / 1000 };
      return setupDone;
    },
    async ollamaStatus() {
      return ollama;
    },
    async reportPreview() {
      return { id: "rehearsal", text: JSON.stringify({ schema: 1, first_run: { setup: { completed: false, steps: ["pc_check"] } } }, null, 2), to: "(리허설 — 보내지 않습니다)" };
    },
    async reportSend() {
      return { ok: true, id: "rehearsal" };
    },
    async ollamaGpuOnly() {
      return { ok: true, setting_written: true, restarted: "external" as const };
    },
    async ollamaInstall() {
      if (ollama.running) return { ok: false, error: "already_running" };
      const total = 1_320_000_000;
      const phases: OllamaStatus["install"][] = [
        { phase: "downloading", received: total / 3, total },
        { phase: "downloading", received: total, total },
        { phase: "verifying" },
        { phase: "extracting" },
        { phase: "ready", version: "v0.12.0" },
      ];
      phases.forEach((install, index) => window.setTimeout(() => {
        ollama = { ...ollama, install, ...(install.phase === "ready" ? { running: true, version: "0.12.0", managed: true, can_install: false } : { can_install: false }) };
      }, 700 * (index + 1)));
      return { ok: true, phase: "resolving" };
    },
    async ollamaRepair() {
      ollama = { ...ollama, runner_missing: false, install: { phase: "starting" } };
      window.setTimeout(() => {
        ollama = { ...ollama, running: true, version: "0.12.0", managed: true, can_install: false, install: { phase: "ready" } };
      }, 1400);
      return { ok: true, phase: "starting" as const, stopped: 1 };
    },
    async backupStatus() {
      return { enabled: true, root: "C:\\Users\\me\\Ontelic\\backup", keep: 3, generations: [], latest: null,
        memory_empty: true, delete_confirmation: "delete-backups" };
    },
    async backupRestore() {
      return { ok: false, error: "not_found" };
    },
    async skillDomains() {
      return domainView;
    },
    async applySkillDomains(domains) {
      await wait(400);
      domainView = {
        ...domainView,
        selected: domains,
        route_enabled: domains.length > 0,
        domains: domainView.domains.map((row) => ({ ...row, selected: domains.includes(row.id) })),
      };
      return domainView;
    },
    async profile() {
      await wait(900);
      return bundle.profile;
    },
    async recommendation() {
      await wait(400);
      return bundle.recommendation;
    },
    async models() {
      await wait(150);
      return {
        models: bundle.models.map((m) => ({ ...m, installed: installed.has(m.ollama_tag) })),
        selection: null,
        current_chat_model: "",
        pulls: { ...pulls },
        satellite: false,
        source: "env",
      };
    },
    async pull(modelKey) {
      const model = bundle.models.find((m) => m.key === modelKey);
      const total = Math.round((model?.download_gb ?? 6) * 1024 ** 3);
      const state: PullState = { model_key: modelKey, status: "pulling", completed: 0, total, detail: "받는 중" };
      pulls[modelKey] = state;
      const timer = window.setInterval(() => {
        state.completed = Math.min(total, state.completed + total / 12);
        if (state.completed >= total) {
          state.status = "done";
          state.detail = "받았습니다";
          if (model) installed.add(model.ollama_tag);
          window.clearInterval(timer);
        }
      }, 500);
      return { ok: true, ...state };
    },
    async apply(): Promise<ApplyResult> {
      await wait(2200);
      return { ok: true, bench: { ok: true, tokens_per_sec: 41.8, load_sec: 6.2 }, offload: { gpu_share: 1 }, warnings: [],
               selection: { chat_model: contextState.chat_model, num_ctx: contextState.num_ctx } };
    },
    async installedModels() {
      await wait(300);
      const known = new Map(bundle.installed_models.map((row) => [row.name, row]));
      // 리허설에서 직접 입력으로 받은 태그는 도구 호출 여부를 모른다 — 「안 됨」으로 둔다(진짜 백엔드는 /api/show 로 묻는다).
      for (const tag of installed) {
        if (!known.has(tag)) known.set(tag, { name: tag, size_gb: 0, capabilities: ["completion"], tools: false,
          embedding_only: false, catalog_key: "", status: "unlisted" });
      }
      return { models: [...known.values()] };
    },
    // 리허설용 고르개 — 진짜 백엔드가 합쳐 주는 것을 여기서는 카탈로그로만 흉내 낸다.
    async modelPicker(role) {
      await wait(200);
      return {
        role,
        current: bundle.models[0]?.ollama_tag ?? "",
        budget_gb: 23.5,
        satellite: false,
        pulls: {},
        models: bundle.models.map((model, index) => ({
          tag: model.ollama_tag, name: model.name, vendor: model.vendor,
          listed: true, installed: model.installed, fits: model.fits,
          size_gb: model.download_gb, num_ctx: model.largest_fitting_ctx,
          vision: model.vision, roles: model.roles,
          grade: model.agent_grade ?? { model: model.ollama_tag, measured: false,
                                        label: "능력을 잰 적 없음", detail: "" },
          current: index === 0,
          blocked: model.fits ? "" : "이 PC 그래픽카드 메모리에 안 들어갑니다",
        })),
      };
    },
    async selectModel(tag, role) {
      await wait(900);
      return { ok: true, role, model: tag };
    },
    // 컨텍스트 상한 리허설 — 카드 메모리로 **흉내만** 낸다(진짜는 이 PC 에서 칸마다 올려 본다).
    async contextStatus(): Promise<ContextView> {
      await wait(150);
      return { ...contextState, ceilings: { ...ceilings },
               live: contextState.live ? { ...contextState.live, steps: [...contextState.live.steps] } : null };
    },
    // 「더 쥐어짜기」 리허설 — 흉내 카드에서는 좁힐 것이 없다고 답한다(진짜는 백엔드 `squeeze_context_ceiling`).
    async squeezeContext() {
      await wait(150);
      return { ok: false, error: "nothing_to_squeeze" };
    },
    async measureContext() {
      if (contextState.measuring) return { ok: false, error: "already_measuring" };
      const model = contextState.chat_model;
      const vram = Math.max(0, ...bundle.profile.gpus.map((gpu) => Number(gpu.vram_total_gb) || 0));
      // 흉내: 카드가 클수록 상한이 크다. 두 배로 올라가다 떨어지면 그 사이를 4K 단위로 좁힌다(진짜와 같은 순서).
      const fits = vram >= 20 ? 94208 : vram >= 10 ? 57344 : 28672;
      const ladder = [16384, 32768, 65536, 131072, 262144]; // 백엔드 CONTEXT_LADDER 와 같게(09-29: 다섯 칸만)
      const steps: ContextRung[] = [];
      contextState.measuring = true;
      contextState.live = { model, model_max: 262144, steps, loading: ladder[0] };
      const probe = async (ctx: number) => {
        contextState.live!.loading = ctx;
        await wait(700);
        const passed = ctx <= fits;
        steps.push({ num_ctx: ctx, passed, why: passed ? "" : "not_fully_on_gpu",
                     gpu_share: passed ? 1 : Math.max(0.5, fits / ctx), tokens_per_sec: passed ? 60 - ctx / 16384 : 31,
                     vram_gb: Math.min(vram, 18 + ctx / 1024 * 0.03) });
        return passed;
      };
      void (async () => {
        let ceiling = 0;
        let failedAt = 0;
        for (const ctx of ladder) {
          if (!(await probe(ctx))) { failedAt = ctx; break; }
          ceiling = ctx;
        }
        if (ceiling && failedAt) {
          let low = ceiling;
          let high = failedAt;
          while (high - low > 4096) {
            const middle = Math.floor((low + high) / 2 / 4096) * 4096;
            if (middle <= low) break;
            if (await probe(middle)) low = middle; else high = middle;
          }
          ceiling = low;
        }
        contextState.live!.loading = -1;
        await wait(700);
        const result: ContextCeiling = { ok: ceiling > 0, model, ceiling, model_max: 262144,
          stopped: ceiling === 262144 ? "ladder_end" : "not_fully_on_gpu", steps, took_sec: steps.length * 24,
          // 백엔드는 이 PC 시각(time.strftime)을 쓴다 — UTC 로 찍으면 새벽에 날짜가 하루 밀린다.
          measured_at: new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 19) };
        ceilings[model] = result;
        contextState.measuring = false;
        contextState.live = null;
      })();
      return { ok: true };
    },
    async applyContext(model, alsoGlobal, numCtx) {
      await wait(alsoGlobal ? 1400 : 500);
      let ceiling = ceilings[model]?.ceiling ?? 0;
      if (!ceiling) return { ok: false, error: "not_measured" };
      if (numCtx) {
        const rung = ceilings[model].steps.find((step) => step.num_ctx === numCtx);
        if (!rung) return { ok: false, error: "not_measured" };
        if (!rung.tokens_per_sec) return { ok: false, error: "rung_did_not_load" };
        ceiling = numCtx;
      }
      contextState.num_ctx = ceiling;
      if (alsoGlobal) contextState.global = { value: String(ceiling), ours: true };
      return { ok: true, num_ctx: ceiling,
               global: alsoGlobal ? { ok: true, restarted: "external" } : undefined };
    },
    async pullTag(tag, _applyCtx, _role) {
      if (!/^(?:(?:hf\.co|huggingface\.co)\/[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*|[a-z0-9][a-z0-9._-]*(\/[a-z0-9][a-z0-9._-]*)?)(:[A-Za-z0-9][A-Za-z0-9._-]*)?$/.test(tag)) {
        return { ok: false, error: "bad_tag", model_key: tag, status: "failed", completed: 0, total: 0, detail: "" };
      }
      const total = 4 * 1024 ** 3;
      const state: PullState = { model_key: tag, status: "pulling", completed: 0, total, detail: "받는 중" };
      pulls[tag] = state;
      const timer = window.setInterval(() => {
        state.completed = Math.min(total, state.completed + total / 8);
        if (state.completed >= total) {
          state.status = "done";
          state.detail = "받았습니다";
          installed.add(tag);
          window.clearInterval(timer);
        }
      }, 400);
      return { ok: true, ...state };
    },
    async applyTag(tag): Promise<ApplyResult> {
      await wait(900);
      const row = bundle.installed_models.find((m) => m.name === tag);
      if (!row || !row.tools) return { ok: false, error: "no_tool_calling", capabilities: row?.capabilities ?? ["completion"] };
      return { ok: true, bench: { ok: true, tokens_per_sec: 38.2, load_sec: 5.1 }, offload: { gpu_share: 1 }, warnings: [] };
    },
    async hfSearch(query, usableGb) {
      await wait(500);
      // 2026-10-01 밤 허깅페이스 API 실측 값(많이 받은 순 일부). 화면 미리보기용.
      const all = [
        { repo: "unsloth/Qwen3.8-27B-GGUF", params_b: 27.3, architecture: "qwen35", downloads: 6271224, likes: 4767, vision: true },
        { repo: "unsloth/Qwen3.5-9B-GGUF", params_b: 9.0, architecture: "qwen35", downloads: 3120044, likes: 1290, vision: true },
        { repo: "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", params_b: 26.9, architecture: "qwen35", downloads: 1679425, likes: 1863, vision: true },
        { repo: "unsloth/Qwen3.6-35B-A3B-GGUF", params_b: 35.1, architecture: "qwen35moe", downloads: 1544210, likes: 980, vision: true },
        { repo: "bartowski/google_gemma-4-26B-A4B-it-GGUF", params_b: 25.8, architecture: "gemma4", downloads: 905113, likes: 512, vision: true },
      ];
      const q = query.trim().toLowerCase();
      const models = all
        .filter((m) => !q || m.repo.toLowerCase().includes(q.replace(/\s+/g, "")) || q.split(/\s+/).every((w) => m.repo.toLowerCase().includes(w)))
        .map((m) => {
          const bits = [8, 6, 5, 4, 3, 2].find((b) => (m.params_b * (b + 0.5)) / 8 * 1.1 + 1.2 <= usableGb) ?? 0;
          const [author, name] = m.repo.split("/");
          const recommended = ["unsloth", "bartowski"].includes(author) && bits >= 3;
          const measured_family = /Qwen3\.5-9B/i.test(m.repo) ? "Qwen 3.5 9B" : /Qwen3\.6-35B/i.test(m.repo) ? "Qwen 3.6 35B-A3B" : "";
          // 확인한 사실(2026-10-03) — 양자화한 곳의 원본은 공식 저장소, 9B 는 이 PC 에서 잰 기록이 있다고 둔다.
          const pc_measured = /Qwen3\.5-9B/i.test(m.repo) ? { quant: "UD-Q4_K_M", ceiling: 131072, tokens_per_sec: 118.4 } : undefined;
          const checks = [author === "ISTA-DASLab" ? "" : "official_base", pc_measured ? "pc_measured" : ""].filter(Boolean) as HfCheck[];
          return { ...m, author, name, context_max: 262144, tools: true, best_bits: bits, updated: "2026-09-20", recommended, measured_family, checks, pc_measured };
        })
        .filter((m) => m.best_bits > 0);
      return { ok: true, query, sort: "downloads" as const, models, hidden: { no_tools: 5, too_big: 7 } };
    },
    async hfFiles(repo, usableGb) {
      await wait(450);
      const sizes: [string, number][] = [
        ["UD-IQ1_M", 6.73], ["UD-IQ2_XXS", 7.27], ["UD-IQ2_S", 8.37], ["UD-Q2_K_XL", 9.83], ["UD-IQ3_XXS", 10.93],
        ["UD-IQ3_S", 12.04], ["UD-Q3_K_XL", 13.15], ["UD-IQ4_XS", 14.25], ["UD-Q4_K_S", 15.36], ["UD-Q4_K_M", 16.46],
        ["UD-Q5_K_M", 19.77], ["UD-Q6_K", 21.98], ["Q8_0", 29.05],
      ];
      const scale = repo.includes("9B") ? 9 / 27.3 : 1;
      const files = sizes.map(([quant, size]) => {
        const gb = Math.round(size * scale * 100) / 100;
        const fit = gb + 0.9 + 1.2 <= usableGb ? "fits" : gb + 0.9 + 0.4 <= usableGb ? "tight" : "over";
        const bits = Number((quant.replace("UD-", "").match(/\d/) ?? ["0"])[0]);
        const pc_measured = repo.includes("9B") && quant === "UD-Q4_K_M" ? { ceiling: 131072, tokens_per_sec: 118.4 } : undefined;
        return { quant, file: `${repo.split("/")[1]}-${quant}.gguf`, gb: Math.round((gb + 0.9) * 100) / 100, file_gb: gb, projector_gb: 0.9,
          bits, fit: fit as "fits" | "tight" | "over", tag: `hf.co/${repo}:${quant}`, pc_measured };
      });
      const fitting = files.filter((f) => f.fit === "fits" && f.bits >= 2);
      const best = fitting[fitting.length - 1];
      return { ok: true, repo, files: files.map((f) => ({ ...f, recommended: f === best })), margin_gb: 1.2 };
    },
    async connectScan() {
      await wait(400);
      return connectView();
    },
    async connectApply(client) {
      await wait(700);
      const row = cx.scan.clients.find((c) => c.id === client);
      if (!row) return { ok: false, error: "unknown_client" };
      // 실제 백엔드처럼: 켜져 있으면 거절하지 않고 닫히기를 기다린다(2026-09-16 부터 — `wait_for_desktop_close`).
      if (row.running && !connected.has(client)) {
        desktopWaiting = true;
        return { ok: true };
      }
      if (row.reason === "cli_missing") return { ok: false, error: "cli_missing", manual: cx.manual_claude_code };
      connected.add(client);
      return { ok: true, backups: row.config_paths?.length ? [`${row.config_paths[0]}.bak-jarvis`] : [] };
    },
    async connectRemove(client) {
      await wait(400);
      connected.delete(client);
      return { ok: true };
    },
    async connectRestartDesktop() {
      await wait(1800);
      const row = cx.scan.clients.find((c) => c.id === "claude_desktop");
      if (!row?.installed) return { ok: false, error: "not_installed" };
      // `&setupClaude=stuck` — 앱이 안 꺼지는 PC 를 리허설한다(작업 표시줄에서 직접 끄라는 안내가 나와야 한다).
      if (new URLSearchParams(window.location.search).get("setupClaude") === "stuck") {
        return { ok: false, error: "claude_desktop_did_not_close" };
      }
      connected.add("claude_desktop");
      return { ok: true, desktop: row.running ? "restarted" : "was_not_running", backups: row.config_paths?.length ? [`${row.config_paths[0]}.bak-jarvis`] : [] };
    },
    async connectVerify() {
      await wait(1500);
      return cx.verify;
    },
    async guideSkillStatus() {
      await wait(200);
      return {
        name: "sonjari-guide",
        claude_code: { installed: guideInstalled, path: "C:\Users\you\.claude\skills\sonjari-guide\SKILL.md", available: true, foreign: false },
        zip: { exists: guideZip, path: "C:\Users\you\Documents\Ontelic\sonjari-guide.zip" },
        notes: {
          claude_code: { path: "C:\\Users\\you\\.claude\\CLAUDE.md", exists: true, installed: guideNote,
                         guide_path: "C:\\Users\\you\\.claude\\skills\\sonjari-guide\\SKILL.md", guide_exists: guideInstalled },
          codex: { path: "C:\\Users\\you\\.codex\\AGENTS.md", exists: true, installed: false,
                   guide_path: "C:\\Users\\you\\.codex\\sonjari-guide.md", guide_exists: false },
        },
      };
    },
    async guideSkill(action) {
      await wait(400);
      if (action === "install_claude_code") guideInstalled = true;
      if (action === "remove_claude_code") guideInstalled = false;
      if (action === "build_zip") guideZip = true;
      if (action === "install_note") guideNote = true;
      if (action === "remove_note") guideNote = false;
      if (action === "manual_note") return { ok: true, text: "## Sonjari 가 이 PC 에 있다\n- Sonjari 관련이면 스킬 파일을 먼저 읽는다" };
      return { ok: true };
    },
    async openGuideSkillFolder() {
      return { ok: true };
    },
    async connectHook(enabled) {
      await wait(300);
      hookOn = enabled;
      return { ok: true };
    },
    async importScan(project) {
      await wait(350);
      if (!project) return withImported(imp.global);
      if (!/^[A-Za-z]:\\/.test(project)) return { ...imp.global, project: "", project_error: "project_not_found" };
      return withImported(imp.project);
    },
    async importPreview(_project, ids, paste, redactContacts) {
      await wait(700);
      const pool = redactContacts ? imp.preview.contacts : imp.preview.plain;
      const items: ImportPreviewItem[] = ids.map((id) => pool.find((item) => item.id === id) ?? { id, error: "not_in_list" });
      if (paste) items.push({ ...imp.paste_example, tool: paste.tool });
      return { items };
    },
    async importCommit(_project, items, paste) {
      await wait(600);
      const saved = [];
      for (const { id } of paste ? [...items, { id: "paste" }] : items) {
        const row = imp.imported[id];
        if (!row) continue;
        const next = { ...row, import_id: nextImportId++, imported_at: Date.now() / 1000, status: "same" as const };
        stored.set(id, next);
        saved.push({ import_id: next.import_id, id, source_path: next.source_path, secret_total: next.secret_total });
      }
      return { ok: true, saved, refused: [] };
    },
    async importList() {
      await wait(120);
      const items = [...stored.values()].sort((a, b) => b.import_id - a.import_id);
      return { count: items.length, items };
    },
    async importRemove(importId) {
      await wait(200);
      for (const [key, row] of stored) {
        if (row.import_id === importId) {
          stored.delete(key);
          return { ok: true };
        }
      }
      return { ok: false, error: "not_found" };
    },
    async aboutMe() {
      await wait(150);
      return aboutView();
    },
    async aboutMeSave(content) {
      await wait(200);
      if (content.trim().length > 6000) return aboutView({ ok: false, error: "too_long", chars: content.trim().length });
      aboutText = content;
      return aboutView({ saved: true });
    },
    async aboutMeCardPreview(answers) {
      await wait(80);
      const next = asAnswers(answers);
      const lines = fakeLines(next);
      const content = withCard(lines);
      return { ...aboutView(), ok: true, answers: next, card_lines: lines, content_raw: content, chars: content.trim().length, fits: true };
    },
    async aboutMeCardSave(answers) {
      await wait(250);
      aboutAnswers = asAnswers(answers);
      const lines = fakeLines(aboutAnswers);
      aboutText = withCard(lines);
      return aboutView({ saved: true, card_lines: lines });
    },
    async aboutMeImportLines(importId) {
      await wait(150);
      const row = [...stored.values()].find((item) => item.import_id === importId);
      if (!row) return { ok: false, error: "not_found", import_id: importId, tool_name: "", source_path: "", lines: [], allowed_count: 0 };
      const present = new Set(aboutText.split("\n").map((line) => line.trim()));
      const lines = row.text.split("\n").map((raw, index) => {
        const reason = !raw.trim() ? "blank" as const : raw.includes("[비밀 걷어 냄:") ? "secret" as const
          : present.has(raw.trim()) ? "already" as const : "" as const;
        return { index, raw, allowed: !reason, reason };
      });
      return { ok: true, import_id: importId, tool_name: row.tool_name, source_path: row.source_path, lines,
        allowed_count: lines.filter((line) => line.allowed).length };
    },
    async aboutMeAppendImport(importId, indexes) {
      await wait(200);
      const row = [...stored.values()].find((item) => item.import_id === importId);
      if (!row) return aboutView({ ok: false, error: "not_found" });
      const picked = row.text.split("\n").filter((raw, index) => indexes.includes(index) && raw.trim() && !raw.includes("[비밀 걷어 냄:"));
      if (!picked.length) return aboutView({ ok: false, error: "nothing_to_add" });
      aboutText = `${aboutText.trim() ? `${aboutText.trim()}\n\n` : ""}<!-- 가져옴: ${row.tool_name} -->\n${picked.join("\n")}\n`;
      return aboutView({ added: picked.length, refused: [] });
    },
    async aboutMeOpen() {
      return { ok: true };
    },
  };
}
