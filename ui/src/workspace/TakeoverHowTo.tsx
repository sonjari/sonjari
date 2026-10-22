/**
 * 이어받기를 **어떻게 시작하는지** 알려 주는 짧은 안내 (2026-10-22 대표).
 *
 * 이어받기는 반자동이다(`takeover.py` 머리말): 알림을 밀지 않고, 사람이 손자리 창에 「클로드 한도 걸렸어」처럼 말하면 그때
 * 이 PC 에 남은 기록에서 멈춘 자리를 찾는다. 그런데 그렇게 말하라는 안내가 마법사에도 설정에도 없었다 — 스위치뿐이었다.
 * 그래서 사람들은 기능이 있는 줄도, 뭐라고 해야 하는지도 몰랐다.
 *
 * 마법사 「연결」 칸과 설정 › 이어받기가 같이 쓴다(마법사는 한 번 보고 지나가니 다시 찾을 자리가 있어야 한다).
 *
 * ## 사실 — 고치기 전에 코드를 다시 본다
 *
 * - 읽는 기록: Claude Code(`~/.claude/projects` — 데스크톱 앱 Code 탭도 여기에 쌓인다) · Codex(`~/.codex/sessions`).
 *   웹 · 휴대폰 채팅은 기록이 이 PC 에 없어 못 받는다(`takeover.py` `NO_RECORDS_ANSWER`).
 * - 예시 문장은 문(`_WORTH_ASKING`: 한도 · 이어받 · 「코덱스 … 멈」)을 지나고, 뜻은 모델이 가른다(이어받자는 말 7개 21/21).
 */
import { t } from "../i18n";
import { Workflow } from "lucide-react";
import "./takeover-howto.css";

/** 손자리 창에 그대로 말하면 되는 예. 바꾸면 `_WORTH_ASKING` 문을 지나는지 시험(`TakeoverHowTo.test`)이 본다. */
export const TAKEOVER_PHRASES = [t("클로드 한도 걸렸어, 이어받아 줘"), t("코덱스 멈췄어, 하던 거 이어서 해 줘")] as const;

export function TakeoverHowTo({ compact = false }: { compact?: boolean }) {
  return (
    <section className={`takeover-howto${compact ? " is-compact" : ""}`} aria-labelledby="takeover-howto-title">
      <p id="takeover-howto-title" className="takeover-howto-title">
        <Workflow size={15} aria-hidden /> {t("클로드 코드가 사용량 한도로 멈추면")}
      </p>
      <p className="takeover-howto-body">
        {t("손자리 창에 이렇게 말하세요. 이 PC 에 남은 대화 기록에서 멈춘 자리를 찾아, 이어서 할지 먼저 묻습니다.")}
      </p>
      <ul className="takeover-howto-phrases">
        {TAKEOVER_PHRASES.map((phrase) => <li key={phrase}>「{phrase}」</li>)}
      </ul>
      <p className="takeover-howto-fine">
        {t("이 PC 의 Claude Code(데스크톱 앱 Code 탭 포함) · Codex 대화만 이어받습니다. 웹이나 휴대폰 채팅은 기록이 이 PC 에 없어 이어받지 못합니다. 원래 대화와 작업 폴더는 건드리지 않습니다.")}
      </p>
    </section>
  );
}
