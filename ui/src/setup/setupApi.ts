/**
 * 첫 실행 화면이 부르는 곳 — 백엔드 `/v1/setup/*` (전략안 §43, P1·P2).
 *
 * 화면은 **계산하지 않는다.** 들어가는지·무엇을 권하는지는 백엔드가 이 PC 를 재서
 * 정한다(`setup_profile.recommend`). 화면이 VRAM 을 따로 계산하면 두 벌이 되고,
 * 두 벌은 반드시 갈린다.
 */
import { t } from "../i18n";
import type { BackendBootstrap, SkillDomainsView } from "../types";

export interface GpuCard {
  index: number;
  name: string;
  vram_total_gb: number;
  vram_used_gb: number;
  driver: string;
  display_active: boolean;
  /** 화면 출력·드라이버가 가져가는 몫. 백엔드 규칙 한 곳에서 온다(annotate_gpus). */
  reserve_gb: number;
  usable_gb: number;
  /** M1: NVIDIA 밖의 카드도 본다. 레지스트리에서 온 카드는 화면 출력 여부를 몰라 보수적으로 잡는다. */
  vendor?: "nvidia" | "amd" | "intel" | "other";
  integrated?: boolean;
  backend?: "cuda" | "rocm" | "vulkan";
  source?: "nvidia-smi" | "registry";
}

export interface PcProfile {
  measured_at: string;
  os: string;
  cpu: string;
  ram_gb: number | null;
  gpus: GpuCard[];
  gpu_error: string;
  /** 윈도우 장치 오류 코드로 가른 드라이버 상태(2026-09-17). 사람이 할 일이 상태마다 다르다. */
  gpu_driver?: {
    state: "ok" | "missing" | "broken" | "disabled" | "reboot_pending" | "mismatch" | "smi_only" | "no_nvidia" | "unknown";
    code?: number;
    cards?: { name: string; code: number; driver: string }[];
  };
  disk_free_gb: number | null;
  ollama: { reachable: boolean; version: string; installed: string[]; vulkan_enabled: boolean; vulkan_setting?: "" | "on" | "off" };
}

export interface ModelLink {
  label: string;
  url: string;
}

/** 등급마다 검증 1 + 외부 1 (docs/모델_큐레이션_2026-09-15). 외부 칸은 반드시 「미검증」으로 보인다. */
export interface ModelPick {
  /** `open_alternative` = 추천 모델의 라이선스에 조건이 있을 때 같이 내미는 **조건 없는** 차선책(§55-24 덧붙임 2). */
  kind: "verified" | "external" | "open_alternative";
  /** 「똑똑함 · 빠름」 둘로 나눠 권할 때의 역할(2026-10-28 · 첫 추천이 Swift 27B 일 때만 온다). */
  role?: "smart" | "fast";
  model_key: string;
  name: string;
  ollama_tag: string;
  num_ctx: number;
  vram_gb?: number;
  vram_estimate_gb?: number;
  download_gb: number;
  installed: boolean;
  license: string;
  confidence?: "measured" | "memory_only";
  chain?: { ok: number; total: number; ctx: number } | null;
  evidence?: string[];
  caution?: string;
  links?: ModelLink[];
  checked_at?: string;
}

export interface Recommendation {
  /** `no_gpu`·`too_small` 은 막다른 「준비 중」이 아니라 이유와 권장 사양을 말한다. CPU 경로는 없다. */
  mode: "local" | "no_gpu" | "too_small" | "satellite";
  model_key: string | null;
  ollama_tag?: string;
  num_ctx: number | null;
  installed?: boolean;
  confidence?: "measured" | "memory_only" | "external" | "hardware";
  reasons: string[];
  warnings: string[];
  /** 마법사가 모델을 올리기 전에 **직접** 맞출 것. `ollama_gpu_only` = Ollama 가 NVIDIA 카드만 쓰게. */
  fixes?: string[];
  alternatives?: { model_key: string; num_ctx: number; vram_gb: number }[];
  /** 추천이 「그림 부속을 뗀 채」 올리라는 것인가(2026-10-12 — 16GB 급). 화면이 「글만 읽기」를 골라 두고 그렇게 적용한다. */
  text_only?: boolean;
  budget_gb?: number;
  tier_gb?: number | null;
  picks?: ModelPick[];
  card?: { name: string; vendor: string; backend: string; vram_total_gb: number } | null;
}

export interface CatalogModel {
  agent_grade?: { model: string; measured: boolean; label: string; detail: string };
  memory_device?: string;
  minimum_vram_gb?: number;
  key: string;
  name: string;
  vendor: string;
  ollama_tag: string;
  download_gb: number;
  vram_gb: Record<string, number>;
  chain: { ok: number; total: number; ctx: number } | null;
  roles: string[];
  vision: boolean;
  blurb: string;
  /** 잰 근거가 있는 것만 — 잘하는 일 / 약한 일(§55-13 기대 맞추기). */
  good_at?: string;
  weak_at?: string;
  /** 제작사 주장 · 참고용 — 공식 카드의 「큰 모델 ○○ 와 같은 시험에서 비슷한 점수」. 우리가 잰 숫자가 아니다. */
  vendor_claim?: string;
  vendor_claim_links?: { label: string; url: string }[];
  vendor_claim_checked?: string;
  installed: boolean;
  fits: boolean;
  largest_fitting_ctx: number | null;
  /** 그림을 켠 채로는 빠듯해 「글만 읽기」로 보이고 그렇게 올리는 칸(2026-10-15 · 백엔드가 정한다). */
  text_only?: boolean;
  text_only_need_gb?: number | null;
  status: "verified" | "external";
  license: string;
  evidence: string[];
  caution: string;
  links: ModelLink[];
  checked_at: string;
  /** false 면 `vram_gb` 는 받는 크기로 **추정**한 값이다. */
  vram_measured: boolean;
  // ── 아래 여섯 칸은 2026-10-08 에 늘었다. 옛 백엔드는 안 준다 — 없으면 화면은 예전과 똑같이 그린다. ──
  /** true = 널리 알려진 자유 라이선스(Apache-2.0·MIT). false = 조건이 붙은 라이선스. 화면은 조건의 **내용**을 풀어 쓰지 않는다. */
  license_open?: boolean;
  /** 라이선스 원문 주소. 없으면 빈 글. */
  license_url?: string;
  /** 같은 모델의 다른 크기끼리 같은 값 — 화면이 카드 하나로 합친다. 빈 글이면 단독 모델. */
  family?: string;
  /** 묶음의 이름(크기 표기를 뺀 이름). */
  family_name?: string;
  /** 양자화 코드(`IQ3_S`) — 화면에서는 `title` 로만 보인다. */
  quant?: string;
  /** 쉬운 말(「3비트」·「3비트 작게」) — 「크기 고르기」 칩의 글. */
  quant_label?: string;
  /** 그림 읽기를 켜고 끌 수 있는 모델인가(그림 부속을 따로 붙이는 모델). 옛 백엔드는 이 칸을 안 준다 — 줄을 안 그린다. */
  pictures_optional?: boolean;
  /** 「글만 읽기」로 올렸을 때 Ollama 에 생기는 이름. */
  text_only_tag?: string;
  /** 그림 부속을 떼면 덜 쓰는 그래픽카드 메모리(GB) — 백엔드가 잰 값. */
  text_only_saves_gb?: number;
  /** 「글만 읽기」로 올렸을 때 **잰** 메모리 — 창(토큰) → GB. 없는 창은 `vram_gb − text_only_saves_gb` 로 어림한다. */
  text_only_vram_gb?: Record<string, number>;
}

/** 허깅페이스에서 직접 고르기 (2026-10-01 밤) — 내려받기 **전에** 허깅페이스가 알려 준 것만. 크기 판정은 추정이다. */
export interface HfModel {
  repo: string;
  author: string;
  name: string;
  params_b: number | null;
  architecture: string;
  context_max: number;
  tools: boolean;
  /** 이 카드에 들어갈 가장 높은 비트(추정). */
  best_bits: number;
  downloads: number;
  likes: number;
  updated: string;
  vision: boolean;
  /** 규칙으로 고른 추천(잰 것 아님) — 믿을 만한 제작자 · 개조판 아님 · 3비트 이상 · 많이 받은 순. */
  recommended?: boolean;
  /** 이 제품에서 실제로 잰 계열이면 그 이름. */
  measured_family?: string;
  /** 안전 장치를 걷어 냈거나 역할극용으로 바꾼 개조판. */
  modded?: boolean;
  /** 확인한 사실만(2026-10-03) — official · official_base · pc_measured. 「추천」 대신 이것을 적는다. */
  checks?: HfCheck[];
  /** 이 PC 에서 실제로 올려 보고 잰 기록(그 저장소의 양자화 중 하나). */
  pc_measured?: PcMeasured & { quant: string };
}

export type HfCheck = "official" | "official_base" | "pc_measured";

export interface PcMeasured {
  /** GPU 에 다 올라간다고 잰 가장 큰 컨텍스트. */
  ceiling: number;
  tokens_per_sec: number | null;
}

export interface HfSearch {
  ok: boolean;
  error?: string;
  query?: string;
  sort?: "downloads" | "trending";
  models: HfModel[];
  hidden?: { no_tools: number; too_big: number };
}

export interface HfFile {
  quant: string;
  file: string;
  gb: number;
  bits: number;
  /** fits = 여유 있게 · tight = 컨텍스트를 줄여야 할 수 있음 · over = 안 들어감(추정). */
  fit: "fits" | "tight" | "over";
  /** Ollama 받기 이름 — `hf.co/작성자/저장소:양자화`. */
  tag: string;
  /** 여유 있게 들어가는 것 중 가장 큰 양자화(1비트 제외). */
  recommended?: boolean;
  /** 모델 파일만의 크기 · 화면 읽기 부속(mmproj) 크기 — `gb` 는 둘을 더한 받기 크기. */
  file_gb?: number;
  projector_gb?: number;
  /** 이 PC 에서 이 양자화를 실제로 잰 기록. */
  pc_measured?: PcMeasured;
}

export interface HfFiles {
  ok: boolean;
  error?: string;
  repo?: string;
  files: HfFile[];
  margin_gb?: number;
  /** 여유를 잰 대화 길이. */
  ctx?: number;
}

/** 이 PC Ollama 에 이미 있는 모델 — 도구 호출 여부는 Ollama `/api/show` 가 말한 것. */
/** 대화·코드는 **서로 다른 모델**을 쓴다 — 고르개는 어느 역할의 것인지 알고 있어야 한다. */
export type ModelRole = "chat" | "code";

/** 고르개 한 줄. `listed:false` 는 사용자가 직접 받아 둔 모델(우리가 능력을 잰 적 없음). */
export interface PickerModel {
  tag: string;
  name: string;
  vendor: string;
  listed: boolean;
  installed: boolean;
  fits: boolean;
  size_gb: number;
  num_ctx: number | null;
  vision: boolean;
  roles: string[];
  grade: { model: string; measured: boolean; label: string; detail: string };
  current: boolean;
  /** 빈 문자열이면 고를 수 있다. 값이 있으면 **그 이유를 적어서** 못 누르게 한다. */
  blocked: string;
}

export interface ModelPickerView {
  role: ModelRole;
  current: string;
  budget_gb: number;
  satellite: boolean;
  models: PickerModel[];
  pulls: Record<string, PullState>;
  /** 코드 고르개에서만 — 지금 코드 모델보다 훨씬 큰 모델이 이 카드에 들어가면 그 하나(규칙 추천, 2026-10-01 밤). */
  suggestion?: CodeUpgrade | null;
}

export interface CodeUpgrade {
  tag: string;
  name: string;
  size_gb: number;
  params_b: number;
  current: string;
  current_params_b: number;
  installed: boolean;
  /** 왜 이것인가 — 규칙인지 잰 것인지 그대로 적는다. */
  basis: string;
  measured: boolean;
}

export interface SelectResult {
  ok: boolean;
  error?: string;
  role?: string;
  model?: string;
  num_ctx?: number;
  kept?: string;
  warnings?: string[];
}

export interface InstalledModel {
  name: string;
  size_gb: number;
  capabilities: string[];
  tools: boolean;
  embedding_only: boolean;
  catalog_key: string;
  status: "verified" | "external" | "unlisted";
}

export interface GpuFixResult {
  ok: boolean;
  error?: string;
  setting_written?: boolean;
  restarted?: "not_running" | "managed" | "external";
}

export interface PullState {
  model_key: string;
  status: "pulling" | "done" | "failed";
  completed: number;
  total: number;
  detail: string;
  /** 무슨 단계인가 — 받기 · 받은 파일 확인(크기 없음, 1~2분) · 마무리. 옛 백엔드는 안 보낸다(2026-09-29). */
  phase?: "downloading" | "verifying" | "finishing";
  /** 백엔드가 받은 뒤 바로 적용했으면 그 결과. */
  applied?: ApplyResult;
  /** 실패 원인 갈래(2026-10-01). 「ollama_not_running」이면 인터넷이 아니라 이 PC 의 Ollama 가 꺼진 것이다. */
  reason?: "ollama_not_running" | "disk_full" | "";
}

/** 받기 실패를 사람의 다음 할 일로 (2026-10-01 베타 첫 사용자: 연결 거부인데 「인터넷을 확인하라」고 했다). */
/**
 * 돌려 보기는 됐는데 그래픽카드에 얼마나 올라갔는지 못 읽었을 때 할 말 (2026-10-05).
 *
 * 화면에 내부 코드(`gpu_measurement_unavailable`)가 그대로 나왔다. 이 PC 에서는 마법사가 재는 바로 그 순간 다른 손자리가
 * 자기 모델을 올려 밀어낸 것이었다 — Ollama 를 같이 쓰는 프로그램이 있으면 새 사용자도 똑같이 본다. 다시 누르면 된다는 것을 말한다.
 */
export function pushedOutReason(seen?: string[]): string {
  const others = (seen ?? []).filter(Boolean);
  return others.length
    ? t("돌려 보기는 됐는데, 재는 순간 다른 모델({0})이 올라와 이 모델이 내려갔습니다 — 다른 프로그램이 같은 때 Ollama 를 쓴 것입니다. 기존 모델을 그대로 둡니다. 잠시 뒤 다시 적용해 주세요.", others.join(" · "))
    : t("돌려 보기는 됐는데 그래픽카드에 얼마나 올라갔는지 읽지 못했습니다. 기존 모델을 그대로 둡니다 — 잠시 뒤 다시 적용해 주세요.");
}

export function pullFailureText(pull: PullState): string {
  if (pull.reason === "ollama_not_running") {
    return t("Ollama 가 켜져 있지 않아 받지 못했습니다 — 위의 「Ollama 설치」를 먼저 눌러 주세요. 이미 깔았다면 시작 메뉴에서 Ollama 를 켠 뒤 다시 누르세요. ")
      + t("회사 PC 라면 보안 프로그램이 Ollama 실행을 막았을 수 있습니다.");
  }
  if (pull.reason === "disk_full") {
    return t("디스크 공간이 모자라 받지 못했습니다({0}). 공간을 비운 뒤 다시 누르세요.", pull.detail);
  }
  return t("받지 못했습니다: {0}. 인터넷 연결과 디스크 여유를 확인한 뒤 다시 누르세요.", pull.detail);
}

export interface ModelsView {
  models: CatalogModel[];
  selection: { catalog_key: string; chat_model: string; num_ctx: number; reads_pictures?: boolean } | null;
  current_chat_model: string;
  /**
   * 지금 쓰는 대화 모델의 그림 읽기 — 목록 밖 모델(허깅페이스에서 고른 것)도 켜고 끌 수 있게 백엔드가 알려 준다.
   * `source_tag` 는 그림을 읽는 쪽 이름이다: 이 이름에 `eyes` 를 실어 `applyTag` 를 부른다. 옛 백엔드는 이 칸이 없다.
   */
  eyes?: { tag: string; reads_pictures: boolean; can_switch: boolean; source_tag: string; saves_gb: number; listed: boolean };
  pulls: Record<string, PullState>;
  satellite: boolean;
  source: "env" | "setup";
}

/** 고른 모델을 그래픽카드에 다 못 올렸을 때 사람이 고를 두 길(백엔드 `model_setup.way_out`). 모르는 값은 null 이다. */
export interface WayOutInfo {
  model_key: string;
  model_name: string;
  /** 이 모델이 가장 작은 창으로도 필요한 그래픽 메모리. */
  needs_gb: number;
  card: { total_gb: number | null; used_gb: number | null; free_gb: number | null };
  /** 닫을 수 있는 프로그램(윈도우 기본은 빠져 있다)과, 다 닫으면 들어가는가. 닫는 것은 사람이 한다. */
  close: { apps: string[]; would_fit: boolean | null };
  /** 지금 빈 자리에 들어가는 한 단계 작은 모델. 없으면 null. */
  smaller: {
    model_key: string; name: string; num_ctx: number; needs_gb: number; download_gb: number;
    installed: boolean; weak_at?: string; good_at?: string;
    /** 그림 부속을 뗀 채(글만 읽기)로 올리는 칸인가 — 그러면 적용 · 받기에 eyes=false 를 준다(2026-10-26). */
    text_only?: boolean;
  } | null;
}

export interface ApplyResult {
  ok: boolean;
  error?: string;
  bench?: { ok: boolean; tokens_per_sec?: number; load_sec?: number; error?: string };
  kept?: string;
  /** 올린 뒤 실제로 그래픽카드에 올라간 비율(`/api/ps`). 낮으면 CPU 로 돈다. */
  offload?: { gpu_share: number | null; /** 못 읽었을 때 그 순간 Ollama 에 떠 있던 모델들. */ seen?: string[] };
  warnings?: string[];
  capabilities?: string[];
  /** 적용된 선택 — 모델 태그와 컨텍스트(백엔드 `_measure_and_save`). */
  selection?: { chat_model: string; num_ctx: number };
  /** 메모리가 모자라 못 올렸을 때 그 카드를 지금 쓰는 프로그램(백엔드 `gpu_users`). 윈도우는 프로그램별 양을 안 준다. */
  gpu_users?: { used_gb?: number; total_gb?: number; apps?: string[] };
  /** 그래픽카드에 다 못 올렸을 때의 두 길. 재료를 못 만들었으면 빈 객체다 — 화면은 예전 글을 쓴다. */
  way_out?: WayOutInfo | Record<string, never>;
}

// ── 지침 가져오기 (P4) ──────────────────────────────────────────────────────
// 미리보기·넣기는 **경로가 아니라 후보 id** 를 보낸다. 후보 목록은 백엔드만 만든다.

export type ImportStatus = "same" | "changed" | "missing" | "unreadable";
// Claude Desktop 의 지침(사용자 지정 › 지침·프로젝트 지침)은 계정에 있어 PC 에 파일이 없다 — 붙여 넣어 받는다(2026-09-16).
export type PasteTool = "claude_desktop" | "manus" | "windsurf" | "other";

export interface ImportCandidate {
  id: string;
  tool: string;
  tool_name: string;
  scope: "global" | "project";
  path: string;
  exists: boolean;
  size: number;
  modified_at: number | null;
  readable: boolean;
  skip_reason: "" | "settings_file" | "sensitive_location";
  too_large: boolean;
  imported?: { import_id: number; status: ImportStatus };
}

export interface ImportScan {
  project: string;
  project_error: "" | "project_not_found";
  candidates: ImportCandidate[];
  max_bytes: number;
}

/** 걷은 자리(`secret`)의 `v` 는 표시 글자다 — 원문 비밀은 화면에 오지 않는다. */
export interface ImportSegment {
  t: "text" | "secret" | "contact";
  v: string;
  label?: string;
}

export interface ImportPreviewItem {
  id: string;
  tool?: string;
  tool_name?: string;
  scope?: string;
  path?: string;
  error?: string;
  sha256?: string;
  chars?: number;
  segments?: ImportSegment[];
  secrets?: Record<string, number>;
  secret_total?: number;
  contacts?: Record<string, number>;
  contact_total?: number;
}

export interface PasteInput {
  tool: PasteTool;
  text: string;
  sha256?: string;
}

export interface ImportCommitResult {
  ok: boolean;
  saved: { import_id: number; id: string; source_path: string; secret_total: number }[];
  refused: { id: string; error?: string }[];
}

export interface ImportedItem {
  import_id: number;
  tool: string;
  tool_name: string;
  scope: string;
  source_path: string;
  imported_at: number;
  updated_at: number;
  chars: number;
  text: string;
  secrets: Record<string, number>;
  secret_total: number;
  status: ImportStatus;
}

// ── 다른 도구에 잇기 (P5) ───────────────────────────────────────────────────
// 설정 파일에 넣는 것에는 비밀이 없다(토큰 파일 경로만). 무엇을 넣는지는 백엔드가 정한다.

export type ConnectClientId = "claude_desktop" | "claude_code" | "cursor" | "codex";

export interface ConnectClient {
  id: ConnectClientId;
  name: string;
  installed: boolean;
  registered: boolean | null;
  can_apply: boolean;
  reason: string;
  running?: boolean;
  /** Claude Desktop 이 닫히면 잇겠다고 기다리는 중. */
  waiting_for_close?: boolean;
  config_paths?: string[];
  cli?: string;
}

export interface ConnectScan {
  server_name: string;
  clients: ConnectClient[];
  hooks: { claude_code_session_start: boolean; can_apply: boolean };
  not_supported: { name: string; reason: string }[];
}

export interface ConnectResult {
  ok: boolean;
  error?: string;
  detail?: string;
  manual?: string;
  backups?: string[];
}

/** Claude Desktop 을 닫고 → 잇고 → 다시 켠 결과. `desktop` 은 그 앱에 일어난 일이다(잇기의 성패는 `ok`). */
export interface ConnectRestartResult extends ConnectResult {
  desktop?: "was_not_running" | "restarted" | "closed_only";
}

// ── 첫 실행 판정 · Ollama 한 번 설치 · 기억 복제 폴더 (W1·W2) ──────────────────────

export interface SetupStateView {
  completed: boolean;
  steps: string[];
  completed_at?: number | null;
}

export type OllamaPhase = "idle" | "resolving" | "downloading" | "verifying" | "extracting" | "starting" | "ready" | "error";

export interface OllamaStatus {
  running: boolean;
  version: string;
  bundled: string;
  /** 우리가 깐 Ollama 에 모델을 돌리는 `llama-server.exe` 가 없다 — 서버는 켜져도 모델은 하나도 못 올린다(2026-09-18 노트북). */
  runner_missing?: boolean;
  managed: boolean;
  can_install: boolean;
  source: string;
  install: { phase: OllamaPhase; received?: number; total?: number; version?: string; error?: string };
}

export interface BackupGeneration {
  generation: string;
  created_at: number;
  reason: string;
  tables: Record<string, number>;
  files: string[];
}

export interface BackupStatus {
  enabled: boolean;
  root: string;
  keep: number;
  generations: BackupGeneration[];
  latest: BackupGeneration | null;
  memory_empty: boolean;
  delete_confirmation: string;
}

/** 가이드 스킬 `sonjari-guide` (인수인계 H1-b) — Claude 가 온텔릭을 언제·어떻게 부르는지. */
export interface GuideSkillStatus {
  name: string;
  claude_code: { installed: boolean; path: string; available: boolean; foreign: boolean };
  zip: { exists: boolean; path: string };
  notes?: Record<string, GuideNoteRow>;
}
export type GuideSkillAction =
  | "install_claude_code"
  | "remove_claude_code"
  | "build_zip"
  | "install_note"
  | "remove_note"
  | "manual_note";
/** 전역 지침(CLAUDE.md · AGENTS.md) — 스킬과 달리 **매번 읽힌다**. 온텔릭 관련이면 스킬 파일을 보라고 가리킨다. */
export interface GuideNoteRow {
  path: string;
  exists: boolean;
  installed: boolean;
  guide_path: string;
  guide_exists: boolean;
}
export interface GuideSkillResult {
  ok: boolean;
  path?: string;
  backup?: string;
  error?: string;
  text?: string;
  guide_path?: string;
}

/** 컨텍스트 상한 한 칸 — 이 PC 에서 그 크기로 **실제로 올려 본** 결과(2026-09-23). */
export interface ContextRung {
  num_ctx: number;
  passed: boolean;
  /** 떨어진 까닭: not_fully_on_gpu · context_clamped · too_slow · load_failed 류 */
  why: string;
  gpu_share?: number | null;
  tokens_per_sec?: number;
  vram_gb?: number;
  error?: string;
}
export interface ContextCeiling {
  ok: boolean;
  model: string;
  ceiling: number;
  model_max: number;
  stopped: string;
  steps: ContextRung[];
  took_sec: number;
  measured_at: string;
  error?: string;
  /** 「더 쥐어짜기」를 했으면 — 어디서 어디까지 올렸나. */
  squeezed?: { from: number; to: number; below: number; stopped: string; took_sec: number; at: string };
}
export interface ContextView {
  chat_model: string;
  num_ctx: number;
  ceilings: Record<string, ContextCeiling>;
  measuring: boolean;
  /** 재는 중이면 지금까지의 칸과 올리는 중인 크기(-1 = 상한으로 다시 올리는 중). */
  live: { model: string; model_max: number; steps: ContextRung[]; loading: number } | null;
  /** Ollama 전체 기본값(`OLLAMA_CONTEXT_LENGTH`). `ours` = 온텔릭이 넣은 값. */
  global: { value: string; ours: boolean };
  /** 30분마다 보는 감시 — 잴 때와 모델 카드에 붙은 프로그램이 달라졌나. GB 추정은 없다(역검증에서 틀림). */
  watch?: { state: "changed" | "steady" | "unknown"; left?: string[]; joined?: string[]; measured_at?: string };
}
export interface ContextApplyResult {
  ok: boolean;
  error?: string;
  num_ctx?: number;
  global?: { ok: boolean; error?: string; current?: string; restarted?: string };
}

// ── 「나에 대한 지침」 (2026-10-18) ─────────────────────────────────────────────
// ★ 매 턴 실리는 프로필 파일(`JARVIS_PROFILE.md`)에 화면이 없었고, 지침 가져오기는 아무 데도 안 쓰였다. 둘을 파일 하나로
//   모은다(백엔드 `about_me.py`). 화면은 줄을 **만들지 않는다** — 카드 답 → 줄은 백엔드 결정론 코드 한 곳이다.
export type AboutMeLength = "" | "short" | "normal" | "long";
export type AboutMeTone = "" | "casual" | "polite";

export interface AboutMeAnswers {
  user_label: string;
  work_text: string;
  length: AboutMeLength;
  tone: AboutMeTone;
  sites: string[];
  avoid_text: string;
}

/** 길이 자 — 대화 판에 실제로 실리는 블록을 우리가 잰 글자/토큰 비율로 잰다. */
export interface AboutMeMeter {
  sent_chars: number;
  tokens: number;
  num_ctx: number;
  share: number;
  share_pct: number;
  warn: boolean;
  warn_share: number;
  chars_per_token: number;
}

export interface AboutMeView extends AboutMeMeter {
  ok: boolean;
  error?: string;
  message?: string;
  path: string;
  exists: boolean;
  content_raw: string;
  chars: number;
  max_chars: number;
  truncated: boolean;
  has_card: boolean;
  answers: AboutMeAnswers;
  saved?: boolean;
  card_lines?: string[];
  added?: number;
  refused?: { index: number; reason: string }[];
}

export interface AboutMeCardPreview extends AboutMeMeter {
  ok: boolean;
  error?: string;
  answers: AboutMeAnswers;
  card_lines: string[];
  content_raw: string;
  chars: number;
  max_chars: number;
  fits: boolean;
}

/** 「보내는 답」 — 사이트는 쉼표 글 그대로 보내도 백엔드가 나눈다. */
export type AboutMeAnswersInput = Omit<AboutMeAnswers, "sites"> & { sites: string[] | string };

export interface AboutMeImportLine {
  index: number;
  raw: string;
  allowed: boolean;
  reason: "" | "blank" | "secret" | "already";
}

export interface AboutMeImportLines {
  ok: boolean;
  error?: string;
  import_id: number;
  tool_name: string;
  source_path: string;
  lines: AboutMeImportLine[];
  allowed_count: number;
}

export interface SetupApi {
  setupState(): Promise<SetupStateView>;
  finishSetup(steps: string[]): Promise<SetupStateView>;
  ollamaStatus(): Promise<OllamaStatus>;
  ollamaInstall(): Promise<{ ok: boolean; error?: string; phase?: OllamaPhase }>;
  /** 고장난 우리 Ollama 를 끄고 새 자리로 옮겨 켠다. 사람이 깐 Ollama 는 `not_ours` 로 거절한다. */
  ollamaRepair(): Promise<{ ok: boolean; error?: string; phase?: OllamaPhase; stopped?: number }>;
  ollamaGpuOnly(): Promise<GpuFixResult>;
  backupStatus(): Promise<BackupStatus>;
  backupRestore(generation: string): Promise<{ ok: boolean; error?: string; tables?: Record<string, number> }>;
  /** 「문제 보내기」 — 마법사에서 막힌 사람도 보낼 수 있게(2026-10-06). 작업 화면과 같은 백엔드 문이다. */
  reportPreview(jobId?: string): Promise<{ id: string; text: string; to: string }>;
  reportSend(id: string, note: string, consent: boolean): Promise<{ ok: boolean; id?: string; error?: string }>;
  skillDomains(): Promise<SkillDomainsView>;
  applySkillDomains(domains: string[]): Promise<SkillDomainsView>;
  connectScan(): Promise<ConnectScan>;
  connectApply(client: ConnectClientId): Promise<ConnectResult>;
  connectRemove(client: ConnectClientId): Promise<ConnectResult>;
  /** 사람이 「다시 켤까요?」에 누른 뒤에만 부른다 — Claude Desktop 에서 돌던 일이 끊긴다. */
  connectRestartDesktop(): Promise<ConnectRestartResult>;
  connectVerify(): Promise<{ ok: boolean; tool_count?: number; error?: string }>;
  connectHook(enabled: boolean): Promise<ConnectResult>;
  guideSkillStatus(): Promise<GuideSkillStatus>;
  guideSkill(action: GuideSkillAction, client?: string): Promise<GuideSkillResult>;
  openGuideSkillFolder(): Promise<{ ok: boolean; path?: string }>;
  profile(fresh?: boolean): Promise<PcProfile>;
  recommendation(): Promise<Recommendation>;
  models(): Promise<ModelsView>;
  /** `applyCtx` 를 주면 다 받은 뒤 **백엔드가** 적용한다 — 마법사를 닫아도 적용된다. */
  pull(modelKey: string, applyCtx?: number, eyes?: boolean): Promise<PullState & { ok: boolean; error?: string }>;
  /** `eyes: false` — 그림 부속을 뺀 「글만 읽기」로 올린다. 안 주면 예전 그대로 그림을 읽게 올린다. */
  apply(modelKey: string, numCtx: number, eyes?: boolean): Promise<ApplyResult>;
  installedModels(): Promise<{ models: InstalledModel[] }>;
  /** 머리의 모델 이름을 눌렀을 때 — 카탈로그 + 이 PC 가 받아 둔 것을 합친 한 번의 답. */
  modelPicker(role: ModelRole): Promise<ModelPickerView>;
  selectModel(tag: string, role: ModelRole, numCtx?: number): Promise<SelectResult>;
  contextStatus(): Promise<ContextView>;
  measureContext(model?: string): Promise<{ ok: boolean; error?: string }>;
  /** 잰 상한과 그 위 첫 불합격 칸 사이를 두 번 더 올려 본다(10-25 「더 쥐어짜기」). */
  squeezeContext(model?: string): Promise<{ ok: boolean; error?: string }>;
  /** `numCtx` = 잰 칸 하나(09-29 칸별 고르기). 비우면 잰 상한. */
  applyContext(model: string, alsoGlobal: boolean, numCtx?: number): Promise<ContextApplyResult>;
  /** `role: "code"` 면 다 받은 뒤 코드 역할에만 적용한다(대화 모델은 그대로). */
  /** `eyes: false` — 다 받은 뒤 그림 부속을 뺀 「글만 읽기」로 적용한다. 안 주면 예전 그대로다. */
  pullTag(tag: string, applyCtx?: number, role?: ModelRole, eyes?: boolean): Promise<PullState & { ok: boolean; error?: string }>;
  applyTag(tag: string, numCtx?: number, eyes?: boolean): Promise<ApplyResult>;
  hfSearch(query: string, usableGb: number, sort?: "downloads" | "trending"): Promise<HfSearch>;
  /** `ctx` = 받은 뒤 적용할 대화 길이 — 여유를 그 길이에서 잰다(2026-10-03). */
  hfFiles(repo: string, usableGb: number, ctx?: number): Promise<HfFiles>;
  importScan(project: string): Promise<ImportScan>;
  importPreview(project: string, ids: string[], paste: PasteInput | null, redactContacts: boolean): Promise<{ items: ImportPreviewItem[] }>;
  importCommit(
    project: string,
    items: { id: string; sha256: string }[],
    paste: PasteInput | null,
    redactContacts: boolean,
  ): Promise<ImportCommitResult>;
  importList(): Promise<{ count: number; items: ImportedItem[] }>;
  importRemove(importId: number): Promise<{ ok: boolean; error?: string }>;
  aboutMe(): Promise<AboutMeView>;
  /** 원문 저장(개발자 편집기). 상한을 넘으면 `{ok:false, error:"too_long"}` — 파일은 그대로다. */
  aboutMeSave(content: string): Promise<AboutMeView>;
  aboutMeCardPreview(answers: AboutMeAnswersInput, lang: string): Promise<AboutMeCardPreview>;
  aboutMeCardSave(answers: AboutMeAnswersInput, lang: string): Promise<AboutMeView>;
  aboutMeImportLines(importId: number): Promise<AboutMeImportLines>;
  aboutMeAppendImport(importId: number, lines: number[]): Promise<AboutMeView>;
  aboutMeOpen(): Promise<{ ok: boolean; path?: string; error?: string }>;
}

export function createSetupApi(bootstrap: BackendBootstrap): SetupApi {
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!bootstrap.controlToken) {
      throw new Error(t("Sonjari에 연결하지 못했습니다. 앱 백엔드를 다시 시작해 주세요."));
    }
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    headers.set("X-JARVIS-TOKEN", bootstrap.controlToken);
    const response = await fetch(`${bootstrap.baseUrl}${path}`, { ...init, headers });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`.trim());
    return response.json() as Promise<T>;
  }
  return {
    setupState: () => call("/v1/setup/state"),
    finishSetup: (steps) => call("/v1/setup/state", { method: "POST", body: JSON.stringify({ completed: true, steps }) }),
    ollamaStatus: () => call("/v1/setup/ollama"),
    ollamaInstall: () => call("/v1/setup/ollama/install", { method: "POST", body: "{}" }),
    ollamaRepair: () => call("/v1/setup/ollama/repair", { method: "POST", body: "{}" }),
    ollamaGpuOnly: () => call("/v1/setup/ollama/gpu-only", { method: "POST", body: "{}" }),
    backupStatus: () => call("/v1/backup"),
    backupRestore: (generation) => call("/v1/backup/restore", { method: "POST", body: JSON.stringify({ generation }) }),
    reportPreview: (jobId = "") => call(`/v1/report/preview?job_id=${encodeURIComponent(jobId)}`),
    reportSend: (id, note, consent) => call("/v1/report/send", { method: "POST", body: JSON.stringify({ id, note, consent }) }),
    skillDomains: () => call("/v1/skills/domains"),
    applySkillDomains: (domains) => call("/v1/skills/domains", { method: "POST", body: JSON.stringify({ domains }) }),
    profile: (fresh = false) => call(`/v1/setup/profile${fresh ? "?fresh=true" : ""}`),
    recommendation: () => call("/v1/setup/recommendation"),
    models: () => call("/v1/setup/models"),
    pull: (modelKey, applyCtx, eyes) =>
      call("/v1/setup/models/pull", { method: "POST", body: JSON.stringify({ model_key: modelKey, apply_ctx: applyCtx ?? 0, ...(eyes === undefined ? {} : { eyes }) }) }),
    apply: (modelKey, numCtx, eyes) =>
      call("/v1/setup/models/apply", {
        method: "POST",
        body: JSON.stringify({ model_key: modelKey, num_ctx: numCtx, ...(eyes === undefined ? {} : { eyes }) }),
      }),
    installedModels: () => call("/v1/setup/models/installed"),
    modelPicker: (role) => call(`/v1/setup/models/picker?role=${encodeURIComponent(role)}`),
    selectModel: (tag, role, numCtx = 0) =>
      call("/v1/setup/models/select", { method: "POST", body: JSON.stringify({ tag, role, num_ctx: numCtx }) }),
    contextStatus: () => call("/v1/setup/context"),
    measureContext: (model) =>
      call("/v1/setup/context/measure", { method: "POST", body: JSON.stringify({ model: model ?? "" }) }),
    squeezeContext: (model) =>
      call("/v1/setup/context/squeeze", { method: "POST", body: JSON.stringify({ model: model ?? "" }) }),
    applyContext: (model, alsoGlobal, numCtx) =>
      call("/v1/setup/context/apply", { method: "POST", body: JSON.stringify({ model, also_global: alsoGlobal, num_ctx: numCtx ?? 0 }) }),
    pullTag: (tag, applyCtx, role = "chat", eyes) =>
      call("/v1/setup/models/pull-tag", { method: "POST", body: JSON.stringify({ tag, apply_ctx: applyCtx ?? 0, role, ...(eyes === undefined ? {} : { eyes }) }) }),
    applyTag: (tag, numCtx = 32768, eyes) =>
      call("/v1/setup/models/apply-tag", { method: "POST", body: JSON.stringify({ tag, num_ctx: numCtx, ...(eyes === undefined ? {} : { eyes }) }) }),
    hfSearch: (query, usableGb, sort = "downloads") =>
      call(`/v1/setup/hf/search?q=${encodeURIComponent(query)}&usable_gb=${usableGb}&sort=${sort}`),
    hfFiles: (repo, usableGb, ctx = 32768) =>
      call(`/v1/setup/hf/files?repo=${encodeURIComponent(repo)}&usable_gb=${usableGb}&ctx=${ctx}`),
    importScan: (project) => call(`/v1/setup/import/scan?project=${encodeURIComponent(project)}`),
    importPreview: (project, ids, paste, redactContacts) =>
      call("/v1/setup/import/preview", {
        method: "POST",
        body: JSON.stringify({ project, ids, paste, redact_contacts: redactContacts }),
      }),
    importCommit: (project, items, paste, redactContacts) =>
      call("/v1/setup/import/commit", {
        method: "POST",
        body: JSON.stringify({ project, items, paste, redact_contacts: redactContacts }),
      }),
    importList: () => call("/v1/setup/import/list"),
    connectScan: () => call("/v1/setup/connect/scan"),
    connectApply: (client) =>
      call("/v1/setup/connect/apply", { method: "POST", body: JSON.stringify({ client }) }),
    connectRemove: (client) =>
      call("/v1/setup/connect/remove", { method: "POST", body: JSON.stringify({ client }) }),
    connectRestartDesktop: () => call("/v1/setup/connect/restart-desktop", { method: "POST", body: "{}" }),
    connectVerify: () => call("/v1/setup/connect/verify", { method: "POST", body: "{}" }),
    connectHook: (enabled) =>
      call("/v1/setup/connect/hook", { method: "POST", body: JSON.stringify({ enabled }) }),
    guideSkillStatus: () => call("/v1/setup/guide-skill"),
    guideSkill: (action, client) =>
      call("/v1/setup/guide-skill", { method: "POST", body: JSON.stringify({ action, client }) }),
    openGuideSkillFolder: () =>
      call("/v1/desktop/open-folder", { method: "POST", body: JSON.stringify({ which: "guide_skill" }) }),
    importRemove: (importId) =>
      call("/v1/setup/import/remove", { method: "POST", body: JSON.stringify({ import_id: importId }) }),
    aboutMe: () => call("/v1/about-me"),
    aboutMeSave: (content) => call("/v1/about-me", { method: "PUT", body: JSON.stringify({ content }) }),
    aboutMeCardPreview: (answers, lang) =>
      call("/v1/about-me/card/preview", { method: "POST", body: JSON.stringify({ answers, lang }) }),
    aboutMeCardSave: (answers, lang) =>
      call("/v1/about-me/card", { method: "POST", body: JSON.stringify({ answers, lang }) }),
    aboutMeImportLines: (importId) => call(`/v1/about-me/import-lines?import_id=${importId}`),
    aboutMeAppendImport: (importId, lines) =>
      call("/v1/about-me/import-lines", { method: "POST", body: JSON.stringify({ import_id: importId, lines }) }),
    aboutMeOpen: () => call("/v1/about-me/open", { method: "POST", body: "{}" }),
  };
}

/** `131072` → `128K`. 화면 어디서나 같은 표기. */
export function ctxLabel(ctx: number): string {
  return `${Math.round(ctx / 1024)}K`;
}
