/**
 * **자비스의 컴퓨터** — 오른쪽 칸 (R6 → P10·P11·P12 로 다시).
 *
 * ## 무엇이 달라졌나
 *
 * R6 까지 이 칸은 **상태**만 말했다: 지금 무슨 도구를 부르는지, 화면이 어떻게 생겼는지,
 * 시킨 것을 몇 개 채웠는지. 정작 자비스가 **만진 내용**은 한 글자도 없었다.
 *
 * 화면을 먼저 만들려다 알았다 — 내용이 여기까지 **오지를 않았다.** 이벤트로 오는
 * 장부는 200자에서 잘리고(`agent._step_evidence`) 파일 경로는 아예 빠져 있어서,
 * 파일을 읽어도 화면은 어느 파일인지조차 몰랐다. 그래서 백엔드에 관측 보관소를
 * 만들고(`observations.py`) 여기서 **걸음을 눌러 꺼내 본다.**
 *
 * ## 이 칸의 구조
 *
 *     머리말        무엇을 하는 중인가 · 몇 초 됐나
 *     걸음 눈금자   도구 호출 하나가 눈금 하나. 누르면 그때로 되감긴다
 *     뷰어          그 걸음이 본 것 — 코드·문서·표·화면·초안
 *     시킨 것       요구 대조표
 *
 * ## 규칙 (R6 에서 그대로 가져온다)
 *
 * **놀 때는 아예 없다.** 폭이 0 으로 접히고 대화가 화면을 다 쓴다. 뷰어가 생겼다고
 * 자리를 미리 차지하지 않는다.
 */
import { t } from "../i18n";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Brain, ChevronDown, Code2, Loader2, Maximize2, Minimize2, Monitor, Square, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { JarvisClient } from "../backend";
import { toolLabel } from "../trajectory";
import type { AnswerCheck } from "./answerChecks";
import type { AgentProgress, BrowserFrame, BrowserStatus, PlanItem, WorkspaceMode } from "../types";
import { ObservationView, Empty } from "./ObservationView";
import { StepScrubber } from "./StepScrubber";
import {
  TABS, followingStep, latestOfTab, stepBeside, tabCounts, tabOf,
  type Observation, type StepRow, type TabKey,
} from "./observation";
import { agoLabel, screenProblem, screenWarnings, seamLabel, shortUrl, staleLabel } from "./screen";
import { EditReplay } from "./EditReplay";
import { CodePreview } from "./CodePreview";
import { LiveStage } from "./LiveStage";
import { paneWidth } from "./jobs";
import { UnityStageView } from "./UnityEditorSection";

const FRAME_INTERVAL_MS = 1_500;
const STATUS_INTERVAL_MS = 10_000;
const STEPS_INTERVAL_MS = 2_000;
const ease = [0.22, 1, 0.36, 1] as const;

export function ComputerPane(props: {
  client: JarvisClient | null;
  mode?: WorkspaceMode;
  /** 창 틀의 모드(사람이 고른 탭). 칸의 **폭**은 이것을 따른다 — `mode` 는 무엇을 보일지만 정한다. 안 주면 `mode` 와 같다. */
  frameMode?: WorkspaceMode;
  codeWorkspace?: string;
  /** 열려 있는가. 일이 도는 동안만 참이고, 닫히면 아무것도 안 가져온다. */
  open: boolean;
  /** 지금 도는 작업이 있는가. 폴링이 도는 조건이다. */
  live: boolean;
  /** 지금 작업. 걸음을 어느 잡에서 가져올지가 여기서 갈린다. */
  jobId: string;
  progress: AgentProgress[];
  plan: PlanItem[];
  /** 마지막 답에 붙어 온 「확인할 것」 — 본문에서 떼어 여기 노란 줄로 둔다. */
  checks?: AnswerCheck[];
  elapsedLabel: string;
  /** 모델의 사고 원문. 비어 있으면 칸 자체가 안 뜬다. */
  thinkingText?: string;
  /** 같은 사고의 한국어판. 정찰기가 뒤따라 보내 준다 — 늦거나 안 올 수 있다. */
  thinkingKo?: string;
  /** 좁은 창에서 대화를 덮고 있을 때만 준다 — 칸 스스로 닫는 버튼이 뜬다. */
  onClose?: () => void;
  /** 지금 승인을 기다리는 건의 action_id. 그 초안을 보고 있을 때만 버튼이 뜬다 (P12). */
  approvalActionId?: string;
  onApprove?: (approve: boolean) => void;
  onCancel: () => void;
  onCodeFeedback?: (prompt: string) => void;
  /** 브라우저 무대 모드 — 칸이 넓어지고 크롬 화면이 주인공이 된다(2026-09-24). */
  stage?: boolean;
  /** 무대 모드일 때 칸의 폭(px). 칸 폭이 그리드의 오른쪽 열을 정한다. */
  stageWidth?: number;
  /** 머리말의 「크게/작게」. 없으면 버튼이 안 뜬다. */
  onStageToggle?: () => void;
  /** 사람이 무대에서 크롬을 넘겨받았나. 넘겨받은 동안 무대를 접지 않으려고 위로 알린다. */
  onControlChange?: (active: boolean) => void;
}) {
  const { client, open, live, jobId, progress, plan } = props;
  const checks = props.checks ?? [];
  const codeMode = props.mode === "code";
  const still = useReducedMotion();
  // 어느 쪽으로 되감았는지. 뷰어가 들어오는 방향이 여기서 정해진다.
  const previous = useRef<number | null>(null);

  const [frame, setFrame] = useState<BrowserFrame | null>(null);
  const [status, setStatus] = useState<BrowserStatus | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const imageUrlRef = useRef("");

  const [rows, setRows] = useState<StepRow[]>([]);
  /** 사람이 직접 고른 걸음. null 이면 **따라가는 중**(마지막 걸음/지금). */
  const [pinned, setPinned] = useState<number | null>(null);
  /** 지금 열어 놓은 것: 걸음 번호, 또는 `null` = 「지금 화면」. */
  const [selected, setSelected] = useState<number | null>(null);
  const [item, setItem] = useState<Observation | null>(null);
  const [loading, setLoading] = useState(false);
  const [missing, setMissing] = useState("");
  // ★ 2026-09-28 제품 결정: 코드 모드의 주인공은 **작업 근거**다. 제품 화면은 띄운 프론트가 없으면 「기다리고 있습니다」 빈 칸뿐이었다.
  //   에이전트가 실제로 프론트를 띄운(local_preview_page 성공) 그때만 제품 화면으로 넘어간다 — 아래 agentPreviewUrl 효과.
  const [codeView, setCodeView] = useState<"preview" | "evidence">("evidence");
  const [agentPreviewUrl, setAgentPreviewUrl] = useState("");
  /** 무대 스트림이 도는 중이면 예전 1.5초 스크린샷은 안 당긴다 — 브라우저 일꾼 줄을 괜히 붙들지 않게. */
  const [streaming, setStreaming] = useState(false);
  const [controlling, setControlling] = useState(false);
  const { onControlChange } = props;
  const handleControl = useCallback((active: boolean) => {
    setControlling(active);
    onControlChange?.(active);
  }, [onControlChange]);

  useEffect(() => () => {
    if (imageUrlRef.current) URL.revokeObjectURL(imageUrlRef.current);
  }, []);

  // 잡이 바뀌면 전부 새로. 이전 잡의 걸음이 남아 있으면 **다른 작업의 근거**를
  // 지금 작업의 근거인 것처럼 보여 주게 된다.
  useEffect(() => {
    setRows([]); setPinned(null); setSelected(null); setItem(null); setMissing("");
    setAgentPreviewUrl("");
  }, [jobId]);

  // ── 화면 한 장 ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!client || !open || codeMode) return;
    let alive = true;
    const pullFrame = async () => {
      const next = await client.getBrowserFrame();
      if (!alive) return;
      // ★ 2026-09-23: 브라우저가 앞 동작 중이라 **이번 한 장만** 못 찍었으면 직전 그림을 지우지 않는다.
      //   예전엔 그림 없는 한 장이 덮어써서 노란 「지금 다른 동작을 하는 중입니다」 상자가 그림 자리를 차지했고,
      //   사람은 그걸 「시킨 것 말고 딴짓을 하나?」로 읽었다(스토어 촬영 중 제품 검토). 그림은 두고 이유만 바꾼다.
      if (!next.blob && next.reason.includes("browser_busy")) {
        setFrame((previous) => (previous?.blob ? { ...previous, reason: next.reason, fresh: false } : next));
        return;
      }
      setFrame(next);
      if (!next.blob) return;
      const url = URL.createObjectURL(next.blob);
      if (imageUrlRef.current) URL.revokeObjectURL(imageUrlRef.current);
      imageUrlRef.current = url;
      setImageUrl(url);
    };
    const pullStatus = async () => {
      try {
        const next = await client.getBrowserStatus();
        if (alive) setStatus(next);
      } catch {
        // 상태를 못 읽어도 그림은 그림대로 보여 준다.
      }
    };
    if (!streaming) void pullFrame();
    void pullStatus();
    if (!live) return () => { alive = false; };
    const frameTimer = window.setInterval(() => { if (!streaming) void pullFrame(); }, FRAME_INTERVAL_MS);
    const statusTimer = window.setInterval(() => void pullStatus(), STATUS_INTERVAL_MS);
    return () => {
      alive = false;
      window.clearInterval(frameTimer);
      window.clearInterval(statusTimer);
    };
  }, [client, open, live, codeMode, streaming]);

  // ── 걸음 목록 ─────────────────────────────────────────────────────────
  // 목록은 가볍다(본문이 없다). 그래서 도는 동안 2초마다 물어봐도 된다.
  useEffect(() => {
    if (!client || !open || !jobId) return;
    let alive = true;
    const pull = async () => {
      try {
        const next = await client.listSteps(jobId);
        if (alive) setRows(next.items ?? []);
      } catch {
        // 걸음을 못 읽어도 이 칸의 나머지는 산다.
      }
    };
    void pull();
    if (!live) return () => { alive = false; };
    const timer = window.setInterval(() => void pull(), STEPS_INTERVAL_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, [client, open, jobId, live]);

  // 에이전트가 local_preview_page 로 만든 주소를 사람의 제품 화면에도 연결한다.
  // 목록에는 주소가 없으므로 그 한 걸음의 관측만 연다.
  const previewStep = [...rows].reverse().find((row) => row.tool === "local_preview_page" && row.ok)?.step;
  useEffect(() => {
    if (!client || !codeMode || !jobId || previewStep === undefined) return;
    let alive = true;
    void client.getStep(jobId, previewStep).then((observation) => {
      if (!alive) return;
      const url = String(observation?.payload?.url ?? "");
      setAgentPreviewUrl(url);
      // 새로 띄운 걸음마다 한 번 넘긴다. 사람이 다시 근거로 돌아가면 다음 미리보기 걸음 전까지 안 끌고 간다.
      if (url) setCodeView("preview");
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [client, codeMode, jobId, previewStep]);

  // 따라가기: 사람이 고른 것이 없으면 마지막 걸음을 본다. 단 **도는 중에는**
  // 「지금 화면」이 기본이다 — 일하는 걸 보고 싶은 것이 먼저다.
  useEffect(() => {
    if (pinned !== null) {
      setSelected(pinned);
      return;
    }
    setSelected(live ? null : followingStep(rows, null));
  }, [rows, pinned, live]);

  // ── 본문으로 열 걸음 ──────────────────────────────────────────────────
  //
  // ★ 「지금」을 보고 있어도 **마지막 걸음의 내용**을 연다 (2026-08-20).
  //
  // 예전에는 화면이냐 본문이냐 하나만 나왔다: 「지금」을 누르면 그림만, 3걸음을
  // 누르면 글만. 그래서 "자비스가 지금 뭘 보고 있나"를 알려면 둘 사이를 계속
  // 오가야 했고, 도는 동안에는 기본이 「지금」이라 **본문을 아예 못 봤다.**
  const latest = rows.length ? rows[rows.length - 1].step : null;
  const bodyStep = selected ?? latest;

  useEffect(() => {
    if (!client || bodyStep === null || !jobId) { setItem(null); setMissing(""); return; }
    let alive = true;
    setLoading(true);
    void client.getStep(jobId, bodyStep).then((next) => {
      if (!alive) return;
      setLoading(false);
      setItem(next);
      setMissing(next ? "" : t("이 걸음의 내용이 남아 있지 않습니다. 오래된 작업은 원문을 버립니다."));
    });
    return () => { alive = false; };
  }, [client, jobId, bodyStep]);

  // ← → 로 걸음 되감기. 이 칸이 열려 있을 때만 듣는다.
  const move = useCallback((delta: number) => {
    setPinned((current) => stepBeside(rows, current ?? followingStep(rows, null), delta));
  }, [rows]);

  useEffect(() => {
    if (!open || !rows.length) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
      if (event.key === "ArrowLeft") { move(-1); event.preventDefault(); }
      if (event.key === "ArrowRight") { move(1); event.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, rows.length, move]);

  // 밑줄 자리. 활성 칸의 실제 위치를 재서 옮긴다.
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const [underline, setUnderline] = useState<{ transform: string; width: number; opacity: number }>({
    transform: "translateX(0px)", width: 0, opacity: 0,
  });

  const counts = useMemo(() => tabCounts(rows), [rows]);
  const activeTab: TabKey | null = useMemo(() => {
    // 본문이 열려 있으면 그 칸에 밑줄이 간다 — 「지금」이어도 마찬가지다.
    // 예전에는 selected 만 봐서, 도는 동안 내내 밑줄이 꺼져 있었다.
    if (bodyStep === null) return null;
    const row = rows.find((entry) => entry.step === bodyStep);
    return row ? tabOf(row.kind) : null;
  }, [rows, bodyStep]);

  useLayoutEffect(() => {
    const bar = tabsRef.current;
    if (!bar) return;
    const active = activeTab ? bar.querySelector<HTMLElement>(`[data-tab="${activeTab}"]`) : null;
    // 고른 칸이 없으면(=「지금」을 보는 중) 밑줄을 숨긴다. 아무 데나 두면 그 칸을
    // 보고 있다고 거짓말한다.
    if (!active) { setUnderline((value) => ({ ...value, opacity: 0 })); return; }
    setUnderline({ transform: `translateX(${active.offsetLeft}px)`, width: active.offsetWidth, opacity: 1 });
  }, [activeTab, rows.length, open]);

  const seam = seamLabel(selected, latest, live);
  const problem = screenProblem(status, frame);
  const warnings = screenWarnings(status);
  const stale = staleLabel(frame);
  const where = frame?.title || shortUrl(frame?.pageUrl ?? "");
  const step = progress[progress.length - 1];
  // 게임 팩 2단계(2026-09-27): 온텔릭이 열린 유니티 에디터를 다루는 판이면 브라우저 대신 유니티 창을 비춘다.
  const unityEditorJob = rows.some((row) => String(row.tool ?? "").startsWith("unity_editor_"))
    || String(step?.tool ?? "").startsWith("unity_editor_");
  const met = plan.filter((entry) => entry.met).length;
  // ★ 무대의 주인공은 **지금 걸음**을 따라간다 (2026-09-30, 대표: 「3걸음까지는 브라우저를 쓰는데 그다음부터는 안 쓸 때는?」).
  //   무대(넓은 칸)는 일이 끝날 때까지 유지한다 — 걸음마다 폭이 튀면 정신없다. 대신 **그 안의 크기**를 바꾼다:
  //   지금 걸음이 브라우저면 브라우저가 크게, 문서·표·코드·파일 걸음이면 브라우저는 위로 작게 접히고 그 걸음이 만진
  //   것이 본문을 차지한다. 예전에는 무대에서 브라우저가 늘 컸다 — 4걸음째 문서를 쓰는 동안 멈춘 웹 화면이 주인공이었다.
  //   사람이 크롬을 넘겨받은 동안은 무조건 크게 — 사람이 일하는 자리를 줄이면 안 된다.
  const bodyRow = rows.find((row) => row.step === bodyStep);
  const liveTool = live && selected === null ? String(step?.tool ?? "") : "";
  const browserFocus = bodyStep === null
    || controlling
    || /^(browser_|site_)/.test(liveTool)
    || (!liveTool && bodyRow?.kind === "page");

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          className={`computer-pane${codeMode ? " code-pane" : ""}`}
          initial={{ width: 0, opacity: 0 }}
          animate={{
            // 폭은 창 틀을 따른다 — 맡긴 일의 모드가 틀과 다르면 칸 절반이 비었다(`paneWidth` 의 설명).
            width: paneWidth({ frame: props.frameMode ?? props.mode ?? "cowork", stage: Boolean(props.stage), stageWidth: props.stageWidth }),
            opacity: 1,
          }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.42, ease }}
        >
          {/* ★ 연출은 **한 번의 순서**로 (2026-08-23).
              효과를 여기저기 흩뿌리면 화면이 산만해지고 AI 가 만든 티가 난다.
              이 칸이 열릴 때 위에서 아래로 **한 번** 차례로 내려앉는다 —
              머리말 → 눈금자 → 갈래 → 본문 → 바닥 레일. 기계가 켜지는 순서다.

              칸이 도로 접힐 때는 순서 없이 함께 사라진다. 나갈 때까지 줄 세우면
              닫는 동작이 굼떠 보인다.

              `prefers-reduced-motion` 이면 전부 0초 — 켜고 끄는 것이 아니라
              같은 순서를 **즉시** 밟는다. */}
          <motion.div
            className="computer-inner"
            variants={{
              hidden: {},
              shown: { transition: { staggerChildren: still ? 0 : 0.045, delayChildren: still ? 0 : 0.06 } },
            }}
            initial="hidden"
            animate="shown"
          >
            <motion.header className="computer-head" variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}>
              <span className="computer-mark">{codeMode ? <Code2 size={13} /> : <Monitor size={13} />}</span>
              <strong>{codeMode ? t("코드 작업공간") : t("Sonjari의 컴퓨터")}</strong>
              <span className="computer-elapsed">{props.elapsedLabel}</span>
              {!codeMode && props.onStageToggle && (
                <button
                  type="button"
                  className="computer-stage-toggle"
                  onClick={props.onStageToggle}
                  aria-label={props.stage ? t("브라우저 화면 작게 보기") : t("브라우저 화면 크게 보기")}
                  title={props.stage ? t("작게 보기") : t("크게 보기")}
                >
                  {props.stage ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                </button>
              )}
              {props.onClose && (
                <button type="button" className="computer-close" onClick={props.onClose} aria-label={t("컴퓨터 칸 닫기")} title={t("닫기")}>
                  <X size={14} />
                </button>
              )}
            </motion.header>

            {/* 지금 무엇을 하는가 — 한 줄. 걸음 목록 전체는 답 옆의 궤적에 남는다.
                ★ 2026-08-23: 끝난 판에서 **세 줄이 서로 다른 말을 했다.**
                  "끝났습니다" · "도구를 고르는 중" · "0걸음" — 그런데 눈금자에는
                  걸음이 둘 있었다. `progress` 는 판이 끝나면 비워지는데 그걸 그대로
                  세고 있었고, 도구 줄은 끝났다는 사실을 몰랐다.
                  끝난 뒤에는 **보관소에 남은 걸음 수**(rows)를 말한다. */}
            {codeMode ? (
              <>
                <CodeOperation
                  live={live}
                  progress={step}
                  item={item}
                  workspace={props.codeWorkspace ?? ""}
                />
                <ThinkingTrace text={props.thinkingText ?? ""} ko={props.thinkingKo ?? ""} live={live} client={client} mode="code" />
              </>
            ) : (
              <motion.div className="computer-now" variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}>
                <p>{step?.message ?? (live ? t("판단하고 있습니다") : t("끝났습니다"))}</p>
                <small>
                  {step?.tool
                    ? toolLabel(step.tool)
                    : live
                      ? t("도구를 고르는 중")
                      : rows.length ? t("남긴 것을 볼 수 있습니다") : t("도구를 쓰지 않았습니다")}
                </small>
              </motion.div>
            )}

            {/* ★ 계기를 박스로 세웠다가 뺐다 (2026-08-23).
                26px 숫자를 테 두른 칸 셋에 넣었더니 **대시보드 클리셰**가 됐다.
                게다가 그 값은 대부분 0이다 — 정보가 없는 숫자를 크게 쓴 것뿐.

                덜어내는 쪽이 맞다. 숫자는 조용한 한 줄로 두고, 시각적 무게는
                **걸음 눈금자**가 진다. 이 칸의 서명은 눈금자지 계기판이 아니다. */}
            {(!codeMode || live || rows.length > 0 || plan.length > 0) && (
              <motion.p
                className="computer-tally"
                variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}
              >
                <span>{(live ? progress.length : rows.length) || 0}{t("걸음")}</span>
                <span>{props.elapsedLabel}</span>
                {plan.length > 0 && (
                  <span className={met === plan.length ? "met" : ""}>{t("시킨 것")} {met}/{plan.length}</span>
                )}
              </motion.p>
            )}

            {codeMode && (
              <div className="code-view-switch" role="tablist" aria-label={t("코드 작업 보기")}>
                <button type="button" role="tab" aria-selected={codeView === "preview"} className={codeView === "preview" ? "on" : ""} onClick={() => setCodeView("preview")}>{t("제품 화면")}</button>
                <button type="button" role="tab" aria-selected={codeView === "evidence"} className={codeView === "evidence" ? "on" : ""} onClick={() => setCodeView("evidence")}>{t("작업 근거")}{rows.length ? ` ${rows.length}` : ""}</button>
              </div>
            )}

            {(!codeMode || codeView === "evidence") && <StepScrubber
              rows={rows}
              selected={selected}
              live={live}
              onSelect={(next) => setPinned(next === null && !live ? null : next)}
            />}

            {/* 칸 — 누르면 그 칸의 마지막 걸음으로 간다. 빈 칸은 안 눌린다. */}
            {rows.length > 0 && (!codeMode || codeView === "evidence") && (
              <div className="obs-tabs" role="tablist" aria-label={t("본 것 갈래")} ref={tabsRef}>
                {TABS.map((tab) => {
                  const count = counts[tab.key];
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      data-tab={tab.key}
                      role="tab"
                      aria-selected={activeTab === tab.key}
                      className={`obs-tab${activeTab === tab.key ? " on" : ""}`}
                      disabled={!count}
                      onClick={() => {
                        const target = latestOfTab(rows, tab.key);
                        if (target !== null) setPinned(target);
                      }}
                    >
                      {tab.label}{count ? <em>{count}</em> : null}
                    </button>
                  );
                })}
                {/* 밑줄은 **하나**다. 칸 사이를 미끄러져 어디서 어디로 갔는지 남긴다.
                    자리는 직접 잰다 — layoutId 투영은 이 칸처럼 자주 다시 그려지는
                    곳에서 한 칸 뒤에 멈췄다(2026-08-19 실측). */}
                <span className="obs-tab-underline" style={underline} aria-hidden />
              </div>
            )}

            <motion.div className="computer-body" variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}>
              {unityEditorJob && client && (
                // 유니티 일은 코드 모드든 코워크든 유니티 화면이 주인공이다 — 무대가 펴지면 그 칸을 비율 그대로 채운다.
                <UnityStageView client={client} />
              )}
              {codeMode && (
                <div hidden={codeView !== "preview" || unityEditorJob} className="code-preview-host">
                  <CodePreview workspace={props.codeWorkspace ?? ""} agentUrl={agentPreviewUrl} onFeedback={(prompt) => props.onCodeFeedback?.(prompt)} />
                </div>
              )}
              {(!codeMode || codeView === "evidence") && <>
              {/* ★ 화면은 **언제나 지금**이다 (2026-08-20).
                  관측 보관소에 그림이 없으므로(`observations.shape` 는 글·표·초안만
                  저장한다) 지난 걸음의 화면은 존재하지 않는다. 그런데 3걸음의 글
                  위에 지금 화면을 얹으면 사람은 그것을 3걸음의 화면으로 읽는다 —
                  그래서 아래 이음선이 **본문이 지금이 아니면 그렇다고 적는다.**

                  `compact` 는 본문이 **있을 자리인가**로 정한다. `loading` 에 걸면
                  걸음을 고를 때마다 그림이 컸다 작았다 튄다 — 읽던 자리가 발밑에서
                  움직이는 것이 이 칸에서 제일 나쁜 일이다. */}
              {!unityEditorJob && !codeMode && (
                <LiveStage
                  client={client}
                  active={open}
                  stage={Boolean(props.stage)}
                  caption={live ? step?.message ?? "" : ""}
                  where={where}
                  compact={bodyStep !== null && !(props.stage && browserFocus)}
                  onStreamingChange={setStreaming}
                  onControlChange={handleControl}
                  fallback={
                    <LiveScreen
                      where={where}
                      stale={stale}
                      problem={problem}
                      imageUrl={imageUrl}
                      pageUrl={frame?.pageUrl}
                      compact={bodyStep !== null}
                    />
                  }
                />
              )}

              {seam && (
                <p className={`obs-seam${seam.rewound ? " rewound" : ""}`}>
                  <span>{seam.label}</span>
                  {seam.rewound && item ? <em>{agoLabel(item.at * 1000, Date.now())}</em> : null}
                </p>
              )}

              {codeMode && bodyStep === null && !loading ? (
                <Empty
                  title={props.codeWorkspace ? t("저장소를 읽을 준비가 됐습니다") : t("프로젝트 폴더를 지정해 주세요")}
                  detail={props.codeWorkspace
                    ? t("작업을 보내면 루트 구조를 먼저 인덱싱하고, 읽은 파일과 수정 줄을 이곳에 순서대로 보여 줍니다.")
                    : t("왼쪽 상단에 허용된 로컬 프로젝트 경로를 입력하면 Code 모드를 시작할 수 있습니다.")}
                />
              ) : loading && !item ? (
                <div className="obs-loading"><Loader2 size={15} className="spin" /> {t("그때 것을 가져오는 중입니다")}</div>
              ) : item ? (
                <ObservationView
                  item={item}
                  direction={directionOf(previous, item.step)}
                  approvalActionId={props.approvalActionId}
                  onApprove={props.onApprove}
                />
              ) : bodyStep !== null ? (
                <Empty title={t("내용이 남아 있지 않습니다")} detail={missing} />
              ) : null}
              </>}
            </motion.div>

            {/* ★ 바닥 레일 — 빈 공간을 **정보로** 채운다 (2026-08-23).
                본문이 짧으면 이 칸 아래가 통째로 비어 있었다(사용자 화면에서
                절반이 여백). 장식으로 메우지 않고, 지금 보고 있는 것이 **어디서
                온 것인지**를 바닥에 고정한다.

                "근거가 있는 답"이 이 제품의 핵심 주장이다. 그 주장이 화면에서도
                늘 보이는 편이 맞다 — 답을 읽는 내내 출처가 눈에 있어야 한다. */}
            <motion.div className={`computer-rail${live ? " live" : ""}`} variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}>
              <span className="dot" aria-hidden />
              <b title={railWhere(item, codeMode ? props.codeWorkspace ?? "" : where)}>
                {railWhere(item, codeMode ? props.codeWorkspace ?? "" : where) || t("아직 본 것이 없습니다")}
              </b>
              <em>{item ? t("{0}번째 걸음", item.step) : ""}</em>
            </motion.div>

            {!codeMode && warnings.map((line) => (
              <p className="agent-screen-warn" key={line} role="status">
                <TriangleAlert size={12} />{line}
              </p>
            ))}

            {/* 남은 것 — 몇 분씩 걸릴 때 이게 보이는 것과 안 보이는 것의 차이가 크다. */}
            {(plan.length > 0 || checks.length > 0) && (
              <div className="computer-plan">
                {plan.length > 0 && <p>{t("시킨 것")} <b>{met}/{plan.length}</b></p>}
                <ul>
                  {plan.map((entry) => (
                    <li key={entry.label} className={entry.met ? "met" : ""}>
                      <span>{entry.label}</span>
                      <em>{entry.saw}</em>
                    </li>
                  ))}
                  {/* 확인하지 못한 것 — 초록 줄(확인된 것) 아래에 노란 줄로 (2026-10-13 대표). 답 본문에는 안 싣는다.
                      줄에 올리면 서버가 보낸 문장이 그대로 보인다. */}
                  {checks.map((check) => (
                    <li key={check.detail} className="unsure" title={check.detail}>
                      <span>{check.title}{check.what ? ` — ${check.what}` : ""}</span>
                      <em>{t("확인 안 됨")}</em>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {live && (
              <button type="button" className="now-stop" onClick={props.onCancel}>
                <Square size={12} fill="currentColor" /> {t("여기서 멈추기")}
              </button>
            )}
          </motion.div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/** 「지금」 — 브라우저가 지금 보고 있는 화면. 이유 있는 빈 상태는 `screen.ts` 가 정한다. */
function LiveScreen(props: {
  where: string;
  stale: string;
  problem: ReturnType<typeof screenProblem>;
  imageUrl: string;
  pageUrl?: string;
  /** 아래에 본문이 있는가. 있으면 그림이 자리를 양보한다 — 둘 다 반쪽이면 둘 다 못 읽는다. */
  compact?: boolean;
}) {
  return (
    <div className={`computer-screen${props.compact ? " strip" : ""}`}>
      {props.where && (
        <p className="computer-where" title={props.pageUrl}>
          {props.where}{props.stale && <em>{props.stale}</em>}
        </p>
      )}
      {props.problem ? (
        <div className={`agent-screen-empty tone-${props.problem.tone}`}>
          <strong>{props.problem.title}</strong>
          <p>{props.problem.detail}</p>
        </div>
      ) : (
        <img src={props.imageUrl} alt={props.where ? t("{0} 화면", props.where) : t("Sonjari가 보고 있는 화면")} />
      )}
    </div>
  );
}

/**
 * 이번에 고른 걸음이 앞인가 뒤인가. 부수 효과로 마지막 걸음을 기억한다.
 *
 * 렌더 중에 ref 를 건드리는 것이 마음에 걸리지만, 방향은 **그리는 순간**에만
 * 쓰이고 다시 그릴 이유를 만들지 않아야 한다(상태로 두면 무한 루프가 된다).
 */
function directionOf(previous: { current: number | null }, step: number): number {
  const before = previous.current;
  previous.current = step;
  if (before === null || before === step) return 0;
  return step > before ? 1 : -1;
}

export default ComputerPane;

/**
 * 바닥 레일에 적을 **한 줄 출처**.
 *
 * 열어 놓은 걸음이 있으면 그 근거가 어디서 왔는지(경로·주소)를 말하고, 없으면
 * 지금 브라우저가 보고 있는 곳을 말한다. 둘 다 없으면 빈 문자열이다 -
 * 없는 것을 있는 척하지 않는다.
 */
function railWhere(item: Observation | null, live: string): string {
  if (item) {
    const payload = item.payload as Record<string, unknown>;
    const where = String(
      payload.path || payload.url || item.arguments?.path || item.arguments?.url || "",
    );
    return where || toolLabel(item.tool);
  }
  return live;
}

/**
 * 코드 모드의 작업 척추.
 *
 * 여섯 신호를 여섯 칸짜리 상태판으로 펼치지 않는다. 지금 성립한 근거만 한 축에
 * 붙인다. 읽지 않은 파일, 정하지 않은 명령처럼 **없는 정보는 그리지 않는다.**
 */
/** 모델이 무슨 생각으로 그 손을 골랐나 — **원문 그대로.**
 *
 * 2026-08-29. 지금까지 이 칸은 "판단하고 있습니다" 한 줄이 몇 분씩 떠 있었다.
 * 원문은 `on_chunk` 까지 오고 있었는데 글자 수만 세고 버렸다(`agent._model_message`).
 *
 * ## 왜 펼쳐 두고, 왜 자동으로 따라가나
 *
 * 코워크에서는 기본으로 펼친다. Code에서는 작업 근거·제품 화면을 먼저 볼 수 있도록
 * 접어 두되, 생각의 길이와 진행 여부는 머리말에 계속 보인다.
 *
 * 대신 **답이 아니라 과정**이라는 것은 자리와 생김새로 말한다 — 답 자리가 아닌
 * 작업공간 칸, 등폭·낮은 대비·작은 글씨, 그리고 언제든 접을 수 있음.
 *
 * 펴 놓은 동안에는 맨 아래를 자동으로 따라간다. 다만 사람이 위로 올려 읽고
 * 있으면 **따라가지 않는다.** 읽는 중에 끌려 내려가는 것만큼 방해되는 것이 없다.
 *
 * 흐르는 글자를 답처럼 보이게 하지 않는다. 등폭·낮은 대비·작은 글씨로 두어
 * 「이것은 근거가 아니라 과정」임을 생김새로 말한다.
 */
// 생각 번역 방식은 PC 마다 하나라 한 번만 묻는다(정찰기 있으면 live, 없으면 after).
let translationMode: Promise<"live" | "after"> | null = null;
function thinkingTranslationMode(client: JarvisClient): Promise<"live" | "after"> {
  translationMode ??= client
    .getHealth()
    .then((health) => health.thinking_translation ?? "live")
    .catch(() => {
      translationMode = null;
      return "live" as const;
    });
  return translationMode;
}

export function ThinkingTrace({
  text,
  ko,
  live,
  client = null,
  mode = "cowork",
}: {
  text: string;
  ko: string;
  live: boolean;
  client?: JarvisClient | null;
  mode?: WorkspaceMode;
}) {
  const [open, setOpen] = useState(mode !== "code");
  // ★ 그래픽카드 한 장 PC (인수인계 H3): 실시간 번역이 없다. 원문과 안내를 보여 주고, 판이 끝나면
  //   사람이 눌러 주 모델로 옮긴다. 판 중에는 주 모델을 안 건드린다 — 버튼도 판이 끝나야 뜬다.
  const [after, setAfter] = useState(false);
  const [afterKo, setAfterKo] = useState("");
  const [translating, setTranslating] = useState(false);
  const [translateError, setTranslateError] = useState("");

  useEffect(() => {
    if (!client) return;
    let alive = true;
    void thinkingTranslationMode(client).then((value) => {
      if (alive) setAfter(value === "after");
    });
    return () => {
      alive = false;
    };
  }, [client]);

  // 새 판이 시작되면 앞 판의 번역을 버린다.
  useEffect(() => {
    if (live) {
      setAfterKo("");
      setTranslateError("");
    }
  }, [live]);

  const translateNow = async () => {
    if (!client || translating) return;
    setTranslating(true);
    setTranslateError("");
    try {
      const result = await client.translateThinking(text, mode);
      setAfterKo(result.text);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setTranslateError(message.includes("busy") ? t("Sonjari가 일하는 중이라 지금은 옮기지 않습니다. 끝난 뒤 다시 눌러 주세요.") : t("옮기지 못했습니다. 원문을 보여 드립니다."));
    } finally {
      setTranslating(false);
    }
  };
  // 한국어가 오면 그것을 보여 준다. 원문은 버리지 않는다 — 식별자를 확인하거나
  // 번역이 이상할 때 대조할 것이 있어야 한다.
  const [raw, setRaw] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  // 사람이 위로 올렸는가. 올렸으면 자동으로 안 내린다.
  const followRef = useRef(true);

  useEffect(() => {
    const box = boxRef.current;
    if (!open || !box || !followRef.current) return;
    box.scrollTop = box.scrollHeight;
  }, [text, open]);

  if (!text) return null;

  // 번역이 아직 안 왔으면 원문을 보여 준다. 빈 칸을 두고 기다리게 하지 않는다.
  const koText = ko.trim() ? ko : afterKo;
  const translated = koText.trim().length > 0;
  const shown = !raw && translated ? koText : text;
  const chars = shown.length;
  return (
    <div className={`code-think${open ? " open" : ""}`}>
      <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <Brain size={12} />
        <span>{t("생각")}</span>
        <small>{live ? t("이어지는 중") : t("끝")} · {chars.toLocaleString()}{t("자")}</small>
        {translated && (
          <span
            className="code-think-raw"
            role="button"
            tabIndex={0}
            onClick={(event) => { event.stopPropagation(); setRaw((value) => !value); }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.stopPropagation();
                setRaw((value) => !value);
              }
            }}
          >
            {raw ? t("번역") : t("원문")}
          </span>
        )}
        <ChevronDown size={13} className="code-think-caret" />
      </button>
      {open && (
        <div
          className="code-think-body"
          ref={boxRef}
          onScroll={(event) => {
            const box = event.currentTarget;
            // 바닥에서 24px 안이면 따라가는 것으로 본다.
            followRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
          }}
        >
          {after && !translated && (
            <p className="code-think-note">
              {t("생각은 영어로 나옵니다.")}
              {!live && client && (
                <button type="button" className="code-think-raw" onClick={() => void translateNow()} disabled={translating}>
                  {translating ? t("옮기는 중…") : t("한국어로 보기")}
                </button>
              )}
            </p>
          )}
          {translateError && <p className="code-think-note">{translateError}</p>}
          <pre>{shown}</pre>
        </div>
      )}
    </div>
  );
}

function CodeOperation(props: {
  live: boolean;
  progress?: AgentProgress;
  item: Observation | null;
  workspace: string;
}) {
  if (!props.live && !props.progress && !props.item) return null;

  const progressTool = props.progress?.tool || "";
  const tool = progressTool || props.item?.tool || "";
  const observationMatches = !progressTool || progressTool === props.item?.tool;
  const payload = ((observationMatches ? props.item?.payload : null) ?? {}) as Record<string, unknown>;
  const args = ((observationMatches ? props.item?.arguments : null) ?? {}) as Record<string, unknown>;
  const path = String(payload.path || args.path || "");
  const lineStart = Number(payload.line_start || 0);
  const lineEnd = Number(payload.line_end || 0);
  const location = path
    ? `${path}${lineStart ? `:${lineStart}${lineEnd > lineStart ? `–${lineEnd}` : ""}` : ""}`
    : tool === "local_index_codebase" && props.workspace ? props.workspace : "";
  const commandValue = payload.command;
  const command = Array.isArray(commandValue)
    ? commandValue.map(String).join(" ")
    : typeof commandValue === "string" ? commandValue : "";
  const verified = payload.verified;
  const outcome = verified === true
    ? t("통과{0}", payload.exit_code !== undefined ? ` · exit ${String(payload.exit_code)}` : "")
    : verified === false
      ? t("실패{0}", payload.exit_code !== undefined ? ` · exit ${String(payload.exit_code)}` : "")
      : "";
  const next = verified === false
    ? t("실패 출력을 읽고 원인을 고친 뒤 같은 검증을 다시 실행합니다")
    : verified === true
      ? t("변경 경계와 남은 회귀를 확인합니다")
      : tool === "local_index_codebase"
        ? t("관련 심볼의 실제 파일을 엽니다")
        : t("근거가 모이면 최소 패치를 적용합니다");
  const phase = codePhaseLabel(tool, verified);
  const message = props.progress?.message
    || (props.live ? t("{0} 단계를 진행하고 있습니다", phase) : t("{0} 기록", phase));
  // 바꾼 자리를 되짚어 보여 줄 재료. 없으면 안 그린다 — 없는 걸 있는 척하지 않는다.
  const preview = payload.edit_preview as
    | { start_line?: number; removed?: string[]; added?: string[]; truncated?: boolean; added_count?: number }
    | undefined;
  const locationLabel = ["local_write_file", "local_apply_edit"].includes(tool)
    ? t("바꾼 곳")
    : tool === "local_index_codebase" ? t("범위") : t("읽은 곳");
  const facts = [
    location ? { label: locationLabel, value: location, tone: "" } : null,
    command ? { label: t("검증"), value: command, tone: "" } : null,
    outcome ? { label: t("결과"), value: outcome, tone: verified === true ? "pass" : "fail" } : null,
  ].filter((fact): fact is { label: string; value: string; tone: string } => Boolean(fact));
  const tone = verified === false ? "fail" : verified === true ? "pass" : "active";

  return (
    <motion.section
      className={`code-operation tone-${tone}${props.live ? " live" : ""}`}
      variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}
      aria-label={t("코드 작업 판단 근거 · {0}", phase)}
    >
      <span className="code-operation-spine" aria-hidden><i /></span>
      <p className="code-operation-phase">
        <b>{phase}</b>
        <span>{props.live ? t("진행 중") : t("남긴 기록")}</span>
      </p>
      <p className="code-operation-title">{message}</p>
      {facts.length > 0 && (
        <dl className="code-operation-facts">
          {facts.map((fact) => (
            <div key={`${fact.label}-${fact.value}`} className={fact.tone ? `tone-${fact.tone}` : ""}>
              <dt>{fact.label}</dt>
              <dd title={fact.value}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {preview && <EditReplay preview={preview} path={path} />}
      {(props.live || verified !== undefined) && (
        <p className="code-operation-next"><span>{t("다음")}</span>{next}</p>
      )}
    </motion.section>
  );
}

function codePhaseLabel(tool: string, verified: unknown): string {
  if (tool === "local_index_codebase") return t("색인");
  if (tool.startsWith("browser_") || tool.startsWith("web_") || tool.includes("site_search")) return t("조사");
  if (["local_list_directory", "local_search_files", "local_read_text_file"].includes(tool)) return t("읽기");
  if (["local_write_file", "local_apply_edit"].includes(tool)) return t("패치");
  if (tool === "local_run_project_command") return verified === false ? t("수리") : t("검증");
  if (tool.includes("prepare") || tool.includes("draft")) return t("초안");
  return t("계획");
}
