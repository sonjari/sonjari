import { describe, expect, it } from "vitest";
import { applyLearnEvent, idleLearn, isWholeCommand, slashKey, slashMenu, stepSentence } from "./recipeLearn";

describe("입력창의 / 명령 목록", () => {
  it("/ 한 글자면 레시피 하나가 뜨고, 영어판은 /recipe 로 보인다", () => {
    expect(slashMenu("/", "ko").map((item) => item.command)).toEqual(["/레시피"]);
    expect(slashMenu("/", "en").map((item) => item.command)).toEqual(["/recipe"]);
    expect(slashMenu("/", "ko")[0].hint).toBe("해 보여서 가르치기");
  });

  it("어느 언어로 치기 시작해도 찾는다", () => {
    expect(slashMenu("/레", "en")).toHaveLength(1);
    expect(slashMenu("/rec", "ko")).toHaveLength(1);
    expect(slashMenu("/RECIPE", "ko")).toHaveLength(1);
  });

  it("다른 글이면 안 뜬다 — 일반 문장 · 경로 · 이름을 치는 중", () => {
    expect(slashMenu("레시피", "ko")).toEqual([]);
    expect(slashMenu("/zzz", "ko")).toEqual([]);
    expect(slashMenu("/레시피 쿠팡", "ko")).toEqual([]);
    expect(slashMenu("", "ko")).toEqual([]);
  });

  it("화살표로 고르고 Enter 로 채운다 · 완성된 명령이면 Enter 가 보낸다", () => {
    const items = slashMenu("/", "ko");
    expect(slashKey("/", items, 0, "Enter")).toEqual({ kind: "fill", text: "/레시피 " });
    expect(slashKey("/", items, 0, "Tab")).toEqual({ kind: "fill", text: "/레시피 " });
    expect(slashKey("/레시피", slashMenu("/레시피", "ko"), 0, "Enter")).toEqual({ kind: "send" });
    expect(slashKey("/recipe", slashMenu("/recipe", "en"), 0, "Enter")).toEqual({ kind: "send" });
    expect(slashKey("/", items, 0, "ArrowDown")).toEqual({ kind: "move", index: 0 });
    expect(slashKey("/", [], 0, "Enter")).toEqual({ kind: "none" });
    expect(slashKey("/", items, 0, "a")).toEqual({ kind: "none" });
  });

  it("완성된 명령 낱말만 그렇게 본다", () => {
    expect(isWholeCommand("/레시피")).toBe(true);
    expect(isWholeCommand(" /recipe ")).toBe(true);
    expect(isWholeCommand("/레시피를")).toBe(false);
    expect(isWholeCommand("/레시피 쿠팡")).toBe(false);
  });
});

describe("배우는 중 패널", () => {
  it("시작 → 걸음이 하나씩 쌓인다 → 끝나면 비운다", () => {
    let state = applyLearnEvent(idleLearn, "demo_started", { label: "쿠팡 장바구니" });
    expect(state.phase).toBe("learning");
    expect(state.label).toBe("쿠팡 장바구니");
    state = applyLearnEvent(state, "demo_step", { n: 1, kind: "fill", name: "검색", where: "coupang.com" });
    state = applyLearnEvent(state, "demo_step", { n: 2, kind: "click", name: "장바구니", where: "coupang.com/cart" });
    expect(state.steps.map((step) => step.n)).toEqual([1, 2]);
    expect(applyLearnEvent(state, "demo_ended", { outcome: "stopped" })).toEqual(idleLearn);
  });

  it("같은 번호가 다시 오면 덮어쓰고 · 배우는 중이 아닐 때 온 걸음은 버린다", () => {
    let state = applyLearnEvent(idleLearn, "demo_step", { n: 1, kind: "click", name: "x" });
    expect(state).toEqual(idleLearn);
    state = applyLearnEvent(idleLearn, "demo_started", { label: "" });
    state = applyLearnEvent(state, "demo_step", { n: 1, kind: "click", name: "처음" });
    state = applyLearnEvent(state, "demo_step", { n: 1, kind: "click", name: "고침" });
    expect(state.steps).toHaveLength(1);
    expect(state.steps[0].name).toBe("고침");
  });

  it("한 번 해 보기: 걸음마다 맞음 · 틀림이 쌓이고 끝나면 비운다", () => {
    let state = applyLearnEvent(idleLearn, "demo_replay_started", { total: 3 });
    expect(state.phase).toBe("replaying");
    expect(state.total).toBe(3);
    state = applyLearnEvent(state, "demo_replay_step", { n: 1, text: "주소를 연다", ok: true });
    state = applyLearnEvent(state, "demo_replay_step", { n: 2, text: "「검색」 칸에 넣는다", ok: null });
    state = applyLearnEvent(state, "demo_replay_step", { n: 2, text: "「검색」 칸에 넣는다", ok: false, note: "칸을 못 찾음" });
    expect(state.replay.map((row) => row.state)).toEqual(["ok", "bad"]);
    expect(state.replay[1].note).toBe("칸을 못 찾음");
    expect(applyLearnEvent(state, "demo_replay_done", { ok: false })).toEqual(idleLearn);
  });

  it("모르는 사건은 그대로 둔다", () => {
    const state = applyLearnEvent(idleLearn, "demo_started", { label: "a" });
    expect(applyLearnEvent(state, "something_else", {})).toBe(state);
  });

  it("걸음 한 줄은 종류 · 칸 이름 · 곳만 — 입력한 글은 싣지 않는다", () => {
    expect(stepSentence({ n: 1, kind: "fill", name: "검색", where: "coupang.com" }, "ko")).toBe("입력 · 「검색」 (coupang.com)");
    expect(stepSentence({ n: 2, kind: "click", name: "Cart", where: "" }, "en")).toBe("Click · Cart");
    expect(stepSentence({ n: 3, kind: "nav", name: "", where: "a.com/x" }, "ko")).toBe("이동 (a.com/x)");
  });
});
