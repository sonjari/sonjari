import { t } from "../i18n";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Check, FileSearch, GitBranch, Loader2, MessageSquareText, Minus, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import type { CoworkTakeoverCard, CoworkTakeoverOffer, HandoffDirection } from "../types";

export type TakeoverRelayStage = "detected" | "indexing" | "ready" | "transfer" | "error";
export type TakeoverDirection = HandoffDirection;

export type HandoffOrigin = { tool: string; toolName: string; title: string };

export function originTone(tool: string): "claude" | "codex" | "cursor" | "other" {
  const normalized = tool.trim().toLowerCase();
  if (normalized.includes("claude")) return "claude";
  if (normalized.includes("codex")) return "codex";
  if (normalized.includes("cursor")) return "cursor";
  return "other";
}

/**
 * MCP 호스트 이름(clientInfo)을 사람이 읽는 이름으로 (2026-09-30).
 * 대표: 「클로드·코덱스를 동시에 쓰면 누가 Sonjari를 불렀는지 모른다」. 색만으로 구별하지 않는다 — 이름을 늘 함께 적는다.
 */
export function callerLabel(caller: string): string {
  const normalized = caller.trim().toLowerCase();
  if (!normalized) return t("바깥 AI");
  if (normalized.includes("claude-code") || normalized.includes("claude code")) return "Claude Code";
  if (normalized.includes("claude")) return "Claude";
  if (normalized.includes("codex")) return "Codex";
  if (normalized.includes("cursor")) return "Cursor";
  return caller.trim();
}

/** MCP 과제의 보이는 문장 앞머리. 호스트 이름을 따로 두르므로 말풍선·목록에서는 떼어 낸다. */
export const DELEGATED_PREFIX = t("바깥 AI 가 맡긴 일 · ");

/** 멈춘 이유는 카드의 `stop_kind` 가 말한다. 문구를 고정하면 오류로 멈춘 것도 「한도」가 된다. */
export function stopReasonText(kind: string | undefined): string {
  switch (kind) {
    case "rate_limit": return t("사용량 한도로 멈춤");
    case "api_error": return t("오류로 멈춤");
    case "aborted": return t("중간에 멈춤");
    // 멈춘 기록 없이 사람이 「이어받자」고 해서 고른 가장 최근 대화(2026-10-05). 「멈췄다」고 지어내지 않는다.
    case "none": return t("한도로 멈춘 기록 없음");
    default: return t("멈춘 이유 기록 없음");
  }
}

/** 두 줄 제목. ★ 문장을 토막 내 옮기면 영어 어순이 깨진다 — 「Original Claude Code Your conversations and folders stay as they are.」가
 *  스토어 사진에 찍혔다(2026-10-06). 통문장을 옮기고, 줄바꿈 자리만 여기서 나눈다. */
function twoLines(text: string) {
  const [first, ...rest] = text.split("\n");
  return rest.length ? <>{first}<br />{rest.join(" ")}</> : <>{first}</>;
}

export type RelayFact = { label: string; detail: string; found: boolean };

/**
 * 캡슐이 「찾았다」고 말하는 줄은 전부 카드에 실제로 있는 값에서 나온다.
 *
 * 카드는 서버가 기록 파일을 이미 다 읽고 만든 것이다. 화면이 그 뒤에 진행률이나
 * 「진행 중」을 그리면 일어나지 않는 작업을 일어난 것처럼 말하게 된다.
 * 바뀐 파일은 추적 중인 파일만 센다 — 추적 안 한 파일은 저장소마다 수천 개라 신호가 아니다.
 */
export function relayFacts(card: CoworkTakeoverCard): { rows: RelayFact[]; evidence: number; changed: number } {
  const changed = Math.max(0, Number(card.git?.changed_count ?? 0));
  const lastRequest = (card.last_request || "").trim();
  const tasks = card.open_tasks?.length ?? 0;
  const files = card.files?.length ?? 0;
  const folder: RelayFact = card.git?.repo
    ? { label: t("작업 폴더"), detail: t("{0}바뀐 파일 {1}개", card.git.branch ? `${card.git.branch} · ` : "", changed), found: true }
    : { label: t("작업 폴더"), detail: card.cwd ? t("git 저장소 아님") : t("기록에 없음"), found: Boolean(card.cwd) };
  return {
    rows: [
      { label: t("마지막 요청"), detail: lastRequest || t("기록에 없음"), found: Boolean(lastRequest) },
      folder,
      { label: t("남은 할 일"), detail: tasks ? t("{0}개", tasks) : t("기록에 없음"), found: tasks > 0 },
    ],
    evidence: tasks + files + (lastRequest ? 1 : 0),
    changed: card.git?.repo ? changed : 0,
  };
}

export function TakeoverRelay(props: {
  offer: CoworkTakeoverOffer;
  stage: TakeoverRelayStage;
  busy: boolean;
  error?: string;
  /** 능력을 잰 적 없는 모델이면 한 줄(`modelCaution`). 이어받기는 남이 하던 일을 통째로 받는 자리라 더 위험하다. */
  caution?: string | null;
  onContinue: (direction: TakeoverDirection, custom: string) => void;
  /** ★ 진짜 코드 이어받기 — 따로 만든 가지에서 실제로 고친다 (2026-09-20). 저장소일 때만 보인다. */
  onContinueInCode?: () => void;
  onDismiss: () => void;
}) {
  const still = useReducedMotion();
  const [direction, setDirection] = useState<TakeoverDirection>("continue");
  const [custom, setCustom] = useState("");
  const { card } = props.offer;
  const tone = originTone(card.tool || card.tool_name);
  const source = card.tool_name || t("다른 AI 도구");
  const facts = relayFacts(card);
  const spring = still ? { duration: 0 } : { duration: 0.58, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <AnimatePresence>
      <motion.aside
        className={`takeover-relay source-${tone}`}
        initial={{ width: 0, opacity: 0 }}
        animate={{ width: 468, opacity: 1 }}
        exit={{ width: 0, opacity: 0 }}
        transition={spring}
        aria-label={t("{0}에서 Sonjari로 작업 이어오기", source)}
      >
        <div className="takeover-relay-stage">
          <AnimatePresence>
            {props.stage === "detected" && (
              <motion.div
                className="takeover-gate"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: still ? 0 : 0.16 }}
                aria-hidden
              >
                <motion.span initial={{ x: "-102%" }} animate={{ x: 0 }} transition={spring} />
                <motion.span initial={{ x: "102%" }} animate={{ x: 0 }} transition={spring} />
              </motion.div>
            )}
          </AnimatePresence>

          <motion.section
            className="takeover-capsule"
            initial={{ x: 72, opacity: 0, scale: 0.985 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            transition={spring}
          >
            <header className="takeover-relay-head">
              <span className="takeover-source-mark" aria-hidden>{source.slice(0, 1).toUpperCase()}</span>
              <span>
                <strong>{props.stage === "ready" || props.stage === "transfer" ? t("Sonjari 인계 준비") : t("{0} 작업 감지", source)}</strong>
                <small>{props.stage === "ready" || props.stage === "transfer" ? t("{0}에서 읽은 맥락", source) : t("읽기 전용 · 원본 유지")}</small>
              </span>
              <button type="button" className="takeover-close" onClick={props.onDismiss} aria-label={t("이어오기 닫기")}><X size={16} /></button>
            </header>

            <div className="takeover-source-seam" aria-hidden><span /></div>

            <AnimatePresence mode="wait" initial={false}>
              {props.stage === "detected" && (
                <motion.div key="detected" className="takeover-relay-body" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
                  <p className="takeover-eyebrow">{card.stop_kind === "none" ? t("최근 작업 발견") : t("멈춘 작업 발견")}</p>
                  {card.stop_kind === "none"
                    ? <h2>{t("{0}에서 가장 최근에 하던 일을 찾았습니다", source)}</h2>
                    : <h2>{twoLines(t("{0}가 멈춘 지점을\n찾았습니다", source))}</h2>}
                  <p>{t("원래 대화와 작업 폴더는 건드리지 않고, 이어갈 맥락만 읽어옵니다.")}</p>
                  <div className="takeover-found">
                    <MessageSquareText size={16} />
                    <span><strong>{card.title || t("제목 없는 작업")}</strong><small>{t("{0}분 전 · {1}", card.stopped_minutes_ago ?? 0, stopReasonText(card.stop_kind))}</small></span>
                  </div>
                </motion.div>
              )}

              {props.stage === "indexing" && (
                <motion.div key="indexing" className="takeover-relay-body" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
                  <p className="takeover-eyebrow">{t("읽어 온 맥락")}</p>
                  <h2>{twoLines(t("{0} 기록에서\n이만큼 찾았습니다", source))}</h2>
                  <div className="takeover-milestones" aria-live="polite">
                    {facts.rows.map((row) => (
                      <p key={row.label} className={row.found ? undefined : "is-missing"}>
                        {row.found ? <Check size={15} /> : <Minus size={15} />}
                        <span>{row.label}</span>
                        <small title={row.detail}>{row.detail}</small>
                      </p>
                    ))}
                  </div>
                  <div className="takeover-evidence"><FileSearch size={15} /> {t("근거 {0}개", facts.evidence)}{facts.changed ? t(" · 바뀐 파일 {0}개", facts.changed) : ""}</div>
                </motion.div>
              )}

              {props.stage === "ready" && (
                <motion.form
                  key="ready"
                  className="takeover-relay-body"
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                  onSubmit={(event) => { event.preventDefault(); props.onContinue(direction, custom.trim()); }}
                >
                  <p className="takeover-eyebrow is-jarvis">{t("이어갈 준비 완료")}</p>
                  <h2>{twoLines(t("이 작업을 Sonjari에서\n어떻게 이어갈까요?"))}</h2>
                  <p>{t("원래 {0} 대화와 폴더는 그대로 둡니다.", source)}</p>
                  <fieldset className="takeover-choices">
                    <legend className="sr-only">{t("이어가기 방식")}</legend>
                    <label><input type="radio" name="takeover-direction" checked={direction === "continue"} onChange={() => setDirection("continue")} /><span><strong>{t("멈춘 자리부터 이어가기")}</strong><small>{t("읽은 맥락으로 가능한 Cowork 작업을 계속합니다")}</small></span></label>
                    <label><input type="radio" name="takeover-direction" checked={direction === "review"} onChange={() => setDirection("review")} /><span><strong>{t("먼저 지금까지 한 일 검토하기")}</strong><small>{t("결정과 근거가 맞는지부터 확인합니다")}</small></span></label>
                    <label><input type="radio" name="takeover-direction" checked={direction === "tasks"} onChange={() => setDirection("tasks")} /><span><strong>{t("남은 일만 정리하기")}</strong><small>{t("실행하지 않고 체크리스트를 만듭니다")}</small></span></label>
                  </fieldset>
                  <label className={`takeover-custom${direction === "custom" ? " active" : ""}`}>
                    <span>{t("다르게 이어가려면 적어 주세요")}</span>
                    <textarea
                      rows={2} value={custom} maxLength={800}
                      onFocus={() => setDirection("custom")}
                      onChange={(event) => { setCustom(event.target.value); setDirection("custom"); }}
                      placeholder={t("예: 수정은 하지 말고 실패 원인부터 찾아줘")}
                    />
                  </label>
                  {props.caution && (
                    <p className="takeover-caution" role="alert">
                      <ShieldAlert size={14} /> {props.caution}
                    </p>
                  )}
                  {props.onContinueInCode && props.offer.card.git?.repo && (
                    <button
                      type="button"
                      className="takeover-code"
                      disabled={props.busy}
                      onClick={props.onContinueInCode}
                    >
                      <GitBranch size={15} /> {t("코드로 이어받기")}
                      <small>{t("따로 만든 가지에서 실제로 고칩니다 · 원래 폴더는 그대로")}</small>
                    </button>
                  )}
                  <div className="takeover-actions">
                    <button type="button" className="takeover-secondary" onClick={props.onDismiss}>{t("지금은 안 함")}</button>
                    <button type="submit" className="takeover-primary" disabled={props.busy || (direction === "custom" && !custom.trim())}>
                      {props.busy ? <Loader2 size={15} className="spin" /> : <ArrowRight size={15} />}
                      {t("Sonjari에서 이어가기")}
                    </button>
                  </div>
                </motion.form>
              )}

              {props.stage === "transfer" && (
                <motion.div key="transfer" className="takeover-relay-body takeover-transfer" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
                  <span className="takeover-transfer-mark"><ShieldCheck size={24} /></span>
                  <h2>{twoLines(t("멈춘 자리에서\n이어갈 준비가 됐습니다"))}</h2>
                  <p>{t("출처와 근거가 연결된 새 Sonjari 대화를 열고 있습니다.")}</p>
                </motion.div>
              )}

              {props.stage === "error" && (
                <motion.div key="error" className="takeover-relay-body" role="alert" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <p className="takeover-eyebrow is-error">{t("이어오지 못했습니다")}</p>
                  <h2>{twoLines(t("인계 카드를 다시\n찾아야 합니다"))}</h2>
                  <p>{props.error || t("원래 대화는 그대로입니다. 잠시 뒤 다시 시도해 주세요.")}</p>
                  <button type="button" className="takeover-secondary takeover-block" onClick={props.onDismiss}>{t("닫기")}</button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.section>
        </div>
      </motion.aside>
    </AnimatePresence>
  );
}
