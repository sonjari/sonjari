/**
 * 고른 모델을 그래픽카드에 다 못 올렸을 때 — 빨간 글 한 줄 대신 **사람이 고를 두 길** (2026-10-10 대표).
 *
 *   「다른 GPU 앱을 종료한 뒤 다시 시도해 주세요」는 막다른 길이었다. 무엇을 닫아야 하는지도, 닫으면 되는지도,
 *   안 닫고 가는 길도 없었다. 재료는 백엔드가 준다(`model_setup.way_out`) — 여기는 그대로 보여 주고 누를 것을 단다.
 *
 * 지키는 것
 *   - 닫는 것은 사람이 한다. 우리는 남의 프로그램을 끄지 않는다(저장 안 한 일을 날리면 그게 더 큰 사고다).
 *   - 다 닫아도 안 들어가는 카드에는 「닫으세요」를 말하지 않는다(`close.would_fit === false`).
 *   - 모르는 것은 모른다고 쓴다. 「들어갑니다」는 백엔드가 잰 값이 있을 때만.
 *   - 색은 호박색이다 — 이 앱에서 빨강은 「되돌릴 수 없다」이고, 여기는 「사람이 고를 차례」다.
 */
import { t } from "../i18n";
import type { WayOutInfo } from "./setupApi";
import "./wayOut.css";

function gb(value: number | null | undefined): string {
  return value == null ? "?" : (Math.round(value * 10) / 10).toString();
}

/** 카드 한 장의 메모리 — 남이 쓰는 몫, 그리고 이 모델이 필요한 몫이 어디까지 가는지. */
function MemoryBar({ info }: { info: WayOutInfo }) {
  const total = info.card.total_gb;
  const used = info.card.used_gb;
  if (!total || used == null) return null;
  const usedPct = Math.min(100, (used / total) * 100);
  const needPct = (info.needs_gb / total) * 100;
  const over = usedPct + needPct > 100;
  return (
    <div className="wayout-bar" role="img"
      aria-label={t("그래픽카드 {0}GB 가운데 다른 프로그램이 {1}GB 를 쓰고 있고, 이 모델은 {2}GB 가 필요합니다", gb(total), gb(used), gb(info.needs_gb))}>
      <span className="wayout-bar-used" style={{ width: `${usedPct}%` }} />
      <span className={over ? "wayout-bar-need is-over" : "wayout-bar-need"}
        style={{ left: `${usedPct}%`, width: `${Math.min(needPct, 100 - usedPct)}%` }} />
      <em className="num">
        {t("다른 프로그램 {0}GB · 이 모델 {1}GB · 카드 {2}GB", gb(used), gb(info.needs_gb), gb(total))}
      </em>
    </div>
  );
}

export function WayOut({ info, busy, onRetry, onSmaller }: {
  info: WayOutInfo;
  busy?: boolean;
  onRetry?: () => void;
  onSmaller?: (smaller: NonNullable<WayOutInfo["smaller"]>) => void;
}) {
  const { close, smaller } = info;
  const cannotFit = close.would_fit === false;
  return (
    <section className="wayout" role="alert" data-testid="way-out">
      <header className="wayout-head">
        <b>{t("「{0}」 모델을 그래픽카드에 다 올리지 못했습니다", info.model_name)}</b>
        <span>{t("기존 모델은 그대로 두었습니다. 아래 둘 가운데 하나로 이어 갈 수 있습니다.")}</span>
      </header>
      <MemoryBar info={info} />
      <div className="wayout-ways">
        <article className="wayout-way" data-testid="way-out-close">
          <h4>{cannotFit ? t("프로그램을 닫아도 들어가지 않습니다") : t("그래픽카드를 비우고 다시 재기")}</h4>
          {cannotFit ? (
            <p>{t("이 모델은 가장 작은 창으로도 {0}GB 가 필요한데, 이 그래픽카드는 {1}GB 입니다.", gb(info.needs_gb), gb(info.card.total_gb))}</p>
          ) : (
            <>
              {close.apps.length ? (
                <>
                  <p>{t("지금 그래픽카드를 쓰는 프로그램입니다. 닫은 뒤 다시 재 보세요.")}</p>
                  <ul className="wayout-apps">{close.apps.map((name) => <li key={name}>{name}</li>)}</ul>
                </>
              ) : (
                <p>{t("그래픽카드를 쓰는 다른 프로그램(게임 · 영상 편집 · 다른 AI 프로그램)을 닫은 뒤 다시 재 보세요.")}</p>
              )}
              <p className="wayout-note">
                {close.would_fit == null
                  ? t("닫으면 들어가는지는 재 보지 못했습니다. 저장하지 않은 작업은 먼저 저장하세요 — Sonjari는 다른 프로그램을 끄지 않습니다.")
                  : t("저장하지 않은 작업은 먼저 저장하세요 — Sonjari는 다른 프로그램을 끄지 않습니다.")}
              </p>
              {onRetry ? (
                <button type="button" className="wayout-btn" disabled={busy} onClick={onRetry}>
                  {t("닫았어요 — 다시 재기")}
                </button>
              ) : null}
            </>
          )}
        </article>
        <article className="wayout-way" data-testid="way-out-smaller">
          <h4>{t("더 작은 모델로 가기")}</h4>
          {smaller ? (
            <>
              <p>
                <b>{smaller.name}</b>
                <span className="num wayout-meta">
                  {t("필요 {0}GB · 창 {1}K", gb(smaller.needs_gb), Math.round(smaller.num_ctx / 1024))}
                  {smaller.text_only ? ` · ${t("글만 읽기(그림 읽기 끔)")}` : ""}
                  {" · "}
                  {smaller.installed ? t("이미 받아 둠") : t("받을 크기 {0}GB", gb(smaller.download_gb))}
                </span>
              </p>
              <p className="wayout-note">
                {smaller.weak_at
                  ? t("지금 빈 자리에 들어갑니다. 약한 점: {0}", smaller.weak_at)
                  : t("지금 빈 자리에 들어갑니다.")}
              </p>
              {onSmaller ? (
                <button type="button" className="wayout-btn" disabled={busy} onClick={() => onSmaller(smaller)}>
                  {smaller.installed ? t("이 모델로 바꾸기") : t("이 모델 받기")}
                </button>
              ) : null}
            </>
          ) : (
            <p>{t("지금 빈 자리에 들어가는 더 작은 모델을 찾지 못했습니다. 그래픽카드를 비운 뒤 다시 재 보세요.")}</p>
          )}
        </article>
      </div>
    </section>
  );
}

/** 이 실패에 두 길을 보여 줄 수 있나 — 백엔드가 재료를 실어 보냈을 때만. */
export function hasWayOut(applied: { error?: string; way_out?: WayOutInfo | Record<string, never> } | null | undefined): applied is { way_out: WayOutInfo } {
  const info = applied?.way_out as WayOutInfo | undefined;
  return Boolean(info && info.model_key && info.close && info.card);
}
