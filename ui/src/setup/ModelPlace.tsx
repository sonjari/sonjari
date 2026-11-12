import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { isMac } from "../platform";
import type { FoundHome, ModelPlaceView, SetupApi } from "./setupApi";
import { friendlyModelName, modelSource } from "./modelNames";
import { OutsideHomeMac } from "./OutsideHome";
import { openExternalUrl } from "../backend";
import "../workspace/whatsNewShow.css";
import "./modelPlace.css";

/**
 * 모델 자리 — [Mac | Satellite] (설계_짝짓기_모델자리_2026-11-03 §9 · 11-04 대표).
 *
 * 대표(11-04): 「이 맥이 아니라 Mac, 위성은 영어로만(Satellite) · 단추가 너무 커서 짜증난다 · 작게 · Satellite 누르면 쓰는 법 쇼에서
 * 클로드와 손자리가 이어지는 것처럼 조화롭고 한몸처럼 보이게 · 위성이 됐다는 것도 알아야 한다」.
 *
 * - 단추: 높이 24 · 글자 12 의 한 묶음. 고른 쪽만 보라로 채운다. 이름표 · 설명 줄 없음.
 * - Satellite 면 아래에 **연결 띠** — 쓰는 법 쇼의 실(`wns-thread`)과 구슬(`wns-bead`)을 그대로 쓴다.
 *   찾는 중(점선 깜빡) · 짝 코드(실 반쯤 + 숫자 6칸) · 연결됨(꽉 찬 실 · 초록 점) · 끊김(실이 끊기고 회색).
 *   구슬은 **이 맥이 집 PC 로 모델을 실제로 부를 때만**(`home_llm_call`) 갔다가 돌아온다 — 꾸밈으로 돌리지 않는다.
 * - 집 PC 를 아직 모르는 맥에서 Satellite 를 누르면 그 자리에서 찾기 → 짝 코드 → 연결(옛 「집 PC 빌려 쓰기」 흐름을 띠 안으로).
 * - 바꾸면 다시 켜지 않는다 — 다음 모델 호출부터. 일하는 중이면 그 일이 끝난 뒤.
 * - 화면 말: Mac(윈도우 자식이면 PC) · Satellite · 집 PC 이름. 「위성 · 본체 · 포트 · 토큰」은 쓰지 않는다(§3-3).
 */

/** 백엔드 `home_llm_call` 을 화면 사건으로 넘긴 이름(WorkspaceApp). detail: { phase: "start" | "end" }. */
export const HOME_LLM_EVENT = "sonjari:home-llm";

export const HERE = isMac ? "Mac" : "PC";

export interface PlaceState {
  view: ModelPlaceView | null;
  load: () => Promise<void>;
  setView: (next: ModelPlaceView | null) => void;
}

/** 자리 읽기 — 칩(위쪽 표시)과 막대가 같은 답을 나눠 쓴다(집 PC 를 두 번 묻지 않게). */
export function useModelPlace(api: SetupApi | null): PlaceState {
  const [view, setView] = useState<ModelPlaceView | null>(null);
  const load = useCallback(async () => {
    if (!api?.modelPlace) return;
    try {
      setView(await api.modelPlace());
    } catch {
      setView(null);
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  return { view, load, setView };
}

/** 칩에 붙는 작은 표시 — Mac 「●」 · Satellite 「●━●」 · 끊김 「●┄○」.
 *  ★ 11-08 대표 「이모티콘 말고 그림으로」: 노란 카드 대신 같은 그림말로 상태를 더 말한다 —
 *  켜는 중 「● 숨쉬기」 · 이 기기 문제 「○」(호박색) · 집 PC 에 모델이 안 떠 있음 「●━○」(호박색). */
export type PlaceKind = "here" | "here-wait" | "here-off" | "satellite" | "down" | "far-missing";

/** 자리(`placeKind`)에 건강 판정(`readinessProblem` 의 kind)을 얹는다. */
export function statusKind(base: PlaceKind, problem: string | null | undefined): PlaceKind {
  switch (problem) {
    case "ollama_starting": return "here-wait";
    case "ollama_down":
    case "model_missing": return "here-off";
    case "home_unreachable": return "down";
    case "home_model_missing": return "far-missing";
    default: return base;
  }
}

export function placeKind(view: ModelPlaceView | null): PlaceKind {
  if (!view || view.place !== "home_pc") return "here";
  return view.home && !view.home.reachable ? "down" : "satellite";
}

export function PlaceMark({ kind }: { kind: PlaceKind }) {
  const gid = useId();
  if (kind === "here" || kind === "here-wait" || kind === "here-off") {
    return <i className={`place-mark place-mark-${kind}`} aria-hidden />;
  }
  return (
    <svg className={`place-mark place-mark-${kind}`} viewBox="0 0 22 8" width="22" height="8" aria-hidden>
      <defs>
        {/* 가로선 하나에 상자 기준(objectBoundingBox) 그라데이션을 걸면 높이가 0 이라 선이 안 그려진다 — 좌표로 준다. */}
        <linearGradient id={gid} gradientUnits="userSpaceOnUse" x1="4" x2="18" y1="0" y2="0">
          <stop offset="0" stopColor="rgb(var(--origin-claude))" />
          <stop offset="1" stopColor="rgb(var(--brand-bright))" />
        </linearGradient>
      </defs>
      <line x1="4" y1="4" x2="18" y2="4" className="place-mark-wire" stroke={kind === "satellite" || kind === "far-missing" ? `url(#${gid})` : undefined} />
      <circle cx="4" cy="4" r="2.6" className="place-mark-a" />
      <circle cx="18" cy="4" r="2.6" className="place-mark-b" />
    </svg>
  );
}

type Flow =
  | { phase: "off" }
  | { phase: "finding" }
  | { phase: "pick"; found: FoundHome[] }
  | { phase: "notfound"; why: string }
  | { phase: "code"; home: FoundHome; error: string }
  | { phase: "sending"; home: FoundHome; stage: "start" | "finish" };

export function ModelPlaceBar({ api, onChanged, onSatellite, place, showForget = false }: {
  api: SetupApi | null;
  onChanged?: () => void;
  /** Satellite 쪽이 켜졌는가(짝짓는 중 포함) — 칩 창이 이 기기 목록을 숨길 때 쓴다. */
  onSatellite?: (on: boolean) => void;
  /** 위쪽 칩처럼 이미 읽은 자리가 있으면 그것을 쓴다. 없으면 스스로 읽는다. */
  place?: PlaceState;
  /** 설정 › 모델에서만 — 「짝 끊기」. */
  showForget?: boolean;
}) {
  const own = useModelPlace(place ? null : api);
  const { view, load, setView } = place ?? own;
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [flow, setFlow] = useState<Flow>({ phase: "off" });
  const satOnNow = flow.phase !== "off" || view?.place === "home_pc";
  useEffect(() => { onSatellite?.(satOnNow); }, [satOnNow, onSatellite]);

  if (!api?.modelPlace || !view) return null;
  // 집 PC 를 모르는 윈도우(집 PC 자체 · 그래픽카드 PC)에는 자리 고르기가 없다. 맥은 Satellite 로 짝을 지을 수 있다.
  const canPair = isMac && Boolean(api.pairDiscover);
  if (!view.home_known && !canPair) return null;

  const satOn = satOnNow;

  async function find(address = "") {
    setFlow({ phase: "finding" }); setError("");
    try {
      const found = (await api!.pairDiscover!(address)).found;
      if (found.length === 1) return start(found[0]);
      if (found.length > 1) return setFlow({ phase: "pick", found });
      setFlow({ phase: "notfound", why: t("같은 와이파이에서 손자리가 켜진 PC 를 찾지 못했습니다.") });
    } catch {
      setFlow({ phase: "notfound", why: t("같은 와이파이에서 손자리가 켜진 PC 를 찾지 못했습니다.") });
    }
  }

  async function start(home: FoundHome) {
    setFlow({ phase: "sending", home, stage: "start" });
    const done = await api!.pairStart!(home).catch(() => ({ ok: false, error: "unreachable" }));
    if (!done.ok) {
      setFlow({ phase: "notfound", why: done.error === "not_a_home_pc"
        ? t("그 PC 는 다른 PC 를 빌려 쓰는 중이라 빌려 줄 수 없습니다.")
        : done.error === "locked"
          ? t("틀린 숫자가 많아 집 PC 가 짝짓기를 하루 동안 막았습니다. 집 PC 에서 손자리를 다시 켜면 풀립니다.")
        : done.error === "too_fast" || done.error === "too_many"
          ? t("잠시 뒤 다시 눌러 주세요.")
          : t("집 PC 에 닿지 못했습니다. 집 PC 에서 손자리가 켜져 있는지 봐 주세요.") });
      return;
    }
    setFlow({ phase: "code", home, error: "" });
  }

  async function finish(home: FoundHome, code: string) {
    setFlow({ phase: "sending", home, stage: "finish" });
    const done = await api!.pairFinish!(code).catch(() => ({ ok: false, error: "unreachable" } as { ok: false; error: string; tries_left?: number }));
    if (done.ok) {
      setFlow({ phase: "off" });
      onChanged?.();
      await load();
      return;
    }
    if (done.error === "wrong_code") {
      setFlow({ phase: "code", home, error: t("숫자가 맞지 않습니다. {0}번 더 칠 수 있습니다.", done.tries_left ?? 0) });
    } else if (done.error === "locked") {
      setFlow({ phase: "notfound", why: t("틀린 숫자가 많아 집 PC 가 짝짓기를 하루 동안 막았습니다. 집 PC 에서 손자리를 다시 켜면 풀립니다.") });
    } else if (done.error === "closed" || done.error === "no_request") {
      setFlow({ phase: "notfound", why: t("짝 코드가 닫혔습니다(세 번 틀렸거나 5분이 지났습니다). 처음부터 다시 해 주세요.") });
    } else {
      setFlow({ phase: "code", home, error: t("짝을 짓지 못했습니다. 다시 해 주세요.") });
    }
  }

  async function choose(target: "this_pc" | "home_pc") {
    setError(""); setNote("");
    if (target === "this_pc" && flow.phase !== "off") {
      setFlow({ phase: "off" });
      if (view?.place !== "home_pc") return;
    }
    // 집 PC 를 모르거나 · 옛 방식(모델 서버에 바로 붙던 위성 설정)으로만 아는 맥이면 짝짓기부터 —
    // 11-04 실제 시험: 옛 설정 맥에서 Satellite 가 옛 직접 길로 가서, 집 PC 모델 서버를 닫자 [Retry] 로 영영 못 붙을 뻔했다.
    if (target === "home_pc" && (!view?.home_known || (canPair && !view?.paired))) { void find(); return; }
    if (!api?.setModelPlace || view?.place === target) return;
    setBusy(target);
    try {
      const done = await api.setModelPlace(target);
      if (!done.ok) {
        setError(done.error === "no_home_pc" ? t("집 PC 를 아직 모릅니다.") : t("바꾸지 못했습니다."));
        return;
      }
      setView(view ? { ...view, ...done } as ModelPlaceView : view);
      if (done.pending) setNote(t("지금 하는 일이 끝난 뒤 바뀝니다."));
      onChanged?.();
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function pickHome(tag: string) {
    if (!api?.setHomeModel) return;
    setBusy(tag); setError("");
    try {
      const done = await api.setHomeModel(tag);
      if (!done.ok) {
        setError(done.error === "not_on_home_pc" ? t("집 PC 에 그 모델이 없습니다.") : t("바꾸지 못했습니다."));
        return;
      }
      setView(view ? { ...view, ...done } as ModelPlaceView : view);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const home = view.home;
  const connected = flow.phase === "off" && view.place === "home_pc" && home?.reachable !== false;
  return (
    <div className="place">
      <div className="place-seg" role="radiogroup" aria-label={t("모델을 어디서 돌릴까요")}>
        {([["this_pc", HERE], ["home_pc", "Satellite"]] as const).map(([target, label]) => {
          const on = target === "home_pc" ? satOn : !satOn;
          return (
            <button key={target} type="button" role="radio" aria-checked={on}
              className={`place-seg-btn${on ? " is-on" : ""}`}
              disabled={busy !== "" || flow.phase === "sending"} onClick={() => void choose(target)}>
              {busy === target && <Loader2 size={11} className="spin" aria-hidden />}
              {label}
            </button>
          );
        })}
      </div>
      {satOn && (
        <LinkBand view={view} flow={flow}
          onCode={(code) => flow.phase === "code" && void finish(flow.home, code)}
          onPick={(found) => void start(found)}
          onUseHere={() => void choose("this_pc")}
          onRetry={() => (flow.phase === "off" && (view.paired || !canPair) ? void load() : void find())}
          onOutside={async (step) => {
            const done = await api.outsideStep?.(step).catch(() => null);
            if (done?.url) await openExternalUrl(done.url);
            window.setTimeout(() => void load(), 1500);
          }} />
      )}
      {connected && home?.reachable && view.paired && <OutsideHomeMac api={api} />}
      {note && <p className="place-note">{note}</p>}
      {error && <p className="settings-error">{error}</p>}
      {connected && home?.reachable && (
        <div className="place-models" role="listbox" aria-label={t("집 PC 에 깔린 모델")}>
          {home.models.map((row) => {
            const on = row.tag === view.chat_model;
            const name = friendlyModelName(row.tag);
            // 이름이 같은 줄이 또 있으면 출처 · 파일 꼬리로 가른다(11-04 대표: 「Qwen3.8 27B」 세 줄).
            const twin = home.models.some((other) => other.tag !== row.tag && friendlyModelName(other.tag) === name);
            return (
              <button key={row.tag} type="button" role="option" aria-selected={on} title={row.tag}
                className={`place-model${on ? " is-on" : ""}`} disabled={busy !== "" || on} onClick={() => void pickHome(row.tag)}>
                <span className="place-model-name">
                  {name}
                  {row.home_default && <em className="place-model-default">{t("집 PC 기본")}</em>}
                  {twin && <small className="place-model-source">{modelSource(row.tag)}</small>}
                </span>
                <small>{row.gb ? `${row.gb}GB` : ""}</small>
                {busy === row.tag && <Loader2 size={12} className="spin" aria-hidden />}
              </button>
            );
          })}
          <p className="place-note">{t("여기서 고른 모델은 이 {0}에서만 씁니다. 집 PC 의 선택 · 모델 받기는 집 PC 에서.", HERE)}</p>
        </div>
      )}
      {showForget && view.paired && api.pairForget && flow.phase === "off" && (
        <button type="button" className="place-forget" disabled={busy !== ""} onClick={() => {
          setBusy("forget");
          void api.pairForget!().then(() => { onChanged?.(); return load(); }).finally(() => setBusy(""));
        }}>
          {t("{0} 와 짝 끊기", view.home_host || t("집 PC"))}
        </button>
      )}
    </div>
  );
}

type BandState = "finding" | "code" | "connected" | "down";

/** Mac ━━●━━ PC — 쓰는 법 쇼의 실 · 구슬로 그린 연결 띠. */
function LinkBand({ view, flow, onCode, onPick, onUseHere, onRetry, onOutside }: {
  view: ModelPlaceView;
  flow: Flow;
  onCode: (code: string) => void;
  onPick: (home: FoundHome) => void;
  onUseHere: () => void;
  onRetry: () => void;
  /** 밖에서 안 닿을 때 — 테일스케일 켜기 · 다시 로그인(밖에서도 쓰기 §2-3). */
  onOutside?: (step: "turn_on" | "login") => void;
}) {
  const state: BandState =
    flow.phase === "finding" || flow.phase === "pick" || (flow.phase === "sending" && flow.stage === "start") ? "finding"
      : flow.phase === "code" || flow.phase === "sending" ? "code"
        : flow.phase === "notfound" ? "down"
          : view.home && !view.home.reachable ? "down"
            : !view.home ? "finding" : "connected";
  const farName = "home" in flow && flow.home ? flow.home.name : view.home_host || t("집 PC");
  const farGpu = "home" in flow && flow.home ? flow.home.gpu : view.home_gpu || "";
  const farLine = [farGpu, state === "connected" ? friendlyModelName(view.chat_model) : ""].filter(Boolean).join(" · ");

  const wire = useRef<HTMLSpanElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = wire.current;
    if (!el) return;
    const measure = () => setWidth(el.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);

  // 구슬 — 실제 부르기(home_llm_call)에만. 갔다가(start) 돌아온다(end).
  const [bead, setBead] = useState<{ dir: "go" | "back"; n: number } | null>(null);
  useEffect(() => {
    if (state !== "connected") return;
    let timer = 0;
    const onCall = (event: Event) => {
      const phase = (event as CustomEvent<{ phase?: string }>).detail?.phase;
      window.clearTimeout(timer);
      setBead((old) => ({ dir: phase === "end" ? "back" : "go", n: (old?.n ?? 0) + 1 }));
      if (phase === "end") timer = window.setTimeout(() => setBead(null), 900);
    };
    window.addEventListener(HOME_LLM_EVENT, onCall);
    return () => { window.removeEventListener(HOME_LLM_EVENT, onCall); window.clearTimeout(timer); };
  }, [state]);

  const gid = useId();
  const y = 7;
  const d = width > 16 ? `M 3 ${y} L ${width - 3} ${y}` : "";
  const mid = width / 2;
  const [code, setCode] = useState("");
  useEffect(() => { if (state !== "code") setCode(""); }, [state]);
  const codeError = flow.phase === "code" ? flow.error : "";
  useEffect(() => { if (codeError) setCode(""); }, [codeError]);

  const status =
    state === "finding" ? t("Looking for your PC…")
      : state === "code" ? t("Enter the code on your PC")
        : state === "down" ? t("PC not found")
          : view.home?.via === "tailnet" ? `${t("Connected")} · Tailscale`
            : view.home?.via === "lan" ? `${t("Connected")} · home Wi-Fi`
              : t("Connected");
  // 밖에서 「PC not found」 의 까닭(§2-3) — 테일넷 길을 기억한 기기만 백엔드가 준다.
  const why = flow.phase === "off" && state === "down" ? view.home?.why || "" : "";
  const whyText =
    why === "tailscale_off" ? t("이 {0} 의 Tailscale 이 꺼져 있습니다.", HERE)
      : why === "sign_in_again" ? t("Tailscale 에 다시 로그인해 주세요.")
        : why === "pc_asleep" ? t("집 PC 가 꺼져 있거나 잠들어 있습니다.")
          : why === "pc_not_answering" ? t("집 PC 는 켜져 있는데 손자리가 답하지 않습니다.")
            : "";

  return (
    <div className={`place-link is-${state}`} role="status" aria-live="polite">
      <div className="place-link-row">
        <span className="place-node">
          <i className="place-node-dot is-here" aria-hidden />
          <b>{HERE}</b>
        </span>
        <span className="place-wire" ref={wire}>
          {d && (
            <svg className="wns-thread place-thread" aria-hidden>
              <defs>
                <linearGradient id={gid} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2={width} y2="0">
                  <stop offset="0" stopColor="rgb(var(--origin-claude))" />
                  <stop offset="1" stopColor="rgb(var(--brand-bright))" />
                </linearGradient>
              </defs>
              {state === "down" ? (
                <>
                  <path d={`M 3 ${y} L ${mid - 7} ${y}`} className="place-thread-cut" />
                  <path d={`M ${mid + 7} ${y} L ${width - 3} ${y}`} className="place-thread-cut" />
                </>
              ) : (
                <>
                  <path d={d} className="wns-thread-rest" />
                  {state !== "finding" && (
                    <path d={d} pathLength={1} className={`wns-thread-go is-on${state === "code" ? " place-thread-half" : ""}`} stroke={`url(#${gid})`} />
                  )}
                </>
              )}
              {state === "connected" && bead && (
                <circle key={bead.n} r="3.5" className={`wns-bead wns-bead-${bead.dir}`} style={{ offsetPath: `path("${d}")` }} />
              )}
            </svg>
          )}
          {state === "code" && (
            <label className="place-code">
              <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} autoFocus
                aria-label={t("{0} 화면에 뜬 숫자 6개", farName)} disabled={flow.phase !== "code"}
                onChange={(event) => {
                  const next = event.target.value.replace(/\D/g, "").slice(0, 6);
                  setCode(next);
                  if (next.length === 6) onCode(next);
                }} />
              {Array.from({ length: 6 }, (_, i) => (
                <i key={i} className={`place-code-cell${i === code.length ? " is-next" : ""}`} aria-hidden>{code[i] ?? ""}</i>
              ))}
            </label>
          )}
        </span>
        <span className="place-node is-far">
          <i className={`place-node-dot is-far${state === "connected" ? " is-on" : ""}`} aria-hidden />
          <span className="place-node-text">
            <b>{state === "finding" && flow.phase !== "sending" ? t("PC") : farName}</b>
            {farLine && state !== "finding" && <small>{farLine}</small>}
          </span>
        </span>
      </div>
      <p className="place-link-status">
        <i className="place-status-dot" aria-hidden />
        {status}
        {flow.phase === "notfound" && <small>{flow.why}</small>}
        {whyText && <small className="place-link-why">{whyText}</small>}
        {codeError && <small className="place-link-error">{codeError}</small>}
      </p>
      {flow.phase === "pick" && (
        <div className="place-pick">
          {flow.found.map((home) => (
            <button key={home.address} type="button" className="place-pick-btn" onClick={() => onPick(home)}>
              <b>{home.name}</b>{home.gpu && <small>{home.gpu}</small>}
            </button>
          ))}
        </div>
      )}
      {state === "down" && (
        <div className="place-link-actions">
          {why === "tailscale_off" && onOutside && (
            <button type="button" className="place-act is-primary" onClick={() => onOutside("turn_on")}>{t("Turn on")}</button>
          )}
          {why === "sign_in_again" && onOutside && (
            <button type="button" className="place-act is-primary" onClick={() => onOutside("login")}>{t("Sign in")}</button>
          )}
          <button type="button" className="place-act" onClick={onUseHere}>{t("Use {0}", HERE)}</button>
          <button type="button" className="place-act is-primary" onClick={onRetry}>{t("Retry")}</button>
        </div>
      )}
    </div>
  );
}
