/**
 * 3D 무대 — 손자리가 그림을 3D 로 만드는 동안 컴퓨터 칸에서 그것이 자라나는 모습을 보인다 (2026-11-14 대표 「무대가 핵심」).
 *
 * 장표 무대(`DeckStage`)와 같은 자리 · 같은 방식이다: 백엔드 `gen3d_stage` 알림이 오면 이 판의 주인공이 브라우저 대신 3D 다.
 * 클로드가 MCP 로 `gen_3d` 를 불러도 손자리 판이 생기므로 똑같이 뜬다(브라우저 일을 맡기면 크롬이 무대에 뜨는 것처럼).
 *
 * 화면 규칙(대표 11-14 「글이 많으면 별로 · 아이콘으로」 · tokens.css)
 * - 글은 상태 한 줄과 숫자뿐. 나머지는 아이콘이고 뜻은 마우스를 올리면 뜬다.
 * - 색은 뜻만: 보라 = 지금 일하는 칸 · 초록 = 끝난 칸 · 빨강 = 실패. 기계 쪽 찬 흑연 위, 깊이는 그림자.
 * - 남은 시간은 보이지 않는다. 단계마다 **실제 걸린 초**만(마우스를 올리면).
 * - 그림이 자라는 순서: 넣은 그림 → (회색 메시가 나오면) 회색 → 다 되면 색. 아직 없는 것을 있는 척 그리지 않는다.
 * - 다 만든 뒤에만 다음 행동(다시 굽기 · 블렌더로 · 프린트 파일)이 나타난다.
 */
import { t } from "../i18n";
import { Box, Check, Clock, Cpu, Hand, Printer, RefreshCw, RotateCw, Sparkles, Triangle, X } from "lucide-react";
import { createElement, useEffect, useMemo, useRef, useState } from "react";
import "./gen3dStage.css";
import { GEN3D_STEP_NAMES, fileName, formatFaces, formatGb, stepFill, type Gen3dState, type Gen3dSwap, type Gen3dTake } from "./gen3dState";

/** 판의 파일 하나를 화면이 띄울 수 있는 주소로(열쇠가 필요한 백엔드 파일은 blob 주소로 바꿔 준다). */
export type Gen3dLoad = (genId: string, name: string) => Promise<string>;
export type Gen3dAction = (kind: "again" | "blender" | "print", take: Gen3dTake) => void;

type Camera = "auto" | "me" | "claude";

type ModelViewerEl = HTMLElement & {
  loaded?: boolean;
  autoRotate: boolean;
  cameraOrbit: string;
  model?: { materials: Array<{ pbrMetallicRoughness: { baseColorTexture: { texture: unknown; setTexture: (texture: unknown) => void }; setBaseColorFactor: (rgba: number[]) => void } }> };
};

const RX = 290;
const RY = 30;
const point = (angle: number) => [RX * Math.cos(angle), RY * Math.sin(angle)];
const arc = (a0: number, a1: number) => {
  const [x0, y0] = point(a0);
  const [x1, y1] = point(a1);
  return `M${x0.toFixed(1)} ${y0.toFixed(1)}A${RX} ${RY} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
};

/** 바닥의 물레 고리 — 단계 수만큼 나눈 얇은 칸. 끝난 칸 초록 · 지금 칸 보라(걸음 비율만큼) · 남은 칸 흐림. */
function StepRing({ take }: { take: Gen3dTake }) {
  const total = Math.max(1, take.total);
  const partial = take.part ? take.part[0] / Math.max(1, take.part[1]) : undefined;
  const gap = 0.035;
  return (
    <svg className="g3-ring" viewBox="-300 -40 600 80" aria-hidden>
      {Array.from({ length: total }, (_, i) => {
        const index = i + 1;
        const a0 = -Math.PI / 2 + (i * 2 * Math.PI) / total + gap;
        const a1 = -Math.PI / 2 + ((i + 1) * 2 * Math.PI) / total - gap;
        const fill = stepFill(take, index, partial);
        const done = fill >= 1;
        const now = index === take.index && take.state === "running";
        const step = take.steps.find((row) => row.index === index);
        const label = `${GEN3D_STEP_NAMES[i] || step?.name || ""}${step?.sec != null ? ` · ${step.sec.toFixed(1)}초` : ""}`;
        return (
          <g key={index}>
            <path d={arc(a0, a1)} className={done ? "g3-seg done" : take.state === "failed" && index === take.index ? "g3-seg fail" : "g3-seg"}>
              <title>{label}</title>
            </path>
            {now && fill > 0 && <path d={arc(a0, a0 + (a1 - a0) * fill)} className="g3-seg now" />}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * 모델 갈아타기 장면 — 글 모델 칸이 아래로 스르륵 빠지며 메모리 막대가 비고, 3D 모델 칸이 아래에서 올라오며 막대가 찬다.
 * 막대 길이는 백엔드가 잰 MiB 만 쓴다. 못 재면 막대 대신 띠만 오간다(지어낸 % 금지).
 */
function SwapScene({ swap }: { swap: Gen3dSwap }) {
  const loadFrac = swap.loadedMib != null && swap.expectedMib ? Math.min(1, swap.loadedMib / swap.expectedMib) : null;
  const leaving = swap.phase === "unload";
  return (
    <div className="g3-swap" aria-label={t("모델 갈아타는 중")}>
      {swap.from && (
        <div className={`g3-chip from${leaving ? "" : " gone"}`}>
          <Cpu size={14} />
          <b>{swap.from}</b>
          <span className="g3-chip-bar"><i style={{ width: leaving ? "100%" : "0%" }} /></span>
          <em>{leaving && swap.fromMib ? formatGb(swap.fromMib) : ""}</em>
        </div>
      )}
      <div className={`g3-chip to${leaving ? " waiting" : " here"}`}>
        <Box size={14} />
        <b>{swap.to}</b>
        <span className={`g3-chip-bar${!leaving && loadFrac === null ? " is-waiting" : ""}`}>
          <i style={loadFrac !== null ? { width: `${Math.max(2, loadFrac * 100)}%` } : undefined} />
        </span>
        <em>{!leaving && swap.loadedMib != null && swap.expectedMib ? `${formatGb(swap.loadedMib)} / ${formatGb(swap.expectedMib)}` : ""}</em>
      </div>
    </div>
  );
}

function useTicker(on: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [on]);
}

/** 파일 이름 → 띄울 주소. 같은 이름은 한 번만 불러 온다. */
function useFileUrl(load: Gen3dLoad | undefined, genId: string, name: string | undefined) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    setUrl("");
    const file = fileName(name);
    if (!load || !file) return;
    let alive = true;
    void load(genId, file).then((value) => { if (alive) setUrl(value); }).catch(() => null);
    return () => { alive = false; };
  }, [load, genId, name]);
  return url;
}

export function Gen3dStage({ state, load, onAction, onPick }: {
  state: Gen3dState;
  load?: Gen3dLoad;
  onAction?: Gen3dAction;
  onPick?: (genId: string) => void;
}) {
  const take = state.takes.find((row) => row.genId === state.current) ?? state.takes[state.takes.length - 1];
  const running = take?.state === "running" || take?.state === "queued";
  useTicker(Boolean(running));
  const [camera, setCamera] = useState<Camera>("auto");
  const viewer = useRef<ModelViewerEl | null>(null);
  const [ready, setReady] = useState(false);

  // model-viewer 는 무겁다(three.js) — 3D 무대가 처음 뜰 때만 불러 온다.
  useEffect(() => {
    let alive = true;
    void import("@google/model-viewer").then(() => { if (alive) setReady(true); });
    return () => { alive = false; };
  }, []);

  const glbName = take?.state === "done" ? take.receipt?.files?.glb : take?.meshPreview;
  const glbUrl = useFileUrl(load, take?.genId ?? "", glbName);
  const imageUrl = useFileUrl(load, take?.genId ?? "", take?.image);
  const grey = take?.state !== "done";

  // 색 입히기 전에는 회색으로 — 같은 GLB 라도 아직 색 단계 전이면 색을 숨긴다.
  useEffect(() => {
    const el = viewer.current;
    if (!el) return;
    const paint = () => {
      try {
        for (const material of el.model?.materials ?? []) {
          const slot = material.pbrMetallicRoughness.baseColorTexture;
          const kept = material as unknown as { __kept?: unknown };
          if (grey) {
            if (kept.__kept === undefined) kept.__kept = slot.texture;
            slot.setTexture(null);
            material.pbrMetallicRoughness.setBaseColorFactor([0.55, 0.57, 0.6, 1]);
          } else if (kept.__kept !== undefined) {
            slot.setTexture(kept.__kept);
            material.pbrMetallicRoughness.setBaseColorFactor([1, 1, 1, 1]);
          }
        }
      } catch {
        /* 재질이 없는 메시 — 그대로 둔다 */
      }
    };
    if (el.loaded) paint();
    el.addEventListener("load", paint);
    return () => el.removeEventListener("load", paint);
  }, [grey, glbUrl, ready]);

  // 카메라 세 갈래. 사람이 끌면 그 순간 「내가」로 넘어간다(브라우저 무대의 넘겨받기와 같은 규칙).
  useEffect(() => {
    const el = viewer.current;
    if (!el) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.autoRotate = camera === "auto" && !still;
    if (camera === "claude") el.cameraOrbit = "0deg 84deg auto";
    const grab = (event: Event) => {
      if ((event as CustomEvent<{ source?: string }>).detail?.source === "user-interaction") setCamera("me");
    };
    el.addEventListener("camera-change", grab);
    return () => el.removeEventListener("camera-change", grab);
  }, [camera, glbUrl, ready]);

  const now = Date.now();
  const facts = useMemo(() => {
    if (!take) return [];
    const measured = take.receipt?.measured;
    if (take.state === "done") {
      return [
        { icon: <Clock size={14} />, text: measured?.sec ? `${Math.round(measured.sec)}초` : "", tip: t("걸린 시간") },
        { icon: <Cpu size={14} />, text: formatGb(measured?.vram_peak_mib ?? take.vramMib), tip: t("그래픽카드 메모리 최대") },
        { icon: <Triangle size={14} />, text: formatFaces(measured?.faces), tip: t("면 수") },
        take.receipt?.printable
          ? { icon: <Printer size={14} />, text: take.receipt.printable.ok ? t("가능") : t("확인 필요"), tip: take.receipt.printable.why?.join(" · ") || t("3D 프린트"), ok: take.receipt.printable.ok }
          : null,
      ].filter((row): row is NonNullable<typeof row> => Boolean(row && row.text));
    }
    return [
      { icon: <Clock size={14} />, text: `${Math.max(0, Math.round((now - take.startedAt) / 1000))}초`, tip: t("지금까지") },
      take.vramMib ? { icon: <Cpu size={14} />, text: formatGb(take.vramMib), tip: t("그래픽카드 메모리") } : null,
    ].filter((row): row is NonNullable<typeof row> => Boolean(row));
  }, [take, now]);

  if (!take) return null;

  const swapping = Boolean(take.swap && take.swap.phase !== "ready" && take.index === 0);
  const status = swapping
    ? <><span className="g3-dot work" />{take.swap!.phase === "unload" ? t("글 모델 내리는 중") : t("3D 모델 올리는 중")}</>
    : take.state === "done"
    ? <><span className="g3-dot done" />{t("다 만듦")}</>
    : take.state === "failed"
      ? <><span className="g3-dot fail" />{take.error || t("멈춤")}</>
      : <><span className="g3-dot work" />{take.name}{take.part ? ` ${take.part[0]}/${take.part[1]}` : ""}</>;

  const showModel = ready && Boolean(glbUrl);

  return (
    <section className="g3-stage" aria-label={t("3D 만들기")}>
      <div className="g3-wheel">
        <div className="g3-status" role="status">{status}</div>
        {imageUrl && showModel && <img className="g3-src" src={imageUrl} alt={t("넣은 그림")} />}

        {showModel
          ? createElement("model-viewer", {
              ref: viewer,
              class: "g3-viewer",
              src: glbUrl,
              "camera-controls": "",
              "auto-rotate": "",
              "rotation-per-second": "14deg",
              "camera-orbit": "0deg 80deg auto",
              "interaction-prompt": "none",
              "shadow-intensity": "0.7",
              exposure: "1",
              alt: t("만들고 있는 3D"),
            })
          : swapping
            ? <SwapScene swap={take.swap!} />
          : imageUrl
            ? <img className={`g3-plate${running ? " reading" : ""}`} src={imageUrl} alt={t("넣은 그림")} />
            : <div className="g3-plate empty" />}

        {showModel && (
          <div className="g3-tools" role="group" aria-label={t("카메라")}>
            {([
              ["auto", <RotateCw size={15} key="a" />, t("자동으로 돌기")],
              ["me", <Hand size={15} key="m" />, t("내가 돌려 보기")],
              ["claude", <Sparkles size={15} key="c" />, t("클로드가 보여 주기")],
            ] as const).map(([key, icon, label]) => (
              <button key={key} type="button" className="g3-tb" aria-pressed={camera === key} aria-label={label} data-tip={label} onClick={() => setCamera(key)}>
                {icon}
              </button>
            ))}
          </div>
        )}

        <StepRing take={take} />

        <div className="g3-facts">
          {facts.map((fact, i) => (
            <span key={i} className={"ok" in fact && fact.ok ? "ok" : undefined} title={fact.tip}>{fact.icon}{fact.text}</span>
          ))}
        </div>

        {take.state === "done" && onAction && (
          <div className="g3-acts">
            {take.res !== 1024 && (
              <button type="button" className="g3-tb big" aria-label={t("1024 로 다시 굽기")} data-tip={t("1024 로 다시 굽기")} onClick={() => onAction("again", take)}><RefreshCw size={15} /></button>
            )}
            <button type="button" className="g3-tb big" aria-label={t("블렌더로 보내기")} data-tip={t("블렌더로 보내기")} onClick={() => onAction("blender", take)}><Box size={15} /></button>
            {take.receipt?.printable?.ok && (
              <button type="button" className="g3-tb big" aria-label={t("프린트 파일(3MF)")} data-tip={t("프린트 파일(3MF)")} onClick={() => onAction("print", take)}><Printer size={15} /></button>
            )}
          </div>
        )}
      </div>

      {state.takes.length > 1 && (
        <div className="g3-takes" role="tablist" aria-label={t("판")}>
          {state.takes.map((row) => (
            <TakeThumb key={row.genId} take={row} load={load} on={row.genId === take.genId} onPick={onPick} />
          ))}
        </div>
      )}
    </section>
  );
}

function TakeThumb({ take, load, on, onPick }: { take: Gen3dTake; load?: Gen3dLoad; on: boolean; onPick?: (genId: string) => void }) {
  const url = useFileUrl(load, take.genId, take.receipt?.files?.preview?.[0] ?? take.image);
  const mark = take.state === "done" ? <Check size={10} /> : take.state === "failed" ? <X size={10} /> : null;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      className={`g3-take${on ? " on" : ""}${take.state === "running" || take.state === "queued" ? " wait" : ""}`}
      onClick={() => onPick?.(take.genId)}
      title={`${take.res ?? ""}`}
    >
      {url && <img src={url} alt="" />}
      <b>{take.res ?? ""}{mark}</b>
    </button>
  );
}
