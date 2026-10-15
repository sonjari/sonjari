import { describe, expect, it } from "vitest";

import { forgetLocalSend, rememberLocalSend, takeLocalEcho } from "./localEcho";

describe("내가 보낸 질문이 사건으로 되돌아올 때", () => {
  it("되돌아온 것을 알아본다 — 그래야 화면에 두 번 안 얹힌다", () => {
    const sends = rememberLocalSend([], "돈이 보인다 보여", 1_000);

    const { isEcho, rest } = takeLocalEcho(sends, "돈이 보인다 보여", 1_200);

    expect(isEcho).toBe(true);
    expect(rest).toHaveLength(0);
  });

  it("남이 보낸 질문은 내 것이 아니다", () => {
    // 이걸 잘못 판정하면 반대 고장이 난다 — 작은 HUD 나 음성으로 물은 질문이
    // 이 창에 아예 안 나타난다.
    const sends = rememberLocalSend([], "내 질문", 1_000);

    expect(takeLocalEcho(sends, "남의 질문", 1_200).isEcho).toBe(false);
  });

  it("같은 문장을 두 번 물으면 쪽지도 두 장이고 한 번에 하나씩만 소모한다", () => {
    let sends = rememberLocalSend([], "다시 해줘", 1_000);
    sends = rememberLocalSend(sends, "다시 해줘", 2_000);

    const first = takeLocalEcho(sends, "다시 해줘", 2_100);
    const second = takeLocalEcho(first.rest, "다시 해줘", 2_200);
    const third = takeLocalEcho(second.rest, "다시 해줘", 2_300);

    expect(first.isEcho).toBe(true);
    expect(second.isEcho).toBe(true);
    // 세 번째는 내가 안 보낸 것이다 — 다른 창에서 온 것이므로 화면에 얹혀야 한다.
    expect(third.isEcho).toBe(false);
  });

  it("오래된 쪽지는 남의 질문을 삼키지 않는다", () => {
    const sends = rememberLocalSend([], "어제 질문", 0);

    expect(takeLocalEcho(sends, "어제 질문", 61_000).isEcho).toBe(false);
  });

  it("쪽지를 남길 때 오래된 것은 함께 치운다", () => {
    const old = rememberLocalSend([], "옛날 것", 0);

    const next = rememberLocalSend(old, "새 것", 70_000);

    expect(next).toHaveLength(1);
    expect(next[0].prompt).toBe("새 것");
  });

  it("못 보낸 질문의 쪽지는 거둔다", () => {
    const sends = rememberLocalSend([], "실패할 질문", 1_000);

    expect(forgetLocalSend(sends, "실패할 질문")).toHaveLength(0);
  });
});
