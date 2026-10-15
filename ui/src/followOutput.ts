/** 답이 흘러나오는 동안 화면을 따라 내릴 것인가 — 그 판단 하나.
 *
 * 컴포넌트에서 떼어 낸 이유는 이 판단이 **틀렸을 때 조용하기** 때문이다. 화면은
 * 멀쩡히 그려지고 글자도 잘 나오는데 화면만 안 따라간다. 붙어 있는 채로는
 * 브라우저가 프레임을 그려 줄 때만 확인할 수 있어서, 시험을 돌릴 수가 없다.
 *
 * 2026-08-09 실측으로 드러난 것: **스크롤을 만드는 것은 사람만이 아니다.**
 *
 *   - 스크롤 앵커링(overflow-anchor)이 위쪽 높이 변화를 상쇄하려고 scrollTop 을
 *     직접 옮긴다. 마크다운이 늦게 자리를 잡을 때마다 벌어진다.
 *   - `scroll-behavior: smooth` 가 걸린 채로 바닥에 붙이면 애니메이션이 돌고,
 *     그 중간 위치마다 scroll 이벤트가 나온다.
 *
 * 위치만 보고 "바닥에서 멀어졌으니 사람이 올렸구나" 하면 저 둘에 전부 속는다.
 * 실제로 대화를 열자마자 바닥에서 6,417px 떨어진 채 굳어 있었다 — 손도 안 댔는데.
 *
 * 그래서 규칙은 비대칭이다:
 *
 *   끄는 것은  최근에 **실제 손동작**이 있었을 때만 (휠·터치·키·스크롤바 잡기)
 *   켜는 것은  바닥 근처면 언제나, 이유를 묻지 않고
 *
 * 놓치는 쪽으로 기울인 것이 맞다. 안 따라가야 할 때 따라가면 읽던 자리를 뺏기지만,
 * 따라가야 할 때 안 따라가면 그냥 고장으로 보인다 — 그게 원래 신고된 증상이다.
 */

/** 이 안쪽이면 "아직 바닥을 보고 있다"로 친다. */
export const NEAR_BOTTOM_PX = 72;

/**
 * 손을 댄 뒤 이만큼 안에 도착한 스크롤만 사람이 한 것으로 본다.
 *
 * 휠은 이벤트가 먼저 오고 스크롤이 뒤따르며, 관성 스크롤은 손을 뗀 뒤에도 잠깐
 * 이어진다. 너무 짧으면 관성 구간이 "브라우저가 한 것"으로 새고, 너무 길면
 * 그 사이에 낀 정상 갱신까지 사람 것으로 오해한다.
 */
export const USER_SCROLL_GRACE_MS = 700;

export interface FollowInput {
  /** 지금 따라가고 있는가. */
  following: boolean;
  /** 바닥까지 남은 픽셀. */
  distanceFromBottom: number;
  /** 방금(유예 시간 안에) 사람이 스크롤에 손을 댔는가. */
  userScrolledRecently: boolean;
}

/** scroll 이벤트 하나를 보고, 계속 따라갈지 정한다. */
export function nextFollowState({
  following,
  distanceFromBottom,
  userScrolledRecently,
}: FollowInput): boolean {
  if (distanceFromBottom < NEAR_BOTTOM_PX) return true;
  if (userScrolledRecently) return false;
  // 바닥에서 멀지만 사람이 한 것이 아니다 — 브라우저가 옮긴 것이므로 놓지 않는다.
  return following;
}
