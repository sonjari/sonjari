/**
 * 메모리 자 — 첫 실행 화면의 한 가지 인상.
 *
 * 장식이 아니라 **추천의 근거 그 자체**다. 사용자는 VRAM·컨텍스트라는 말을 몰라도
 * 「내 카드 칸에 이 모델이 들어가나」는 한눈에 본다:
 *
 *     ├──────────── 쓸 수 있는 메모리 23.5GB ────────────┤▨ 화면 1GB
 *     ███████████████ Gemma 4 26B · 128K  15.5GB
 *                  │16K │32K │65K │128K        ← 우리가 잰 자리만 눈금으로
 *
 * 값은 계산하지 않고 백엔드가 준 것만 그린다(카드 크기 · 예약분 · 모델이 차지할 칸).
 */
import { t } from "../i18n";
import { ctxLabel, type CatalogModel, type GpuCard } from "./setupApi";

export function MemoryRuler({ card, model, ctx }: { card: GpuCard; model?: CatalogModel | null; ctx?: number | null }) {
  const total = card.vram_total_gb;
  const reserve = card.reserve_gb;
  const usable = card.usable_gb;
  const need = model && ctx ? model.vram_gb[String(ctx)] ?? null : null;
  const over = need !== null && need > usable;
  const pct = (gb: number) => `${Math.min(100, (gb / total) * 100)}%`;
  // 눈금 글자는 **서로 겹치지 않을 때만** 단다. 9B 의 16K(5.8GB)·32K(6.2GB)는 자에서
  // 1.6% 떨어져 있어 글자가 뭉개졌다(리허설에서 봄). 고른 눈금은 늘 단다.
  const MIN_GAP = 0.06;
  let lastLabeled = -Infinity;
  const ticks = model
    ? Object.entries(model.vram_gb)
        .map(([key, gb]) => ({ ctx: Number(key), gb }))
        .sort((a, b) => a.gb - b.gb)
        .map((tick, index, all) => {
          const at = tick.gb / total;
          const nextActive = all[index + 1]?.ctx === ctx && (all[index + 1].gb / total) - at < MIN_GAP;
          const labeled = tick.ctx === ctx || (at - lastLabeled >= MIN_GAP && !nextActive);
          if (labeled) lastLabeled = at;
          return { ...tick, labeled };
        })
    : [];

  return (
    <figure className="ruler" aria-label={rulerLabel(card, usable, model, ctx, need)}>
      <div className="ruler-track">
        <span className="ruler-usable" style={{ width: pct(usable) }} />
        <span className="ruler-reserve" style={{ left: pct(usable), width: pct(reserve) }} />
        {need !== null && (
          <span className={`ruler-need${over ? " is-over" : ""}`} style={{ width: pct(need) }} />
        )}
        {ticks.map((tick) => (
          <span
            key={tick.ctx}
            className={`ruler-tick${tick.ctx === ctx ? " is-active" : ""}`}
            style={{ left: pct(tick.gb) }}
          >
            {tick.labeled && <span className="ruler-tick-label">{ctxLabel(tick.ctx)}</span>}
          </span>
        ))}
      </div>
      <figcaption className="ruler-caption">
        <span>
          <b>{card.name.replace(/^NVIDIA GeForce /, "")}</b> {t("쓸 수 있는 메모리")} <span className="num">{usable.toFixed(1)}GB</span>
        </span>
        <span className="ruler-caption-side">
          {card.display_active ? <>{t("화면 출력 몫")} <span className="num">{reserve.toFixed(1)}GB</span></> : <>{t("드라이버 몫")} <span className="num">{reserve.toFixed(1)}GB</span></>}
          {need !== null && model && ctx && (
            <>
              {" · "}
              <span className={over ? "is-over-text" : ""}>
                {model.name} {ctxLabel(ctx)} <span className="num">{need.toFixed(1)}GB</span>
                {over ? t(" — 안 들어갑니다") : ""}
              </span>
            </>
          )}
        </span>
      </figcaption>
    </figure>
  );
}

function rulerLabel(card: GpuCard, usable: number, model?: CatalogModel | null, ctx?: number | null, need?: number | null): string {
  const base = t("{0} 쓸 수 있는 메모리 {1}GB", card.name, usable.toFixed(1));
  if (!model || !ctx || need === null || need === undefined) return base;
  return t("{0}. {1} {2} 는 {3}GB 를 차지합니다{4}.", base, model.name, ctxLabel(ctx), need.toFixed(1), need > usable ? t(" — 안 들어갑니다") : "");
}
