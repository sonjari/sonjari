/**
 * 첫 실행 — 세 단계만 (전략안 §43, P3).
 *
 *     PC 확인  →  모델  →  연결
 *
 * ## 모양의 뜻
 *
 * 창을 **온도로** 나눈다. 왼쪽 따뜻한 흑연은 사람 쪽(무엇을 하는지·자비스의 말·누를 것),
 * 오른쪽 찬 흑연은 기계 쪽(잰 값·메모리 자·모델). 기존 작업 화면의 「사람=따뜻 / 기계=참」
 * 을 그대로 쓴다 — 설치 화면만 다른 제품처럼 보이면 안 된다.
 *
 * ## 규율
 *
 * - 화면은 **계산하지 않는다.** 들어가는지·무엇을 권하는지는 백엔드가 재서 준다.
 * - 추천 어시스턴트는 백엔드 `reasons` 를 말로 옮길 뿐이다. 설치 중엔 대화할 모델이 없다.
 * - 추천 칸 테두리는 **세 번** 깜빡이고 멈춘다. 움직임 줄이기면 깜빡임 없이 테두리만.
 * - 아직 없는 기능(MCP 연결)은 누를 수 있는 척하지 않는다.
 * - 지침 가져오기(P4)는 3단계 왼쪽이 고르고 누르는 곳, 오른쪽이 「어디를 여는지」와 걷은 결과.
 */
import { t } from "../i18n";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri, loadBootstrap } from "../backend";
import { FirstRunPanel } from "./FirstRunPanel";
import { finishSetupFlow } from "./finishFlow";
import { ProblemReportDialog } from "../workspace/ProblemReportDialog";
import { SkillDomainPicker } from "./SkillDomainPicker";
import { DemoReel } from "./DemoReel";
import { ClaudeRestartDialog, ConnectPanel, desktopAwaitingRestart } from "./ConnectPanel";
import type { ConnectScan } from "./setupApi";
import { JarvisMark } from "../workspace/JarvisMark";
import { ImportPanel } from "./ImportPanel";
import { ImportPreview } from "./ImportPreview";
import { MemoryRuler } from "./MemoryRuler";
import { HfPicker, type HfPick } from "./HfPicker";
import { pollUnlessBusy } from "./poll";
import { useInstructionImport, type ImportState } from "./useInstructionImport";
import {
  createSetupApi,
  ctxLabel,
  type ApplyResult,
  type CatalogModel,
  type InstalledModel,
  type ModelPick,
  type OllamaStatus,
  type PcProfile,
  type PullState,
  pullFailureText,
  pushedOutReason,
  type GpuFixResult,
  type Recommendation,
  type SetupApi,
} from "./setupApi";
import type { WayOutInfo } from "./setupApi";
import { WayOut, hasWayOut } from "./WayOut";
import "./setup.css";
import { ContextCeilingPanel } from "../workspace/ContextCeilingPanel";

type Step = 0 | 1 | 2 | 3;
// W4: 「쓰임」 — 주로 무엇에 쓰는지 고르면 그 분야 스킬로 세팅한다. 연결보다 앞이다(연결은 선택, 쓰임은 모두에게).
const STEPS = [t("PC 확인"), t("모델"), t("쓰임"), t("연결")] as const;

const FIRST_ASKS = [
  t("사람인에서 여수 회계 채용 공고 3개를 찾아서 표로 된 문서로 만들어줘"),
  t("다나와에서 무선 마우스 인기 상품 3개를 가격과 함께 엑셀로 정리해줘"),
  t("YES24에서 파이썬 입문서 3권의 쪽수와 가격을 비교해서 문서로 만들어줘"),
];

async function openApi(): Promise<SetupApi> {
  if (import.meta.env.DEV) {
    const name = new URLSearchParams(window.location.search).get("setupFixture");
    if (name) {
      const fixtures = await import("./fixtureSetupApi");
      const api = fixtures.createFixtureSetupApi(name);
      if (api) return api;
    }
  }
  return createSetupApi(await loadBootstrap());
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

export default function SetupWizard() {
  const [api, setApi] = useState<SetupApi | null>(null);
  const [step, setStep] = useState<Step>(0);
  const [profile, setProfile] = useState<PcProfile | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [picked, setPicked] = useState<{ key: string; ctx: number; textOnly?: boolean } | null>(null);
  const [said, setSaid] = useState(0);
  const [asked, setAsked] = useState(false);
  const [pulse, setPulse] = useState("");
  const [pull, setPull] = useState<PullState | null>(null);
  // 모델을 받기·올리기 **전에** 한 번 — 권고가 `fixes` 로 준 것을 사람 대신 맞춘다(2026-09-16 노트북 요청).
  const [gpuFix, setGpuFix] = useState<GpuFixResult | "running" | null>(null);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<ApplyResult | null>(null);
  // ★ 2026-09-16 제품 요청: 「시작 버튼 한 번이면 알아서 다 한다」. 추천 → 고르기 → 그래픽 설정 → 받기 → 돌려 보고 적용을
  //   사람이 단계마다 누르던 것을 한 번에 잇는다. 한 판에 한 번만 스스로 시작한다(`autoStarted`) — 사람이 다른 모델을
  //   고르면 그다음은 사람이 누른 대로 간다.
  // ★ 2026-10-07 사무실 PC 첫 설치: 그 「알아서」가 **받기까지** 갔다 — 모델 단계에 들어서자마자 추천 모델을 묻지 않고
  //   받기 시작했고, 허깅페이스 탭에서 직접 고른 사람은 「받고 확인하기」가 꺼진 화면을 만났다(대표: 「무조건 손자리가 고른 걸
  //   받는다」). 수 GB 를 받는 일은 사람이 누른다. 자동은 **추천을 골라 두고 까닭을 말하는 데까지**다.
  const [autopilot, setAutopilot] = useState(false);
  // ★ 2026-10-12 처음 깐 사람: 「모델들이 너무 많아서 어렵다」. 추천 문으로 들어왔는데도 카드 열 장과 탭 셋이 한꺼번에
  //   펼쳐졌다. 추천 문에서는 추천한 모델만 먼저 보이고, 나머지는 「다른 모델 보기」 뒤에 둔다. 직접 고르는 문은 처음부터 다 보인다.
  const [allModels, setAllModels] = useState(false);
  // ★ 2026-10-06 스토어 공개판 첫 설치(RTX 3050 사무실 PC): 「Ollama 설치」를 누르고 바로 「설정 시작」을 눌렀더니 설치가
  //   끝나기 전에 받기가 나가 「Ollama 가 켜져 있지 않아 받지 못했습니다 — 설치를 먼저 눌러 주세요」가 떴다. 이미 누른
  //   사람에게 틀린 안내다. Ollama 가 준비되기 전의 받기는 **실패시키지 않고 붙잡아 뒀다가**(`held`) 준비되는 순간 잇는다.
  const [ollamaNow, setOllamaNow] = useState<OllamaStatus | null>(null);
  const [held, setHeld] = useState<{ tag?: string } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const recheck = useCallback(async () => {
    if (!api) return;
    setRechecking(true);
    try {
      const [p, r] = await Promise.all([api.profile(true), api.recommendation()]);
      setProfile(p);
      setRec(r);
      setModels((await api.models()).models);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRechecking(false);
    }
  }, [api]);
  // 3단계에 들어올 때 찾는다 — 첫 화면부터 지침 파일 자리를 건드릴 이유가 없다.
  const imp = useInstructionImport(step === 3 ? api : null);

  useEffect(() => {
    let alive = true;
    openApi()
      .then(async (client) => {
        if (!alive) return;
        setApi(client);
        const [p, r] = await Promise.all([client.profile(true), client.recommendation()]);
        if (!alive) return;
        setProfile(p);
        setRec(r);
        setModels((await client.models()).models);
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, []);

  // 내장 그래픽은 모델을 올릴 전용 메모리가 없다(M1) — 자에 그리지 않는다.
  const card = useMemo(() => {
    const discrete = (profile?.gpus ?? []).filter((gpu) => !gpu.integrated && gpu.vram_total_gb > 0);
    return discrete.length ? [...discrete].sort((a, b) => b.vram_total_gb - a.vram_total_gb)[0] : null;
  }, [profile]);
  const pickKinds = useMemo(
    () => new Map((rec?.picks ?? []).map((pick) => [pick.model_key, pick.kind])),
    [rec],
  );
  // 갤러리 순서: 이 PC 추천(검증→조건 없는 대안→외부) 먼저, 그다음 들어가는 것, 안 들어가는 것.
  // 같은 `family` 는 카드 하나로 합쳐지고(`groupFamilies`), 그 카드는 묶음에서 가장 앞선 변형의 자리에 선다.
  const ordered = useMemo(() => {
    const rank = (m: CatalogModel) => {
      const kind = pickKinds.get(m.key);
      return kind === "verified" ? 0 : kind === "open_alternative" ? 1 : kind === "external" ? 2 : m.fits ? 3 : 4;
    };
    return [...models].sort((a, b) => rank(a) - rank(b));
  }, [models, pickKinds]);
  const modelsNow = useRef(models);
  modelsNow.current = models;
  const [pickedTag, setPickedTag] = useState("");
  // 묶음 카드에서는 `picked.key` 가 **고른 크기(변형)의 key** 다 — 받기·적용·메모리 자가 전부 이 한 줄을 따른다.
  const pickedModel = models.find((m) => m.key === picked?.key) ?? null;
  // ★ 2026-10-01 밤: 모델을 고르는 길 셋 — 잰 추천 · 허깅페이스에서 직접 · 받아 둔 모델·이름 입력.
  //   한 줄로 쌓아 두니 스크롤이 길고, 「직접 고르기」가 맨 아래에 숨었다.
  const [source, setSource] = useState<"catalog" | "hf" | "other">("catalog");
  const focusModels = useMemo(() => recommendedOnly(models, rec), [models, rec]);
  const focused = autopilot && !allModels && source === "catalog" && focusModels.length > 0;
  const [hfPick, setHfPick] = useState<HfPick | null>(null);
  // 「글만 읽기」로 받기로 한 이름들 — 받기와 그 뒤의 적용이 같은 뜻으로 가게 이름으로 들고 있는다(2026-10-13).
  const textOnlyTags = useRef(new Set<string>());
  // 허깅페이스 양자화를 고르면 위의 메모리 자가 그 크기로 움직인다(추정 — 파일 + 실행 여유).
  const rulerModel: CatalogModel | null = hfPick && source === "hf"
    ? ({ ...(models[0] ?? {}), key: `hf:${hfPick.file.tag}`, name: `${hfPick.repo.split("/")[1]} ${hfPick.file.quant}`,
         vram_gb: { "32768": Math.round((hfPick.file.gb + 1.2) * 10) / 10 } } as CatalogModel)
    : pickedModel;

  // 추천을 **말로** 옮긴다 — 한 줄씩. 움직임 줄이기면 한 번에.
  const askAssistant = useCallback(() => {
    if (!rec) return;
    setAsked(true);
    const lines = rec.reasons.length + rec.warnings.length;
    if (prefersReducedMotion()) {
      setSaid(lines);
    } else {
      setSaid(0);
      for (let i = 1; i <= lines; i += 1) window.setTimeout(() => setSaid(i), 380 * i);
    }
    if (rec.model_key && rec.num_ctx) {
      const delay = prefersReducedMotion() ? 0 : 380 * lines + 200;
      window.setTimeout(() => {
        setSource("catalog");
        setPicked({ key: rec.model_key!, ctx: rec.num_ctx!, textOnly: Boolean(rec.text_only) });
        // 같은 `family` 는 카드 하나다 — 카드의 자리는 변형 key 가 아니라 묶음으로 찾는다.
        //   목록은 추천보다 늦게 올 수 있다 — 타이머가 도는 순간의 목록을 본다.
        const target = modelsNow.current.find((m) => m.key === rec.model_key);
        document.getElementById(target ? modelCardId(target) : `model-${rec.model_key}`)?.scrollIntoView({
          behavior: prefersReducedMotion() ? "auto" : "smooth",
          block: "center",
        });
        setPulse(rec.model_key!);
      }, delay);
    }
  }, [rec]);

  // 받는 중이면 따라간다. 다 받으면 바로 적용한다 — 사람이 다시 누르게 하지 않는다.
  useEffect(() => {
    if (!api || !pull || pull.status !== "pulling") return;
    const stop = pollUnlessBusy(async () => {
      const view = await api.models();
      const next = view.pulls[pull.model_key];
      if (!next) return;
      setPull(next);
      if (next.status !== "pulling") {
        setModels(view.models);
        stop();
      }
    }, 1000);
    return stop;
  }, [api, pull?.model_key, pull?.status]);

  const runApply = useCallback(async () => {
    if (!api || !picked) return;
    setApplying(true);
    setApplied(null);
    try {
      // 「글만 읽기」를 골랐을 때만 그 뜻을 싣는다 — 안 실으면 백엔드는 예전 그대로 그림을 읽게 올린다.
      setApplied(await api.apply(picked.key, picked.ctx, picked.textOnly ? false : undefined));
    } catch (err) {
      setApplied({ ok: false, error: err instanceof Error ? err.message : String(err) });
    } finally {
      setApplying(false);
    }
  }, [api, picked]);

  const ollamaReady = useCallback(async (): Promise<boolean> => {
    if (!api) return false;
    try {
      const status = await api.ollamaStatus();
      setOllamaNow(status);
      return status.running && !status.runner_missing;
    } catch {
      return true; // 상태를 못 읽으면 막지 않는다 — 받기가 스스로 실패를 말한다.
    }
  }, [api]);

  const prepareGpu = useCallback(async (): Promise<boolean> => {
    if (!api || !rec?.fixes?.includes("ollama_gpu_only")) return true;
    if (gpuFix && gpuFix !== "running" && gpuFix.ok) return true;
    setGpuFix("running");
    try {
      const result = await api.ollamaGpuOnly();
      setGpuFix(result);
      // 사람이 일부러 Vulkan 을 켜 둔 PC 는 그대로 두고 진행한다 — 막을 일이 아니다.
      return result.ok || result.error === "user_set_vulkan_on";
    } catch (err) {
      setGpuFix({ ok: false, error: err instanceof Error ? err.message : String(err) });
      return false;
    }
  }, [api, rec, gpuFix]);

  const runApplyTag = useCallback(async (tag: string) => {
    if (!api) return;
    setPickedTag(tag);
    setPicked(null);
    setApplying(true);
    setApplied(null);
    try {
      setApplied(await api.applyTag(tag, undefined, textOnlyTags.current.has(tag) ? false : undefined));
    } catch (err) {
      setApplied({ ok: false, error: err instanceof Error ? err.message : String(err) });
    } finally {
      setApplying(false);
    }
  }, [api]);

  useEffect(() => {
    if (pull?.status !== "done" || applied || applying) return;
    // 백엔드가 받은 뒤 이미 적용했다 — 화면이 한 번 더 돌리지 않는다.
    if (pull.applied) {
      setApplied(pull.applied);
      return;
    }
    if (picked && pull.model_key === picked.key) void runApply();
    else if (pickedTag && pull.model_key === pickedTag) void runApplyTag(pickedTag);
  }, [pull?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const startPullTag = useCallback(async (tag: string) => {
    if (!api) return;
    if (!(await ollamaReady())) {
      setPull(null);
      setHeld({ tag });
      return;
    }
    if (!(await prepareGpu())) return;
    setPickedTag(tag);
    setPicked(null);
    setApplied(null);
    try {
      const started = await api.pullTag(tag, 32768, "chat", textOnlyTags.current.has(tag) ? false : undefined);
      if (!started.ok) throw new Error(started.error === "bad_tag" ? t("모델 이름 모양이 아닙니다 — 예: qwen3.5:4b") : started.error || t("받기를 시작하지 못했습니다"));
      setPull(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api, prepareGpu, ollamaReady]);

  const startApply = useCallback(async () => {
    if (!api || !pickedModel || !picked) return;
    if (!(await ollamaReady())) {
      setPull(null);
      setHeld({});
      return;
    }
    if (!(await prepareGpu())) return;
    if (pickedModel.installed) {
      await runApply();
      return;
    }
    try {
      // 「글만 읽기」로 골랐으면 받기만 시킨다 — 받은 뒤의 적용은 그 뜻을 실어 여기서 한다(아래 `runApply`).
      // 백엔드가 받자마자 적용하면 그림을 읽게 올려 버린다.
      const started = await api.pull(pickedModel.key, picked.textOnly ? undefined : picked.ctx);
      if (!started.ok) throw new Error(started.error || t("받기를 시작하지 못했습니다"));
      setPull(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api, picked, pickedModel, runApply, prepareGpu, ollamaReady]);

  /** 못 올린 뒤 「닫았어요 — 다시 재기」 — 고른 모델 그대로 다시 올려 본다. */
  const retryApply = useCallback(() => { void startApply(); }, [startApply]);

  /** 못 올린 뒤 「더 작은 모델로」 — 그 모델을 고른 것으로 바꾸고, 받아 뒀으면 바로 재고 아니면 받는다(받기가 끝나면 이어서 잰다). */
  const applySmaller = useCallback(async (smaller: NonNullable<WayOutInfo["smaller"]>) => {
    if (!api) return;
    setPickedTag("");
    setPicked({ key: smaller.model_key, ctx: smaller.num_ctx });
    setApplied(null);
    try {
      if (smaller.installed) {
        setApplying(true);
        try {
          setApplied(await api.apply(smaller.model_key, smaller.num_ctx));
        } finally {
          setApplying(false);
        }
        return;
      }
      const started = await api.pull(smaller.model_key, smaller.num_ctx);
      if (!started.ok) throw new Error(started.error || t("받기를 시작하지 못했습니다"));
      setPull(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api]);

  // 붙잡아 둔 받기: Ollama 가 준비됐는지 1.5초마다 다시 보고, 준비되면 **한 번만** 잇는다.
  useEffect(() => {
    if (!held) return;
    let alive = true;
    const stop = pollUnlessBusy(async () => {
      if (!(await ollamaReady()) || !alive) return;
      alive = false;
      setHeld(null);
      if (held.tag) void startPullTag(held.tag);
      else void startApply();
    }, 1500);
    return () => {
      alive = false;
      stop();
    };
  }, [held, ollamaReady, startPullTag, startApply]);

  // 자동 진행 ① 모델 단계에 들어오면 추천을 바로 말하고 고른다.
  useEffect(() => {
    if (autopilot && step === 1 && rec && !asked) askAssistant();
  }, [autopilot, step, rec, asked, askAssistant]);
  // 자동 진행은 여기까지다 — 받기는 사람이 「받고 적용하기」를 눌러 시작한다(위 `autopilot` 주석).

  // 끝냈다는 표시는 **백엔드 파일**(`setup_state.json`)이다. 앱이 다음 실행에 그걸 보고 마법사를
  // 건너뛴다. 예전 `localStorage` 표시는 앱을 다시 깔면 사라져 판정 근거가 못 됐다(W2).
  // ★ 어느 것이 멈춰도 화면은 넘어간다(`finishFlow.ts`, 2026-10-06 「눌러도 반응 없음」). 누른 동안은 단추가 「여는 중…」이다.
  const [finishing, setFinishing] = useState(false);
  // ★ 2026-10-12: 금색 단추만 따라 누르는 사람이 「잇기」를 지나쳐 끝났다(처음 깐 두 사람이 같은 자리). Claude Desktop 이
  //   켜져 있어 아직 못 이었으면 금색 단추가 「잇고 시작하기」가 된다 — 다음만 눌러도 옳게 끝나게.
  const [connectScan, setConnectScan] = useState<ConnectScan | null>(null);
  const [restartOpen, setRestartOpen] = useState(false);
  const desktopPending = step === 3 ? desktopAwaitingRestart(connectScan) : null;
  // 마법사에서 막힌 사람이 보낼 길 — 작업 화면까지 가야만 누를 수 있었다(2026-10-06).
  const [reportOpen, setReportOpen] = useState(false);
  const finish = async (ask: string) => {
    if (finishing) return;
    setFinishing(true);
    const steps = ["pc_check", ...(applied?.ok ? ["model"] : []), ...(usageSaved ? ["usage"] : []), "connect"];
    try {
      await finishSetupFlow({
        record: async () => {
          await api?.finishSetup(steps);
        },
        startup: startup ? () => invoke("startup_task", { enable: true }) : undefined,
        switchWindow: isTauri() ? () => invoke("finish_setup", { draft: ask }) : undefined,
        goSameWindow: () => {
          window.location.search = `?mode=workspace&draft=${encodeURIComponent(ask)}`;
        },
      });
    } finally {
      setFinishing(false);
    }
  };
  const [startup, setStartup] = useState(false);
  const [usageSaved, setUsageSaved] = useState(false);
  const [packaged, setPackaged] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    invoke<{ packaged: boolean }>("app_package_status")
      .then((status) => setPackaged(status.packaged))
      .catch(() => setPackaged(false));
  }, []);

  return (
    <div className={`setup${pull?.status === "pulling" || applying ? " is-docked" : ""}`}>
      {(pull?.status === "pulling" || applying) && (
        // ★ 2026-10-07 사무실 PC 첫 설치(대표: 「UX 0점」): 받기 진행 줄이 왼쪽 칸에만 있었다. 오른쪽의 긴 목록 가운데서 단추를
        //   누른 사람에게는 화면이 그대로였다 — 받는 중인지, 얼마나 남았는지 몰랐다. 어디를 보고 있든 보이게 **창 아래에 띠로** 둔다.
        <div className="setup-dock" role="status" data-testid="setup-dock">
          <b className="setup-dock-name">
            {(models.find((m) => m.key === pull?.model_key)?.name ?? pull?.model_key ?? pickedModel?.name ?? pickedTag ?? "").replace(/^(hf\.co|huggingface\.co)\//, "")}
          </b>
          <ApplyLine pull={pull} applying={applying} applied={applied} api={api} onRetry={retryApply} onSmaller={applySmaller} />
        </div>
      )}
      <section className="setup-human" aria-live="polite">
        <ol className="setup-steps" aria-label={t("설정 단계")}>
          {STEPS.map((label, index) => (
            <li key={label} className={index === step ? "is-now" : index < step ? "is-done" : ""} aria-current={index === step ? "step" : undefined}>
              {label}
            </li>
          ))}
        </ol>

        {error && (
          <div className="setup-error" role="alert">
            <p>{error}</p>
            {isTauri() && (
              // F2 · G1: 백엔드가 늦게 뜨거나 죽었을 때 사람이 할 수 있는 일이 「앱을 다시 켜기」뿐이었다.
              <button type="button" className="setup-btn-quiet" disabled={retrying} onClick={async () => {
                setRetrying(true);
                const ok = await invoke<boolean>("retry_backend").catch(() => false);
                setRetrying(false);
                if (ok) window.location.reload();
                else setError(t("백엔드를 켜지 못했습니다. 앱을 완전히 종료한 뒤 다시 켜 주세요. 계속되면 앱 데이터 폴더의 logs\\backend_start.log(보통 %LOCALAPPDATA%\\Ontelic) 를 보내 주세요."));
              }}>
                {retrying ? t("다시 켜는 중…") : t("다시 시도")}
              </button>
            )}
          </div>
        )}

        {step === 0 && <StepCheckText profile={profile} rec={rec} onRecheck={recheck} rechecking={rechecking} />}
        {step === 0 && <FirstRunPanel api={api} onOllamaReady={() => void recheck()} />}
        {/* 첫 화면(PC 확인)에만. ★ 2026-09-16 노트북: 「받는 동안 다음으로」를 누르면 받기가 계속 돌아 시연이
            2·3단계까지 따라왔고, 걸음이 쌓이며 버튼과 진행 막대를 화면 밖으로 밀어냈다. */}
        {step === 0 && <DemoReel />}
        {step === 1 && (
          <StepModelText rec={rec} asked={asked} said={said} onAsk={askAssistant} />
        )}
        {step === 2 && api && (
          <div className="setup-say">
            <h1>{t("주로 무엇에 쓰시나요")}</h1>
            <p className="setup-lead">{t("고른 분야의 일하는 방법(스킬)을 요청에 맞을 때만 골라 붙입니다. 나중에 설정 › 스킬에서 바꿀 수 있습니다.")}</p>
            <SkillDomainPicker load={() => api.skillDomains()} apply={(domains) => api.applySkillDomains(domains)}
              compact onApplied={() => setUsageSaved(true)} />
          </div>
        )}
        {step === 3 && (
          <SetupReadiness
            rows={readinessRows({
              modelName: applied?.ok ? (pickedModel?.name ?? applied.selection?.chat_model ?? "") : "",
              modelCtx: applied?.ok ? (applied.selection?.num_ctx ?? picked?.ctx ?? 0) : 0,
              scan: connectScan,
            })}
            onFix={(fix) => (fix === "model" ? setStep(1) : setRestartOpen(true))}
          />
        )}
        {step === 3 && <StepConnectText api={api} imp={imp} pull={pull} applied={applied} applying={applying} onAsk={(ask) => void finish(ask)} onImportOpen={setImportOpen} onScan={setConnectScan} />}
        {step === 3 && packaged && (
          // 스토어 앱은 스스로 자동 시작을 못 켠다 — 사람이 고른 것만 Windows 확인 창으로 넘긴다(W1-6).
          <label className="firstrun-check">
            <input type="checkbox" checked={startup} onChange={(event) => setStartup(event.target.checked)} />
            {t("Windows 를 켤 때 Sonjari도 켜기")}
          </label>
        )}

        {/* 진행 줄은 버튼 **위**에 — 아래에 두면 긴 화면에서 밀려나 받는 중인지 안 보였다(2026-09-16 노트북). */}
        {/* Ollama 가 없으면 설치 칸을 **여기에도** 둔다 — 아래 실패 글이 「위의 『Ollama 설치』」를 가리킨다(2026-10-06). */}
        {step === 1 && <FirstRunPanel api={api} onOllamaReady={() => void recheck()} ollamaOnly />}
        {step === 1 && held && <HeldLine ollama={ollamaNow} />}
        {step === 1 && <GpuFixLine fix={gpuFix} />}
        {(step === 1 || (step === 2 && (pull?.status === "pulling" || applying))) && (
          <ApplyLine pull={pull} applying={applying} applied={applied} api={api} onRetry={retryApply} onSmaller={applySmaller} />
        )}
        <div className="setup-actions">
          {step === 2 && (
            <button type="button" className="setup-btn-go" onClick={() => setStep(3)}>
              {usageSaved ? t("연결로 넘어가기") : t("건너뛰고 연결로")}
            </button>
          )}
          {step === 3 && (
            // ★ 2026-09-16 노트북: 연결까지 마쳤는데 **끝내는 버튼이 없었다.** 마법사를 닫는 길이 맨 아래 예시 부탁
            //   칩뿐이었고, 지침·연결 칸 아래로 밀려 안 보여서 「더 이상 안 넘어간다」가 됐다.
            desktopPending ? (
              <>
                {/* 무엇을 하는지 단추에 적는다 — 남의 앱을 끄고 켜는 일을 「다음」 뒤에 숨기지 않는다. 누르면 먼저 묻는다. */}
                <button type="button" className="setup-btn-go" disabled={finishing} onClick={() => setRestartOpen(true)}>
                  {finishing ? t("여는 중…") : t("Claude 에 잇고 시작하기")}
                </button>
                <button type="button" className="setup-btn-quiet" disabled={finishing} onClick={() => void finish("")}>
                  {t("잇지 않고 시작하기")}
                </button>
              </>
            ) : (
            <button type="button" className="setup-btn-go" disabled={finishing} onClick={() => void finish("")}>
              {finishing ? t("여는 중…") : t("Sonjari 시작하기")}
            </button>
            )
          )}
          {step === 0 && (
            <button
              type="button"
              className="setup-btn-go"
              disabled={!profile || !rec}
              onClick={() => {
                setAutopilot(rec?.mode === "local");
                setAllModels(false);
                setStep(1);
              }}
            >
              {rec?.mode === "local" ? t("이 PC 에 맞게 설정 시작") : t("모델 보기")}
            </button>
          )}
          {step === 0 && rec?.mode === "local" && (
            // ★ 2026-10-05 AWS 첫 실행: 위 버튼은 추천 모델을 골라 둔 채로 모델 단계를 연다. 처음부터 직접 고르려는 사람의 문을 따로 둔다
            //   (2026-10-07 부터는 어느 문으로 들어가도 받기는 사람이 누른다).
            <button
              type="button"
              className="setup-btn-quiet"
              disabled={!profile || !rec}
              onClick={() => {
                setAutopilot(false);
                setAllModels(true);
                setStep(1);
              }}
            >
              {t("모델 직접 고르기")}
            </button>
          )}
          {step === 1 && applied?.ok && (
            <button type="button" className="setup-btn-go" onClick={() => setStep(2)}>
              {t("쓰임 고르기")}
            </button>
          )}
          {step === 1 && !applied?.ok && (
            <>
              <button
                type="button"
                className="setup-btn-go"
                disabled={(!picked && !(hfPick && source === "hf")) || applying || pull?.status === "pulling" || gpuFix === "running" || held !== null}
                onClick={() => (hfPick && source === "hf" && !picked ? void startPullTag(hfPick.file.tag) : void startApply())}
              >
                {held
                  ? t("Ollama 를 기다리는 중…")
                  : pull?.status === "pulling"
                  ? pullLabel(pull)
                  : gpuFix === "running"
                    ? t("그래픽카드 설정 맞추는 중…")
                    : applying
                    ? t("돌려 보는 중…")
                    : hfPick && source === "hf" && !picked
                      ? t("{0} 받고 확인하기 · {1}GB", hfPick.file.quant, hfPick.file.gb.toFixed(1))
                    : !pickedModel
                      ? t("모델을 고르세요")
                      : pickedModel.installed
                        ? t("{0} 적용하기", pickedModel.name)
                        : t("받고 적용하기 · {0}GB", pickedModel.download_gb.toFixed(1))}
              </button>
              {rec?.mode !== "local" && (
                // 그래픽카드가 없거나 모자란 PC 만 건너뛴다. 올릴 수 있는 PC 는 **적용돼야** 넘어간다(2026-09-16 제품 요청:
                // 「받는 동안 다음으로」로 넘어갔다가 적용이 안 돼 제품 첫 화면이 「모델 없음」이었다).
                <button type="button" className="setup-btn-quiet" onClick={() => setStep(2)}>
                  {t("나중에 고르기")}
                </button>
              )}
            </>
          )}
          {/* 「뒤로」는 늘 맨 끝 — 1단계만 맨 앞에 있어 누를 자리가 단계마다 바뀌었다(2026-09-16 화면 점검). */}
          {step > 0 && (
            <button type="button" className="setup-btn-quiet" onClick={() => setStep((step - 1) as Step)}>
              {t("뒤로")}
            </button>
          )}
        </div>
        {/* 여기서 막혔을 때 — 무엇을 보내는지 먼저 보여 주고, 동의한 뒤에만 보낸다. */}
        <button type="button" className="setup-report-link" onClick={() => setReportOpen(true)}>
          {t("여기서 막혔나요? 문제 보내기")}
        </button>
        {reportOpen && <ProblemReportDialog api={api} onClose={() => setReportOpen(false)} />}
        {restartOpen && api && (
          <ClaudeRestartDialog api={api} doneLabel={t("Sonjari 시작하기")}
            onDone={() => { setRestartOpen(false); void finish(""); }}
            onClose={() => setRestartOpen(false)} />
        )}
      </section>

      <section className="setup-machine">
        {card ? (
          <MemoryRuler card={card} model={step === 0 ? null : rulerModel}
            ctx={step === 0 ? null : hfPick && source === "hf" ? 32768 : picked?.ctx} />
        ) : profile ? (
          <p className="setup-nocard">
            {t("AI 모델을 올릴 그래픽카드가 보이지 않습니다. Sonjari는 그래픽카드 메모리 8GB 이상을 권합니다.")}
          </p>
        ) : (
          <div className="ruler ruler-loading" aria-hidden="true" />
        )}

        {step === 0 && <Facts profile={profile} />}
        {step === 3 && importOpen && <ImportPreview imp={imp} />}
        {step === 3 && !importOpen && (
          // 지침 가져오기를 접어 둔 동안 오른쪽은 **이 단계에서 온텔릭이 바꾸는 것**만 말한다.
          <dl className="setup-facts">
            <div><dt>{t("잇는 것")}</dt><dd>{t("설치된 Claude 의 설정에 Sonjari 한 줄을 더합니다. 원래 설정은 백업합니다")}</dd></div>
            <div><dt>{t("안 하는 것")}</dt><dd>{t("비밀번호·토큰은 설정에 넣지 않습니다. 다른 설정은 한 글자도 바꾸지 않습니다")}</dd></div>
            <div><dt>{t("되돌리기")}</dt><dd>{t("각 도구 옆 「풀기」, 또는 설정 › 연결에서 언제든")}</dd></div>
            <div><dt>{t("끝나면")}</dt><dd>{t("「Sonjari 시작하기」를 누르면 방금 적용한 모델로 Sonjari가 열립니다")}</dd></div>
          </dl>
        )}
        {step === 2 && (
          // 기계 쪽: 분야를 고르면 **무엇이 바뀌고 무엇이 안 바뀌는지**. 약속을 부풀리지 않는다.
          <dl className="setup-facts">
            <div><dt>{t("바뀌는 것")}</dt><dd>{t("요청에 붙을 수 있는 스킬 후보가 고른 분야로 좁혀집니다")}</dd></div>
            <div><dt>{t("안 바뀌는 것")}</dt><dd>{t("스킬은 요청 낱말이 맞을 때만 붙습니다. 분야를 골라도 평소 대화에는 안 붙습니다")}</dd></div>
            <div><dt>{t("스킬이란")}</dt><dd>{t("밖에서 가져온 일하는 방법 문서입니다. 승인 없이 진행하라는 문장은 Sonjari가 걷어 냅니다")}</dd></div>
            <div><dt>{t("나중에")}</dt><dd>{t("설정 › 스킬에서 언제든 바꿉니다")}</dd></div>
          </dl>
        )}
        {step === 1 && focused && (
          <>
            <ModelGallery
              plain
              models={focusModels}
              pickKinds={pickKinds}
              usable={card?.usable_gb ?? 0}
              asked={asked}
              pulse={pulse}
              onPulseEnd={() => setPulse("")}
              picked={picked}
              onPick={(key, ctx, textOnly) => {
                setPicked({ key, ctx, textOnly });
                setPickedTag("");
                setHfPick(null);
                setApplied(null);
              }}
            />
            <button type="button" className="setup-more-models" onClick={() => setAllModels(true)}>
              {t("다른 모델 보기")}
              <small>{t("목록에서 직접 고르거나, 허깅페이스에서 찾거나, 받아 둔 모델을 쓸 수 있습니다")}</small>
            </button>
          </>
        )}
        {step === 1 && !focused && (
          <>
            <div className="model-source" role="tablist" aria-label={t("모델을 고르는 길")}>
              {([
                ["catalog", t("Sonjari 추천"), t("잰 모델")],
                ["hf", t("허깅페이스에서 고르기"), t("모델·양자화 직접")],
                ["other", t("받아 둔 모델·이름 입력"), "Ollama"],
              ] as const).map(([key, label, sub]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={source === key}
                  className={`model-source-tab is-${key}${source === key ? " is-on" : ""}`}
                  onClick={() => setSource(key)}
                >
                  {label}
                  <small>{sub}</small>
                </button>
              ))}
            </div>
            {source === "catalog" && (
              <ModelGallery
                models={ordered}
                pickKinds={pickKinds}
                usable={card?.usable_gb ?? 0}
                asked={asked}
                pulse={pulse}
                onPulseEnd={() => setPulse("")}
                picked={picked}
                onPick={(key, ctx, textOnly) => {
                  setPicked({ key, ctx, textOnly });
                  setPickedTag("");
                  setHfPick(null);
                  setApplied(null);
                }}
              />
            )}
            {source === "hf" && api && (
              <HfPicker
                api={api}
                card={card}
                busy={applying || pull?.status === "pulling"}
                busyWhy={
                  pull?.status === "pulling"
                    ? t("{0} 를 받는 중입니다 — 끝나면 여기서 다른 모델도 받을 수 있습니다.", models.find((m) => m.key === pull.model_key)?.name ?? pull.model_key)
                    : applying
                      ? t("받은 모델을 돌려 보는 중입니다 — 끝나면 여기서 다른 모델도 받을 수 있습니다.")
                      : ""
                }
                picked={hfPick}
                onPick={(pick) => {
                  setHfPick(pick);
                  setPicked(null);
                  setApplied(null);
                }}
                onGet={(pick) => {
                  if (pick.textOnly) textOnlyTags.current.add(pick.file.tag);
                  else textOnlyTags.current.delete(pick.file.tag);
                  void startPullTag(pick.file.tag);
                }}
                activeTag={pull?.status === "pulling" || applying ? pickedTag ?? "" : ""}
                status={pull?.status === "pulling" || applying
                  ? <ApplyLine pull={pull} applying={applying} applied={applied} api={api} onRetry={retryApply} onSmaller={applySmaller} />
                  : null}
              />
            )}
            {source === "other" && api && (
              <OtherModels api={api} busy={applying || pull?.status === "pulling"} pickedTag={pickedTag}
                onUse={(tag) => void runApplyTag(tag)} onPull={(tag) => void startPullTag(tag)} />
            )}
          </>
        )}
      </section>
    </div>
  );
}

/** 사람이 고치고 **앱을 끄지 않고** 다시 볼 수 있어야 하는 드라이버 상태. */
const DRIVER_ACTION_STATES = new Set(["missing", "disabled", "broken", "mismatch", "reboot_pending"]);

function StepCheckText({ profile, rec, onRecheck, rechecking }: {
  profile: PcProfile | null; rec: Recommendation | null; onRecheck: () => void; rechecking: boolean;
}) {
  return (
    <div className="setup-say">
      <h1>{t("이 PC 에서 Sonjari를 돌릴 수 있는지 봅니다")}</h1>
      {!profile ? (
        <p className="setup-lead">{t("그래픽카드와 메모리를 재는 중입니다. 아무것도 설치하거나 바꾸지 않습니다.")}</p>
      ) : (
        <>
          <p className="setup-lead">
            {rec?.mode === "local"
              ? rec.confidence === "external"
                ? t("이 PC 에서 모델을 돌릴 수 있습니다. 다만 우리가 직접 잰 모델은 이 카드에 안 들어가 외부 평가 모델을 권합니다.")
                : t("이 PC 에서 모델을 직접 돌릴 수 있습니다.")
              : rec?.mode === "satellite"
                ? t("이 PC 는 본체 PC 의 모델을 빌려 씁니다.")
                : rec?.mode === "too_small"
                  ? t("이 PC 의 그래픽카드 메모리로는 Sonjari가 권하는 모델이 여유 있게 안 들어갑니다.")
                  : t("이 PC 에는 AI 모델을 올릴 그래픽카드가 없습니다.")}
          </p>
          {(rec?.mode === "no_gpu" || rec?.mode === "too_small") && (
            <p className="setup-note">
              {t("Sonjari는 그래픽카드에서 도는 로컬 AI 를 씁니다 — 그래픽카드 메모리 8GB 이상을 권합니다. 다른 PC 에 설치해 쓰시거나, 받아 둔 모델이 있으면 오른쪽에서 직접 고를 수 있습니다.")}
            </p>
          )}
          {rec?.warnings.map((line) => (
            <p key={line} className="setup-warn">
              {line}
            </p>
          ))}
          {DRIVER_ACTION_STATES.has(profile.gpu_driver?.state ?? "") && (
            // 드라이버를 설치·켜기 한 뒤 앱을 다시 켜지 않고 확인한다(재시작이 필요한 상태는 PC 를 켠 뒤 앱이 다시 잰다).
            <button type="button" className="setup-btn-quiet" disabled={rechecking} onClick={onRecheck}>
              {rechecking ? t("다시 재는 중…") : t("그래픽카드 다시 확인")}
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function StepModelText({ rec, asked, said, onAsk }: { rec: Recommendation | null; asked: boolean; said: number; onAsk: () => void }) {
  const lines = rec ? [...rec.reasons.map((text) => ({ text, warn: false })), ...rec.warnings.map((text) => ({ text, warn: true }))] : [];
  return (
    <div className="setup-say">
      <h1>{t("쓸 모델을 고릅니다")}</h1>
      {/* ★ 2026-10-02 대표: 「손자리 추천이 어디까지 맞는지 모른 채 시작하는 게 제일 큰 리스크 — 마법사에서 깔고 가야 기준점이 잡힌다」.
          사용자 머릿속 기준은 클로드·챗GPT 다. 그것과 무엇이 다른지를 **고르기 전에** 말한다. 「클로드의 몇 %」는 잰 적이 없어 안 쓴다. */}
      <div className="setup-baseline" role="note">
        <p><b>{t("먼저 알아 두세요 — 이 PC 에 깔리는 모델은 클로드·챗GPT·제미나이 같은 큰 AI 가 아닙니다.")}</b></p>
        <ul>
          <li><b>{t("큰 AI 보다 나은 점")}</b> {t("· 아무리 써도 0원(미터기 없음) · 내 크롬으로 사이트 안까지 직접 열어 확인 · 한도에 안 걸림")}</li>
          <li><b>{t("큰 AI 보다 못한 점")}</b> {t("· 처음 보는 큰 코드, 깊은 기획, 폭넓은 상식은 큰 AI 가 낫습니다 — 그런 일은 클로드와 나눠 하세요(다음 단계에서 잇습니다)")}</li>
          <li><b>{t("그래서 손자리는")}</b> {t("· 확인한 것만 적고, 못 한 건 못 했다고 말합니다. 안 보고 답했으면 그렇다고 표시합니다")}</li>
        </ul>
      </div>
      <p className="setup-lead">{t("오른쪽에서 직접 고르셔도 되고, 이 PC 에 맞는 것을 골라 드릴 수도 있습니다.")}</p>
      {!asked ? (
        <button type="button" className="setup-btn-ask" disabled={!rec} onClick={onAsk}>
          <JarvisMark state="idle" connected size={20} />
          {t("이 PC 에 맞는 모델 추천받기")}
        </button>
      ) : (
        <div className="setup-assistant" role="log">
          {/* 로고 = 상태 표시등: 한 줄씩 말하는 동안 고리가 돌고, 다 말하면 멈춘다. */}
          <JarvisMark state={said < lines.length ? "working" : "idle"} connected size={22} />
          <div>
            {lines.slice(0, said).map((line) => (
              <p key={line.text} className={line.warn ? "setup-warn" : "setup-reason"}>
                {line.text}
              </p>
            ))}
            {rec?.confidence === "memory_only" && said >= lines.length && !lines.some((line) => /성공률|success rate/i.test(line.text)) && (
              <p className="setup-note">{t("이 설정에서 문서 만들기 성공률은 아직 안 쟀습니다. 메모리만 실제로 쟀습니다.")}</p>
            )}
            {rec?.confidence === "external" && said >= lines.length && (
              <p className="setup-note">{t("외부 평가 모델은 메모리도 받는 크기로 추정한 값입니다. 받은 뒤 실제로 한 번 돌려 확인하고 적용합니다.")}</p>
            )}
          </div>
        </div>
      )}
      {/* ★ 2026-10-02 대표: 큰 AI 보다 못한 점을 읽은 뒤 「그래도 이건 다르다」로 끝낸다. 「무제한」은 쓰지 않는다 — 속도는 그래픽카드에
          달렸고, 클로드에게 맡긴 일은 클로드 요금제에서 나간다. 사실만. */}
      <p className="setup-meter">
        <b>{t("이 PC 에서 도는 모델은 써도 요금이 붙지 않습니다 — 미터기가 없습니다.")}</b>{" "}
        {t("전기와 그래픽카드는 이 PC 의 것을 쓰고, 클로드에게 맡긴 일만 클로드 요금제에서 나갑니다.")}
      </p>
    </div>
  );
}

export type ReadinessRow = {
  id: "model" | "claude_desktop" | "claude_code";
  /** `done` 됐다 · `todo` 아직 · `skip` 없어도 된다(이 PC 에 그 도구가 없다). */
  state: "done" | "todo" | "skip";
  text: string;
  /** 그 자리에서 누를 수 있는 고침. 없으면 단추를 안 단다. */
  fix?: "model" | "restart_claude";
};

/**
 * 끝내기 전에 **다 됐는지 한 줄씩** (2026-10-12). 금색 단추만 따라 눌러 온 사람이 무엇이 됐고 무엇이 안 됐는지를
 * 끝에서 한눈에 본다 — 안 된 줄에는 그 자리에서 누를 단추를 단다. 모르는 것(아직 못 찾아본 도구)은 줄을 만들지 않는다.
 */
export function readinessRows({ modelName, modelCtx, scan }: {
  modelName: string; modelCtx: number; scan: ConnectScan | null;
}): ReadinessRow[] {
  const rows: ReadinessRow[] = [
    modelName
      ? { id: "model", state: "done", text: t("모델 · {0} · 창 {1}K 로 돌려 봤습니다", modelName, String(Math.round(modelCtx / 1024))) }
      : { id: "model", state: "todo", text: t("모델 · 아직 적용하지 않았습니다"), fix: "model" },
  ];
  const desktop = scan?.clients.find((client) => client.id === "claude_desktop");
  if (desktop) {
    if (!desktop.installed) rows.push({ id: "claude_desktop", state: "skip", text: t("Claude 앱 · 이 PC 에 없습니다(없어도 Sonjari는 됩니다)") });
    else if (desktop.registered) rows.push({ id: "claude_desktop", state: "done", text: t("Claude 앱 · 이었습니다") });
    else if (desktopAwaitingRestart(scan)) rows.push({ id: "claude_desktop", state: "todo", text: t("Claude 앱 · 켜져 있어 아직 못 이었습니다"), fix: "restart_claude" });
    else rows.push({ id: "claude_desktop", state: "todo", text: t("Claude 앱 · 아직 안 이었습니다 — 아래 「잇기」를 눌러 주세요") });
  }
  const code = scan?.clients.find((client) => client.id === "claude_code");
  if (code) {
    if (!code.installed || code.reason === "cli_missing") rows.push({ id: "claude_code", state: "skip", text: t("Claude Code · 찾지 못했습니다(쓰지 않으면 넘어가도 됩니다)") });
    else if (code.registered) rows.push({ id: "claude_code", state: "done", text: t("Claude Code · 이었습니다") });
    else rows.push({ id: "claude_code", state: "todo", text: t("Claude Code · 아직 안 이었습니다 — 아래 「잇기」를 눌러 주세요") });
  }
  return rows;
}

export function SetupReadiness({ rows, onFix }: { rows: ReadinessRow[]; onFix: (fix: NonNullable<ReadinessRow["fix"]>) => void }) {
  return (
    <ul className="setup-ready" aria-label={t("지금까지 된 것")}>
      {rows.map((row) => (
        <li key={row.id} className={`setup-ready-row is-${row.state}`}>
          <span className="setup-ready-mark" aria-hidden="true">{row.state === "done" ? "✓" : row.state === "todo" ? "·" : "–"}</span>
          <span className="setup-ready-text">{row.text}</span>
          {row.fix && (
            <button type="button" className="imp-link" onClick={() => onFix(row.fix!)}>
              {row.fix === "model" ? t("모델 고르러 가기") : t("지금 닫고 잇기")}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function StepConnectText({
  api,
  imp,
  pull,
  applied,
  applying,
  onAsk,
  onImportOpen,
  onScan,
}: {
  api: SetupApi | null;
  imp: ImportState;
  pull: PullState | null;
  applied: ApplyResult | null;
  applying: boolean;
  onAsk: (ask: string) => void;
  onImportOpen: (open: boolean) => void;
  onScan?: (scan: ConnectScan) => void;
}) {
  return (
    <div className="setup-say">
      <h1>{t("다른 도구와 잇고, 첫 부탁을 해 봅니다")}</h1>
      {/* ★ §55-13 기대 맞추기 1 (2026-10-01): 테스터가 좋아한 것은 「쓰던 클로드에서 그냥 시키는 것」이었고, 실망은 9B 에게 앱 통째를
          시킨 판이었다. 관계를 먼저 말한다 — 머리 쓰는 일은 클로드, 이 PC 에서 움직이는 일은 손자리. */}
      <p className="setup-lead setup-role">
        {t("손자리는")} <b>{t("이 PC 에서 찾고·읽고·돌리고·확인하는 손")}</b>{t("입니다. 새 코드 설계처럼 머리를 쓰는 일은 클로드에게 시키고, 클로드가 손자리를 같이 부르게 하세요 — 아래에서 잇습니다.")}
      </p>
      {(pull?.status === "pulling" || applying) && <ApplyLine pull={pull} applying={applying} applied={applied} api={api} />}
      {/* ★ 2026-09-16 화면 점검: 잇기가 지침 가져오기 **아래**에 있어 한참 내려야 보였다. 첫 실행에 꼭 할 일은
          잇기뿐이라 앞에 두고, 지침 가져오기는 접어 둔다. */}
      <ConnectPanel api={api} autoConnect onScan={onScan} />
      <details className="setup-more" onToggle={(event) => onImportOpen((event.target as HTMLDetailsElement).open)}>
        <summary>{t("다른 AI 에 적어 둔 지침도 가져오기 (선택)")}</summary>
        <ImportPanel imp={imp} />
      </details>
      <p className="setup-lead">{t("이런 부탁부터 해 보세요. 누르면 입력칸에 채워집니다.")}</p>
      <div className="setup-asks">
        {FIRST_ASKS.map((ask) => (
          <button key={ask} type="button" className="setup-ask" onClick={() => onAsk(ask)}>
            {ask}
          </button>
        ))}
      </div>
    </div>
  );
}

function GpuFixLine({ fix }: { fix: GpuFixResult | "running" | null }) {
  if (!fix) return null;
  if (fix === "running") {
    return <p className="setup-reason">{t("Ollama 가 NVIDIA 카드만 쓰도록 맞추고 다시 켜는 중입니다…")}</p>;
  }
  if (fix.ok) {
    return (
      <p className="setup-done">
        {fix.restarted === "not_running"
          ? t("Ollama 가 NVIDIA 카드만 쓰도록 맞췄습니다.")
          : t("Ollama 가 NVIDIA 카드만 쓰도록 맞추고 다시 켰습니다.")}
      </p>
    );
  }
  if (fix.error === "user_set_vulkan_on") {
    return <p className="setup-reason">{t("Ollama 그래픽 설정(Vulkan)을 직접 켜 두셔서 그대로 둡니다.")}</p>;
  }
  return (
    <p className="setup-warn" role="alert">
      {t("Ollama 그래픽카드 설정을 맞추지 못했습니다(")}{fix.error}{t("). 트레이의 Ollama 를 종료한 뒤 다시 눌러 주세요.")}
    </p>
  );
}

function gb(bytes: number): string {
  return (bytes / 2 ** 30).toFixed(1);
}

function pullLabel(pull: PullState): string {
  // 다 받은 뒤 확인하는 1~2분 동안 「받는 중 100%」가 남아 있었다(2026-10-01 AWS) — 지금 하는 일로 부른다.
  if (pull.phase === "verifying") return t("확인 중…");
  if (pull.phase === "finishing") return t("마무리 중…");
  if (!pull.total) return t("받을 준비 중…");
  return t("받는 중 {0}%", Math.round((pull.completed / pull.total) * 100));
}

/** 다 받은 뒤 확인·마무리 단계 — Ollama 가 진행률을 주지 않으니 **지어낸 %를 그리지 않는다.**
 *  흐르는 띠로 「일하는 중」을, 옆에 실제 경과 초를 보인다(2026-10-01 AWS, 대표: 「막대로 보게 해 주는 게 맞다」).
 *  전에는 100% 로 가득 찬 정지 막대라 멈춘 건지 도는 건지 알 수 없었다. */
function PullCheckLine({ phase, total }: { phase: "verifying" | "finishing"; total: number }) {
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  const verifying = phase === "verifying";
  return (
    <div className="setup-pull is-waiting" role="progressbar" aria-busy="true"
      aria-label={verifying ? t("받은 파일 확인 중") : t("받기 마무리 중")}>
      <span />
      <em>
        {verifying ? t("다 받았습니다 — 받은 파일이 온전한지 확인하는 중") : t("마무리하는 중")}
        <span className="setup-pull-size num">
          {seconds}{t("초째")}{verifying ? t(" · 보통 1~3분, 디스크가 느리면 더") : ""}{total ? ` · ${gb(total)}GB` : ""}
        </span>
      </em>
    </div>
  );
}

function RepairOllamaButton({ api }: { api: SetupApi }) {
  const [phase, setPhase] = useState<"idle" | "busy" | "done" | "failed">("idle");
  const [note, setNote] = useState("");
  const run = async () => {
    setPhase("busy");
    // ★ 「설치」가 아니라 「고치기」다 — 옛 자리에서 켜진 고장난 우리 서버를 끄고 옮겨서 켠다.
    //   설치로 불렀더니 `already_running` 으로 거절되고 버튼 옆에 그 낱말만 떴다(2026-09-18 노트북).
    const started = await api.ollamaRepair();
    if (!started.ok) {
      setPhase("failed");
      setNote(
        started.error === "not_ours"
          ? t("직접 설치하신 Ollama 가 돌고 있어 건드리지 않았습니다. 그 Ollama 를 최신으로 바꿔 주세요.")
          : started.error || t("시작하지 못했습니다"),
      );
      return;
    }
    // 끝났는지는 **새 서버가 러너까지 갖추고 떴는지**로 본다 — 「시작했다」는 증거가 아니다.
    for (let i = 0; i < 150; i += 1) {
      await new Promise((wake) => window.setTimeout(wake, 2000));
      const now = await api.ollamaStatus().catch(() => null);
      if (now?.install.phase === "error") {
        setPhase("failed");
        setNote(now.install.error || t("고치지 못했습니다"));
        return;
      }
      if (now && now.running && !now.runner_missing && now.install.phase === "ready") {
        setPhase("done");
        return;
      }
    }
    setPhase("failed");
    setNote(t("시간 안에 안 끝났습니다"));
  };
  if (phase === "done") return <p className="setup-done">{t("Ollama 를 고쳤습니다. 다시 「적용하기」를 눌러 주세요.")}</p>;
  return (
    <p className="setup-reason">
      <button type="button" className="setup-btn-go" disabled={phase === "busy"} onClick={() => void run()}>
        {phase === "busy" ? t("다시 설치하는 중…") : t("Ollama 다시 설치")}
      </button>
      {phase === "failed" ? <span className="setup-warn"> {note}</span> : null}
    </p>
  );
}


type ApplyLineProps = {
  pull: PullState | null; applying: boolean; applied: ApplyResult | null; api?: SetupApi | null;
  /** 못 올렸을 때의 두 길 — 같은 모델을 다시 재기 / 작은 모델로 가기. 안 주면 안내 글만 보인다. */
  onRetry?: () => void;
  onSmaller?: (smaller: NonNullable<WayOutInfo["smaller"]>) => void;
};

export function ApplyLine({ pull, applying, applied, api, onRetry, onSmaller }: ApplyLineProps) {
  if (applied && !applied.ok && hasWayOut(applied)
      && (applied.error === "model_not_fully_on_gpu" || applied.error === "model_out_of_memory")) {
    // ★ 2026-10-10 대표: 빨간 글 한 줄은 막다른 길이었다 — 닫을 것과 작은 모델, 두 길을 누를 수 있게 준다(WayOut.tsx).
    return <WayOut info={applied.way_out} busy={applying || pull?.status === "pulling"} onRetry={onRetry} onSmaller={onSmaller} />;
  }
  if (applied?.ok) {
    return (
      <>
        {/* ★ 2026-10-13 6GB 노트북: 「적용했습니다」 바로 아래 「4B · 32K 는 78.8% 만 올라가 적용하지 않았습니다」가 떠서
            서로 어긋나 보였다 — 실제로는 2B 로 내려 적용한 것이었다. 안 된 것을 먼저, 그 아래에 **무엇을** 적용했는지 적는다. */}
        {applied.warnings?.map((line) => (
          <p key={line} className="setup-warn">{line}</p>
        ))}
        <p className="setup-done">
          {applied.selection?.chat_model
            ? t("{0} 로 적용했습니다. 실제로 돌려 보니 초당",
                `${applied.selection.chat_model.replace(/^sonjari-text-/, "")} · ${ctxLabel(applied.selection.num_ctx)}`)
            : t("적용했습니다. 실제로 돌려 보니 초당")} <span className="num">{applied.bench?.tokens_per_sec}</span> {t("토큰입니다.")}
        </p>
        {/* ★ 2026-09-23: 컨텍스트는 우리 PC 에서 잰 표로 골랐다 — 이 PC 에선 추정이다. 적용한 자리에서 바로
            **실제로 올려 보고** 상한을 잰다. 처음 쓰는 사람에게 묻지 않고 재고, 온텔릭 값에 알아서 적용한다. */}
        {api && applied.selection?.chat_model ? (
          <ContextCeilingPanel api={api} model={applied.selection.chat_model} auto />
        ) : null}
      </>
    );
  }
  if (applied && !applied.ok) {
    // ★ 2026-09-18 노트북: 원인이 셋인데 문구는 하나였다 — Ollama 설치가 반쪽(`llama-server.exe` 없음)이었는데
    //   화면은 드라이버를 의심하라고 했다. 사람이 다음에 할 일이 원인마다 다르니 문구도 갈라야 한다.
    const reason =
      applied.error === "ollama_runner_missing"
        ? t("Ollama 설치가 덜 됐습니다 — 모델을 돌리는 파일이 없습니다. 다시 설치하면 이미 받아 둔 파일을 옮겨 쓰니 금방 끝납니다.")
        : applied.error === "model_out_of_memory"
          ? outOfMemoryReason(applied.gpu_users)
        : applied.error === "model_load_failed"
          ? t("Ollama 가 모델을 올리다 멈췄습니다. 기존 모델을 그대로 둡니다 — 아래 원문을 「문제 보내기」로 보내 주시면 원인을 찾겠습니다.")
        : applied.error === "model_load_timeout"
          ? t("모델을 올리는 데 시간이 너무 오래 걸립니다. 기존 모델을 그대로 둡니다 — 더 작은 모델이나 더 작은 컨텍스트를 골라 보세요.")
          : applied.error === "ollama_not_answering"
            ? t("Ollama 가 응답하지 않습니다. 기존 모델을 그대로 둡니다 — Ollama 가 켜져 있는지 확인해 주세요.")
            : applied.error === "model_did_not_generate"
              ? t("모델을 올렸지만 글자가 나오지 않았습니다. 기존 모델을 그대로 둡니다 — 그래픽카드 드라이버를 확인해 주세요.")
              : applied.error === "gpu_measurement_unavailable"
                ? pushedOutReason(applied.offload?.seen)
              : applied.error === "model_not_fully_on_gpu"
                ? t("작은 모델도 GPU에 전부 올라가지 않아 기존 선택을 유지했습니다. 다른 GPU 앱을 종료한 뒤 다시 시도해 주세요.")
              : applied.error === "no_tool_calling"
                ? t("이 모델은 도구 호출을 못 합니다 — Sonjari가 검색·파일 작업을 할 수 없어 적용하지 않았습니다.")
                : t("적용하지 못했습니다: {0}", applied.error);
    return (
      <>
        <p className="setup-warn" role="alert">{reason}</p>
        {/* ★ 고칠 버튼은 **문구 옆에** 둔다 (2026-09-18 노트북). 「아래 「Ollama 다시 설치」를 눌러 주세요」라고
            적어 놓고 그 버튼은 첫 단계 화면에만 있었다 — 누르라는 것이 그 화면에 없었다. */}
        {applied.error === "ollama_runner_missing" && api ? <RepairOllamaButton api={api} /> : null}
        {/* 무엇이 왔는지 그대로 한 줄 — 「드라이버 재설치」 같은 오탐을 다음 사람이 바로 가려낼 수 있게. */}
        {applied.bench?.error ? <p className="setup-reason setup-detail">{applied.bench.error}</p> : null}
      </>
    );
  }
  if (applying) return <p className="setup-reason">{t("모델을 올리고 실제로 한 번 돌려 보는 중입니다…")}</p>;
  if (pull?.status === "pulling") {
    // ★ 2026-09-29 밤 AWS: 다 받은 뒤 해시 확인 1~2분 동안 「받는 중 0% · 0.0/0.0GB」로 멈춘 듯 보였다(대표:
    //   「또 뭘 받나 봐」). 그 단계는 크기가 없으니 **무엇을 하는지**를 말한다. 막대는 가득 채워 둔다.
    if (pull.phase === "verifying" || pull.phase === "finishing") {
      return <PullCheckLine phase={pull.phase} total={pull.total} />;
    }
    // ★ 크기를 아직 모를 때(Ollama 가 목록을 받는 중) 0% 막대는 폭이 0 이라 **아무것도 안 보였다.**
    if (!pull.total) {
      return (
        <div className="setup-pull is-waiting" role="progressbar" aria-label={t("모델 받을 준비 중")} aria-busy="true">
          <span />
          <em>{t("받을 준비 중입니다 — 크기를 확인하고 있습니다")}</em>
        </div>
      );
    }
    const pct = Math.round((pull.completed / pull.total) * 100);
    return (
      <div className="setup-pull" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t("모델 받는 중")}>
        <span style={{ width: `${pct}%` }} />
        <em>
          {t("받는 중")} <span className="num">{pct}%</span>
          <span className="setup-pull-size num">{gb(pull.completed)} / {gb(pull.total)}GB</span>
        </em>
      </div>
    );
  }
  if (pull?.status === "failed") {
    return <PullFailure pull={pull} />;
  }
  return null;
}

/** 받기를 붙잡아 둔 동안의 한 줄. 설치 중이면 기다리라고, 아직 안 눌렀으면 바로 위 단추를 누르라고 말한다. */
function HeldLine({ ollama }: { ollama: OllamaStatus | null }) {
  const line = useRef<HTMLParagraphElement | null>(null);
  const installing = Boolean(ollama && !ollama.running && !["idle", "ready", "error"].includes(ollama.install.phase));
  useEffect(() => {
    line.current?.scrollIntoView?.({ block: "center" });
  }, [installing]);
  return installing ? (
    <p ref={line} className="setup-reason" role="status">{t("Ollama 를 설치하는 중입니다 — 끝나는 대로 이어서 받습니다. 이 화면을 그대로 두세요.")}</p>
  ) : (
    <p ref={line} className="setup-warn" role="status">
      {t("Ollama 가 아직 없어 받기를 시작하지 않았습니다 — 바로 위의 「Ollama 설치」를 누르면 끝나는 대로 이어서 받습니다. 이미 깔았다면 시작 메뉴에서 Ollama 를 켜 주세요.")}
    </p>
  );
}

/** 받기 실패 글. 바닥에 붙은 단추 줄에 가려 잘려 보였다(2026-10-06 첫 설치 화면) — 뜨는 순간 보이는 자리로 올린다. */
function PullFailure({ pull }: { pull: PullState }) {
  const line = useRef<HTMLParagraphElement | null>(null);
  useEffect(() => {
    line.current?.scrollIntoView?.({ block: "center" });
  }, [pull.reason, pull.detail]);
  return (
    <p ref={line} className="setup-warn" role="alert">{pullFailureText(pull)}</p>
  );
}

function Facts({ profile }: { profile: PcProfile | null }) {
  if (!profile) return <div className="setup-facts is-loading" aria-hidden="true" />;
  const rows: [string, string][] = [
    ...profile.gpus.map((gpu): [string, string] => [
      t("그래픽카드 {0}", gpu.index + 1),
      gpu.integrated
        ? t("{0} · 내장 그래픽", gpu.name)
        : t("{0} · {1}GB{2}", gpu.name.replace(/^NVIDIA GeForce /, ""), gpu.vram_total_gb.toFixed(0), gpu.source === "registry" ? "" : gpu.display_active ? t(" · 화면 출력") : ""),
    ]),
    [t("시스템 메모리"), profile.ram_gb ? `${profile.ram_gb.toFixed(0)}GB` : t("못 쟀습니다")],
    [t("디스크 여유"), profile.disk_free_gb !== null ? `${profile.disk_free_gb.toFixed(0)}GB` : t("못 쟀습니다")],
    ["Ollama", profile.ollama.reachable ? t("켜져 있음 · {0}", profile.ollama.version) : t("꺼져 있거나 설치되지 않았습니다")],
    [t("받아 둔 모델"), profile.ollama.installed.length ? t("{0}개", profile.ollama.installed.length) : t("없음")],
  ];
  return (
    <dl className="setup-facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * 카드 하나의 자리(DOM id). 같은 `family` 는 카드 하나라, 고른 크기가 바뀌어도 자리가 안 바뀌게 묶음으로 이름 붙인다.
 * `family` 가 빈 모델은 예전 그대로 `model-{key}`.
 */
export function modelCardId(model: Pick<CatalogModel, "key" | "family" | "status">): string {
  return model.family ? `model-family-${model.status}-${model.family}` : `model-${model.key}`;
}

export interface ModelGroup {
  id: string;
  /** 목록에서 가장 먼저 나온 변형 — 묶음이 아닐 때는 이 모델 하나가 카드다. */
  lead: CatalogModel;
  variants: CatalogModel[];
}

/**
 * 같은 `family`(같은 모델의 다른 크기)를 카드 하나로 묶는다. 묶음은 목록에서 **먼저 나온 변형의 자리**에 선다.
 * `family` 가 빈 모델(옛 백엔드는 이 칸을 아예 안 준다)은 혼자다 — 예전과 같은 카드 하나.
 */
export function groupFamilies(models: CatalogModel[]): ModelGroup[] {
  const groups: ModelGroup[] = [];
  const byFamily = new Map<string, ModelGroup>();
  for (const model of models) {
    const family = model.family ? `${model.status}:${model.family}` : "";
    const known = family ? byFamily.get(family) : undefined;
    if (known) {
      known.variants.push(model);
      continue;
    }
    const group: ModelGroup = { id: modelCardId(model), lead: model, variants: [model] };
    if (family) byFamily.set(family, group);
    groups.push(group);
  }
  return groups;
}

/** 배지는 카드에 하나 — 묶음 안에 추천이 여럿이면 앞선 것을 단다. */
const BADGE_ORDER: ModelPick["kind"][] = ["verified", "open_alternative", "external"];

/** 잰 모델 / 외부 평가 모델 두 무리의 카드 목록. 같은 `family` 는 카드 하나다. */
/**
 * 추천 문으로 들어온 사람에게 먼저 보일 모델 — **추천한 그 모델**과, 라이선스에 조건이 있을 때 같이 주는 「조건 없는 대안」.
 * 같은 묶음의 다른 크기는 넣지 않는다(고를 것을 줄이는 것이 이 화면의 일이다). 추천이 없으면 빈 목록.
 */
export function recommendedOnly(models: CatalogModel[], rec: Recommendation | null | undefined): CatalogModel[] {
  if (!rec?.model_key) return [];
  const alternatives = new Set((rec.picks ?? []).filter((pick) => pick.kind === "open_alternative").map((pick) => pick.model_key));
  const first = models.filter((model) => model.key === rec.model_key);
  return [...first, ...models.filter((model) => alternatives.has(model.key) && model.key !== rec.model_key)];
}

export function ModelGallery({
  models,
  pickKinds,
  usable,
  asked,
  pulse,
  onPulseEnd,
  picked,
  onPick,
  plain = false,
}: {
  /** 묶음 제목(「직접 잰 모델」 · 「외부 평가」) 없이 준 순서대로만 그린다 — 추천한 것만 보일 때. */
  plain?: boolean;
  /** 보일 순서대로. */
  models: CatalogModel[];
  pickKinds: Map<string, ModelPick["kind"]>;
  usable: number;
  /** 추천을 말로 옮긴 뒤에만 배지를 단다. */
  asked: boolean;
  /** 깜빡일 모델 key — 묶음 안의 key 여도 그 카드가 깜빡인다. */
  pulse: string;
  onPulseEnd: () => void;
  picked: { key: string; ctx: number; textOnly?: boolean } | null;
  onPick: (key: string, ctx: number, textOnly?: boolean) => void;
}) {
  if (plain) {
    return (
      <div className="setup-gallery is-plain">
        {groupFamilies(models).map((group) => {
          const keys = group.variants.map((variant) => variant.key);
          const kind = BADGE_ORDER.find((want) => keys.some((key) => pickKinds.get(key) === want)) ?? null;
          const mine = picked && keys.includes(picked.key) ? picked : null;
          return (
            <ModelCard
              key={group.id}
              model={group.lead}
              variants={group.variants}
              recommendedKey={keys.find((key) => pickKinds.get(key) === "verified")}
              usable={usable}
              recommended={asked ? kind : null}
              pulsing={keys.includes(pulse)}
              onPulseEnd={onPulseEnd}
              pickedKey={mine?.key ?? null}
              picked={mine?.ctx ?? null}
              pickedTextOnly={mine?.textOnly}
              onPick={(ctx, key, textOnly) => onPick(key, ctx, textOnly)}
            />
          );
        })}
      </div>
    );
  }
  return (
    <>
      {(["verified", "external"] as const).map((status) => (
        <div key={status} className="setup-gallery-group">
          <h3 className={`gallery-head is-${status}`}>
            {status === "verified" ? t("Sonjari가 직접 잰 모델") : t("외부 평가 · Sonjari 미검증")}
            <small>
              {status === "verified"
                ? t("같은 조사·문서 과제로 이 제품에서 실제로 돌려 본 모델")
                : t("우리가 시험하지 않았습니다. 공개 평가와 사용자 반응이 좋은 모델입니다")}
            </small>
          </h3>
          <div className="setup-gallery">
            {groupFamilies(models.filter((model) => model.status === status)).map((group) => {
              const keys = group.variants.map((variant) => variant.key);
              const kind = BADGE_ORDER.find((want) => keys.some((key) => pickKinds.get(key) === want)) ?? null;
              const mine = picked && keys.includes(picked.key) ? picked : null;
              return (
                <ModelCard
                  key={group.id}
                  model={group.lead}
                  variants={group.variants}
                  recommendedKey={keys.find((key) => pickKinds.get(key) === "verified")}
                  usable={usable}
                  recommended={asked ? kind : null}
                  pulsing={keys.includes(pulse)}
                  onPulseEnd={onPulseEnd}
                  pickedKey={mine?.key ?? null}
                  picked={mine?.ctx ?? null}
                  pickedTextOnly={mine?.textOnly}
                  onPick={(ctx, key, textOnly) => onPick(key, ctx, textOnly)}
                />
              );
            })}
          </div>
        </div>
      ))}
    </>
  );
}

type Fit = { ctx: number; gb: number; fits: boolean };

/** 창마다 차지할 메모리 — 큰 창부터. 들어가는지는 백엔드가 준 값(`vram_gb`)과 카드의 쓸 수 있는 메모리만 견준다. */
function contextsOf(model: CatalogModel, usable: number, saves = 0): Fit[] {
  // 「글만 읽기」(saves > 0)는 그 창을 **잰 값**이 있으면 그 값을 쓴다 — 추천이 말하는 숫자와 카드의 숫자가 같아야 한다.
  const lean = saves > 0 ? model.text_only_vram_gb ?? {} : {};
  return Object.entries(model.vram_gb)
    .map(([key, gb]) => ({ ctx: Number(key), gb: lean[key] ?? Math.max(0, gb - saves) }))
    .map(({ ctx, gb }) => ({ ctx, gb, fits: gb <= usable }))
    .sort((a, b) => b.ctx - a.ctx);
}

/** 「글만 읽기」를 골랐을 때 덜 쓰는 메모리(GB). 그림을 끌 수 없는 모델 · 그림을 읽게 둔 모델은 0. */
function savedBy(model: CatalogModel, textOnly: boolean): number {
  return textOnly && model.pictures_optional ? model.text_only_saves_gb ?? 0 : 0;
}

/** 처음 보이는 크기: 이 PC 추천 → 들어가는 것 가운데 가장 큰 것 → 첫째. `sizes` 는 받는 크기 오름차순. */
function firstSize(sizes: CatalogModel[], recommendedKey: string | undefined): CatalogModel {
  return sizes.find((size) => size.key === recommendedKey)
    ?? [...sizes].reverse().find((size) => size.fits)
    ?? sizes[0];
}

export function ModelCard({
  model,
  variants,
  recommendedKey,
  usable,
  recommended,
  pulsing,
  onPulseEnd,
  pickedKey,
  picked,
  pickedTextOnly,
  onPick,
}: {
  model: CatalogModel;
  /** 같은 `family` 의 크기들(이 모델 포함). 둘 이상일 때만 「크기 고르기」 줄을 그린다 — 없거나 하나면 예전 카드 그대로. */
  variants?: CatalogModel[];
  /** 묶음 안에서 백엔드가 이 PC 에 권한 크기의 key. 화면이 스스로 정하지 않는다. */
  recommendedKey?: string;
  usable: number;
  recommended: ModelPick["kind"] | null;
  pulsing: boolean;
  onPulseEnd: () => void;
  /** 묶음일 때: 바깥에서 고른 크기의 key(이 묶음 안일 때만). */
  pickedKey?: string | null;
  picked: number | null;
  /** 바깥에서 이 카드를 「글만 읽기」로 골라 두었나. 안 주면 그림을 읽는 것으로 시작한다. */
  pickedTextOnly?: boolean;
  /** 둘째 인자는 고른 모델의 key — 묶음 카드에서는 **고른 크기의 key** 다. 셋째는 「글만 읽기」로 골랐는가. */
  onPick: (ctx: number, key: string, textOnly?: boolean) => void;
}) {
  const sizes = variants && variants.length > 1 ? [...variants].sort((a, b) => a.download_gb - b.download_gb) : null;
  // 보고 있는 크기. 바깥에서 이 묶음의 다른 크기를 고르면(추천을 받아 고른 경우 등) 그리로 따라간다 —
  // 그리는 도중에 맞춰 한 번 깜빡이지 않게 한다.
  const [sizeKey, setSizeKey] = useState(pickedKey ?? "");
  const [seenPick, setSeenPick] = useState(pickedKey ?? null);
  if ((pickedKey ?? null) !== seenPick) {
    setSeenPick(pickedKey ?? null);
    if (pickedKey) setSizeKey(pickedKey);
  }
  const shown = sizes ? sizes.find((size) => size.key === sizeKey) ?? firstSize(sizes, recommendedKey) : model;
  // 묶음에서 고른 창은 **고른 크기의 것일 때만** 켜진 것으로 그린다.
  const pickedCtx = !sizes || pickedKey == null || pickedKey === shown.key ? picked : null;
  const external = shown.status === "external";
  // 그림 읽기 — 끄면 그림 부속만큼 메모리를 덜 써서 더 긴 창이 들어갈 수 있다. 그림을 끌 수 없는 모델에서는 늘 켜짐이다.
  const [textOnly, setTextOnly] = useState(Boolean(pickedTextOnly));
  // 추천은 카드가 그려진 **뒤에** 온다 — 추천이 「글만 읽기」면 그때 따라 바꾼다(2026-10-12, 16GB 급).
  useEffect(() => {
    if (pickedTextOnly !== undefined) setTextOnly(Boolean(pickedTextOnly));
  }, [pickedTextOnly]);
  const eyesOff = textOnly && Boolean(shown.pictures_optional);
  const contexts = contextsOf(shown, usable, savedBy(shown, eyesOff));
  const best = contexts.find((c) => c.fits);
  const chooseSize = (size: CatalogModel) => {
    if (size.key === shown.key && pickedCtx !== null) return;
    setSizeKey(size.key);
    // 크기를 바꾸면 고른 창도 그 크기에 들어가는 가장 큰 창으로 다시 맞춘다(위 `best` 와 같은 규칙).
    const roomiest = contextsOf(size, usable, savedBy(size, textOnly)).find((c) => c.fits);
    if (roomiest) onPick(roomiest.ctx, size.key, textOnly && Boolean(size.pictures_optional));
  };
  const chooseEyes = (off: boolean) => {
    if (off === eyesOff) return;
    setTextOnly(off);
    // 들어가는 창이 달라진다 — 고른 창이 그대로 들어가면 두고, 아니면 들어가는 가장 큰 창으로 맞춘다.
    const next = contextsOf(shown, usable, savedBy(shown, off));
    const kept = next.find((c) => c.ctx === pickedCtx && c.fits) ?? next.find((c) => c.fits);
    if (kept) onPick(kept.ctx, shown.key, off);
  };
  return (
    <article
      id={modelCardId(shown)}
      className={`model-card${pickedCtx ? " is-picked" : ""}${recommended === "verified" || recommended === "external" ? " is-recommended" : ""}${pulsing ? " is-pulsing" : ""}${!shown.fits ? " is-nofit" : ""}`}
      // 안쪽 칩의 강조가 끝난 것을 카드 깜빡임이 끝난 것으로 읽지 않는다.
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) onPulseEnd();
      }}
    >
      <header>
        <span className="model-mark" aria-hidden="true">
          {shown.vendor.slice(0, 1)}
        </span>
        <div>
          {/* 배지는 이름 **위** — 옆에 두면 이름이 두 줄로 깨졌다(2026-09-17 첫 실행 캡처 「Gemma 4 / 26B (QAT)」). */}
          {recommended === "verified" && <span className="model-badge">{t("Sonjari 추천 · 실측")}</span>}
          {recommended === "external" && <span className="model-badge is-external">{t("외부 평가 추천")}</span>}
          {recommended === "open_alternative" && <span className="model-badge is-open">{t("조건 없는 대안")}</span>}
          <h2>{sizes ? shown.family_name || shown.name : shown.name}</h2>
          <p>
            {shown.vendor} ·{" "}
            {shown.installed
              ? <span className="model-have">{t("받아 둠")}</span>
              : <>{t("받기")} <span className="num">{shown.download_gb.toFixed(1)}GB</span></>}
          </p>
        </div>
      </header>
      {/* 라이선스 한 줄. 조건이 붙은 라이선스는 「조건이 있다」는 사실과 원문 링크만 — 조건의 내용은 화면이 풀어 쓰지 않는다(§55-24 덧붙임 2). */}
      {shown.license && (
        <p className="model-license">
          <span className="model-license-label">{t("라이선스")}</span>
          <span className="model-license-name">{shown.license}</span>
          {shown.license_open === false && (
            // 표시와 링크는 한 덩어리로 넘어간다 — 좁은 카드에서 링크만 혼자 다음 줄에 떨어지면 무엇의 원문인지 끊긴다.
            <span className="model-license-more">
              <span className="model-license-terms">{t("사용 조건 있음")}</span>
              {shown.license_url && (
                <a href={shown.license_url} target="_blank" rel="noreferrer">{t("원문 보기")}</a>
              )}
            </span>
          )}
        </p>
      )}
      {/* 크기 고르기 — 같은 모델을 얼마나 눌러 담았는지. 칩에 받는 크기(GB)가 그대로 보인다. 양자화 코드는 title 로만. */}
      {sizes && (
        <div className="model-size">
          <span className="model-size-label">{t("크기 고르기")}</span>
          <div className="model-ctx model-size-chips" role="radiogroup" aria-label={t("{0} 크기 고르기", shown.family_name || shown.name)}>
            {sizes.map((size) => {
              const hint = [size.quant, size.fits ? "" : t("이 PC 에 안 들어갑니다")].filter(Boolean).join(" — ");
              return (
                <button
                  key={size.key}
                  type="button"
                  role="radio"
                  aria-checked={size.key === shown.key}
                  disabled={!size.fits}
                  className={`${size.key === shown.key ? "is-on" : ""}${size.key === recommendedKey ? " is-rec" : ""}`}
                  onClick={() => chooseSize(size)}
                  title={hint || undefined}
                >
                  {(size.quant_label || size.quant) && <>{size.quant_label || size.quant}{" · "}</>}
                  <span className="num">{size.download_gb.toFixed(1)}GB</span>
                  {size.key === recommendedKey && <span className="model-size-rec">{t("이 PC 추천")}</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {/* 그림 읽기 — 그림 부속을 따로 붙이는 모델에서만. 끄면 무엇을 내주고 무엇을 얻는지 한 줄로 같이 보인다(2026-10-12). */}
      {shown.pictures_optional && (
        <div className="model-eyes">
          <span className="model-eyes-label">{t("그림 읽기")}</span>
          <div className="model-eyes-chips" role="radiogroup" aria-label={t("{0} 그림 읽기", shown.family_name || shown.name)}>
            <button type="button" role="radio" aria-checked={!eyesOff} className={!eyesOff ? "is-on" : ""} onClick={() => chooseEyes(false)}>
              {t("그림도 읽기")}
            </button>
            <button type="button" role="radio" aria-checked={eyesOff} className={eyesOff ? "is-on" : ""} onClick={() => chooseEyes(true)}>
              {t("글만 읽기")}
              {(shown.text_only_saves_gb ?? 0) > 0 && <span className="num">−{(shown.text_only_saves_gb ?? 0).toFixed(1)}GB</span>}
            </button>
          </div>
          <p className="model-eyes-note">
            {eyesOff
              ? t("붙인 사진과 페이지 속 그림은 읽지 못합니다. 그만큼 그래픽카드 메모리를 덜 써서 더 긴 대화를 고를 수 있습니다.")
              : t("붙인 사진과 페이지 속 그림까지 읽습니다. 글만 읽기로 바꾸면 그래픽카드 메모리를 덜 씁니다.")}
          </p>
        </div>
      )}
      <p className="model-blurb">{shown.blurb}</p>
      {/* 잘하는 일·약한 일 — 잰 근거가 있을 때만(§55-13 기대 맞추기). 기대를 모델에 묶는다. */}
      {(shown.good_at || shown.weak_at) && (
        <dl className="model-fit-for">
          {shown.good_at && <div><dt>{t("잘함")}</dt><dd>{shown.good_at}</dd></div>}
          {shown.weak_at && <div className="is-weak"><dt>{t("약함")}</dt><dd>{shown.weak_at}</dd></div>}
        </dl>
      )}
      {external && (
        <div className="model-evidence">
          {/* 라이선스는 위의 라이선스 줄이 한 번 적는다 — 여기서 또 적지 않는다(2026-10-08). */}
          <p className="model-unverified">{t("Sonjari가 직접 시험한 모델은 아닙니다")}</p>
          <ul>
            {shown.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {shown.caution && <p className="model-caution">{shown.caution}</p>}
          <p className="model-links">
            {shown.links.map((link) => (
              <a key={link.url} href={link.url} target="_blank" rel="noreferrer">
                {link.label}
              </a>
            ))}
            <span>{t("확인 {0}", shown.checked_at)}</span>
          </p>
        </div>
      )}
      {/* ★ 2026-10-02 대표: 「대형 플랫폼 어떤 모델에 이 정도 근접 — 단 제작사 주장이니 참고용」. 우리가 잰 숫자(아래)와 섞지 않는다. */}
      {shown.vendor_claim && (
        <div className="model-claim">
          <p className="model-claim-head">{t("제작사 주장 · 참고용 (Sonjari가 잰 숫자가 아닙니다)")}</p>
          <p>{shown.vendor_claim}</p>
          {(shown.vendor_claim_links?.length ?? 0) > 0 && (
            <p className="model-links">
              {shown.vendor_claim_links!.map((link) => (
                <a key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.label}</a>
              ))}
              {shown.vendor_claim_checked && <span>{t("확인 {0}", shown.vendor_claim_checked)}</span>}
            </p>
          )}
        </div>
      )}
      {shown.chain && (
        <p className="model-proof">
          {t("조사해서 문서까지 만든 판")}{" "}
          <span className="num">
            {shown.chain.ok}/{shown.chain.total}
          </span>{" "}
          <span className="model-proof-ctx">({ctxLabel(shown.chain.ctx)} {t("에서 쟀음)")}</span>
        </p>
      )}
      <div className="model-ctx" role="radiogroup" aria-label={t("{0} 컨텍스트", shown.name)}>
        {contexts.map(({ ctx, gb, fits }) => (
          <button
            key={ctx}
            type="button"
            role="radio"
            aria-checked={pickedCtx === ctx}
            disabled={!fits}
            className={pickedCtx === ctx ? "is-on" : ""}
            onClick={() => onPick(ctx, shown.key, eyesOff)}
            title={t("{0}{1}GB{2}", external ? t("추정 ") : "", gb.toFixed(1), fits ? t(" 를 차지합니다") : t(" — 이 PC 에 안 들어갑니다"))}
          >
            {ctxLabel(ctx)}
            <span className="num">{external ? "≈" : ""}{gb.toFixed(1)}</span>
          </button>
        ))}
      </div>
      {!best && <p className="model-nofit">{t("이 PC 에는 어느 설정도 안 들어갑니다.")}</p>}
    </article>
  );
}

/**
 * 목록 밖 모델 (M3) — 이 PC Ollama 에 이미 있는 모델 전부 + 이름 직접 입력.
 *
 * 도구 호출 여부는 **Ollama 가 말한 것**(`/api/show` capabilities)이다. 우리 표나 웹 요약이 아니다
 * (웹 요약이 Gemma 4 의 tools 를 빠뜨린 날 실측). 도구 호출이 없으면 누를 수 없다 — 온텔릭이 일을 못 한다.
 */
function OtherModels({
  api,
  busy,
  pickedTag,
  onUse,
  onPull,
}: {
  api: SetupApi;
  busy: boolean;
  pickedTag: string;
  onUse: (tag: string) => void;
  onPull: (tag: string) => void;
}) {
  const [rows, setRows] = useState<InstalledModel[] | null>(null);
  const [typed, setTyped] = useState("");
  const loadRef = useRef(api);
  useEffect(() => {
    let alive = true;
    loadRef.current
      .installedModels()
      .then((view) => alive && setRows(view.models))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [busy]);
  const unlisted = (rows ?? []).filter((row) => row.status === "unlisted" && !row.embedding_only);
  return (
    <section className="other-models" aria-label={t("목록 밖 모델")}>
      <h3 className="gallery-head is-other">
        {t("다른 모델 쓰기")}
        <small>{t("이미 받아 둔 모델이나 Ollama 에 있는 모델 이름으로 직접 고릅니다 · Sonjari 미검증")}</small>
      </h3>
      {rows === null ? (
        <p className="setup-reason">{t("받아 둔 모델을 확인하는 중…")}</p>
      ) : unlisted.length === 0 ? (
        <p className="setup-reason">{t("목록 밖에서 받아 둔 모델이 없습니다.")}</p>
      ) : (
        <ul className="other-list">
          {unlisted.map((row) => (
            <li key={row.name} className={pickedTag === row.name ? "is-picked" : ""}>
              <span className="other-name">{row.name}</span>
              <span className="num">{row.size_gb ? `${row.size_gb.toFixed(1)}GB` : ""}</span>
              {row.tools ? (
                <button type="button" className="setup-btn-quiet" disabled={busy} onClick={() => onUse(row.name)}>
                  {t("이 모델 쓰기")}
                </button>
              ) : (
                <span className="other-no-tools" title={t("기능: {0}", row.capabilities.join(", ") || t("알 수 없음"))}>
                  {t("도구 호출 불가 — 작업에 못 씀")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <form
        className="other-typed"
        onSubmit={(event) => {
          event.preventDefault();
          if (typed.trim()) onPull(typed.trim());
        }}
      >
        <label htmlFor="other-tag">{t("모델 이름 직접 입력")}</label>
        <input id="other-tag" value={typed} placeholder={t("예: qwen3.5:4b · hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M")} spellCheck={false}
          onChange={(event) => setTyped(event.target.value)} />
        <button type="submit" className="setup-btn-quiet" disabled={busy || !typed.trim()}>
          {t("받고 확인하기")}
        </button>
        <p className="setup-note">{t("받은 뒤 도구 호출이 되는지 Ollama 에 묻고, 실제로 한 번 돌려 봐야 적용합니다. 크기는 받기를 시작하면 표시됩니다.")}</p>
      </form>
    </section>
  );
}

/** 메모리가 모자라 못 올렸을 때 할 말 (2026-10-01 밤 RTX 3050 6GB 노트북). 다시 설치는 소용없다 — 무엇을 닫으면 되는지 말한다. */
export function outOfMemoryReason(users?: { used_gb?: number; total_gb?: number; apps?: string[] }): string {
  const used = users?.used_gb != null && users?.total_gb ? t(" 지금 그래픽카드 메모리 {0}GB / {1}GB 를 다른 프로그램이 쓰고 있습니다.", users.used_gb, users.total_gb) : "";
  const apps = users?.apps?.length ? t(" 쓰는 프로그램: {0}.", users.apps.join(" · ")) : "";
  const ollama = users?.apps?.some((name) => /ollama|llama-server/i.test(name))
    ? t(" 예전에 깐 다른 Ollama(위성 등)가 모델을 쥐고 있을 수 있습니다 — 작업 표시줄 오른쪽 Ollama 아이콘에서 끄거나 그 프로그램을 지운 뒤")
    : t(" 게임·영상 편집처럼 그래픽카드를 쓰는 프로그램을 닫은 뒤");
  return t("그래픽카드 메모리가 모자라 모델을 올리지 못했습니다. 기존 모델을 그대로 둡니다 — 다시 설치해도 풀리지 않습니다.{0}{1}{2} 다시 적용해 주세요.", used, apps, ollama);
}
