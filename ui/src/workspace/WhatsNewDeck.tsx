import { t } from "../i18n";
import { ChevronLeft, ChevronRight, MessageSquareText, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { WhatsNewSlide, WhatsNewStat } from "../types";
import { MarkdownView } from "../MarkdownView";
import "./whatsNew.css";

/**
 * **업데이트 뒤 「바뀐 것」 슬라이드** (2026-10-21 대표 「그림에 글을 넣어 피피티마냥 한눈에 알아보고 이쁘게」).
 *
 * 0.4.29.0 의 목록은 22줄이었다 — 아무도 안 읽는다. 한 장에 하나만: 위에 그림이나 전 · 후 막대, 아래 큰 제목 · 한두 문장 ·
 * 「이렇게 말해 보세요」. 긴 목록은 버리지 않고 마지막 장 뒤에 접어 둔다.
 *
 * - 「나중에 보기」 · Esc · 바깥 누르기 · X = 닫기만. 위의 한 줄은 남고, 다음에 켜면 다시 뜬다.
 * - 마지막 장의 「다 봤어요」 = 「봤다」를 적는다(위 한 줄의 「닫기」와 같다).
 * - 숫자 막대에는 잰 조건(`basis`)이 늘 붙는다 — 백엔드가 조건 없는 숫자는 장에서 뺀다.
 * - 그림이 없는 장은 「이렇게 말해 보세요」를 위쪽 칸에 크게 둔다. 그린 가짜 화면은 넣지 않는다.
 */
export function WhatsNewDeck({ version, slides, changes, tour, onLater, onDone }: {
  version: string;
  slides: WhatsNewSlide[];
  changes: string;
  tour: string;
  onLater: () => void;
  onDone: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const primary = useRef<HTMLButtonElement>(null);
  const count = slides.length;
  const last = index === count - 1;
  const slide = slides[Math.min(index, count - 1)];

  const go = useCallback((next: number) => {
    setIndex(Math.max(0, Math.min(count - 1, next)));
    setShowAll(false);
  }, [count]);

  // 열린 동안 키보드: ← → 로 넘기고 Esc 로 닫는다. 닫히면 연 단추로 초점을 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    primary.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onLater(); }
      else if (event.key === "ArrowRight") { event.preventDefault(); setIndex((value) => Math.min(count - 1, value + 1)); setShowAll(false); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); setIndex((value) => Math.max(0, value - 1)); setShowAll(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [count, onLater]);

  if (!slide) return null;
  const visual = slide.visual;
  // 그림 · 막대가 없는 장은 「이렇게 말해 보세요」가 위쪽 칸의 주인공이다. 둘 다 없으면 위쪽 칸을 접는다.
  const sayOnStage = !visual && !!slide.try;
  const stage = !showAll && (visual || sayOnStage);

  return (
    <div className="settings-veil wn-veil" role="presentation" onClick={onLater}>
      <section className="wn-deck" role="dialog" aria-modal="true" aria-labelledby="wn-title"
        onClick={(event) => event.stopPropagation()}>
        <header className="wn-head">
          <span className="wn-eyebrow"><Sparkles size={13} aria-hidden /> {t("Sonjari {0} 에서 바뀐 것", version)}</span>
          <button type="button" className="settings-close" onClick={onLater} aria-label={t("나중에 보기")}><X size={16} /></button>
        </header>

        {stage && (
          <div className={`wn-stage ${visual ? `wn-stage-${visual.kind}` : "wn-stage-say"}`} key={`stage-${index}`}>
            {visual?.kind === "stat" && <StatBars stat={visual} />}
            {visual?.kind === "image" && <img src={`${import.meta.env.BASE_URL}${visual.src}`} alt={visual.alt} />}
            {sayOnStage && <SayStage text={slide.try ?? ""} />}
          </div>
        )}

        <div className="wn-copy" key={`copy-${index}`} aria-live="polite">
          <h2 id="wn-title">{slide.title}</h2>
          <p className="wn-body">{slide.body}</p>
          {slide.try && !sayOnStage && (
            <p className="wn-try"><MessageSquareText size={15} aria-hidden /><span><Said text={slide.try} /></span></p>
          )}
          {slide.try && sayOnStage && showAll && (
            <p className="wn-try"><MessageSquareText size={15} aria-hidden /><span><Said text={slide.try} /></span></p>
          )}
          {last && (changes || tour) && (
            <button type="button" className="wn-all-toggle" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>
              {showAll ? t("접기") : t("바뀐 것 전부 보기")}
              <ChevronRight size={14} aria-hidden className={showAll ? "wn-turned" : ""} />
            </button>
          )}
          {last && showAll && (
            <div className="wn-all">
              {changes && <MarkdownView>{changes}</MarkdownView>}
              {tour && <MarkdownView className="whats-new-tour">{tour}</MarkdownView>}
              <p className="whats-new-hint">{t("대화창에 「뭐가 바뀌었어?」라고 물어도 다시 볼 수 있습니다.")}</p>
            </div>
          )}
        </div>

        <footer className="wn-foot">
          <button type="button" className="wn-ghost wn-later" onClick={onLater}>{t("나중에 보기")}</button>
          <div className="wn-dots">
            {slides.map((item, at) => (
              <button key={at} type="button" className={at === index ? "on" : ""} onClick={() => go(at)}
                aria-label={t("{0}번째 장: {1}", at + 1, item.title)} aria-current={at === index ? "step" : undefined} />
            ))}
          </div>
          <div className="wn-steps">
            {index > 0 && (
              <button type="button" className="wn-ghost" onClick={() => go(index - 1)}>
                <ChevronLeft size={15} aria-hidden /> {t("이전")}
              </button>
            )}
            <button type="button" className="wn-primary" ref={primary} onClick={last ? onDone : () => go(index + 1)}>
              {last ? t("다 봤어요") : <>{t("다음")} <ChevronRight size={15} aria-hidden /></>}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

/**
 * 「이렇게 말해 보세요」 안의 **말할 문장**(「…」 · "…")만 칩으로 띄운다 — 사람이 그대로 따라 칠 부분이 한눈에 보이게.
 * 따옴표가 없으면(「설정 › 실험실 › …」 같은 안내) 글 그대로다.
 */
function Said({ text }: { text: string }) {
  const parts = text.split(/(「[^」]+」|"[^"]+")/);
  return <>{parts.map((part, at) => (/^(「.*」|".*")$/.test(part)
    ? <q key={at} className="wn-q">{part.slice(1, -1)}</q>
    : <span key={at}>{part}</span>))}</>;
}

/**
 * 그림이 없는 장의 위쪽 칸 — 따라 말할 문장을 **말풍선으로 위에서 아래로** 쌓는다(대화창에 치는 차례 그대로).
 * 「이렇게 말해 보세요: 「A」, 다 하시면 「B」」 → 머리 「이렇게 말해 보세요」 · 풍선 A · 작은 이음말 「다 하시면」 · 풍선 B.
 * 따옴표가 없으면(설정 위치 안내 등) 글을 크게 그대로 둔다.
 */
function SayStage({ text }: { text: string }) {
  const parts = text.split(/(「[^」]+」|"[^"]+")/);
  const isQuote = (part: string) => /^(「.*」|".*")$/.test(part);
  if (!parts.some(isQuote)) {
    return <p className="wn-say"><MessageSquareText size={22} aria-hidden /><span>{text}</span></p>;
  }
  const tidy = (part: string) => part.replace(/^[\s,.:：·]+|[\s,.:：·]+$/g, "");
  const head = tidy(parts[0]);
  const rest = parts.slice(1);
  return (
    <div className="wn-bubbles">
      {head && <p className="wn-bubbles-head"><MessageSquareText size={15} aria-hidden /> {head}</p>}
      {rest.map((part, at) => {
        if (isQuote(part)) return <q key={at} className="wn-bubble">{part.slice(1, -1)}</q>;
        const between = tidy(part);
        return between ? <span key={at} className="wn-bubble-join">{between}</span> : null;
      })}
    </div>
  );
}

/** 전 · 후 막대. 긴 쪽이 칸을 다 쓰고 짧은 쪽은 그 비율로 — 숫자는 기계가 잰 값이라 고정폭 글꼴이다. */
function StatBars({ stat }: { stat: WhatsNewStat }) {
  const longest = Math.max(stat.before, stat.after) || 1;
  const width = (value: number) => `${Math.max(2, (value / longest) * 100)}%`;
  const show = (value: number) => `${value.toFixed(1)}${stat.unit}`;
  // 숫자는 고정폭(기계가 잰 값), 단위는 보통 글꼴 — 고정폭 글꼴엔 한글이 없어 「초」만 다른 글꼴로 튄다.
  const shown = (value: number) => <>{value.toFixed(1)}<small className="wn-unit">{stat.unit}</small></>;
  const change = stat.before > 0 ? Math.round(((stat.after - stat.before) / stat.before) * 100) : 0;
  return (
    <figure className="wn-stat" aria-label={`${stat.label}: ${show(stat.before)} → ${show(stat.after)}`}>
      <figcaption>{stat.label}</figcaption>
      <p className="wn-stat-head" aria-hidden>
        <span className="wn-stat-before">{shown(stat.before)}</span>
        <ChevronRight size={22} />
        <strong>{shown(stat.after)}</strong>
        {change !== 0 && <em>{change > 0 ? "+" : "−"}{Math.abs(change)}%</em>}
      </p>
      <div className="wn-bars" aria-hidden>
        <span>{t("전")}</span><i className="wn-bar"><b style={{ width: width(stat.before) }} /></i>
        <span>{t("후")}</span><i className="wn-bar wn-bar-after"><b style={{ width: width(stat.after) }} /></i>
      </div>
      <small className="wn-basis">{stat.basis}</small>
    </figure>
  );
}
