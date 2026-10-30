/**
 * 「쓰는 법」 쇼의 장면 넷 (2026-10-27 대표 · 설계서 generated_reports/usage_show_1027/설계서.md).
 *
 * 사람들은 스토어에서 받아 바로 연다 — 앱을 연 첫 10초가 우리 소개다. 「바뀐 것」 쇼(`WhatsNewShow`)와 같은 집안:
 * 가짜 그림을 새로 그리지 않고 앱의 진짜 부품(생각 상자 `ThinkingTrace` · 바뀐 줄 `edit-replay`)을 예시 데이터로 움직이고,
 * 「예시 화면」 표시가 늘 붙는다. 움직임을 줄인 사람에게는 마지막 모습만 보인다.
 *
 * ## 서명: 실
 *
 * 사람 쪽(따뜻한 바닥)에서 이 PC 쪽(찬 바닥)으로 건너가는 실 한 가닥을 네 장 내내 같은 말로 쓴다.
 *   1장  세 컷(찾고 읽기 → 파일 → 코드)을 아래의 실 한 줄이 잇는다.
 *   2장  쓰던 AI(클로드)가 맡기면 실이 건너가 「손자리가 받았습니다」 — 그 뒤 두 쪽이 **동시에** 일하고 표가 실을 타고 돌아온다.
 *   3장  2장의 다음 박자다 — 같은 화면, 실은 이미 걸려 있다. 돌아오는 실 위로는 **결과만** 지나가고, 영수증이 뜬다.
 *   4장  실 세 가닥(손자리 창 · 폰 디스코드 · 쓰던 클로드 · 코덱스)이 이 PC 로 모인다.
 *
 * ## 지키는 말(설계서)
 *
 * - 주어는 손자리다. 클로드의 도구 · 손 · 조수로 보이게 하지 않는다.
 * - 숫자는 실제 기록에서만, 날짜와 함께. 3장의 영수증 숫자 하나(최소 6,401 토큰)는 `jarvis.db` 의 2026-10-26 19:48 판
 *   (`49c150bd`, 이 PC 26걸음 · 읽기 6번)의 `host_context_kept_out.tokens_at_least` 하한이다. 막대에는 숫자를 안 붙인다.
 * - 1장은 촬영 조건(RTX 3090 · Qwen3.8 27B)을 구석에 적는다 — 「어느 PC 에서나 이렇게 된다」고 말하지 않는다.
 */
import { t } from "../i18n";
import { useReducedMotion } from "framer-motion";
import { AppWindow, Check, FileSpreadsheet, Globe, Hand, Loader2, MessageCircle, Plug, Smartphone } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { ThinkingTrace } from "./ComputerPane";
import { JarvisMark } from "./JarvisMark";
import { frozenAt, useBeats, useThreads } from "./showKit";
import "./whatsNewShow.css";
import "./usageShow.css";

export type UsageScene = "this-pc" | "handoff" | "limit" | "anywhere";
export type UsageSettingsSection = "connect" | "discord";

export function UsageShowStage({ scene, onOpenSettings }: { scene: UsageScene; onOpenSettings?: (section: UsageSettingsSection) => void }) {
  return (
    <div className="wns us" data-scene={scene}>
      <span className="wns-example">{t("예시 화면")}</span>
      {scene === "this-pc" && <ThisPcScene />}
      {(scene === "handoff" || scene === "limit") && <HandoffScene chapter={scene === "handoff" ? 2 : 3} />}
      {scene === "anywhere" && <AnywhereScene onOpenSettings={onOpenSettings} />}
    </div>
  );
}

/** 글자가 한 줄씩 쓰이듯 흘러오는 것 — 생각 상자에 쓴다. 움직임을 줄였거나 세워 둔 장면이면 `settled` 에 따라 한 번에 다 보인다. */
function useTyped(full: string, run: boolean, settled: boolean): string {
  const [count, setCount] = useState(settled ? full.length : 0);
  useEffect(() => {
    if (settled) { setCount(full.length); return; }
    if (!run) { setCount(0); return; }
    const id = window.setInterval(() => setCount((value) => Math.min(full.length, value + 4)), 45);
    return () => window.clearInterval(id);
  }, [run, settled, full]);
  return full.slice(0, count);
}

// ── ① 손자리는 이 컴퓨터에서 도는 AI ─────────────────────────────────────────────────────

//            슬로건   ┌ 컷① 크롬: 열림 · 공고 셋          ┐ ┌ 컷② 엑셀: 틀 · 세 줄 · 파일 ┐ ┌ 컷③ 코드: 빨강 → 고침 → 초록 ┐
const PC_BEATS = [2800, 3600, 4300, 5000, 5800, 6300, 6800, 7300, 8000, 9700, 11000, 12200];

function ThisPcScene() {
  const [phase, round] = useBeats(PC_BEATS, 14600);
  const settled = Boolean(useReducedMotion()) || frozenAt() !== null;
  const hero = phase === 0 && round <= 1;
  const cut = phase < 5 ? 0 : phase < 9 ? 1 : 2;
  const jobsRead = Math.max(0, Math.min(3, phase - 1));
  const rowsFilled = Math.max(0, Math.min(3, phase - 5));
  const fileSaved = phase >= 8;
  const thinking = phase >= 9;
  const patched = phase >= 10;
  const green = phase >= 11;

  const thought = t("apply_discount 가 1100 을 돌려준다. 기대값은 9900. 할인액만 돌려주고 있다 — 가격에서 빼야 한다. price * rate 를 price * (1 - rate) 로 바꾸고 같은 시험을 다시 돌린다.");
  const typed = useTyped(thought, thinking, settled && phase >= 10);

  const jobs = [
    { title: t("회계 담당 · 경력 3년 이상"), where: t("여수 · A사") },
    { title: t("경리 · 경력 무관"), where: t("여수 · B사") },
    { title: t("회계 사무 · 신입 가능"), where: t("여수 · C사") },
  ];
  const sheet = [
    [t("A사"), t("회계 담당"), t("3년 이상"), t("여수")],
    [t("B사"), t("경리"), t("무관"), t("여수")],
    [t("C사"), t("회계 사무"), t("신입"), t("여수")],
  ];

  return (
    <div className="us-pc">
      {/* 슬로건 — 한 번 크게 선 뒤 위로 올라앉는다(크게 서는 쪽과 올라앉은 쪽이 겹쳐 바뀐다).
          올라앉은 모습이 이 장면의 머리말이다 — 움직임을 줄이면 이것만 본다. 영문 슬로건은 번역하지 않고 두 언어에 똑같이 쓴다(대표 10-27). */}
      <div className={`us-hero${hero ? " is-on" : ""}`} aria-hidden={!hero}>
        <p className="us-slogan-main">{t("Watch AI work in your browser.")}</p>
        <p className="us-slogan-sub">{t("Runs on your PC.")}</p>
        <p className="us-slogan-note">{t("크롬, 파일, 엑셀, 한글을 직접 다루고 읽은 곳을 붙여 드립니다.")}</p>
      </div>
      <header className={`us-dock${hero ? " is-hidden" : ""}`}>
        <p className="us-slogan-line">
          <b className="us-slogan-main">{t("Watch AI work in your browser.")}</b>
          <span className="us-slogan-sub">{t("Runs on your PC.")}</span>
        </p>
        <p className="us-slogan-note">{t("크롬, 파일, 엑셀, 한글을 직접 다루고 읽은 곳을 붙여 드립니다.")}</p>
      </header>

      <div className={`us-cuts${hero ? " is-hidden" : ""}`}>
        {/* 컷 ① — 크롬이 혼자 열려 공고를 찾고 읽는다 */}
        <section className={`us-cut${cut === 0 ? " is-active" : ""}`} aria-label={t("웹에서 읽기")}>
          <div className="us-chrome">
            <div className="us-chrome-bar">
              <i /><i /><i />
              <span className="us-url"><Globe size={11} aria-hidden />{t("saramin.co.kr/jobs?loc=yeosu")}</span>
            </div>
            <ul className="us-jobs">
              {jobs.map((job, i) => (
                <li key={i} className={i < jobsRead ? "is-read" : i === jobsRead && phase >= 1 ? "is-reading" : ""}>
                  <span className="us-job-title">{job.title}</span>
                  <span className="us-job-where">{job.where}</span>
                  <span className="us-job-mark" aria-hidden>{i < jobsRead ? <Check size={13} /> : i === jobsRead && phase >= 1 ? <Loader2 size={12} className="spin" /> : null}</span>
                </li>
              ))}
            </ul>
            <p className="us-chrome-state">
              {jobsRead < 3 ? t("공고 {0}/{1} 읽는 중", Math.max(1, jobsRead + (phase >= 1 ? 1 : 0)), 3) : t("공고 {0}개 다 읽음", 3)}
            </p>
          </div>
        </section>

        {/* 컷 ② — 엑셀 파일이 떨어진다 */}
        <section className={`us-cut${cut === 1 ? " is-active" : ""}`} aria-label={t("파일로 받기")}>
          <div className="us-sheet-wrap">
            <div className="us-sheet" role="presentation">
              <div className="us-sheet-row us-sheet-head">
                {[t("회사"), t("직무"), t("경력"), t("지역")].map((cell) => <span key={cell}>{cell}</span>)}
              </div>
              {sheet.map((row, i) => (
                <div key={i} className={`us-sheet-row${i < rowsFilled ? " is-filled" : ""}`}>
                  {row.map((cell, k) => <span key={k}>{cell}</span>)}
                </div>
              ))}
            </div>
            <p className={`us-file${fileSaved ? " is-on" : ""}`}>
              <FileSpreadsheet size={16} aria-hidden />
              <b>{t("여수_회계_공고_비교.xlsx")}</b>
              <span>{t("저장했습니다")}</span>
            </p>
          </div>
        </section>

        {/* 컷 ③ — 코드 모드: 빨간 시험이 초록으로. 생각 상자는 앱의 진짜 부품이다. */}
        <section className={`us-cut${cut === 2 ? " is-active" : ""}`} aria-label={t("코드까지 고치기")}>
          <div className="us-code">
            <div className="us-code-think">
              <ThinkingTrace text={typed || "…"} ko="" live={thinking && !green} mode="code" local translate={false} />
            </div>
            <div className="us-code-side">
              <div className={`us-term${green ? " is-green" : " is-red"}`}>
                <p className="us-term-cmd"><span>$</span> pytest -q tests/test_price.py</p>
                {!green ? (
                  <>
                    <p className="us-term-out">F</p>
                    <p className="us-term-fail">FAILED test_discount — assert 1100 == 9900</p>
                    <p className="us-term-sum is-red">{patched ? t("고친 뒤 다시 실행 중…") : t("1개 실패")}</p>
                  </>
                ) : (
                  <>
                    <p className="us-term-out">.</p>
                    <p className="us-term-sum is-green"><Check size={13} aria-hidden />{t("1개 통과")}</p>
                  </>
                )}
              </div>
              {patched && (
                <div className="edit-replay us-patch">
                  <p className="edit-replay-head"><span className="edit-replay-title">{t("방금 이렇게 바꿨습니다")}</span><code className="edit-replay-path">price.py</code><span className="edit-replay-count">−1 +1</span></p>
                  <pre className="edit-replay-body">
                    <span className="edit-line removed"><em>14</em><span>    return price * rate</span></span>
                    <span className="edit-line added"><em>14</em><span>    return price * (1 - rate)</span></span>
                  </pre>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* 실 — 세 컷을 한 줄로 잇는다. 지나간 컷까지 색이 채워진다. */}
      <ol className={`us-rail${hero ? " is-hidden" : ""}`}>
        {[t("웹에서 읽기"), t("파일로 받기"), t("코드까지 고치기")].map((label, i) => (
          <li key={label} className={i < cut ? "is-past" : i === cut ? "is-now" : ""}>
            <i aria-hidden />
            <span>{label}</span>
          </li>
        ))}
        <li className="us-rail-cond" aria-label={t("촬영 조건")}><span>{t("촬영 조건")}</span><code>RTX 3090 · Qwen3.8 27B</code></li>
      </ol>
    </div>
  );
}

// ── ②③ 쓰던 AI가 맡기고 · 이 PC 가 읽고 · 결과만 돌아온다 ──────────────────────────────────

const RIVAL_COUNT = 4;
const RIVALS = ["A", "B", "C", "D"];
const RIVAL_PRICES = ["9,900", "12,000", "8,500", "10,500"];

//            나눔 · 맡김 · 실이 건너감 · 받음+동시에 · 읽기 넷 · 표가 돌아옴 · 마무리
const HANDOFF_BEATS = [500, 1400, 2100, 2600, 3500, 4050, 4600, 5150, 5700, 6500, 7500];
//            읽기 넷 · 결과만 돌아옴 · 영수증
const LIMIT_BEATS = [400, 1000, 1600, 2200, 3000, 3900];

type DiffLine = { kind: "rm" | "add"; text: string; at: number; final?: { text: string; at: number } };

function HandoffScene({ chapter }: { chapter: 2 | 3 }) {
  const limit = chapter === 3;
  const [phase] = useBeats(limit ? LIMIT_BEATS : HANDOFF_BEATS, limit ? 9600 : 10500);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const fromRef = useRef<HTMLLIElement | null>(null);
  const toRef = useRef<HTMLDivElement | null>(null);
  const threads = useThreads(boxRef, [{ from: { ref: fromRef, side: "right" }, to: { ref: toRef, side: "left" } }]);
  const thread = threads[0];

  // 2장은 처음부터 · 3장은 같은 화면의 다음 박자 — 실은 이미 걸려 있고 손자리는 읽는 중이다.
  const userOn = limit || phase >= 1;
  const saysOn = limit || phase >= 2;
  const handed = limit || phase >= 3;
  const threadDrawn = limit || phase >= 4;
  const received = limit || phase >= 5;
  const read = limit ? Math.max(0, Math.min(RIVAL_COUNT, phase - 1)) : Math.max(0, Math.min(RIVAL_COUNT, phase - 5));
  const reading = limit ? phase >= 1 && read < RIVAL_COUNT : phase >= 5 && read < RIVAL_COUNT;
  const returned = limit ? phase >= 5 : phase >= 10;
  const finished = !limit && phase >= 11;
  const both = !limit && phase >= 5 && phase < 11;
  const receipt = limit && phase >= 6;
  const nudged = limit && phase >= 5;
  const beadGo = !limit && phase === 4;
  const beadBack = returned && !(limit ? receipt : finished);

  const diff: DiffLine[] = [
    { kind: "rm", text: `  <h2>${t("요금표")}</h2>`, at: 5 },
    { kind: "add", text: `  <h2>${t("요금표 · 경쟁사 비교")}</h2>`, at: 5 },
    { kind: "add", text: '  <table class="plans compare">', at: 6 },
    { kind: "add", text: `    <th>${t("우리")}</th><th>${t("경쟁사")}</th>`, at: 7 },
    { kind: "add", text: `    <td class="rival">${t("조사 결과를 기다리는 중")}</td>`, at: 8,
      final: { text: `    <td class="rival">${t("월 {0}원", "8,500 ~ 12,000")}</td>`, at: 11 } },
  ];

  return (
    <div className="wns-hands us-hand" ref={boxRef} data-chapter={chapter}>
      <section className="wns-human us-human" aria-label={t("클로드 쪽")}>
        <p className="wns-chip"><i className="wns-dot-claude" aria-hidden />Claude</p>
        <p className={`wns-you us-fade${userOn ? " is-on" : ""}`}>{t("경쟁사 가격 조사해서 우리 가격표 페이지 고쳐 줘")}</p>
        <p className={`us-says us-fade${saysOn ? " is-on" : ""}`}>{t("조사는 손자리에게 넘기고, 페이지는 제가 고칩니다")}</p>
        <ol className="wns-steps">
          <li ref={fromRef} className={`wns-handoff${handed ? " is-on" : ""}${returned ? " is-done" : ""}`}>
            {returned ? <Check size={13} aria-hidden /> : <Hand size={13} aria-hidden />}
            <span>{t("손자리에게 맡김")} <small>{t("경쟁사 가격 읽기")}</small></span>
          </li>
          <li className={finished ? "is-done" : received ? "is-on" : "is-wait"}>
            {finished ? <Check size={13} aria-hidden /> : received ? <Loader2 size={13} className="spin" aria-hidden /> : <i className="wns-hollow" aria-hidden />}
            {t("가격표 페이지 고치기")}
          </li>
        </ol>

        {limit ? (
          // 3장 — 클로드 쪽 사용량 막대. 숫자는 안 붙인다(모양만) · 결과가 돌아올 때 조금 움직인다.
          <div className="us-meter us-meter-claude" role="img" aria-label={t("클로드 사용량은 거의 그대로입니다")}>
            <span>{t("클로드 사용량")}</span>
            <i><b className={nudged ? "is-nudged" : ""} /></i>
          </div>
        ) : (
          <div className="edit-replay us-diff" aria-label={t("바뀐 줄")}>
            <p className="edit-replay-head">
              <span className="edit-replay-title">{finished ? t("방금 이렇게 바꿨습니다") : t("고치는 중")}</span>
              <code className="edit-replay-path">pricing.html</code>
            </p>
            <pre className="edit-replay-body">
              {diff.map((line, i) => {
                const text = line.final && phase >= line.final.at ? line.final.text : line.text;
                const flashed = Boolean(line.final && phase >= line.final.at);
                return (
                  <span key={`${i}-${flashed}`} className={`edit-line ${line.kind === "rm" ? "removed" : "added"} us-line${phase >= line.at ? " is-on" : ""}${flashed ? " is-flash" : ""}`}>
                    <em>{42 + i}</em><span>{text}</span>
                  </span>
                );
              })}
            </pre>
          </div>
        )}
      </section>

      <section className="wns-machine us-machine" aria-label={t("손자리의 컴퓨터")}>
        <header className="wns-pc-head">
          <b>{t("손자리의 컴퓨터")}</b>
          <span>{t("내 PC · Qwen3.8 27B")}</span>
        </header>
        <div ref={toRef} className={`wns-got${received ? " is-on" : ""}`}>
          <Hand size={14} aria-hidden />
          <span>{received ? t("손자리가 받았습니다") : t("기다리는 중")}</span>
          {received && <small>{t("클로드가 맡긴 일")}</small>}
        </div>
        <div className={`us-rivals${received ? " is-on" : ""}`} aria-hidden>
          <p className="wns-url"><Globe size={11} />{read < RIVAL_COUNT ? t("가격 페이지 {0}/{1} 읽는 중", Math.max(1, read + (received ? 1 : 0)), RIVAL_COUNT) : t("가격 페이지 {0}개 다 읽음", RIVAL_COUNT)}</p>
          <ul>
            {RIVALS.map((name, i) => (
              <li key={name} className={i < read ? "is-read" : i === read && reading ? "is-reading" : ""}>
                <span className="us-rival-name">{t("{0}사 요금 페이지", name)}</span>
                <span className="us-rival-price">{i < read ? t("월 {0}원", RIVAL_PRICES[i]) : ""}</span>
                {i < read && <Check size={11} />}
              </li>
            ))}
          </ul>
        </div>
        {limit ? (
          <div className="us-meter us-meter-pc" role="img" aria-label={t("이 PC에서 읽은 양")}>
            <span>{t("이 PC에서 읽은 양")}</span>
            <i><b style={{ width: `${(read / RIVAL_COUNT) * 100}%` }} /></i>
          </div>
        ) : null}
        <p className={`wns-private${returned ? " is-on" : ""}`}>{t("페이지 원문은 이 PC 에 남고, 결과만 클로드에게 갑니다")}</p>
      </section>

      {both && <span className="us-both"><i aria-hidden />{t("동시에")}</span>}

      {thread && (
        <svg className="wns-thread" aria-hidden>
          <defs>
            <linearGradient id={`us-thread-${chapter}`} gradientUnits="userSpaceOnUse" x1={thread.x1} y1="0" x2={thread.x2} y2="0">
              <stop offset="0" stopColor="rgb(var(--origin-claude))" />
              <stop offset="1" stopColor="rgb(var(--brand-bright))" />
            </linearGradient>
          </defs>
          <path d={thread.d} className="wns-thread-rest" />
          <path d={thread.d} pathLength={1} className={`wns-thread-go${threadDrawn ? " is-on" : ""}`} stroke={`url(#us-thread-${chapter})`} />
          {beadGo && <circle r="4.5" className="wns-bead wns-bead-go" style={{ offsetPath: `path("${thread.d}")` }} />}
          {beadBack && <circle r={limit ? 3 : 4.5} className="wns-bead wns-bead-back" style={{ offsetPath: `path("${thread.d}")` }} />}
        </svg>
      )}

      {/* 영수증 — 3장의 끝. 숫자는 이 하나뿐이고, 날짜 · 어느 판인지 · 하한을 같이 적는다. */}
      {limit && (
        <aside className={`us-receipt${receipt ? " is-on" : ""}`} aria-label={t("영수증")}>
          <p className="us-receipt-label">{t("이 PC에서 읽고 클로드로 안 보낸 양")}</p>
          <p className="us-receipt-figure">{(() => {
            // 숫자는 고정폭(기계가 잰 값) · 「최소」 「토큰」은 보통 글꼴 — 고정폭 글꼴엔 한글이 없어 글자가 튄다(ReceiptCard 와 같은 방식).
            const [before, after] = t("최소 {0} 토큰", "§").split("§");
            return <>{before && <small>{before}</small>}<b>6,401</b>{after && <small>{after}</small>}</>;
          })()}</p>
          <p className="us-receipt-basis">{t("10월 26일 실제 판 · 이 PC 26걸음 · 센 글자로 잡은 하한")}</p>
        </aside>
      )}
    </div>
  );
}

// ── ④ 어디서든 — 실 세 가닥이 이 PC 로 모인다 ────────────────────────────────────────────

//            ┌ 창  보냄 · 받음 ┐ ┌ 폰  보냄 · 받음 ┐ ┌ 클로드 · 코덱스  보냄 · 받음 ┐ 쉼
const ANYWHERE_BEATS = [500, 1350, 2150, 3000, 3800, 4650, 5800];

function AnywhereScene({ onOpenSettings }: { onOpenSettings?: (section: UsageSettingsSection) => void }) {
  const [phase] = useBeats(ANYWHERE_BEATS, 9000);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const pcRef = useRef<HTMLDivElement | null>(null);
  const a = useRef<HTMLDivElement>(null);
  const b = useRef<HTMLDivElement>(null);
  const c = useRef<HTMLDivElement>(null);
  const refs: RefObject<HTMLDivElement>[] = [a, b, c];
  const threads = useThreads(boxRef, refs.map((ref) => ({ from: { ref, side: "right" as const }, to: { ref: pcRef, side: "left" as const } })));

  const sources = [
    { id: "window", icon: <AppWindow size={14} aria-hidden />, name: t("손자리 창"), say: t("이 엑셀 읽고 반별 평균 내 줘"), file: t("반별_평균.xlsx"), color: "var(--brand)" },
    { id: "phone", icon: <Smartphone size={14} aria-hidden />, name: t("폰 · 디스코드"), say: t("사람인에서 여수 회계 공고 3개 찾아 줘"), file: t("공고_비교표.xlsx"), color: "var(--text-3)" },
    { id: "ai", icon: <i className="us-ai-dots" aria-hidden><b /><b /></i>, name: t("쓰던 클로드 · 코덱스"), say: t("경쟁사 가격 조사해서 정리해 줘"), file: t("가격_조사.md"), color: "var(--origin-claude)" },
  ];

  const sent = (i: number) => phase >= 2 * i + 1;
  const got = (i: number) => phase >= 2 * i + 2;
  const flying = (i: number) => phase === 2 * i + 1;
  const busy = phase >= 1 && phase < 6;

  return (
    <div className="us-anywhere" ref={boxRef}>
      <div className="us-any-main">
        <div className="us-sources">
          {sources.map((source, i) => (
            <div key={source.id} ref={refs[i]} className={`us-source${sent(i) ? " is-sent" : ""}`} data-source={source.id}>
              <p className="us-source-name">{source.icon}{source.name}</p>
              <p className={`us-source-say us-fade${sent(i) ? " is-on" : ""}`}>{source.say}</p>
            </div>
          ))}
        </div>

        <div ref={pcRef} className={`us-pcnode${busy ? " is-busy" : ""}`}>
          <header>
            <JarvisMark state={busy ? "working" : "idle"} connected size={26} />
            <span><b>{t("이 PC")}</b><small>{t("손자리")}</small></span>
          </header>
          <ul>
            {sources.map((source, i) => (
              <li key={source.id} className={got(i) ? "is-got" : ""}>
                <i aria-hidden style={{ background: got(i) ? `rgb(${source.color})` : undefined }} />
                <span>{got(i) ? source.file : t("받을 곳")}</span>
                {got(i) && <Check size={12} aria-hidden />}
              </li>
            ))}
          </ul>
          <p>{t("파일은 이 PC에 저장됩니다")}</p>
        </div>
      </div>

      <div className="us-any-actions">
        <button type="button" className="us-link" onClick={() => onOpenSettings?.("connect")}>
          <Plug size={14} aria-hidden />{t("Claude 에 잇기")}
        </button>
        <button type="button" className="us-link" onClick={() => onOpenSettings?.("discord")}>
          <MessageCircle size={14} aria-hidden />{t("디스코드 잇기")}
        </button>
      </div>

      {threads.length === 3 && (
        <svg className="wns-thread" aria-hidden>
          <defs>
            {sources.map((source, i) => (
              <linearGradient key={source.id} id={`us-any-${source.id}`} gradientUnits="userSpaceOnUse" x1={threads[i].x1} y1="0" x2={threads[i].x2} y2="0">
                <stop offset="0" stopColor={`rgb(${source.color})`} />
                <stop offset="1" stopColor="rgb(var(--brand-bright))" />
              </linearGradient>
            ))}
          </defs>
          {sources.map((source, i) => (
            <g key={source.id}>
              <path d={threads[i].d} className="wns-thread-rest" />
              <path d={threads[i].d} pathLength={1} className={`wns-thread-go${sent(i) ? " is-on" : ""}`} stroke={`url(#us-any-${source.id})`} />
              {flying(i) && <circle r="4.5" className="wns-bead wns-bead-go" style={{ offsetPath: `path("${threads[i].d}")` }} />}
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}
