import { t } from "../i18n";
import { memo } from "react";
import { Bot } from "lucide-react";
import { JarvisMark } from "./JarvisMark";
import { MarkdownView } from "../MarkdownView";
import { ClaudeReceipt } from "../claudeAgent/HandoffCard";
import { claudeButtonLabel, isClaudeBrain } from "../claudeAgent/brain";
import type { ConversationMessage } from "../types";
import { timeLabel } from "./format";
import { userInitial, userLabel } from "./userLabel";
import { MessageAttachments, type ShownAttachment } from "./MessageAttachments";
import { DELEGATED_PREFIX, callerLabel, originTone } from "./TakeoverRelay";
import { splitAnswerChecks } from "./answerChecks";
import { OutboundReceipt, type OutboundRecord } from "./OutboundReceipt";
import { ShowcaseStrip, type ShowcaseSource } from "./ShowcaseStrip";

/** 지난 말 한 줄. **바뀐 것이 없으면 다시 그리지 않는다**(memo) — 넘기는 함수는 고정된 것이어야 한다(`useStableCallback`). */
export const MessageView = memo(function MessageView({
  message,
  onObserveAgain,
  onContinue,
  onSay,
  showcase,
}: {
  message: ConversationMessage;
  onObserveAgain?: (message: ConversationMessage) => void;
  /** 끝내지 못한 판의 메모 아래 「이어서 하기」 — 대화의 마지막 말일 때만 넘어온다. */
  onContinue?: () => void;
  /** 답 아래 단추(「보여 주기」 · 「한 번 해 볼게요」 …)가 누르면 보내는 말 — 대화의 마지막 말일 때만 넘어온다. 사람이 그 말을 친 것과 같은 문이다. */
  onSay?: (text: string) => void;
  /** 답이 기댄 페이지의 사진을 가져오는 손(2026-10-18). 고정된 것이어야 한다 — memo 가 깨진다. */
  showcase?: ShowcaseSource;
}) {
  // ★ 출처 도장 (2026-09-30). 이 판에서 성공한 도구 걸음이 0 이면 — 답이 「확인했습니다」라고 써도 —
  //   찾아본 답이 아니다. 낱말을 읽지 않고 서버가 센 걸음 수(`runtime.answer_grounding`)만 믿는다.
  const grounding = message.metadata?.grounding as { basis?: string } | undefined;
  const fromMemory = message.role === "assistant" && grounding?.basis === "memory";
  // ★ 끝내지 못한 판(실패·멈춤)의 메모 (2026-10-04). 답이 아니라 「어디까지 했는지」다 — 서버가 걸음 기록에서 만든다.
  //   답처럼 보이면 안 되므로 조용한 글씨로, 괄호는 떼고 보여 준다(괄호는 다음 판의 모델이 「답이 아님」을 알게 하는 표시다).
  const unfinished = message.role === "assistant" && typeof message.metadata?.unfinished === "string" && Boolean(message.metadata.unfinished);
  const unfinishedText = unfinished ? message.content.replace(/^\(/, "").replace(/\)$/, "") : "";
  // ★ 바깥 AI 가 맡긴 말 (2026-09-30). 클로드·코덱스를 같이 쓰면 누가 Sonjari를 불렀는지 몰랐다 — 그 호스트의 출처 이음선과
  //   이름을 두른다(tokens.css `--origin-*`: 면을 칠하지 않고 2px 이음선과 출처 글자에만, 이름을 늘 함께).
  const caller = typeof message.metadata?.caller === "string" ? message.metadata.caller : "";
  const delegated = message.role === "user" && (Boolean(caller) || message.content.startsWith(DELEGATED_PREFIX));
  const shownContent = delegated && message.content.startsWith(DELEGATED_PREFIX)
    ? message.content.slice(DELEGATED_PREFIX.length)
    : message.content;
  const attachments = Array.isArray(message.metadata?.attachments)
    ? message.metadata.attachments as ShownAttachment[]
    : [];
  const model = typeof message.metadata?.model === "string"
    ? message.metadata.model.replace("claude-", "").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
    : "";
  // ★ 답 끝에 붙어 오는 「확인할 것」(⚠ 문단)은 본문에서 뗀다 (2026-10-13 대표: 「이런 게 나오는 게 불편하다」).
  //   없애지 않는다 — 답 아래 접힌 한 줄과 오른쪽 판의 노란 줄로 자리를 옮긴다(`answerChecks.ts`).
  const answer = message.role === "assistant" && !unfinished ? splitAnswerChecks(message.content) : { body: message.content, checks: [] };
  const outbound = message.role === "assistant" && !unfinished && message.metadata?.outbound && typeof message.metadata.outbound === "object"
    ? message.metadata.outbound as OutboundRecord
    : null;
  // ★ 답이 기댄 페이지(대표사진 · 2026-10-18 대표 결정). 안착한 답에만 — 끝내지 못한 판의 메모 · 기억으로 쓴 답(0걸음)에는
  //   기댄 페이지가 없다. 그 판 번호(`metadata.job_id`)가 없는 옛 기록도 그리지 않는다.
  const showcaseJob = message.role === "assistant" && !unfinished && !fromMemory && typeof message.metadata?.job_id === "string"
    ? message.metadata.job_id
    : "";
  // ★ 앱 안의 Claude Agent 가 쓴 답 (2026-10-26) — 이름은 「Claude Agent · Sonnet 5.5」, 표식은 주황 점(공식 로고는 안 씀), 끝에 영수증 줄.
  const byClaude = message.role === "assistant" && message.metadata?.brain === "claude";
  const claudeModel = byClaude ? String(message.metadata?.model ?? "") : "";
  const thinkingTokens = Number(message.metadata?.thinking_tokens ?? 0);
  const cacheReadTokens = Number(message.metadata?.cache_read_tokens ?? 0);
  const runtime = message.role === "assistant"
    ? [
        byClaude ? "" : model,
        thinkingTokens > 0 ? t("생각 {0}토큰", thinkingTokens.toLocaleString()) : "",
        cacheReadTokens > 0 ? t("캐시 {0}토큰 재사용", cacheReadTokens.toLocaleString()) : "",
      ].filter(Boolean).join(" · ")
    : "";
  // ★ 답 아래 단추 (2026-10-28 · `/레시피`). 백엔드가 대화 기록(`quick_replies`)에 남긴 `{label, say}` 를 그대로 그린다 — 화면은 말을 해석하지 않는다.
  const quickReplies = message.role === "assistant" && onSay && Array.isArray(message.metadata?.quick_replies)
    ? (message.metadata.quick_replies as { label?: unknown; say?: unknown }[])
        .filter((item) => typeof item?.label === "string" && typeof item?.say === "string" && item.label && item.say)
        .slice(0, 4) as { label: string; say: string }[]
    : [];
  return (
    <article className={`workspace-message message-${message.role}${delegated ? ` message-delegated origin-${originTone(caller)}` : ""}`}>
      <div className="message-avatar">
        {/* Sonjari의 말에는 로고 마크 — 끝난 말이라 멈춰 있다. 쓰는 중인 말은 WorkspaceApp 에서 고리가 돈다.
            바깥 AI 의 말은 「다른 AI」 표식을 출처 색으로 — 이니셜은 Claude·Codex·Cursor 가 전부 C 라 못 가른다(09-30 화면 확인). */}
        {byClaude ? <span className="brain-dot claude message-claude-mark" aria-hidden /> : message.role === "assistant" ? <JarvisMark state="idle" connected size={18} /> : delegated ? <Bot size={15} aria-hidden /> : userInitial()}
      </div>
      <div className="message-body">
        <div className="message-meta">
          <strong>{byClaude ? (isClaudeBrain(claudeModel) ? claudeButtonLabel(claudeModel) : "Claude Agent") : message.role === "assistant" ? "Sonjari" : delegated ? t("{0}가 맡긴 일", callerLabel(caller)) : userLabel()}</strong>
          <span>{timeLabel(message.created_at)}</span>
          {runtime && <span className="message-runtime">{runtime}</span>}
        </div>
        <MessageAttachments files={attachments} />
        {unfinished ? (
          <p className="message-unfinished">
            <span>{unfinishedText}</span>
            {onContinue && <button type="button" onClick={onContinue}>{t("이어서 하기")}</button>}
          </p>
        ) : message.role === "assistant" ? <MarkdownView className="workspace-markdown">{answer.body}</MarkdownView> : <p>{shownContent}</p>}
        {quickReplies.length > 0 && (
          <div className="message-quick-replies" role="group" aria-label={t("바로 답하기")}>
            {quickReplies.map((item) => (
              <button type="button" key={`${item.label}:${item.say}`} onClick={() => onSay?.(item.say)}>{item.label}</button>
            ))}
          </div>
        )}
        {showcase && showcaseJob && <ShowcaseStrip jobId={showcaseJob} source={showcase} />}
        {answer.checks.length > 0 && (
          <details className="message-checks">
            <summary>{t("확인할 것 {0}", answer.checks.length)}</summary>
            <ul>
              {answer.checks.map((check) => (
                <li key={check.detail}>
                  <b>{check.title}</b>{check.what && <span>{check.what}</span>}
                  <p>{check.detail}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
        {/* 바깥 AI 에게 무엇이 나갔나 — 한 줄 영수증(2026-10-15 · §55-32). 바깥 AI 가 맡긴 판에만 서버가 남긴다. */}
        {outbound && <OutboundReceipt record={outbound} />}
        {byClaude && <ClaudeReceipt metadata={message.metadata} />}
        {/* 일하는 도중 덧붙인 말 (2026-10-01, 대표). 서버는 질문 기록에 `steer_notes` 로 남기는데 화면이 안 그려서,
            판이 끝나면 「구글에서 봐 줘」 같은 방향 전환이 기록에서 사라졌다. 질문 아래·답 위 — 일어난 순서 그대로. */}
        {message.role === "user" && Array.isArray(message.metadata?.steer_notes) && (message.metadata.steer_notes as unknown[]).map((note, index) => (
          <p className="message-steer-note" key={index}><span>{t("덧붙인 말")}</span>{String(note)}</p>
        ))}
        {/* 도장이 아니라 계기 — 도구를 쓴 답은 척추에 「3걸음 · 12초」 궤적이 붙는다. 기억으로 쓴 답은 같은 문법으로
            「0걸음」이라고 적는다. 0 이라는 숫자가 곧 사실이고, 그래서 색도 테두리도 필요 없다. */}
        {fromMemory && (
          <p className="message-grounding">
            <span title={t("이 답을 쓰는 동안 사이트·파일·화면을 하나도 열지 않았습니다. 답에 「확인했다」는 말이 있어도 기억으로 쓴 것입니다.")}>
              {t("0걸음 · 기억으로 답함")}
            </span>
            {onObserveAgain && (
              <button type="button" onClick={() => onObserveAgain(message)}>{t("찾아보고 다시 답하기")}</button>
            )}
          </p>
        )}
      </div>
    </article>
  );
});
