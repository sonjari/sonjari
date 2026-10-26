import { describe, expect, it } from "vitest";
import { applyDeckEvent } from "./DeckStage";

describe("deck events (10-25)", () => {
  it("collects slides of one deck and follows the latest", () => {
    let deck = applyDeckEvent(undefined, "deck_slide", { title: "손자리 소개", index: 1, total: 3, html: "<p>1</p>" });
    deck = applyDeckEvent(deck, "deck_slide", { title: "손자리 소개", index: 2, total: 3, html: "<p>2</p>" });
    expect(deck?.latest).toBe(2);
    expect(Object.keys(deck?.slides ?? {})).toEqual(["1", "2"]);
    deck = applyDeckEvent(deck, "deck_built", { title: "손자리 소개", path: "C:/x/손자리 소개.pptx", slides: 3 });
    expect(deck?.built?.path).toBe("C:/x/손자리 소개.pptx");
  });

  it("starts over when a different deck begins and ignores broken events", () => {
    const first = applyDeckEvent(undefined, "deck_slide", { title: "A", index: 1, total: 2, html: "a" });
    const second = applyDeckEvent(first, "deck_slide", { title: "B", index: 1, total: 5, html: "b" });
    expect(second?.title).toBe("B");
    expect(Object.keys(second?.slides ?? {})).toEqual(["1"]);
    expect(applyDeckEvent(second, "deck_slide", { title: "B" })).toBe(second);
    expect(applyDeckEvent(undefined, "deck_built", { path: "x" })).toBeUndefined();
  });

  it("keeps the three suggested styles and marks the one the slides use", () => {
    const picks = [
      { theme: "scorecard", name: "분기 성적표", why: "요청의 「보고 · 분기」", html: "<section>a</section>" },
      { theme: "paper", name: "흰 종이", html: "<section>b</section>" },
      { theme: "bad", name: "빈 것", html: "" },
    ];
    let deck = applyDeckEvent(undefined, "deck_themes", { title: "카페 보고", picks });
    expect(deck?.picks?.map((pick) => pick.theme)).toEqual(["scorecard", "paper"]);
    expect(deck?.total).toBe(0);
    deck = applyDeckEvent(deck, "deck_slide", { title: "카페 보고", index: 1, total: 6, html: "<p>1</p>", theme: "scorecard" });
    expect(deck?.theme).toBe("scorecard");
    expect(deck?.picks?.length).toBe(2);
    expect(applyDeckEvent(deck, "deck_themes", { title: "카페 보고", picks: [] })).toBe(deck);
  });

  it("walks the co-create flow: pick a style, settle the storyboard, notes per slide, assembly count (10-25 2차)", () => {
    const picks = [{ theme: "ir-brief", name: "IR", html: "<section>a</section>" }, { theme: "paper", name: "흰 종이", html: "<section>b</section>" }];
    let deck = applyDeckEvent(undefined, "deck_themes", { title: "IR", picks, say: "숫자가 많아 차분한 결", chosen: "ir-brief", wait_s: 9 }, 1000);
    expect(deck?.ask).toEqual({ kind: "theme", until: 10_000 });
    expect(deck?.say).toBe("숫자가 많아 차분한 결");
    deck = applyDeckEvent(deck, "deck_theme_set", { title: "IR", theme: "paper", by: "person" });
    expect(deck?.theme).toBe("paper");
    expect(deck?.themeBy).toBe("person");
    expect(deck?.ask).toBeUndefined();
    const cards = [{ layout: "ir-cover", claim: "표지" }, { layout: "parts", claim: "한 곳 5.6만 원" }, { layout: "ir-closing", claim: "요청" }];
    deck = applyDeckEvent(deck, "deck_outline", { title: "IR", cards, say: "숫자 장을 가운데", wait_s: 14 }, 2000);
    expect(deck?.outline?.length).toBe(3);
    expect(deck?.ask?.kind).toBe("outline");
    deck = applyDeckEvent(deck, "deck_outline_set", { title: "IR", cards: cards.slice(0, 2), by: "person" });
    expect(deck?.outlineSettled).toBe(true);
    expect(deck?.total).toBe(2);
    deck = applyDeckEvent(deck, "deck_slide", { title: "IR", index: 1, total: 2, html: "<p>1</p>", note: "표지는 짧게" });
    deck = applyDeckEvent(deck, "deck_slide", { title: "IR", index: 1, total: 2, html: "<p>1b</p>" });
    expect(deck?.notes?.[1]).toBe("표지는 짧게");
    expect(deck?.versions?.[1]).toBe(2);
    deck = applyDeckEvent(deck, "deck_built", { title: "IR", path: "C:/x/IR.pptx", assembly: { parts: 1, template: 1 } });
    expect(deck?.built?.parts).toBe(1);
    expect(deck?.built?.template).toBe(1);
  });

  it("keeps photo spots per slide and does not replay the build when a photo lands (10-25 사진 넣기)", () => {
    const slots = [{ id: "s1", label: "매장 전경", filled: false }, { id: "s2", label: "관리자 화면", filled: false }];
    let deck = applyDeckEvent(undefined, "deck_slide", { title: "IR", index: 2, total: 3, html: "<p>2</p>", slots });
    deck = applyDeckEvent(deck, "deck_slide", { title: "IR", index: 3, total: 3, html: "<p>3</p>" });
    expect(deck?.slots?.[2]?.map((slot) => slot.id)).toEqual(["s1", "s2"]);
    deck = applyDeckEvent(deck, "deck_built", { title: "IR", path: "C:/x/IR.pptx" });
    deck = applyDeckEvent(deck, "deck_slide", { title: "IR", index: 2, total: 3, html: "<p>2 img</p>", photo: true,
                                                slots: [{ ...slots[0], filled: true }, slots[1]] });
    expect(deck?.slots?.[2]?.[0]?.filled).toBe(true);
    expect(deck?.still?.[2]).toBe(deck?.versions?.[2]);
    expect(deck?.latest).toBe(3);
    expect(deck?.built?.path).toBe("C:/x/IR.pptx");
  });
});
