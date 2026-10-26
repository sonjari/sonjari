/**
 * 장표 무대 — 손자리가 장표를 그리는 동안 컴퓨터 칸에서 **사람과 같이 만든다** (2026-10-25 대표 2차 시안).
 *
 * 흐름(백엔드 `slide_inbox` · `local_make_slide` 와 짝):
 *   ① 결 고르기   `deck_themes` — 표지 셋 + 모델의 한 줄 + 남은 시간. 누르면 그 결(`/v1/slides/answer` kind=theme)
 *   ② 이야기판    `deck_outline` — 장마다 「틀 · 한 줄 주장」 카드. 올리기 · 내리기 · 빼기 · 문장 고치기 → 「이대로 만들기」
 *   ③ 만들기      `deck_slide` — 장이 한 장씩 그려지고 손자리의 혼잣말(note)이 뜬다. 다 된 장에 「한마디」(kind=note) · 잠깐 멈춤
 *   ④ 마무리      `deck_built` — PPTX 완성 · 부품으로 조립한 장 수
 * 사람이 아무것도 안 해도 백엔드가 남은 시간 뒤에 권한 결 · 이야기판 그대로 간다. 클로드가 맡긴 판은 기다리지 않는다.
 *
 * 지키는 것
 * - 모델이 쓴 HTML 은 **스크립트가 못 도는 칸**(sandbox 에 allow-scripts 없음)에 넣는다. 백엔드도 `<script>` 를 지우고 보낸다(두 겹).
 *   ★ 2026-10-26: 다 된 장의 칸도 짓는 칸처럼 `allow-same-origin` 만 준다 — 완전히 잠근 칸(`sandbox=""`)은 출처가 없어
 *   본체(127.0.0.1:8091)의 앱 글꼴 요청이 막혀, 글꼴을 기다리는 3초 동안 글이 안 보였고 그 뒤엔 윈도우 글꼴로 그렸다(쇼 연습 화면에서 잼).
 * - 1280×720 장을 칸 폭에 맞춰 줄여 그린다 — 장의 비율 · 배치가 PPT 와 같게 보인다.
 * - 새 장이 오면 그 장으로 따라간다. 사람이 아래 작은 그림을 누르면 그 장에 머문다(다음 장이 와도).
 */
import { t } from "../i18n";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowDown, ArrowUp, Check, FileCheck2, FolderOpen, ImagePlus, Loader2, Pause, Play, Send, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import "./deckStage.css";
import { withSlideFonts } from "./slideFonts";

/** 큐레이션 화면의 추천 결 하나(`deck_themes` · 10-25 대표 「템플릿을 깔아 두고 큐레이션」). */
export type DeckPick = { theme: string; name: string; when?: string; why?: string; html: string };
/** 이야기판 카드 하나 — 장의 틀(또는 parts) · 한 줄 주장. */
export type DeckCard = { layout: string; claim: string };

export type DeckState = {
  title: string;
  total: number;
  slides: Record<number, string>;
  latest: number;
  built?: { path: string; slides?: number; text_boxes?: number; parts?: number; template?: number };
  picks?: DeckPick[];
  theme?: string;
  /** 모델이 사람에게 건넨 한 줄(결 고르기 · 이야기판). */
  say?: string;
  /** 모델이 권한 결. */
  chosen?: string;
  themeBy?: "person" | "default";
  /** 지금 사람의 답을 기다리는 것과 그 끝 시각(ms). */
  ask?: { kind: "theme" | "outline"; until: number };
  outline?: DeckCard[];
  outlineSay?: string;
  outlineBy?: string;
  outlineSettled?: boolean;
  /** 장마다 손자리의 혼잣말. */
  notes?: Record<number, string>;
  /** 장마다 몇 번 그려졌나 — 한마디를 보낸 뒤 다시 그려지면 「고쳤어요」. */
  versions?: Record<number, number>;
  /** 장마다 사진 자리(사람이 끌어다 넣는 칸). */
  slots?: Record<number, DeckSlot[]>;
  /** 사진을 넣어 다시 그려진 판 — 짓는 연출을 다시 틀지 않는다. */
  still?: Record<number, number>;
};

export type DeckSlot = { id: string; label: string; filled: boolean };
export type DeckPhoto = (index: number, slot: string, file: File) => Promise<unknown>;

export type DeckAnswer = (kind: "theme" | "outline" | "note" | "pause" | "resume" | "touch", value?: unknown) => void;

const SLIDE_W = 1280;
const SLIDE_H = 720;

function fresh(title: string, deck: DeckState | undefined, total = 0): DeckState {
  return deck && deck.title === title ? deck : { title, total, slides: {}, latest: 0 };
}

function asCards(value: unknown): DeckCard[] {
  return Array.isArray(value)
    ? (value as Record<string, unknown>[]).map((card) => ({ layout: String(card?.layout ?? ""), claim: String(card?.claim ?? "") }))
      .filter((card) => card.claim || card.layout)
    : [];
}

/** 장표 알림 하나를 상태에 더한다 — 같은 판이면 모으고, 다른 제목이면 새로 시작한다. */
export function applyDeckEvent(
  deck: DeckState | undefined, event: string, payload: Record<string, unknown>, now: number = Date.now(),
): DeckState | undefined {
  const title = String(payload.title ?? "");
  const wait = Number(payload.wait_s ?? 0);
  if (event === "deck_themes") {
    const picks = Array.isArray(payload.picks)
      ? (payload.picks as Record<string, unknown>[]).map((pick) => ({
          theme: String(pick.theme ?? ""), name: String(pick.name ?? ""), when: String(pick.when ?? ""),
          why: String(pick.why ?? ""), html: String(pick.html ?? ""),
        })).filter((pick) => pick.theme && pick.html)
      : [];
    if (!picks.length) return deck;
    const base = fresh(title, deck);
    return { ...base, picks, say: String(payload.say ?? "") || base.say, chosen: String(payload.chosen ?? "") || base.chosen,
             ask: wait > 0 ? { kind: "theme", until: now + wait * 1000 } : undefined };
  }
  if (event === "deck_theme_set") {
    const base = fresh(title, deck);
    return { ...base, theme: String(payload.theme ?? "") || base.theme,
             themeBy: payload.by === "person" ? "person" : "default", ask: base.ask?.kind === "theme" ? undefined : base.ask };
  }
  if (event === "deck_outline") {
    const cards = asCards(payload.cards);
    if (!cards.length) return deck;
    const base = fresh(title, deck);
    return { ...base, outline: cards, outlineSay: String(payload.say ?? ""), outlineSettled: false,
             theme: String(payload.theme ?? "") || base.theme,
             ask: wait > 0 ? { kind: "outline", until: now + wait * 1000 } : undefined };
  }
  if (event === "deck_outline_set") {
    const cards = asCards(payload.cards);
    const base = fresh(title, deck);
    return { ...base, outline: cards.length ? cards : base.outline, outlineSettled: true, outlineBy: String(payload.by ?? ""),
             total: cards.length || base.total, ask: undefined };
  }
  if (event === "deck_slide") {
    const index = Number(payload.index ?? 0);
    const total = Number(payload.total ?? 0);
    if (!index || !total) return deck;
    const base = fresh(title, deck, total);
    const theme = String(payload.theme ?? "") || base.theme;
    const note = String(payload.note ?? "");
    const version = (base.versions?.[index] ?? 0) + 1;
    const slots = Array.isArray(payload.slots)
      ? (payload.slots as Record<string, unknown>[]).map((slot) => ({
          id: String(slot.id ?? ""), label: String(slot.label ?? ""), filled: Boolean(slot.filled),
        })).filter((slot) => slot.id)
      : [];
    const photo = Boolean(payload.photo);
    return {
      ...base, total, latest: photo ? base.latest || index : index, built: photo ? base.built : undefined, theme, ask: undefined,
      slides: { ...base.slides, [index]: String(payload.html ?? "") },
      notes: note ? { ...(base.notes ?? {}), [index]: note } : base.notes,
      versions: { ...(base.versions ?? {}), [index]: version },
      slots: { ...(base.slots ?? {}), [index]: slots },
      still: photo ? { ...(base.still ?? {}), [index]: version } : base.still,
    };
  }
  if (event === "deck_built" && deck) {
    const assembly = (payload.assembly ?? {}) as Record<string, unknown>;
    return { ...deck, built: { path: String(payload.path ?? ""), slides: Number(payload.slides ?? 0) || undefined,
                               text_boxes: Number(payload.text_boxes ?? 0) || undefined,
                               parts: Number(assembly.parts ?? 0) || undefined, template: Number(assembly.template ?? 0) || undefined } };
  }
  return deck;
}

/** 장 안에서 「하나씩 놓을」 요소 — 부품 장이면 머리 · 헤드라인 · 부품마다, 틀째 쓴 장이면 큰 덩어리 안으로 들어가 칸마다. */
export function buildUnits(doc: Document): HTMLElement[] {
  const section = doc.querySelector("section");
  if (!section) return [];
  const parts = Array.from(section.querySelectorAll<HTMLElement>(".ir-head, .ir-lede, .ir-rule, .pz, .pz-bottom, .ir-src"));
  if (parts.length >= 2) return parts.slice(0, 18);
  const out: HTMLElement[] = [];
  const walk = (el: Element, depth: number) => {
    for (const child of Array.from(el.children) as HTMLElement[]) {
      if (child.tagName === "STYLE" || child.classList.contains("folio")) continue;
      const box = child.getBoundingClientRect();
      if (box.width < 8 || box.height < 8) continue;
      const area = (box.width * box.height) / (SLIDE_W * SLIDE_H);
      if (area > 0.3 && child.children.length > 1 && depth < 3) walk(child, depth + 1);
      else out.push(child);
    }
  };
  walk(section, 0);
  return out.slice(0, 16);
}

const pause = (ms: number) => new Promise<void>((done) => window.setTimeout(done, ms));

/**
 * 짓는 연출(10-25 대표 「시안에서는 마우스가 움직이며 실시간으로 만드는 느낌이었는데, 이건 다 된 게 한 장 띡」).
 * 장이 도착하면 요소를 숨기고, 「손자리」 커서가 요소 자리로 가서 하나씩 놓는다. 장 HTML 은 여전히 스크립트를 못 돌린다
 * (sandbox 에 allow-scripts 없음) — 같은 출처만 허락해 손자리 화면이 요소의 자리를 읽고 보이기만 바꾼다.
 */
function BuildFrame({ html, width, label, note, onDone, pace = 1 }: { html: string; width: number; label: string; note?: string; onDone: () => void; pace?: number }) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [ready, setReady] = useState(false);
  const [cursor, setCursor] = useState<{ x: number; y: number; on: boolean }>({ x: 40, y: 40, on: false });
  const scale = width / SLIDE_W;
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let cancelled = false;
    const run = async () => {
      const doc = frame.contentDocument;
      const units = doc ? buildUnits(doc) : [];
      if (!units.length) { setReady(true); doneRef.current(); return; }
      for (const unit of units) {
        unit.style.transition = "opacity .38s ease, transform .38s cubic-bezier(.22,1,.36,1)";
        unit.style.opacity = "0";
        unit.style.transform = "translateY(8px)";
      }
      setReady(true);
      await pause(280 * pace);
      for (const unit of units) {
        if (cancelled) return;
        const box = unit.getBoundingClientRect();
        setCursor({ x: box.left + Math.min(box.width * 0.35, 140), y: box.top + Math.min(box.height * 0.5, 46), on: true });
        await pause(430 * pace);
        if (cancelled) return;
        unit.style.opacity = "1";
        unit.style.transform = "none";
        await pause(240 * pace);
      }
      setCursor((now) => ({ ...now, on: false }));
      doneRef.current();
    };
    let started = false;
    const onLoad = () => { if (!started) { started = true; void run(); } };
    frame.addEventListener("load", onLoad);
    // 효과가 붙기 전에 장이 이미 다 읽혔으면 바로 시작한다 — 아니면 load 를 놓쳐 장이 영영 안 보인다.
    if (frame.contentDocument?.querySelector("section")) onLoad();
    // 그래도 못 시작하면 1.5초 뒤 그냥 보인다(연출보다 장이 먼저다).
    const fallback = window.setTimeout(() => { if (!started) { setReady(true); doneRef.current(); } }, 1500);
    return () => { cancelled = true; window.clearTimeout(fallback); frame.removeEventListener("load", onLoad); };
  }, [html]);
  return (
    <div className="deck-frame deck-build" style={{ width, height: SLIDE_H * scale }}>
      <iframe
        ref={frameRef}
        title={label}
        sandbox="allow-same-origin"
        srcDoc={withSlideFonts(html)}
        tabIndex={-1}
        style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})`, transformOrigin: "0 0", opacity: ready ? 1 : 0 }}
      />
      <div
        className={`deck-cursor${cursor.on ? " is-on" : ""}`}
        style={{ transform: `translate(${cursor.x * scale}px, ${cursor.y * scale}px)` }}
        aria-hidden
      >
        <svg width="18" height="20" viewBox="0 0 18 20"><path d="M1 1 L1 15.5 L5 11.8 L8 18.5 L10.6 17.4 L7.7 10.9 L13 10.9 Z" /></svg>
        <span>{note ? `${t("손자리")} · ${note}` : t("손자리")}</span>
      </div>
    </div>
  );
}

/**
 * 사진 자리가 있는 장 — 장 위에 점선 칸을 겹쳐 그리고, 사람이 사진을 끌어다 놓거나 눌러서 고른다(10-25 대표).
 * 장 HTML 은 스크립트를 못 돌린다(allow-scripts 없음). 같은 출처만 허락해 자리의 위치를 읽는다.
 */
function SlotFrame({ html, width, label, index, slots, onPhoto }: {
  html: string; width: number; label: string; index: number; slots: DeckSlot[]; onPhoto: DeckPhoto;
}) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [boxes, setBoxes] = useState<Record<string, { x: number; y: number; w: number; h: number }>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [over, setOver] = useState<string | null>(null);
  const [error, setError] = useState("");
  const scale = width / SLIDE_W;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const measure = () => {
      const doc = frame.contentDocument;
      if (!doc) return;
      const found: Record<string, { x: number; y: number; w: number; h: number }> = {};
      doc.querySelectorAll<HTMLElement>("[data-slot]").forEach((el) => {
        const box = el.getBoundingClientRect();
        found[el.dataset.slot ?? ""] = { x: box.left, y: box.top, w: box.width, h: box.height };
      });
      setBoxes(found);
    };
    frame.addEventListener("load", measure);
    if (frame.contentDocument?.querySelector("section")) measure();
    return () => frame.removeEventListener("load", measure);
  }, [html]);
  const put = async (slot: string, file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) { setError(t("사진 파일만 넣을 수 있어요")); return; }
    if (file.size > 15 * 1024 * 1024) { setError(t("15MB 보다 작은 사진만 넣을 수 있어요")); return; }
    setError("");
    setBusy((rows) => ({ ...rows, [slot]: true }));
    try { await onPhoto(index, slot, file); } catch { setError(t("사진을 넣지 못했어요 — 다시 해 보세요")); }
    setBusy((rows) => ({ ...rows, [slot]: false }));
  };
  return (
    <div className="deck-slots">
      <div className="deck-frame" style={{ width, height: SLIDE_H * scale }}>
        <iframe
          ref={frameRef}
          title={label}
          sandbox="allow-same-origin"
          srcDoc={withSlideFonts(html)}
          tabIndex={-1}
          style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})`, transformOrigin: "0 0" }}
        />
        {slots.map((slot) => {
          const box = boxes[slot.id];
          if (!box) return null;
          return (
            <label
              key={slot.id}
              className={`deck-slot${slot.filled ? " is-filled" : ""}${over === slot.id ? " is-over" : ""}`}
              style={{ left: box.x * scale, top: box.y * scale, width: box.w * scale, height: box.h * scale }}
              onDragOver={(event) => { event.preventDefault(); setOver(slot.id); }}
              onDragLeave={() => setOver(null)}
              onDrop={(event) => { event.preventDefault(); setOver(null); void put(slot.id, event.dataTransfer.files?.[0]); }}
            >
              <input type="file" accept="image/*" hidden onChange={(event) => { void put(slot.id, event.target.files?.[0]); event.target.value = ""; }} />
              <span>
                {busy[slot.id] ? <Loader2 size={13} className="spin" aria-hidden /> : <ImagePlus size={13} aria-hidden />}
                {busy[slot.id] ? t("넣는 중") : slot.filled ? t("사진 바꾸기") : t("사진 넣기 · {0}", slot.label)}
              </span>
            </label>
          );
        })}
      </div>
      <div className="deck-slot-list">
        <span>{t("사진 자리 {0}곳 — 장 위 점선 칸에 끌어다 놓거나 눌러서 고르세요", slots.length)}</span>
        {slots.map((slot) => (
          <span key={slot.id} className={`deck-slot-chip${slot.filled ? " is-filled" : ""}`}>
            {slot.filled ? <Check size={12} aria-hidden /> : <ImagePlus size={12} aria-hidden />}{slot.label}
          </span>
        ))}
        {error ? <span className="deck-slot-error" role="alert">{error}</span> : null}
      </div>
    </div>
  );
}

function SlideFrame({ html, width, label }: { html: string; width: number; label: string }) {
  const scale = width / SLIDE_W;
  return (
    <div className="deck-frame" style={{ width, height: SLIDE_H * scale }}>
      <iframe
        title={label}
        sandbox="allow-same-origin"
        srcDoc={withSlideFonts(html)}
        tabIndex={-1}
        style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})`, transformOrigin: "0 0" }}
      />
    </div>
  );
}

/** 남은 시간 막대 — 사람이 안 고르면 이 시간 뒤에 손자리가 권한 쪽으로 간다. */
function Countdown({ until, label }: { until: number; label: string }) {
  const [now, setNow] = useState(() => Date.now());
  const [span] = useState(() => Math.max(1000, until - Date.now()));
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  const left = Math.max(0, until - now);
  return (
    <div className="deck-count" role="timer" aria-label={label}>
      <span className="deck-count-bar"><i style={{ width: `${Math.min(100, (left / span) * 100)}%` }} /></span>
      <span>{t("{0}초 뒤 그대로 가요", Math.ceil(left / 1000))}</span>
    </div>
  );
}

function OutlineEditor({ deck, onAnswer }: { deck: DeckState; onAnswer?: DeckAnswer }) {
  const [cards, setCards] = useState<DeckCard[]>(deck.outline ?? []);
  const [sent, setSent] = useState(false);
  const lastTouch = useRef(0);
  useEffect(() => { setCards(deck.outline ?? []); setSent(false); }, [deck.outline]);
  const editable = Boolean(onAnswer) && !deck.outlineSettled && !sent;
  const touch = () => {
    // 고치는 중이면 기다림을 늘린다(백엔드는 상한 180초) — 3초에 한 번만 알린다.
    if (!onAnswer || Date.now() - lastTouch.current < 3000) return;
    lastTouch.current = Date.now();
    onAnswer("touch");
  };
  const change = (next: DeckCard[]) => { setCards(next); touch(); };
  const move = (from: number, to: number) => {
    if (to < 0 || to >= cards.length) return;
    const next = [...cards];
    const [card] = next.splice(from, 1);
    next.splice(to, 0, card);
    change(next);
  };
  return (
    <div className="deck-outline">
      {deck.outlineSay ? <p className="deck-say"><b>{t("손자리")}</b>{deck.outlineSay}</p> : null}
      <ol className="deck-cards">
        {cards.map((card, i) => (
          <li key={`${i}:${card.layout}`} className="deck-card">
            <span className="deck-card-n">{i + 1}</span>
            <span className="deck-card-layout">{card.layout === "parts" ? t("조립") : card.layout}</span>
            {editable ? (
              <input
                className="deck-card-claim"
                value={card.claim}
                aria-label={t("{0}번 장 주장", i + 1)}
                onChange={(event) => change(cards.map((c, j) => (j === i ? { ...c, claim: event.target.value } : c)))}
              />
            ) : <span className="deck-card-claim">{card.claim}</span>}
            {editable ? (
              <span className="deck-card-tools">
                <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0} aria-label={t("위로")}><ArrowUp size={13} /></button>
                <button type="button" onClick={() => move(i, i + 1)} disabled={i === cards.length - 1} aria-label={t("아래로")}><ArrowDown size={13} /></button>
                <button type="button" onClick={() => change(cards.filter((_, j) => j !== i))} disabled={cards.length <= 2} aria-label={t("빼기")}><X size={13} /></button>
              </span>
            ) : null}
          </li>
        ))}
      </ol>
      {editable ? (
        <div className="deck-actions">
          {deck.ask?.kind === "outline" ? <Countdown key={deck.ask.until} until={deck.ask.until} label={t("이야기판 남은 시간")} /> : <span />}
          <button type="button" className="deck-go" onClick={() => { onAnswer?.("outline", cards); setSent(true); }}>{t("이대로 만들기")}</button>
        </div>
      ) : (
        <p className="deck-state">
          {deck.outlineSettled
            ? (deck.outlineBy === "person" ? t("고친 이야기판으로 만드는 중") : t("이 이야기판으로 만드는 중"))
            : t("보냈어요 — 이 순서로 만들어요")}
        </p>
      )}
    </div>
  );
}

function NoteBox({ index, version, onAnswer }: { index: number; version: number; onAnswer: DeckAnswer }) {
  const [text, setText] = useState("");
  const [sent, setSent] = useState<Record<number, { text: string; version: number }>>({});
  const mine = sent[index];
  return (
    <form
      className="deck-notebox"
      onSubmit={(event) => {
        event.preventDefault();
        const value = text.trim();
        if (!value) return;
        onAnswer("note", { index, text: value });
        setSent({ ...sent, [index]: { text: value, version } });
        setText("");
      }}
    >
      {mine ? (
        <span className={`deck-sent${version > mine.version ? " is-fixed" : ""}`}>
          {version > mine.version ? t("한마디대로 고쳤어요: {0}", mine.text) : t("한마디 보냄 — 다음 장 전에 고쳐요: {0}", mine.text)}
        </span>
      ) : null}
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={t("{0}번 장에 한마디(예: 제목을 더 짧게)", index)}
        aria-label={t("{0}번 장에 한마디", index)}
        maxLength={300}
      />
      <button type="submit" disabled={!text.trim()} aria-label={t("한마디 보내기")}><Send size={13} /></button>
    </form>
  );
}

export function DeckStage({ deck, onAnswer, onOpen, onPhoto, pace }: {
  deck: DeckState; onAnswer?: DeckAnswer; onOpen?: (path: string, reveal: boolean) => void; onPhoto?: DeckPhoto;
  /** 짓는 연출의 빠르기 배수(기본 1). 업데이트 쇼(WhatsNewShow)는 빨리 돌려 장 하나를 다 짓고 넘어간다. */
  pace?: number;
}) {
  const still = useReducedMotion();
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);
  const [picked, setPicked] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [mine, setMine] = useState("");
  // 짓는 연출은 장마다(다시 그려지면 그 판마다) 한 번 — 사람이 작은 그림을 눌러 돌아가 볼 때는 다 된 장을 바로 보인다.
  const [played, setPlayed] = useState<Record<string, true>>({});
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => setWidth(Math.max(240, Math.floor(box.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, []);
  const shown = picked !== null && deck.slides[picked] ? picked : deck.latest;
  const numbers = Array.from({ length: deck.total }, (_, i) => i + 1);
  const drawn = Object.keys(deck.slides).length;
  const picks = deck.picks ?? [];
  const current = deck.theme || mine || deck.chosen;
  const chosen = picks.find((pick) => pick.theme === current);
  const others = picks.filter((pick) => pick.theme !== current).map((pick) => pick.name);

  if (!drawn && deck.outline?.length) {
    return (
      <section className="deck-stage" ref={boxRef} aria-label={t("이야기판")}>
        <header className="deck-head">
          <strong>{deck.title}</strong>
          {chosen ? <span className="deck-theme">{t("결: {0}", chosen.name)}</span> : null}
        </header>
        <OutlineEditor deck={deck} onAnswer={onAnswer} />
      </section>
    );
  }
  if (!drawn && picks.length) {
    // 결 고르기 — 장이 그려지기 전, 추천 결 셋에 이 발표의 제목을 넣은 표지를 나란히 보인다.
    const cardWidth = Math.max(160, Math.floor((width - 16) / Math.min(3, picks.length)));
    const open = Boolean(onAnswer) && !deck.theme && !mine;
    return (
      <section className="deck-stage" ref={boxRef} aria-label={t("장표 결 고르기")}>
        <header className="deck-head">
          <strong>{deck.title}</strong>
          <span className="deck-progress">
            {deck.theme
              ? (deck.themeBy === "person" ? t("고른 결로 이야기판을 짜는 중") : t("권한 결로 이야기판을 짜는 중"))
              : <><Loader2 size={13} className="spin" aria-hidden />{t("어울리는 결 셋을 골랐어요")}</>}
          </span>
        </header>
        {deck.say ? <p className="deck-say"><b>{t("손자리")}</b>{deck.say}</p> : null}
        <div className="deck-picks" role="list">
          {picks.map((pick, order) => {
            const on = pick.theme === current;
            const body = (
              <>
                <SlideFrame html={pick.html} width={cardWidth} label={pick.name} />
                <figcaption>
                  <b>{pick.name}{pick.theme === deck.chosen ? <em className="deck-badge">{t("권함")}</em> : null}</b>
                  {pick.why ? <span>{pick.why}</span> : null}
                </figcaption>
              </>
            );
            return (
              <motion.figure
                key={pick.theme}
                role="listitem"
                className={`deck-pick${on ? " is-on" : ""}`}
                initial={still ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: still ? 0 : order * 0.12, ease: [0.22, 1, 0.36, 1] }}
              >
                {open ? (
                  <button type="button" className="deck-pick-btn" onClick={() => { setMine(pick.theme); onAnswer?.("theme", pick.theme); }}
                    aria-label={t("{0} 결로 만들기", pick.name)}>{body}</button>
                ) : body}
              </motion.figure>
            );
          })}
        </div>
        {open && deck.ask?.kind === "theme" ? <Countdown key={deck.ask.until} until={deck.ask.until} label={t("결 고르기 남은 시간")} /> : null}
      </section>
    );
  }
  const note = deck.notes?.[shown];
  return (
    <section className="deck-stage" ref={boxRef} aria-label={t("장표 미리보기")}>
      <header className="deck-head">
        <strong>{deck.title}</strong>
        {chosen ? (
          <span className="deck-theme" title={others.length ? t("다른 후보: {0}", others.join(" · ")) : undefined}>
            {t("결: {0}", chosen.name)}
          </span>
        ) : null}
        {deck.built ? (
          <span className="deck-done"><FileCheck2 size={14} aria-hidden /> {t("PPTX 완성 · {0}", deck.built.path.split(/[\\/]/).pop() ?? "")}</span>
        ) : (
          <span className="deck-progress">
            {paused ? t("잠깐 멈춤") : <><Loader2 size={13} className="spin" aria-hidden />
              {drawn >= deck.total ? t("PPTX 로 굽는 중") : t("{0} / {1}장 그리는 중", drawn, deck.total)}</>}
          </span>
        )}
        {onAnswer && !deck.built ? (
          <button type="button" className="deck-pause" onClick={() => { onAnswer(paused ? "resume" : "pause"); setPaused(!paused); }}
            aria-label={paused ? t("이어 만들기") : t("잠깐 멈추기")}>
            {paused ? <Play size={13} /> : <Pause size={13} />}
          </button>
        ) : null}
      </header>
      <motion.div
        key={`${deck.title}:${shown}:${deck.versions?.[shown] ?? 0}`}
        className="deck-main"
        initial={still ? false : { opacity: 0, scale: 0.97, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        {deck.slides[shown] ? (
          !still && picked === null && !played[`${shown}:${deck.versions?.[shown] ?? 1}`]
            && deck.still?.[shown] !== (deck.versions?.[shown] ?? 1)
            ? <BuildFrame
                html={deck.slides[shown]}
                width={width}
                label={t("{0}번 장", shown)}
                note={deck.notes?.[shown]}
                pace={pace}
                onDone={() => setPlayed((rows) => ({ ...rows, [`${shown}:${deck.versions?.[shown] ?? 1}`]: true }))}
              />
            : onPhoto && (deck.slots?.[shown]?.length ?? 0) > 0
              ? <SlotFrame html={deck.slides[shown]} width={width} label={t("{0}번 장", shown)} index={shown}
                  slots={deck.slots?.[shown] ?? []} onPhoto={onPhoto} />
              : <SlideFrame html={deck.slides[shown]} width={width} label={t("{0}번 장", shown)} />
        ) : null}
      </motion.div>
      {note ? <p className="deck-say deck-say-slide"><b>{t("손자리")}</b>{note}</p> : null}
      {onAnswer && !deck.built && deck.slides[shown]
        ? <NoteBox index={shown} version={deck.versions?.[shown] ?? 1} onAnswer={onAnswer} /> : null}
      {deck.built && deck.built.path && onOpen ? (
        <div className="deck-open">
          <button type="button" className="deck-go" onClick={() => onOpen(deck.built!.path, false)}>
            <FileCheck2 size={14} aria-hidden /> {t("PPTX 열기")}
          </button>
          <button type="button" className="deck-ghost" onClick={() => onOpen(deck.built!.path, true)}>
            <FolderOpen size={14} aria-hidden /> {t("폴더에서 보기")}
          </button>
        </div>
      ) : null}
      {deck.built && (deck.built.parts || deck.built.template) ? (
        <p className="deck-state">{t("부품으로 조립한 장 {0} · 틀째 쓴 장 {1}", deck.built.parts ?? 0, deck.built.template ?? 0)}</p>
      ) : null}
      <div className="deck-strip" role="list">
        {numbers.map((number) => (
          <button
            key={number}
            type="button"
            role="listitem"
            className={`deck-thumb${number === shown ? " is-current" : ""}${deck.slides[number] ? "" : " is-empty"}`}
            onClick={() => setPicked(deck.slides[number] ? (number === deck.latest ? null : number) : picked)}
            aria-label={t("{0}번 장 보기", number)}
          >
            {deck.slides[number]
              ? <SlideFrame html={deck.slides[number]} width={112} label={t("{0}번 장", number)} />
              : <span>{number}</span>}
          </button>
        ))}
      </div>
    </section>
  );
}
