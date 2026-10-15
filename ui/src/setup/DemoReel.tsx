/**
 * 「자비스는 이렇게 일한다」 — **실제로 한 판**을 빠르게 되감아 보여 준다.
 *
 * ## 왜 영상이 아니라 되감기인가 (2026-09-14 사용자·다른 사용자 결정)
 *
 * 영상은 exe 를 수십 MB 키우고, 화면을 바꿀 때마다 다시 녹화해야 하고, 글자가 흐리다.
 * 무엇보다 **지어낸 연출**이 된다. 우리가 파는 것이 「검증」인데 첫인상이 연출이면 안 된다.
 * 그래서 진짜 판 하나의 기록(`demoReplay.json`)을 우리 부품으로 재생한다.
 *
 * ## 기록에 담지 않는 것
 *
 * 기사 본문은 안 담는다(저작권). 제목·언론사·자비스가 쓴 짧은 요약·주소의 호스트만.
 * 날짜를 적는다 — 나중에 봐도 「오늘 뉴스」라고 거짓말하지 않게.
 *
 * ## 기다림이 있는 자리에만 뜬다
 *
 * PC 확인(빈 왼쪽 칸) · 모델 받는 동안. 움직임 줄이기면 재생하지 않고 한 번에 다 보여 준다.
 */
import { t, lang, locale } from "../i18n";
import { useEffect, useMemo, useState } from "react";
import replay from "./demoReplay.json";
import replayEn from "./demoReplay.en.json";

/** 「2026년 09월 14일」 → 화면 언어의 날짜. 못 읽으면 원문 그대로. */
function recordedOn(): string {
  const m = /(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일/.exec(DATA.recorded_on);
  if (!m || lang() === "ko") return DATA.recorded_on;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" });
}

type Beat = { at: number; kind: "search" | "open" | "read" | "write" | "check"; label: string; detail: string };
type Row = { title: string; press: string; host: string };
type Replay = {
  recorded_on: string;
  prompt: string;
  real_seconds: number;
  beats: Beat[];
  result: { file: string; rows: Row[]; check: string; columns?: string[] };
};

// ★ 2026-10-05: 영어 화면에는 **영어로 돌린 실제 판**을 보여 준다. 전에는 한국어 판(네이버 뉴스)에 영어 풀이를 달았는데,
//   영어 스토어 스크린샷의 첫 화면이 한국어 과제였다. 이 판은 스토어 빌드 0.4.2.0 · 추천 모델 · 새 프로필로 돌린 8688cf90 이고,
//   시각은 그 판의 도구 실행 기록에서 뽑았다(지어낸 연출이 아니다).
const KOREAN_RUN = replay as Replay;
const DATA = lang() === "en" ? (replayEn as Replay) : KOREAN_RUN;
/** 한 바퀴를 몇 초에 보여 줄지. 실제 시간과 상관없이 이 길이로 줄인다. */
const PLAY_SECONDS = 16;
const HOLD_SECONDS = 5;

const KIND_LABEL: Record<Beat["kind"], string> = {
  search: t("찾기"),
  open: t("열기"),
  read: t("읽기"),
  write: t("만들기"),
  check: t("대조"),
};

function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

export function DemoReel() {
  const still = useMemo(reducedMotion, []);
  const [elapsed, setElapsed] = useState(still ? PLAY_SECONDS : 0);

  useEffect(() => {
    if (still) return;
    const started = performance.now();
    const cycle = (PLAY_SECONDS + HOLD_SECONDS) * 1000;
    const timer = window.setInterval(() => {
      const t = ((performance.now() - started) % cycle) / 1000;
      setElapsed(Math.min(t, PLAY_SECONDS));
    }, 120);
    return () => window.clearInterval(timer);
  }, [still]);

  // ★ 실제 시간 비율로 재생하지 않는다. 기록된 판에는 첫 기사를 열기까지 150초 공백이
  //   있었다(순위 번호를 잘못 부른 실패 둘 + 생각). 비율대로면 10초 가까이 커서만 깜빡인다.
  //   재생은 **걸음 순서대로 고르게**, 옆에 적는 시각은 **실제 시각 그대로** — 줄였다는 것을
  //   머리말에 적으므로 거짓이 아니다.
  const shown = DATA.beats.filter((_beat, index) => elapsed >= ((index + 1) / (DATA.beats.length + 1)) * PLAY_SECONDS);
  const done = elapsed >= PLAY_SECONDS;

  return (
    <section className="reel" aria-label={t("Sonjari가 실제로 한 작업 되감기")}>
      <header className="reel-head">
        <span className="reel-title">{t("Sonjari가 실제로 한 판")}</span>
        <span className="reel-meta">
          {recordedOn()} {t("· 실제")} <span className="num">{clock(DATA.real_seconds)}</span>
          {" · "}{t("주요 걸음만 줄여서")}
        </span>
      </header>

      <p className="reel-ask">{DATA.prompt}</p>
      {/* 실제 판의 기록이라 원문 그대로 둔다 — 영어 화면에선 한국어로 돌린 판이라고 밝히고 번역을 곁에 단다. */}
      {lang() === "en" && DATA === KOREAN_RUN && <p className="reel-ask-note">{t("한국어 사이트에서 실제로 돌린 판입니다 — 시킨 말:")} {t(DATA.prompt)}</p>}

      <ol className="reel-beats">
        {/* 최근 여섯 걸음만 — 다 쌓으면 칸이 화면보다 길어진다 */}
        {shown.slice(-6).map((beat) => (
          <li key={`${beat.at}-${beat.label}`} className={`reel-beat is-${beat.kind}`}>
            <span className="reel-time num">{clock(beat.at)}</span>
            <span className="reel-kind">{KIND_LABEL[beat.kind]}</span>
            <span className="reel-label">
              {t(beat.label)}
              {beat.detail && <em>{beat.detail}</em>}
            </span>
          </li>
        ))}
        {!done && <li className="reel-cursor" aria-hidden="true" />}
      </ol>

      {done && (
        <div className="reel-result">
          <p className="reel-file">{DATA.result.file}</p>
          <table>
            <thead>
              <tr>
                <th>{DATA.result.columns ? DATA.result.columns[0] : t("기사")}</th>
                <th>{DATA.result.columns ? DATA.result.columns[1] : t("언론사")}</th>
              </tr>
            </thead>
            <tbody>
              {DATA.result.rows.map((row) => (
                <tr key={row.title}>
                  <td>{row.title}</td>
                  <td>{row.press}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="reel-check">{t(DATA.result.check)}</p>
        </div>
      )}
    </section>
  );
}
