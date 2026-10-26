/**
 * 모델 고르개 안의 **컨텍스트 칸** — 이 PC 에서 몇 K 까지 들어가는지 **실제로 올려 보고** 정한다
 * (2026-09-23 제품 요청).
 *
 *     컨텍스트 64K                       이 PC 상한 96K · 09-29 잼   [다시 재기]
 *     [8K ✓ 110] [16K ✓ 108] [32K ✓ 104] [64K ✓ 98] [96K ✓ 95] [128K CPU 7% 83]   ← 잰 칸마다 버튼
 *     64K — 그래픽카드에 다 들어갑니다 · 98 tok/s
 *     ☐ 다른 프로그램(클로드 코드 등)도 이 값으로 — Ollama 를 한 번 다시 켭니다      [64K 적용]
 *
 * ★ 2026-09-29 대표 요청: 「모델을 누르면 컨텍스트를 단위별로 고를 수 있게」. 예전엔 「잰 상한 적용」 하나뿐이라
 *   「64K 로 빠르게 · 128K 로 길게」를 못 골랐다. 잰 칸이면 CPU 로 샌 칸도 속도를 보고 고를 수 있다.
 *   숫자는 전부 이 PC 에서 잰 것 — 들어가도 깡성능이 낮은 모델(젬마 128K)은 tok/s 가 말한다.
 *
 * ## 왜 여기인가
 *
 * 머리의 「Qwen3.6 · 35B · 128K」가 이미 컨텍스트를 말하고 있다. 그 숫자를 누른 자리에서 그 숫자를 바꾼다.
 * 설치 마법사는 처음 한 번 자동으로 재고, 이 칸은 모델·PC 가 바뀌었을 때 사람이 다시 잰다.
 *
 * ## 지키는 것
 *
 * - **잰 줄을 그대로 보인다.** 「128K 권장」만 주면 추정과 구별이 안 된다. 칸마다 그래픽카드 비율·속도를 적는다.
 * - **재는 것과 적용은 따로.** 재기만 해서는 아무것도 안 바뀐다 — 결과를 보고 누른다.
 * - **다른 프로그램 기본값은 묻고 넣는다**(제품 결정). 기본은 꺼 둔다. 사람이 적어 둔 값은 서버가 안 덮는다.
 */
import { t } from "../i18n";
import { Check, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ContextCeiling, ContextRung, ContextView, SetupApi } from "../setup/setupApi";
import { pollUnlessBusy } from "../setup/poll";
import "./contextCeiling.css";

const k = (ctx: number) => `${Math.round(ctx / 1024)}K`;

function rungText(rung: ContextRung): string {
  const speed = rung.tokens_per_sec ? ` · ${rung.tokens_per_sec.toFixed(0)} tok/s` : "";
  if (rung.passed) return t("그래픽카드 100%{0}", speed);
  switch (rung.why) {
    case "not_fully_on_gpu": {
      const spilled = rung.gpu_share == null ? "" : ` ${Math.round((1 - rung.gpu_share) * 100)}%`;
      return t("CPU 로{0} 샘{1}", spilled, speed);
    }
    case "context_clamped":
      return t("Ollama 가 더 작게 올렸습니다");
    case "too_slow":
      return t("첫 칸보다 30% 넘게 느려짐{0}", speed);
    case "gpu_measurement_unavailable":
      return t("그래픽카드 비율을 읽지 못했습니다");
    case "model_load_timeout":
      return t("올리는 데 너무 오래 걸림");
    case "model_out_of_memory":
      return t("그래픽카드 메모리 부족");
    case "ollama_not_answering":
      return t("Ollama 가 답하지 않음");
    default:
      return t("올리지 못했습니다");
  }
}

/** 두 배로 올라가다 떨어지면 그 사이를 좁혀 잰다 — 잰 순서가 크기 순서가 아니다. 보일 때는 크기로 줄 세운다. */
function bySize(rungs: ContextRung[]): ContextRung[] {
  return [...rungs].sort((a, b) => a.num_ctx - b.num_ctx);
}

function errorText(error: string | undefined, current?: string, record?: ContextCeiling): string {
  switch (error) {
    case "busy":
      return t("Sonjari가 일하는 중입니다 — 재는 동안 모델을 내렸다 올려서, 끝난 뒤에 다시 눌러 주세요.");
    case "already_measuring":
      return t("이미 재는 중입니다.");
    case "not_measured":
      return t("아직 안 잰 값은 적용하지 않습니다.");
    case "not_the_chat_model":
      return t("지금 대화 모델이 바뀌었습니다 — 다시 재 주세요.");
    case "user_set_context_length":
      return t("Ollama 기본값이 이미 {0} 로 적혀 있어 건드리지 않았습니다(직접 넣으신 값).", k(Number(current) || 0));
    case "nothing_to_squeeze":
      return t("더 좁힐 사이가 없습니다.");
    case "rung_did_not_load":
      return t("그 칸은 올리지 못했던 칸이라 고를 수 없습니다.");
    case "no_context_fits": {
      const first = record?.steps?.[0]?.num_ctx;
      return t("가장 작은 칸({0})도 그래픽카드에 온전히 안 들어갑니다 — 더 작은 모델을 권합니다.", first ? k(first) : "16K");
    }
    case "first_rung_failed": {
      // ★ 10-25: 올라가지도 못한 것을 「안 들어감」으로 말하지 않는다 — 모델이 작다는 뜻이 아니다.
      const step = record?.steps?.[0];
      const why = step ? rungText(step) : t("올리지 못했습니다");
      return t("첫 칸{0}을 재지 못했습니다({1}). 모델이 커서가 아니라 그때 올리지 못한 것이라, 잠시 뒤 다시 재 주세요.",
        step ? `(${k(step.num_ctx)})` : "", why);
    }
    default:
      return error || t("알 수 없는 이유");
  }
}

/** 「더 쥐어짜기」로 좁힐 사이 — 합격 상한과 그 위 첫 불합격 칸(그래픽카드에 안 들어간 칸만). 백엔드 `squeeze_gap` 과 같은 셈. */
const FIT_WHY = new Set(["not_fully_on_gpu", "context_clamped", "too_slow", "model_out_of_memory"]);
const SQUEEZE_STEP = 8192;
export function squeezeGap(row: ContextCeiling | undefined): [number, number] | null {
  const ceiling = row?.ceiling ?? 0;
  if (!row || !ceiling) return null;
  const above = (row.steps ?? []).filter((r) => !r.passed && r.num_ctx > ceiling && FIT_WHY.has(r.why)).map((r) => r.num_ctx);
  if (!above.length) return null;
  const high = Math.min(...above);
  const middle = Math.floor((ceiling + high) / 2 / SQUEEZE_STEP) * SQUEEZE_STEP;
  return ceiling < middle && middle < high ? [ceiling, high] : null;
}

/** 잰 기록만 — 고른 칸만 적힌 기록은 `undefined`. */
export function measuredRecord(row: ContextCeiling | undefined): ContextCeiling | undefined {
  return row && row.measured_at ? row : undefined;
}

export function ContextCeilingPanel({ api, model, onApplied, auto = false, role = "chat" }: {
  api: SetupApi;
  /** 이 고르개의 모델 태그 — 고르개가 이미 알고 있다. */
  model: string;
  onApplied?: () => void;
  /** 설치 마법사: 처음 쓰는 사람은 컨텍스트가 뭔지 몰라도 된다 — 안 쟀으면 **알아서 재고, 온텔릭 값에 알아서 적용**한다.
   *  다른 프로그램 기본값(Ollama 전체)은 여기서도 체크를 사람에게 둔다(묻고 넣기). */
  auto?: boolean;
  /** Code 탭 고르개에도 보인다(09-29). 같은 모델이면 대화와 **한 값**을 쓴다 — 두 값이면 러너가 둘이 되어 서로 쫓아낸다. */
  role?: "chat" | "code";
}) {
  const [view, setView] = useState<ContextView | null>(null);
  const [alsoGlobal, setAlsoGlobal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  /** 사람이 누른 칸. 안 눌렀으면 지금 값(잰 칸일 때) 또는 잰 상한. */
  const [chosen, setChosen] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setView(await api.contextStatus());
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  // 재는 동안만 1초마다 다시 읽는다 — 칸이 하나씩 채워지는 것이 보여야 「멈췄나?」가 안 된다.
  const measuring = Boolean(view?.measuring);
  useEffect(() => {
    if (!measuring) return;
    // 앞 물음이 안 끝났으면 다시 묻지 않는다 — 재는 동안은 그래픽카드가 바빠 물음 하나가 1초를 넘기 쉽다(`poll.ts`).
    return pollUnlessBusy(load, 1000);
  }, [measuring, load]);

  // 마법사 자동 모드 — 처음 한 번만 재기 시작, 다 재면 한 번만 적용. 두 번 돌지 않게 표시해 둔다.
  const autoState = useRef({ started: false, applied: false });
  useEffect(() => {
    if (!auto || !view || autoState.current.started) return;
    autoState.current.started = true;
    if (!view.ceilings[model] && !view.measuring) void measure();
  });
  useEffect(() => {
    if (!auto || !view || view.measuring || autoState.current.applied) return;
    const found = view.ceilings[model];
    if (found?.ok && found.ceiling !== view.num_ctx) {
      autoState.current.applied = true;
      void apply(found.ceiling);
    }
  });

  const measure = async () => {
    setMessage("");
    setChosen(null);
    const done = await api.measureContext(model);
    if (!done.ok) setMessage(errorText(done.error));
    await load();
  };

  const squeeze = async () => {
    setMessage("");
    setChosen(null);
    const done = await api.squeezeContext(model);
    if (!done.ok) setMessage(errorText(done.error));
    await load();
  };

  const apply = async (numCtx: number) => {
    setBusy(true);
    setMessage("");
    try {
      const done = await api.applyContext(model, alsoGlobal, numCtx);
      if (!done.ok) {
        setMessage(errorText(done.error));
      } else if (done.global && !done.global.ok) {
        setMessage(t("Sonjari에는 적용했습니다. 다른 프로그램 기본값은 못 바꿨습니다 — {0}", errorText(done.global.error, done.global.current)));
      } else {
        setChosen(null);
      }
      await load();
      onApplied?.();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  // ★ 칸이 빠진 응답(옛 백엔드·위성)에도 죽지 않는다 — 여기서 던지면 **모델 고르개 전체**가 안 그려진다.
  if (!view || !view.ceilings) return null;
  const bare = (tag: string) => tag.trim().toLowerCase().replace(/:latest$/, "");
  if (role === "code" && view.chat_model && bare(model) !== bare(view.chat_model)) {
    return (
      <section className="context-ceiling" aria-label={t("컨텍스트")}>
        <p className="context-note">{t("코드 모델이 대화 모델과 달라 따로 올라갑니다. 창 크기는 대화 모델 고르개에서 고릅니다.")}</p>
      </section>
    );
  }
  // ★ 2026-10-05: 「이 크기로 쓰기로 했다」만 적힌 기록(모델을 적용하면 백엔드가 남긴다, 09-30)은 **잰 기록이 아니다.**
  //   그것을 잰 기록으로 읽어, 첫 실행에서 모델을 적용하자마자 이유 없는 경고(「알 수 없는 이유」)와 「다시 재기」가 떴다.
  //   잰 기록에는 늘 잰 시각이 있다.
  const last = measuredRecord(view.ceilings[model]);
  const live = view.live && view.live.model === model ? view.live : null;
  const ceiling = last?.ceiling ?? 0;
  const gap = squeezeGap(last);
  // 고를 수 있는 칸 = 이 PC 에서 **실제로 올려 토큰을 만든** 칸. 못 올린 칸은 고를 게 없다.
  const choices = bySize(last?.steps ?? []).filter((rung) => (rung.tokens_per_sec ?? 0) > 0);
  const currentIsRung = choices.some((rung) => rung.num_ctx === view.num_ctx);
  const target = chosen ?? (currentIsRung ? view.num_ctx : ceiling);
  const targetRung = choices.find((rung) => rung.num_ctx === target);
  const globalMatches = view.global?.value === String(target);
  const needsApply = !measuring && target > 0 && (target !== view.num_ctx || (alsoGlobal && !globalMatches));

  return (
    <section className="context-ceiling" aria-label={t("컨텍스트 상한")}>
      <div className="context-ceiling-head">
        <div>
          <strong>{t("컨텍스트")} <span>{k(view.num_ctx)}</span></strong>
          <small>
            {measuring
              ? t("이 PC 에서 한 칸씩 올려 보는 중입니다")
              : last?.ok
                ? t("이 PC 상한 {0} · {1} 잼", k(ceiling), last.measured_at.slice(5, 10).replace("-", "."))
                : t("이 PC 에서 아직 안 쟀습니다")}
          </small>
        </div>
        <button type="button" onClick={() => void measure()} disabled={measuring || busy}>
          {measuring ? <Loader2 size={13} className="spin" /> : null}
          {measuring ? t("재는 중") : last ? t("다시 재기") : t("상한 재기")}
        </button>
      </div>

      {/* 잰 칸마다 버튼 — 그래픽카드 비율과 속도를 같이 적는다(09-29). 크기만 적으면 「들어가지만 느린」 칸을 못 가린다.
          예전의 여섯 줄 목록은 모델 목록을 찌부러뜨려(09-23 실물) 한 줄 요약으로 접었었다 — 버튼 칸은 줄바꿈되는 알약이라 낮다. */}
      {!live && choices.length > 0 && (
        <div className="context-choices" role="radiogroup" aria-label={t("컨텍스트 크기 고르기")}>
          {choices.map((rung) => (
            <button
              key={rung.num_ctx}
              type="button"
              role="radio"
              aria-checked={rung.num_ctx === target}
              className={`${rung.passed ? "passed" : "failed"} ${rung.num_ctx === target ? "selected" : ""}`}
              onClick={() => setChosen(rung.num_ctx)}
              disabled={busy}
              title={rungText(rung)}
            >
              <b>{k(rung.num_ctx)}</b>
              <small>
                {rung.passed ? "✓" : `CPU${rung.gpu_share == null ? "" : ` ${Math.round((1 - rung.gpu_share) * 100)}%`}`}
                {rung.tokens_per_sec ? ` ${rung.tokens_per_sec.toFixed(0)} tok/s` : ""}
              </small>
            </button>
          ))}
        </div>
      )}
      {live && (
        <ol className="context-rungs">
          {bySize(live.steps).map((rung) => (
            <li key={rung.num_ctx} className={rung.passed ? "passed" : "failed"}>
              <b>{k(rung.num_ctx)}</b>
              {rung.passed ? <Check size={13} aria-label={t("들어감")} /> : <X size={13} aria-label={t("안 들어감")} />}
              <span>{rungText(rung)}</span>
            </li>
          ))}
          {live.loading !== 0 && (
            <li className="loading">
              <b>{live.loading > 0 ? k(live.loading) : k(Math.max(0, ...live.steps.filter((r) => r.passed).map((r) => r.num_ctx)))}</b>
              <Loader2 size={13} className="spin" aria-hidden />
              <span>{live.loading > 0 ? t("올려서 토큰을 만들어 보는 중") : t("상한으로 다시 올려 두는 중")}</span>
            </li>
          )}
        </ol>
      )}

      {/* ★ 서버는 **시작할 때만** 도는 일이 있는지 본다 — 도중에 들어온 일은 막지 않는다. 막는 척하지 않는다. */}
      {/* 30분 감시가 본 것 — 붙은 프로그램이 바뀌었다는 **사실**만. 얼마나 늘었는지는 말하지 않는다(역검증에서 틀림). */}
      {!measuring && last?.ok && view.watch?.state === "changed" && (
        <p className="context-note hint">
          {t("잰 뒤로 이 그래픽카드를 쓰는 프로그램이 바뀌었습니다")}
          {view.watch.left?.length ? t(" — 빠짐: {0}", view.watch.left.join(", ")) : ""}
          {view.watch.joined?.length ? t(" — 새로: {0}", view.watch.joined.join(", ")) : ""}{t(". 다시 재 보면 상한이 달라질 수 있습니다.")}
        </p>
      )}
      {measuring && <p className="context-note">{t("재는 동안(보통 1~3분)은 일을 맡기지 말아 주세요 — 모델을 내렸다 올립니다.")}</p>}

      {/* ★ 10-25 대표: 「128K 다음은 256K 로만 가나」 — 처음 재기는 둥근 칸만(09-29 결정), 그 사이는 사람이 누를 때만 두 번 더. */}
      {!measuring && last?.ok && gap && (
        <div className="context-squeeze">
          <button type="button" onClick={() => void squeeze()} disabled={busy}>{t("더 쥐어짜기")}</button>
          <small className="context-note">
            {t("{0} 와 {1} 사이를 두 번 더 올려 봅니다(모델을 두 번 더 올려 1분 안쪽). 창을 넓혀도 그만큼 기록이 길어지면 처음부터 읽을 때 더 기다립니다.", k(gap[0]), k(gap[1]))}
          </small>
        </div>
      )}
      {!measuring && last?.squeezed && (
        <small className="context-note">
          {t("쥐어짜기: {0} → {1} · {2}초", k(last.squeezed.from), k(last.squeezed.to), Math.round(last.squeezed.took_sec))}
        </small>
      )}

      {!measuring && last && !last.ok && <p className="context-note warn">{errorText(last.error, undefined, last)}</p>}

      {!measuring && target > 0 && (
        <div className="context-apply">
          <p>
            <b>{k(target)}</b>
            {targetRung
              ? targetRung.passed
                ? t(" — 그래픽카드에 다 들어갑니다{0}", targetRung.tokens_per_sec ? ` · ${targetRung.tokens_per_sec.toFixed(0)} tok/s` : "")
                : t(" — {0}. 창은 길어지지만 모든 걸음이 느려집니다", rungText(targetRung))
              : ""}
            {target === ceiling
              ? last?.stopped === "model_limit" ? t(" — 모델이 지원하는 최대치입니다.") : t(" — 이 PC 에서 다 들어가는 가장 큰 칸입니다.")
              : ""}
          </p>
          <small className="context-note">
            {role === "code" ? t("대화 탭도 같은 모델이라 같이 바뀝니다. ") : t("Code 탭이 같은 모델이면 같이 바뀝니다. ")}
            {t("다음 요청에서 모델을 한 번 다시 올립니다(보통 20~30초).")}
          </small>
          <label>
            <input type="checkbox" checked={alsoGlobal} onChange={(event) => setAlsoGlobal(event.target.checked)}
                   disabled={busy} />
            <span>
              {t("다른 프로그램(클로드 코드 등)도 이 값으로")}
              <small>
                {view.global?.ours && globalMatches
                  ? t("Ollama 기본값도 {0} 로 맞춰져 있습니다", k(target))
                  : view.global?.value && !view.global?.ours && view.global?.value !== "unknown"
                    ? t("지금 Ollama 기본값은 {0} 입니다(직접 넣으신 값이라 안 바꿉니다)", k(Number(view.global?.value) || 0))
                    : t("Ollama 를 한 번 다시 켭니다. 안 켜면 그 프로그램이 먼저 올릴 때 Ollama 기본값(그래픽카드 메모리에 따라 4K~32K)으로 올라옵니다")}
              </small>
            </span>
          </label>
          <button type="button" className="primary" onClick={() => void apply(target)} disabled={busy || !needsApply}>
            {busy ? <Loader2 size={13} className="spin" /> : null}
            {needsApply ? t("{0} 적용", k(target)) : t("적용돼 있습니다")}
          </button>
        </div>
      )}

      {message && <p className="context-note warn" role="alert">{message}</p>}
    </section>
  );
}
