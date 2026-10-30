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
 * - recipe-learn  `/레시피` — 사람이 손자리 크롬에서 한 번 해 보이면 걸음이 쌓이고, 저장 전에 손자리가 그대로 한 번 해 보고 「검증됨」.
 *                 진짜 부품(`/` 명령 목록 · 「배우는 중」 칸)에 2026-10-28 운영에서 실제로 저장된 위키 검색 레시피(3걸음 · 검증됨)를 흘린다.
 * - smart-fast    처음 설정의 두 카드 — 「똑똑함」 Swift 27B · 「빠름」 Qwen 3.6 2비트. 숫자는 목록(`model_catalog.py`)에 적힌 잰 값만.
 * - notify        윈도우 알림 셋(끝났어요 · 기다려요 · 막혔어요). 그림은 진짜 알림이 쓰는 그림(`src-tauri/icons/notify/`), 문구는 `notify.ts` 의 꼴.
 *
 * 예시 장표는 `scripts/build_whats_new_show.py` 가 제품과 같은 길(결 추천 · 결 CSS · 크기 맞춤)로 만든다(`whatsNewShow.fixture.json`).
 * 움직임을 줄인 사람에게는 마지막 모습만 보인다.
 */
import { lang, t } from "../i18n";
import { useReducedMotion } from "framer-motion";
import { Check, FileText, Globe, Hand, Loader2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { WhatsNewShow as ShowVisual } from "../types";
import { applyDeckEvent, DeckStage, type DeckState } from "./DeckStage";
import { withSlideFonts } from "./slideFonts";
import { useBeats } from "./showKit";
import { applyLearnEvent, idleLearn, slashMenu, type LearnState } from "../recipeLearn";
import { RecipeLearnPanel, SlashMenu } from "./RecipeLearnPanel";
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

export function WhatsNewShowStage({ visual }: { visual: ShowVisual }) {
  return (
    <div className="wns" data-scene={visual.scene}>
      <span className="wns-example">{t("예시 화면")}</span>
      {visual.scene === "claude-hands" && <ClaudeHandsScene />}
      {visual.scene === "deck-build" && <DeckBuildScene />}
      {visual.scene === "pptx-fonts" && <FontWipeScene />}
      {visual.scene === "recipe-learn" && <RecipeLearnScene />}
      {visual.scene === "smart-fast" && <SmartFastScene />}
      {visual.scene === "notify" && <NotifyScene />}
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

// ── ④ 한 번 보여 주면 배운다 — `/레시피` ─────────────────────────────────────────────────

//                  /레시피  보냄  걸음1 걸음2 걸음3 다했어 확인1 확인2 확인3 저장
const RECIPE_BEATS = [900, 1900, 2900, 3900, 4900, 6100, 6900, 7700, 8500, 9400];
const WIKI_HOST = "ko.wikipedia.org";

/** 박자마다의 「배우는 중」 칸 — 진짜 칸이 받는 것과 같은 사건을 차례로 흘린다(`applyLearnEvent`). */
function learnAt(phase: number): LearnState {
  const field = t("위키백과 검색");
  let state = idleLearn;
  if (phase < 2) return state;
  state = applyLearnEvent(state, "demo_started", { label: t("위키 검색") });
  const steps = [
    { n: 1, kind: "nav", name: "", where: WIKI_HOST },
    { n: 2, kind: "fill", name: field, where: WIKI_HOST },
    { n: 3, kind: "press", name: field, where: WIKI_HOST },
  ];
  for (const step of steps.slice(0, Math.min(3, phase - 2))) state = applyLearnEvent(state, "demo_step", step);
  if (phase < 6 || phase >= 10) return phase >= 10 ? idleLearn : state;
  state = applyLearnEvent(state, "demo_replay_started", { total: 3 });
  const rows = [
    t("{0} 대문을 연다", WIKI_HOST),
    t("「{0}」 칸에 {1} 을 넣는다", field, t("로봇")),
    t("Enter 를 누른다  → 확인: 주소가 바뀐다"),
  ];
  rows.forEach((text, i) => {
    if (phase >= 6 + i) state = applyLearnEvent(state, "demo_replay_step", { n: i + 1, text, ok: phase >= 7 + i ? true : null });
  });
  return state;
}

function RecipeLearnScene() {
  const [phase] = useBeats(RECIPE_BEATS, 13500);
  const command = lang() === "en" ? "/recipe" : "/레시피";
  const draft = phase === 0 ? "/" : phase === 1 ? `${command} ${t("위키 검색")}` : "";
  const learning = phase >= 2 && phase < 6;
  const replaying = phase >= 6 && phase < 10;
  const saved = phase >= 10;
  // 브라우저 화면: 사람이 보일 때는 걸음 2 · 3, 손자리가 해 볼 때는 확인 2 · 3 에서 같은 모습이 된다.
  const typed = (learning && phase >= 4) || (replaying && phase >= 8) || saved;
  const article = (learning && phase >= 5) || (replaying && phase >= 9) || saved;
  return (
    <div className="wns-recipe">
      <section className="wns-recipe-chat" aria-label={t("앱 대화창")}>
        {phase >= 2 && <p className="wns-you">{command} {t("위키 검색")}</p>}
        <div className="wns-recipe-panel">
          <RecipeLearnPanel state={learnAt(phase)} onDone={() => undefined} onCancel={() => undefined} />
          <p className={`wns-recipe-saved${saved ? " is-on" : ""}`}>
            <Check size={14} aria-hidden />
            <b>{t("검증된 레시피로 저장")}</b>
            <span>{t("위키 검색 · 3걸음 · 다음부터 「위키에서 ○○ 찾아 줘」")}</span>
          </p>
        </div>
        <form className="wns-recipe-composer" onSubmit={(event) => event.preventDefault()}>
          <SlashMenu items={slashMenu(draft, lang())} index={0} onPick={() => undefined} />
          <div className="wns-recipe-draft">{draft || <span>{t("Sonjari에게 메시지를 보내거나 파일을 맡겨보세요")}</span>}</div>
        </form>
      </section>

      <section className="wns-machine wns-recipe-browser" aria-label={t("손자리 크롬")}>
        <header className="wns-pc-head">
          <b>{t("손자리 크롬")}</b>
          <span>{learning ? t("사람이 보여 주는 중") : replaying ? t("손자리가 그대로 해 보는 중") : saved ? t("배운 대로 함") : t("기다리는 중")}</span>
        </header>
        <div className={`wns-band${learning ? " is-learning" : replaying ? " is-replay" : ""}`}>
          {learning ? <><i aria-hidden />{t("배우는 중")}<em>{t("다 했어")}</em><em>{t("취소")}</em></>
            : replaying ? <><Loader2 size={12} className="spin" aria-hidden />{t("한 번 해 보는 중")}</> : null}
        </div>
        <div className={`wns-browser${phase >= 2 ? " is-on" : ""}`} aria-hidden>
          <p className="wns-url"><Globe size={11} />{article ? `${WIKI_HOST}/wiki/${t("로봇")}` : `${WIKI_HOST}/wiki/${t("위키백과:대문")}`}</p>
          {article ? (
            <div className="wns-wiki">
              <b>{t("로봇")}</b>
              {[92, 78, 86, 64, 80].map((width, i) => <span key={i} style={{ width: `${width}%` }} />)}
            </div>
          ) : (
            <div className="wns-wiki is-home">
              <p className={`wns-search${typed ? " is-typed" : ""}`}><Globe size={11} aria-hidden />{typed ? t("로봇") : t("위키백과 검색")}</p>
              {[70, 55, 62].map((width, i) => <span key={i} style={{ width: `${width}%` }} />)}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

// ── ⑤ 똑똑한 모델 · 빠른 모델 ─────────────────────────────────────────────────────────

function SmartFastScene() {
  const [phase] = useBeats([400, 1300, 2400], 9000);
  const cards = [
    { role: "smart", badge: t("똑똑함"), name: "Swift 1.5 · Qwen 3.8 27B", fact: t("코드 과제 12개 중 12개"), fit: t("어려운 일 · 코드 · 긴 조사") },
    { role: "fast", badge: t("빠름"), name: t("Qwen 3.6 35B-A3B (2비트)"), fact: t("코드 과제 12개 중 10개 · 초당 116토큰"), fit: t("빨리 끝낼 일 · 짧은 조사") },
  ];
  return (
    <div className="wns-models">
      <p className="wns-models-head">{t("이 PC 에 들어가는 모델 둘")}</p>
      <div className="wns-models-row">
        {cards.map((card, i) => (
          <article key={card.role} className={`wns-model is-${card.role}${phase >= i + 1 ? " is-on" : ""}${phase >= 3 ? " is-badged" : ""}`}>
            <span className="wns-model-badge">{card.badge}</span>
            <h3>{card.name}</h3>
            <p className="wns-model-fact">{card.fact}</p>
            <p className="wns-model-fit">{card.fit}</p>
          </article>
        ))}
      </div>
      <small className="wns-models-basis">{t("같은 바깥 코드 과제 12개 · 창 64K · 과제마다 한 판 · 속도는 RTX 3090")}</small>
    </div>
  );
}

// ── ⑥ 끝나면 알려 드린다 — 윈도우 알림 ────────────────────────────────────────────────

const HERO = {
  done: {
    ko: new URL("../../src-tauri/icons/notify/hero_done_ko.png", import.meta.url).href,
    en: new URL("../../src-tauri/icons/notify/hero_done_en.png", import.meta.url).href,
  },
  waiting: {
    ko: new URL("../../src-tauri/icons/notify/hero_waiting_ko.png", import.meta.url).href,
    en: new URL("../../src-tauri/icons/notify/hero_waiting_en.png", import.meta.url).href,
  },
  stuck: {
    ko: new URL("../../src-tauri/icons/notify/hero_stuck_ko.png", import.meta.url).href,
    en: new URL("../../src-tauri/icons/notify/hero_stuck_en.png", import.meta.url).href,
  },
};

function NotifyScene() {
  // 알림 셋이 차례로 오른쪽 아래에서 올라온다. 박자 0 은 빈 화면(다른 일 하는 중).
  const [phase] = useBeats([900, 4100, 7300], 10500);
  const language = lang() === "en" ? "en" : "ko";
  const toasts = [
    { key: "done" as const, from: t("조사"), title: t("이번 주 국내 AI 소식 5개 장표로"), body: t("끝났습니다"), buttons: [t("열기"), t("결과 폴더")] },
    { key: "waiting" as const, from: t("대화"), title: t("쿠팡 장바구니 담기"), body: t("로그인이 필요해요 — 크롬 창에서 로그인해 주세요."), buttons: [t("열기")] },
    { key: "stuck" as const, from: t("코드"), title: t("주간 보고 엑셀 정리"), body: t("끝내지 못했습니다 — 그래픽카드가 가득 차 있어 다른 프로그램을 닫은 뒤 「이어서 해줘」라고 보내 주세요"), buttons: [t("열기")] },
  ];
  const shown = phase >= 1 ? toasts[Math.min(phase, 3) - 1] : null;
  return (
    <div className="wns-notify">
      <div className="wns-desk" aria-hidden>
        <div className="wns-desk-window"><i /><span style={{ width: "62%" }} /><span style={{ width: "80%" }} /><span style={{ width: "48%" }} /></div>
        <p>{t("다른 일 하는 중")}</p>
      </div>
      {shown && (
        <div key={shown.key} className={`wns-toast is-${shown.key}`} role="img" aria-label={`${shown.title} — ${shown.body}`}>
          <p className="wns-toast-app"><i aria-hidden />Sonjari · {shown.from}</p>
          <img src={HERO[shown.key][language]} alt="" />
          <b>{shown.title}</b>
          <p className="wns-toast-body">{shown.body}</p>
          <div className="wns-toast-buttons">{shown.buttons.map((label) => <span key={label}>{label}</span>)}</div>
        </div>
      )}
    </div>
  );
}
