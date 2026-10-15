/**
 * 설정 › 모델 — 이 PC 에서 돌릴 수 있는 모델을 한눈에 보고, 누르면 받아서 실제로 돌려 본 뒤 바꾼다 (2026-09-16 제품 요청).
 *
 * 예전 이 칸은 「첫 실행 다시 하기를 쓰세요」 한 줄이었다. 모델을 바꾸려고 첫 실행 마법사를 처음부터 다시 도는 것은
 * 사람이 할 일이 아니다. 여기서는 목록이 전부다:
 *
 *   ● 사용 중   Qwen 3.5 9B · Alibaba      32K 까지 · 6.2GB     받아 둠
 *   ○ 가능      Granite 4.1 8B · IBM      32K 까지 · 6.3GB     받기 5.3GB   [받고 바꾸기]
 *   ✕ 불가      Gemma 4 26B · Google      15.5GB 필요 · 이 PC 7.0GB
 *
 * 「가능·불가」는 화면이 계산하지 않는다 — 백엔드 `catalog_view` 가 이 PC 의 쓸 수 있는 메모리로 판정한 `fits` 를 그대로 쓴다
 * (규칙이 두 벌이면 갈린다). 받기가 끝나면 **백엔드가** 적용한다(`apply_ctx`) — 설정 창을 닫아도 바뀐다.
 */
import { t } from "../i18n";
import { Check, Circle, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ctxLabel, pullFailureText, pushedOutReason, type ApplyResult, type CatalogModel, type GpuCard, type ModelsView, type SetupApi, type WayOutInfo } from "../setup/setupApi";
import { WayOut, hasWayOut } from "../setup/WayOut";
import { HfPicker, type HfPick } from "../setup/HfPicker";

type Row = CatalogModel & { current: boolean };

function bestCtx(model: CatalogModel): number {
  return model.largest_fitting_ctx ?? Math.min(...Object.keys(model.vram_gb).map(Number));
}

function orderOf(row: Row): number {
  if (row.current) return 0;
  if (row.fits && row.installed) return 1;
  if (row.fits) return 2;
  return 3;
}

export function ModelSection({ api, onChanged }: { api: SetupApi | null; onChanged?: () => void }) {
  const [view, setView] = useState<ModelsView | null>(null);
  const [usable, setUsable] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [results, setResults] = useState<Record<string, ApplyResult>>({});
  // ★ 2026-10-01 밤 대표: 「마법사 말고 설정에서도 모델을 바꿀 수 있어야」 — 허깅페이스 고르개를 여기에도 둔다.
  const [card, setCard] = useState<GpuCard | null>(null);
  const [tab, setTab] = useState<"catalog" | "hf">("catalog");
  const [hfPick, setHfPick] = useState<HfPick | null>(null);
  const [hfTag, setHfTag] = useState("");

  const load = useCallback(async () => {
    if (!api) return;
    try {
      const next = await api.models();
      setView(next);
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, [api]);

  useEffect(() => {
    void load();
    if (!api) return;
    api.profile(false)
      .then((profile) => {
        const cards = profile.gpus.filter((gpu) => !gpu.integrated && gpu.vram_total_gb > 0);
        const card = [...cards].sort((a, b) => b.vram_total_gb - a.vram_total_gb)[0];
        setUsable(card ? card.usable_gb ?? null : 0);
        setCard(card ?? null);
      })
      .catch(() => setUsable(null));
  }, [api, load]);

  // 받는 중이면 1초마다 — 끝나면(백엔드가 적용까지 마치면) 목록과 대화 화면의 모델 표시를 새로 읽는다.
  const pulling = Object.values(view?.pulls ?? {}).some((pull) => pull.status === "pulling");
  useEffect(() => {
    if (!pulling) return;
    const timer = window.setInterval(async () => {
      const next = await load();
      if (!next) return;
      for (const pull of Object.values(next.pulls)) {
        if (pull.status === "done" && pull.applied) {
          setResults((current) => ({ ...current, [pull.model_key]: pull.applied! }));
          if (pull.applied.ok) onChanged?.();
        }
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [pulling, load, onChanged]);

  /** 지금 쓰는 모델의 그림 읽기를 켜거나 끈다 — 같은 모델 · 같은 대화 길이로 다시 올린다(받는 것은 없다). */
  const setPictures = async (model: CatalogModel, on: boolean, ctx: number) => {
    if (!api) return;
    setBusyKey(model.key);
    setError("");
    try {
      const done = await api.apply(model.key, ctx, on);
      setResults((current) => ({ ...current, [model.key]: done }));
      if (done.ok) onChanged?.();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey("");
    }
  };

  /**
   * 목록 밖 모델(허깅페이스에서 고른 것)을 쓰는 중일 때의 그림 읽기 — 그림을 읽는 쪽 이름에 켬/끔을 실어 다시 올린다.
   * 끄면 백엔드가 그림 부속만 뺀 이름을 만들어 올리고, 켜면 원래 이름으로 돌아간다(받는 것은 없다 · 2026-10-13).
   */
  const setPicturesOfTag = async (sourceTag: string, on: boolean, ctx: number) => {
    if (!api) return;
    setBusyKey(sourceTag);
    setError("");
    try {
      const done = await api.applyTag(sourceTag, ctx, on);
      setResults((current) => ({ ...current, [sourceTag]: done }));
      if (done.ok) onChanged?.();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey("");
    }
  };

  const choose = async (model: CatalogModel, ctxOverride?: number) => {
    if (!api) return;
    // 「더 작은 모델로」에서 올 때는 백엔드가 지금 빈 자리에 맞춰 고른 창을 그대로 쓴다(WayOut).
    const ctx = ctxOverride ?? bestCtx(model);
    setBusyKey(model.key);
    setError("");
    try {
      if (model.installed) {
        const done = await api.apply(model.key, ctx);
        setResults((current) => ({ ...current, [model.key]: done }));
        if (done.ok) onChanged?.();
      } else {
        const started = await api.pull(model.key, ctx);
        if (!started.ok) throw new Error(started.error || t("받기를 시작하지 못했습니다"));
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey("");
    }
  };

  // 받은 뒤 적용할 대화 길이 — 고르개의 「들어가나」도 이 길이로 판정한다(같은 값 한 곳, 2026-10-03).
  const hfCtx = (usable ?? 0) >= 20 ? 65536 : 32768;

  const getFromHf = async (pick: HfPick) => {
    if (!api) return;
    setError("");
    setHfTag(pick.file.tag);
    try {
      // 큰 카드는 64K 로 올려 본다 — 새면 백엔드가 한 칸씩 줄여 잰다(`_measure_and_save`).
      const started = await api.pullTag(pick.file.tag, hfCtx, "chat", pick.textOnly ? false : undefined);
      if (!started.ok) throw new Error(started.error === "bad_tag" ? t("받을 이름 모양이 아닙니다") : started.error || t("받기를 시작하지 못했습니다"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  /** 못 올린 까닭이 「자리가 모자라서」이고 백엔드가 두 길의 재료를 실어 보냈나. */
  const showsWayOut = (result: ApplyResult): result is ApplyResult & { way_out: WayOutInfo } =>
    (result.error === "model_not_fully_on_gpu" || result.error === "model_out_of_memory") && hasWayOut(result);

  if (!api) return <p className="settings-note">{t("모델 목록을 읽을 수 없습니다 — 앱을 다시 켜 주세요.")}</p>;
  if (!view) return <p className="settings-note"><Loader2 size={14} className="spin" /> {t("이 PC 에 맞는 모델을 확인하는 중입니다")}</p>;
  if (view.satellite) return <p className="settings-note">{t("이 PC 는 본체의 모델을 빌려 씁니다 — 모델은 본체에서 바꿉니다.")}</p>;

  const selected = view.selection?.catalog_key ?? "";
  const rows: Row[] = view.models
    .map((model) => ({ ...model, current: model.key === selected }))
    .sort((a, b) => orderOf(a) - orderOf(b));
  const anyBusy = busyKey !== "" || pulling;

  const hfPull = hfTag ? view.pulls[hfTag] : undefined;
  const hfResult = hfTag ? results[hfTag] ?? (hfPull?.status === "done" ? hfPull.applied : undefined) : undefined;

  // 목록 밖 모델을 쓰는 중 — 아래 목록에는 그 줄이 없으니, 그림 읽기를 켜고 끄는 줄을 맨 위에 따로 둔다.
  const loose = view.eyes && !view.eyes.listed && view.eyes.can_switch ? view.eyes : null;
  const looseResult = loose ? results[loose.source_tag] : undefined;

  return (
    <div className="settings-block model-list">
      {loose && (
        <div className="model-loose-eyes">
          <p className="model-row-eyes">
            <span>
              <b className="model-loose-name">{loose.tag.replace(/^sonjari-text-/, "").replace(/:latest$/, "")}</b>{" — "}
              {loose.reads_pictures
                ? t("그림 읽기 켜짐 — 붙인 사진과 페이지 속 그림까지 읽습니다.")
                : t("글만 읽는 중 — 그림은 읽지 못하고, 그래픽카드 메모리를 {0}GB 쯤 덜 씁니다.", loose.saves_gb.toFixed(1))}
            </span>
            <button type="button" className="model-row-btn" disabled={anyBusy}
              onClick={() => void setPicturesOfTag(loose.source_tag, !loose.reads_pictures, view.selection?.num_ctx ?? 32768)}>
              {busyKey === loose.source_tag ? t("돌려 보는 중…") : loose.reads_pictures ? t("글만 읽기로 바꾸기") : t("그림도 읽기로 바꾸기")}
            </button>
          </p>
          {looseResult && !looseResult.ok && (
            <p className="settings-error" role="alert">
              {looseResult.error === "model_not_fully_on_gpu"
                ? t("그래픽카드에 다 올라가지 않아 바꾸지 않았습니다 — 지금 모델을 그대로 씁니다.")
                : `${t("바꾸지 못했습니다:")} ${looseResult.error}`}
            </p>
          )}
        </div>
      )}
      <div className="model-source" role="tablist" aria-label={t("모델을 고르는 길")}>
        <button type="button" role="tab" aria-selected={tab === "catalog"}
          className={`model-source-tab is-catalog${tab === "catalog" ? " is-on" : ""}`} onClick={() => setTab("catalog")}>
          {t("Sonjari 추천")}<small>{t("잰 모델")}</small>
        </button>
        <button type="button" role="tab" aria-selected={tab === "hf"}
          className={`model-source-tab is-hf${tab === "hf" ? " is-on" : ""}`} onClick={() => setTab("hf")}>
          {t("허깅페이스에서 고르기")}<small>{t("모델·양자화 직접")}</small>
        </button>
      </div>
      {tab === "hf" && (
        <div className="settings-hf">
          <HfPicker api={api} card={card} busy={anyBusy} picked={hfPick} onPick={setHfPick} onGet={(pick) => void getFromHf(pick)} ctx={hfCtx} />
          {hfPull?.status === "pulling" && (
            <p className="settings-note" role="status">
              <Loader2 size={13} className="spin" /> {hfTag} {t("받는 중")}
              {hfPull.total ? ` ${Math.round((hfPull.completed / hfPull.total) * 100)}%` : ""} {t("— 다 받으면 실제로 돌려 보고 바꿉니다")}
            </p>
          )}
          {hfPull?.status === "failed" && <p className="settings-error" role="alert">{pullFailureText(hfPull)}</p>}
          {hfResult?.ok && <p className="settings-note" role="status">{t("바꿨습니다 —")} {hfTag}</p>}
          {hfResult && !hfResult.ok && <p className="settings-error" role="alert">{t("바꾸지 못했습니다:")} {hfResult.error}</p>}
          {error && <p className="settings-error" role="alert">{error}</p>}
        </div>
      )}
      {tab === "catalog" && <>
      <p className="settings-note">
        {usable === null
          ? t("이 PC 의 그래픽카드 메모리로 들어가는 모델만 「가능」입니다.")
          : usable > 0
            ? t("이 PC 에서 모델에 쓸 수 있는 그래픽카드 메모리는 {0}GB 입니다. 「가능」은 그 안에 들어가는 모델입니다.", usable.toFixed(1))
            : t("AI 모델을 올릴 그래픽카드가 보이지 않아 전부 「불가」입니다.")}
        {" "}{t("바꾸면 받은 뒤 실제로 한 번 돌려 보고, 되면 그때 바꿉니다.")}
      </p>
      {error && <p className="settings-error" role="alert">{error}</p>}
      <ul className="model-rows">
        {rows.map((row) => {
          const ctx = bestCtx(row);
          // 「글만 읽기」 칸은 그 메모리를 보인다 — 그림을 켠 어림값(4.9GB)을 보이고 글만 읽기로 올리면 말과 일이 어긋난다(2026-10-15).
          const need = row.text_only && row.text_only_need_gb ? row.text_only_need_gb : row.vram_gb[String(ctx)];
          const pull = view.pulls[row.key];
          const isPulling = pull?.status === "pulling";
          const result = results[row.key] ?? (pull?.status === "done" ? pull.applied : undefined);
          const state = row.current ? "current" : row.fits ? "ok" : "no";
          return (
            <li key={row.key} className={`model-row is-${state}`}>
              <span className={`model-fit is-${state}`}>
                {state === "current" ? <Check size={13} /> : state === "ok" ? <Circle size={10} /> : <X size={13} />}
                {state === "current" ? t("사용 중") : state === "ok" ? t("가능") : t("불가")}
              </span>
              <span className="model-row-name">
                <b>{row.name}</b>
                <small>
                  {row.vendor}
                  {row.status === "external" && t(" · Sonjari 미검증")}
                  {row.memory_device && t(" · {0} 메모리 실측", row.memory_device)}
                  {t(" · {0}", row.agent_grade?.label ?? t("능력을 잰 적 없음"))}
                </small>
              </span>
              <span className="model-row-fit num">
                {row.fits
                  ? t("{0} 까지 · {1}GB", ctxLabel(ctx), need?.toFixed(1) ?? "?") + (row.text_only ? t(" · 글만 읽기") : "")
                  : t("{0}GB 필요{1}", need?.toFixed(1) ?? "?", usable ? ` · 이 PC ${usable.toFixed(1)}GB` : "")}
              </span>
              <span className="model-row-have">
                {row.installed ? t("받아 둠") : <span className="num">{t("받기")} {row.download_gb.toFixed(1)}GB</span>}
              </span>
              <span className="model-row-action">
                {isPulling ? (
                  <span className="model-row-progress" role="progressbar"
                    aria-valuenow={pull.total ? Math.round((pull.completed / pull.total) * 100) : undefined}>
                    <span style={{ width: pull.total ? `${Math.round((pull.completed / pull.total) * 100)}%` : "30%" }} />
                    <em className="num">{pull.total ? t("받는 중 {0}%", Math.round((pull.completed / pull.total) * 100)) : t("준비 중")}</em>
                  </span>
                ) : row.fits && !row.current ? (
                  <button type="button" className="model-row-btn" disabled={anyBusy} onClick={() => void choose(row)}>
                    {busyKey === row.key ? t("돌려 보는 중…") : row.installed ? t("이걸로 바꾸기") : t("받고 바꾸기")}
                  </button>
                ) : null}
              </span>
              {row.current && row.pictures_optional && (() => {
                // 그림 읽기 — 지금 쓰는 모델에서만 바꾼다. 옛 선택 기록은 이 칸이 없다: 이름이 「글만 읽는」 이름인지로 본다.
                const reading = view.selection?.reads_pictures ?? view.selection?.chat_model !== row.text_only_tag;
                const keep = view.selection?.num_ctx ?? ctx;
                return (
                  <p className="model-row-eyes">
                    <span>
                      {reading
                        ? t("그림 읽기 켜짐 — 붙인 사진과 페이지 속 그림까지 읽습니다.")
                        : t("글만 읽는 중 — 그림은 읽지 못하고, 그래픽카드 메모리를 {0}GB 쯤 덜 씁니다.", (row.text_only_saves_gb ?? 0).toFixed(1))}
                    </span>
                    <button type="button" className="model-row-btn" disabled={anyBusy} onClick={() => void setPictures(row, !reading, keep)}>
                      {busyKey === row.key ? t("돌려 보는 중…") : reading ? t("글만 읽기로 바꾸기") : t("그림도 읽기로 바꾸기")}
                    </button>
                  </p>
                );
              })()}
              {result && !result.ok && showsWayOut(result) ? (
                // ★ 2026-10-10 대표: 빨간 글 한 줄 대신 두 길 — 닫고 다시 재기 / 지금 들어가는 작은 모델(WayOut.tsx).
                <div className="model-row-wayout">
                  <WayOut info={result.way_out} busy={anyBusy}
                    onRetry={() => void choose(row)}
                    onSmaller={(smaller) => {
                      const target = rows.find((other) => other.key === smaller.model_key);
                      if (!target) return;
                      setResults((current) => { const next = { ...current }; delete next[row.key]; return next; });
                      void choose(target, smaller.num_ctx);
                    }} />
                </div>
              ) : result && !result.ok && (
                <span className="model-row-error" role="alert">
                  {result.error === "model_did_not_generate"
                    ? t("올렸지만 글자가 나오지 않아 바꾸지 않았습니다.")
                    : result.error === "model_not_fully_on_gpu"
                      ? t("작은 모델도 GPU에 전부 올라가지 않아 기존 선택을 유지했습니다. 다른 GPU 앱을 종료한 뒤 다시 시도해 주세요.")
                      : result.error === "gpu_measurement_unavailable"
                        ? pushedOutReason(result.offload?.seen)
                        : t("바꾸지 못했습니다: {0}", result.error)}
                </span>
              )}
              {result?.warnings?.map((warning) => <span key={warning} className="model-row-error" role="status">{warning}</span>)}
              {pull?.status === "failed" && (
                <span className="model-row-error" role="alert">{pullFailureText(pull)}</span>
              )}
            </li>
          );
        })}
      </ul>
      </>}
    </div>
  );
}
