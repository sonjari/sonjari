import { useState } from "react";
import { t } from "../i18n";
import { cardFacts, type QuestId, type QuestState } from "./tutorialState";

/**
 * 「처음 해 볼 것」 — 첫 화면(빈 대화) 안의 카드 하나.
 *
 * 할 일에는 순서가 없어서 번호 대신 동그라미를 쓴다(아무 때나 · 아무 순서로). 끝낸 일에는 초록 도장 「직접 확인함」과
 * 사용자가 실제로 열어 본 주소를 고정폭으로 남긴다 — 손자리가 한 일이 아니라 **사람이 확인한 것**이 이 판의 기억거리다.
 */
export function QuestBoard({ state, tierGb, claudeConnected = false, onStart, onDismiss, onCardSeen, onConnectClaude }: {
  state: QuestState;
  /** 클로드(데스크톱 · 코드)가 손자리에 이어져 있나 — 아니면 ③ 은 「Claude 에 잇기」(연결 화면으로)가 된다. 이어졌으면 「클로드에게 맡겨 보기」(2026-10-27: 전에는 이어진 PC 에서만 보여 그런 길이 있다는 것조차 몰랐다). */
  claudeConnected?: boolean;
  tierGb?: number;
  /** 영어 화면 — 10-17 부터 영어 첫 일도 재서 넣었기에 판의 글은 같다(부르는 쪽 호환으로 남김). */
  english?: boolean;
  onStart: (quest: "watch" | "excel") => void;
  onDismiss: () => void;
  onCardSeen: () => void;
  /** 「Claude 에 잇기」를 누르면 설정의 연결 칸을 연다. 없으면 그 단추를 안 그린다. */
  onConnectClaude?: () => void;
}) {
  const [cardOpen, setCardOpen] = useState(false);
  const facts = cardFacts(tierGb);
  const shown: QuestId[] = ["watch", "excel", "claude", "card"];
  const total = shown.length;
  const finished = shown.filter((id) => state.done[id]).length;

  const row = (id: QuestId, title: string, detail: string, action: JSX.Element | null) => {
    const done = state.done[id];
    return (
      <li className={`quest-row${done ? " is-done" : ""}`} key={id}>
        <span className="quest-mark" aria-hidden="true" />
        <div className="quest-text">
          <strong>{title}</strong>
          {/* 도장의 말은 사람이 한 일 그대로 — 주소를 열어 본 것만 「직접 확인함」이다. 엑셀은 받은 것, 카드 소개는 본 것. */}
          {done
            ? <span className="quest-stamp">{id === "watch" ? t("직접 확인함") : id === "excel" ? t("받았어요") : id === "claude" ? t("맡겼어요") : t("봤어요")}
                {done.host ? <code>{done.host}</code> : null}</span>
            : <span>{detail}</span>}
        </div>
        {!done && action}
      </li>
    );
  };

  return (
    <section className="quest-board" aria-label={t("처음 해 볼 것")}>
      <header>
        <h2>{t("처음 해 볼 것")}</h2>
        <span className="quest-count">{t("{0}개 중 {1}개", total, finished)}</span>
        <button type="button" className="quest-later" onClick={onDismiss}>{t("다음에 하기")}</button>
      </header>
      <ul>
        {row("watch", t("크롬이 움직이는 걸 보기"), t("손자리가 이 컴퓨터의 크롬으로 찾아 읽어요. 끝나면 읽은 페이지를 직접 열어 확인해요."),
        <button type="button" className="quest-start" onClick={() => onStart("watch")}>{t("시작")}</button>)}
        {row("excel", t("엑셀로 받아 보기"), t("찾은 것을 엑셀 파일로 받아요."),
          <button type="button" className="quest-start" onClick={() => onStart("excel")}>{t("시작")}</button>)}
        {claudeConnected || state.done.claude
          ? row("claude", t("클로드에게 맡겨 보기"),
            t("클로드에게 「손자리로 찾아 줘」라고 말해 보세요. 클로드가 맡긴 일이 끝나면 체크돼요."), null)
          : row("claude", t("Claude 에 잇기"),
            t("쓰던 클로드에서 손자리를 부를 수 있게 이어요. 이으면 클로드가 맡긴 일을 이 PC에서 해요."),
            onConnectClaude ? <button type="button" className="quest-start" onClick={onConnectClaude}>{t("잇기")}</button> : null)}
        {row("card", t("내 PC 에서 잘하는 일 보기"), t("이 그래픽카드에서 잰 값을 그대로 보여 드려요."),
          <button type="button" className="quest-start quest-quiet" aria-expanded={cardOpen}
            onClick={() => { setCardOpen(true); onCardSeen(); }}>{t("보기")}</button>)}
      </ul>
      {(cardOpen || state.done.card) && (
        <div className="quest-card-facts" role="note">
          {facts ? (
            <>
              <p><strong>{t("이 PC: {0}급", facts.label)}</strong> · {facts.note}</p>
              {facts.lines.length > 0 && (
                <dl>
                  {facts.lines.map((line) => (
                    <div key={line.what}><dt>{line.what}</dt><dd><code>{line.measured}</code></dd></div>
                  ))}
                </dl>
              )}
            </>
          ) : <p>{t("이 PC 의 그래픽카드를 아직 확인하지 못했어요.")}</p>}
          <p className="quest-card-source">{t("숫자는 깃허브의 시험지(EXAM.md)와 같은 기록에서 왔어요.")}</p>
        </div>
      )}
    </section>
  );
}
