/**
 * 「/레시피」 화면 부분 (2026-10-28) — 배우는 중 칸 · 명령 목록 · 답 아래 단추.
 * 단추가 보내는 말은 백엔드가 정한다(`quick_replies`) — 화면은 그대로 그리고 그대로 보낸다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "../types";
import { applyLearnEvent, idleLearn, slashMenu } from "../recipeLearn";
import { MessageView } from "./MessageView";
import { RecipeLearnPanel, SlashMenu } from "./RecipeLearnPanel";

const noop = () => undefined;

describe("배우는 중 칸", () => {
  it("아무것도 안 하는 때는 그리지 않는다", () => {
    expect(renderToStaticMarkup(<RecipeLearnPanel state={idleLearn} onDone={noop} onCancel={noop} />)).toBe("");
  });

  it("배우는 중에는 이름 · 쌓인 걸음 · [다 했어] [취소] 를 보인다 — 입력한 글은 없다", () => {
    let state = applyLearnEvent(idleLearn, "demo_started", { label: "쿠팡 장바구니" });
    state = applyLearnEvent(state, "demo_step", { n: 1, kind: "fill", name: "검색", where: "coupang.com" });
    state = applyLearnEvent(state, "demo_step", { n: 2, kind: "click", name: "장바구니 담기", where: "coupang.com/vp" });
    const html = renderToStaticMarkup(<RecipeLearnPanel state={state} onDone={noop} onCancel={noop} />);
    expect(html).toContain("배우는 중");
    expect(html).toContain("쿠팡 장바구니");
    expect(html).toContain("입력 · 「검색」 (coupang.com)");
    expect(html).toContain("누르기 · 「장바구니 담기」 (coupang.com/vp)");
    expect(html).toContain(">다 했어<");
    expect(html).toContain(">취소<");
  });

  it("걸음이 아직 없으면 그렇게 말한다", () => {
    const html = renderToStaticMarkup(<RecipeLearnPanel state={applyLearnEvent(idleLearn, "demo_started", { label: "" })} onDone={noop} onCancel={noop} />);
    expect(html).toContain("아직 적힌 걸음이 없습니다");
  });

  it("한 번 해 보는 중에는 걸음마다 맞음 · 틀림과 까닭을 보이고 끝내는 단추는 없다", () => {
    let state = applyLearnEvent(idleLearn, "demo_replay_started", { total: 3 });
    state = applyLearnEvent(state, "demo_replay_step", { n: 1, text: "주소를 연다", ok: true });
    state = applyLearnEvent(state, "demo_replay_step", { n: 2, text: "Enter 를 누른다", ok: false, note: "기대한 변화가 화면에 나타나지 않았습니다" });
    const html = renderToStaticMarkup(<RecipeLearnPanel state={state} onDone={noop} onCancel={noop} />);
    expect(html).toContain("한 번 해 보는 중");
    expect(html).toContain("2/3");
    expect(html).toContain("is-ok");
    expect(html).toContain("is-bad");
    expect(html).toContain("기대한 변화가 화면에 나타나지 않았습니다");
    expect(html).not.toContain("다 했어");
  });
});

describe("/ 명령 목록", () => {
  it("고른 줄을 표시하고 명령 · 설명을 보인다", () => {
    const html = renderToStaticMarkup(<SlashMenu items={slashMenu("/", "ko")} index={0} onPick={noop} />);
    expect(html).toContain("/레시피");
    expect(html).toContain("해 보여서 가르치기");
    expect(html).toContain('aria-selected="true"');
  });

  it("목록이 비면 그리지 않는다", () => {
    expect(renderToStaticMarkup(<SlashMenu items={[]} index={0} onPick={noop} />)).toBe("");
  });
});

const reply = (metadata: Record<string, unknown>, role: "user" | "assistant" = "assistant"): ConversationMessage => ({
  id: 7, session_id: "s", role, content: "막혔습니다.", kind: "chat", metadata, created_at: 0,
});

describe("답 아래 단추", () => {
  const buttons = [{ label: "보여 주기", say: "/레시피 a.com 에서 막혔던 일" }];

  it("백엔드가 남긴 단추를 그대로 그린다 — 마지막 말이라 보내는 손이 있을 때만", () => {
    const html = renderToStaticMarkup(<MessageView message={reply({ quick_replies: buttons })} onSay={noop} />);
    expect(html).toContain("message-quick-replies");
    expect(html).toContain(">보여 주기<");
  });

  it("지난 말(보내는 손 없음)이나 사용자의 말에는 없다", () => {
    expect(renderToStaticMarkup(<MessageView message={reply({ quick_replies: buttons })} />)).not.toContain("message-quick-replies");
    expect(renderToStaticMarkup(<MessageView message={reply({ quick_replies: buttons }, "user")} onSay={noop} />)).not.toContain("message-quick-replies");
  });

  it("모양이 틀린 칸은 버리고 네 개까지만 그린다", () => {
    const messy = [{ label: "", say: "x" }, { label: "ok", say: "" }, { label: 3, say: "x" }, ...Array.from({ length: 6 }, (_, i) => ({ label: `b${i}`, say: `s${i}` }))];
    const html = renderToStaticMarkup(<MessageView message={reply({ quick_replies: messy })} onSay={noop} />);
    expect(html.match(/<button/g)?.length).toBe(4);
    expect(html).not.toContain(">ok<");
  });
});
