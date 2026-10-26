/**
 * 업데이트 「바뀐 것」 슬라이드의 **쇼** (2026-10-26 대표 「영상 말고 프론트로 진짜 보여 주면 되잖아 · 와우 포인트」).
 *
 * 영상 대신 앱의 진짜 화면 조각을 예시 데이터로 움직인다 — 선명하고(그대로 그린다), 가볍고(영상 파일 없음), 두 언어가 되고,
 * 화면이 바뀌면 같이 바뀐다. 진짜 결과로 착각하지 않게 「예시 화면」 표시가 늘 붙는다.
 *
 * - claude-hands  사람 쪽(따뜻한 바닥)의 클로드가 「손자리에게 맡김」 → 실 한 가닥이 기계 쪽(찬 바닥)으로 건너가 「손자리가 받았습니다」
 *                 → 이 PC 가 기사를 읽고 → 결과만 실을 타고 돌아온다 → 영수증. 이 업데이트의 한 문장을 눈으로 보이는 장면.
 * - deck-build    진짜 장표 칸(`DeckStage`)에 예시 사건을 흘린다 — 결 셋 → 고름 → 이야기판 → 장이 한 장씩 지어짐.
 * - pptx-fonts    같은 표지를 0.4.33 의 결(윈도우 글꼴)과 지금(앱 글꼴)으로 그려, 금이 왼쪽에서 오른쪽으로 쓸며 바뀐다.
 *
 * 예시 장표는 `scripts/build_whats_new_show.py` 가 제품과 같은 길(결 추천 · 결 CSS · 크기 맞춤)로 만든다(`whatsNewShow.fixture.json`).
 * 움직임을 줄인 사람에게는 마지막 모습만 보인다.
 */
import { t } from "../i18n";
import { useReducedMotion } from "framer-motion";
import { Check, FileText, Globe, Hand, Loader2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { WhatsNewShow as ShowVisual } from "../types";
import { applyDeckEvent, DeckStage, type DeckState } from "./DeckStage";
import { withSlideFonts } from "./slideFonts";
import fixture from "./whatsNewShow.fixture.json";
import "./whatsNewShow.css";

type Fixture = {
  title: string; chosen: string; say: string;
  picks: { theme: string; name: string; why?: string; html: string }[];
  outline: { layout: string; claim: string }[];
  slides: { html: string; note: string }[];
  font_before: string;
};
const F = fixture as Fixture;

/** 박자: `beats` 의 시각(ms)마다 한 단계씩 올라가고 `loop` 뒤 처음부터. 움직임을 줄였으면 마지막 단계 그대로. */
function useBeats(beats: number[], loop: number): [number, number] {
  const still = Boolean(useReducedMotion());
  const [phase, setPhase] = useState(still ? beats.length : 0);
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (still) { setPhase(beats.length); return; }
    const timers: number[] = [];
    const run = () => {
      setPhase(0);
      setRound((value) => value + 1);
      beats.forEach((at, i) => timers.push(window.setTimeout(() => setPhase(i + 1), at)));
      timers.push(window.setTimeout(run, loop));
    };
    run();
    return () => timers.forEach((id) => window.clearTimeout(id));
    // 박자표는 장면마다 고정이다 — 다시 돌릴 까닭은 움직임 설정뿐.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [still]);
  return [phase, round];
}

export function WhatsNewShowStage({ visual }: { visual: ShowVisual }) {
  return (
    <div className="wns" data-scene={visual.scene}>
      <span className="wns-example">{t("예시 화면")}</span>
      {visual.scene === "claude-hands" && <ClaudeHandsScene />}
      {visual.scene === "deck-build" && <DeckBuildScene />}
      {visual.scene === "pptx-fonts" && <FontWipeScene />}
    </div>
  );
}

// ── ① 클로드가 생각하고, 손자리가 손을 쓴다 ─────────────────────────────────────────────

const ARTICLES = 5;
//            계획   맡김   받음   기사 다섯(0.45초씩)              돌아옴  장표   영수증
const HANDS_BEATS = [500, 1300, 2100, 2600, 3050, 3500, 3950, 4400, 5100, 5900, 6700];

function ClaudeHandsScene() {
  const [phase] = useBeats(HANDS_BEATS, 11000);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const fromRef = useRef<HTMLLIElement | null>(null);
  const toRef = useRef<HTMLDivElement | null>(null);
  const [path, setPath] = useState("");
  const [span, setSpan] = useState({ x1: 0, x2: 1 });

  // 실의 모양 — 「맡김」 줄의 오른쪽 끝에서 「받았습니다」 칸의 왼쪽 끝까지. 칸 크기가 바뀌면 다시 잰다.
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => {
      const from = fromRef.current?.getBoundingClientRect();
      const to = toRef.current?.getBoundingClientRect();
      const base = box.getBoundingClientRect();
      if (!from || !to) return;
      const x1 = from.right - base.left - 6, y1 = from.top + from.height / 2 - base.top;
      const x2 = to.left - base.left + 2, y2 = to.top + to.height / 2 - base.top;
      const bend = Math.max(30, (x2 - x1) * 0.55);
      setPath(`M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + bend).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - bend).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`);
      setSpan({ x1, x2 });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  const planned = phase >= 1;
  const handed = phase >= 2;
  const received = phase >= 3;
  const read = Math.max(0, Math.min(ARTICLES, phase - 3));
  const returned = phase >= 9;
  const drafting = phase >= 10;
  const receipt = phase >= 11;

  return (
    <div className="wns-hands" ref={boxRef}>
      <section className="wns-human" aria-label={t("클로드 쪽")}>
        <p className="wns-chip"><i className="wns-dot-claude" aria-hidden />Claude Agent · Sonnet 5.5</p>
        <p className="wns-you">{t("이번 주 국내 AI 소식 5개 찾아서 장표로 만들어 줘")}</p>
        <ol className="wns-steps">
          <li className={planned ? "is-done" : "is-on"}>
            {planned ? <Check size={13} aria-hidden /> : <Loader2 size={13} className="spin" aria-hidden />}
            {t("계획 세우기")}
          </li>
          <li ref={fromRef} className={`wns-handoff${handed ? " is-on" : ""}${returned ? " is-done" : ""}`}>
            {returned ? <Check size={13} aria-hidden /> : <Hand size={13} aria-hidden />}
            <span>{t("손자리에게 맡김")} <small>{t("웹에서 기사 다섯 읽기")}</small></span>
          </li>
          <li className={drafting ? (receipt ? "is-done" : "is-on") : "is-wait"}>
            {receipt ? <Check size={13} aria-hidden /> : drafting ? <Loader2 size={13} className="spin" aria-hidden /> : <i className="wns-hollow" aria-hidden />}
            {t("받은 결과로 장표 짜기")}
          </li>
        </ol>
        {/* 영수증 — 이 장면의 끝맺음. 두 숫자를 크게: 생각한 값과 손을 쓴 값. */}
        <div className={`wns-receipt${receipt ? " is-on" : ""}`}>
          <p className="wns-cost wns-cost-claude"><span>{t("클로드")}</span><b>$0.07</b></p>
          <p className="wns-cost wns-cost-local"><span>{t("손자리 · 내 PC 26걸음")}</span><b>{t("0원")}</b></p>
          <small>{t("10월 26일 실제 판의 영수증")}</small>
        </div>
      </section>

      <section className="wns-machine" aria-label={t("손자리의 컴퓨터")}>
        <header className="wns-pc-head">
          <b>{t("손자리의 컴퓨터")}</b>
          <span>{t("내 PC · Qwen3.8 27B")}</span>
        </header>
        <div ref={toRef} className={`wns-got${received ? " is-on" : ""}`}>
          <Hand size={14} aria-hidden />
          <span>{received ? t("손자리가 받았습니다") : t("기다리는 중")}</span>
          {received && <small>{t("클로드가 맡긴 일")}</small>}
        </div>
        <div className={`wns-browser${received ? " is-on" : ""}`} aria-hidden>
          <p className="wns-url"><Globe size={11} />{read < ARTICLES ? t("기사 {0}/{1} 읽는 중", Math.max(1, read + (received ? 1 : 0)), ARTICLES) : t("기사 {0}개 다 읽음", ARTICLES)}</p>
          <ul>
            {Array.from({ length: ARTICLES }, (_, i) => (
              <li key={i} className={i < read ? "is-read" : i === read && received ? "is-reading" : ""}>
                <i /><span style={{ width: `${58 + ((i * 17) % 34)}%` }} />{i < read && <Check size={11} />}
              </li>
            ))}
          </ul>
        </div>
        <p className={`wns-private${returned ? " is-on" : ""}`}>{t("페이지 원문은 이 PC 에 남고, 결과만 클로드에게 갑니다")}</p>
      </section>

      {path && (
        <svg className="wns-thread" aria-hidden>
          <defs>
            {/* 실 — 사람 쪽(클로드의 색)에서 기계 쪽(손자리의 색)으로 온도가 바뀐다. */}
            <linearGradient id="wns-thread-go" gradientUnits="userSpaceOnUse" x1={span.x1} y1="0" x2={span.x2} y2="0">
              <stop offset="0" stopColor="rgb(var(--origin-claude))" />
              <stop offset="1" stopColor="rgb(var(--brand-bright))" />
            </linearGradient>
          </defs>
          <path d={path} className="wns-thread-rest" />
          <path d={path} pathLength={1} className={`wns-thread-go${handed ? " is-on" : ""}`} stroke="url(#wns-thread-go)" />
          {handed && !received && <circle r="4.5" className="wns-bead wns-bead-go" style={{ offsetPath: `path("${path}")` }} />}
          {returned && !receipt && <circle r="4.5" className="wns-bead wns-bead-back" style={{ offsetPath: `path("${path}")` }} />}
        </svg>
      )}
    </div>
  );
}

// ── ② 장표를 같이 만든다 — 진짜 장표 칸에 예시 사건 ─────────────────────────────────────

const SLIDE_GAP = 5400;  // 장 하나가 다 지어지는 시간(짓는 연출 · DeckStage)보다 길게
// 글(t)은 그릴 때 읽는다 — 모듈을 읽는 순간에는 화면 언어가 아직 안 정해졌을 수 있다.
const deckEvents = (): [number, string, Record<string, unknown>][] => [
  [200, "deck_themes", { picks: F.picks, say: t(F.say), chosen: F.chosen, wait_s: 2.6 }],
  [2700, "deck_theme_set", { theme: F.chosen, by: "person" }],
  [3100, "deck_outline", { cards: F.outline, say: t("숫자 장을 가운데에 두었습니다"), wait_s: 2.2 }],
  [5300, "deck_outline_set", { cards: F.outline, by: "person" }],
  ...F.slides.map((slide, i): [number, string, Record<string, unknown>] =>
    [5600 + i * SLIDE_GAP, "deck_slide", { index: i + 1, total: F.slides.length, html: slide.html, note: slide.note, theme: F.chosen }]),
  [5600 + F.slides.length * SLIDE_GAP, "deck_built", { path: `${F.title}.pptx`, slides: F.slides.length }],
];

function DeckBuildScene() {
  const still = Boolean(useReducedMotion());
  const [events] = useState(deckEvents);
  const [deck, setDeck] = useState<DeckState | undefined>(() =>
    still ? events.reduce<DeckState | undefined>((now, [, event, payload]) => applyDeckEvent(now, event, { title: F.title, ...payload }), undefined) : undefined);
  useEffect(() => {
    if (still) return;
    const timers: number[] = [];
    const run = () => {
      setDeck(undefined);
      for (const [at, event, payload] of events) {
        timers.push(window.setTimeout(() => setDeck((now) => applyDeckEvent(now, event, { title: F.title, ...payload })), at));
      }
      timers.push(window.setTimeout(run, events[events.length - 1][0] + 4500));
    };
    run();
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [still, events]);
  return (
    <div className="wns-deck">
      {deck ? <DeckStage deck={deck} pace={0.45} /> : <p className="wns-deck-wait"><Loader2 size={14} className="spin" aria-hidden />{t("장표 일을 받는 중")}</p>}
    </div>
  );
}

// ── ③ 같은 표지, 0.4.33 의 글꼴 → 지금의 글꼴 ──────────────────────────────────────────────

const SLIDE_W = 1280;
const SLIDE_H = 720;

function Slide({ html, width, label }: { html: string; width: number; label: string }) {
  const scale = width / SLIDE_W;
  return (
    <div className="wns-slide" style={{ width, height: SLIDE_H * scale }}>
      <iframe title={label} sandbox="allow-same-origin" srcDoc={withSlideFonts(html)} tabIndex={-1}
        style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})`, transformOrigin: "0 0" }} />
    </div>
  );
}

function FontWipeScene() {
  // 0 옛 글꼴 · 1 금이 쓸고 지나감 · 2 파일 칩 · 3 되돌릴 준비(움직임 없이 처음으로)
  const [phase] = useBeats([700, 3000, 7600], 8200);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(560);
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => {
      // 위쪽 칸 높이에 맞춘다 — 장은 16:9, 파일 칩 자리를 아래에 남긴다.
      const byHeight = Math.max(200, (box.clientHeight - 54) * (SLIDE_W / SLIDE_H));
      setWidth(Math.floor(Math.min(box.clientWidth - 8, byHeight)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, []);
  const wiped = phase >= 1 && phase < 3;
  const resetting = phase === 0 || phase >= 3;
  return (
    <div className="wns-fonts" ref={boxRef}>
      <div className={`wns-wipe${wiped ? " is-wiped" : ""}${resetting ? " is-reset" : ""}`} style={{ width }}>
        <Slide html={F.font_before} width={width} label={t("0.4.33 의 글꼴")} />
        <div className="wns-after">
          <Slide html={F.slides[0].html} width={width} label={t("지금의 글꼴")} />
        </div>
        <span className="wns-seam" aria-hidden />
        <span className="wns-tag wns-tag-before">{t("0.4.33 · 윈도우 글꼴")}</span>
        <span className="wns-tag wns-tag-after">{t("지금 · 앱 글꼴")}</span>
      </div>
      <p className={`wns-file${phase >= 2 && phase < 3 ? " is-on" : ""}`}>
        <FileText size={14} aria-hidden />
        <b>{F.title}.pptx</b>
        <span>{t("쓴 글자만 담아 글꼴을 심었습니다 — 파워포인트에서 열어도 이 모양")}</span>
        <em>+ PDF</em>
      </p>
    </div>
  );
}
