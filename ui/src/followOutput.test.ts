import { describe, expect, it } from "vitest";
import { NEAR_BOTTOM_PX, nextFollowState } from "./followOutput";

const at = (distanceFromBottom: number, userScrolledRecently: boolean, following = true) =>
  nextFollowState({ following, distanceFromBottom, userScrolledRecently });

describe("답을 따라 화면을 내릴지", () => {
  it("바닥에 있으면 따라간다", () => {
    expect(at(0, false)).toBe(true);
    expect(at(NEAR_BOTTOM_PX - 1, false)).toBe(true);
  });

  it("사람이 위로 올렸으면 놓는다 — 읽던 자리를 뺏지 않는다", () => {
    expect(at(900, true)).toBe(false);
  });

  it("사람이 바닥으로 돌아오면 다시 따라간다", () => {
    expect(at(10, true, false)).toBe(true);
  });

  // ★ 이 저장소가 실제로 겪은 고장. 스크롤 앵커링과 smooth 애니메이션이 만든
  // 스크롤을 사람이 올린 것으로 오해해서, 대화를 열자마자 바닥에서 6,417px
  // 떨어진 채 굳어 있었다. 손도 안 댔는데.
  it("브라우저가 만든 스크롤에는 속지 않는다", () => {
    expect(at(6417, false)).toBe(true);
    expect(at(300, false)).toBe(true);
  });

  it("한번 놓았으면 사람이 내려오기 전까지는 계속 놓아 둔다", () => {
    expect(at(900, false, false)).toBe(false);
  });

  it("손을 뗀 지 오래면(userScrolledRecently=false) 그 위치는 사람 뜻이 아니다", () => {
    // 같은 위치라도 손동작이 최근이냐에 따라 갈린다 — 그게 이 판단의 전부다.
    expect(at(900, true)).toBe(false);
    expect(at(900, false)).toBe(true);
  });
});
