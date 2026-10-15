/**
 * 내가 방금 보낸 질문이 사건으로 되돌아온 것인가.
 *
 * ## 왜 있나
 *
 * 백엔드는 잡을 만드는 **순간** `job_queued` 를 발행한다. 그건 `POST /chat` 이
 * 응답을 돌려주기 전이다. 그래서 화면에서는 이런 순서가 된다:
 *
 * ```
 * send()  화면에 내 질문 추가 ─→ await POST ─────────────→ 대기열에 job_id 기록
 *                                   ↑                            ↑
 *         잡 생성 → job_queued 발행 ─┘  SSE 먼저 도착           너무 늦다
 * ```
 *
 * 사건이 도착한 시점에 대기열은 아직 비어 있다. "내가 만든 작업인가"를 대기열로
 * 판별하던 코드는 그래서 **아니오**라고 답했고, 내 질문을 화면에 한 번 더 얹었다
 * (2026-08-06 사용자 화면: 같은 문장이 같은 분에 두 번).
 *
 * 답이 느릴수록 이 창이 넓어진다 — thinking 모드에서 특히 잘 터진 이유다.
 *
 * 고치는 방법은 **await 앞에서** 쪽지를 남기는 것뿐이다. 그 시점이 사건보다 확실히
 * 앞서는 유일한 지점이다.
 */

export type LocalSend = { prompt: string; at: number };

/** 쪽지의 유효 기간. 답이 아무리 느려도 이 안에는 job_queued 가 온다. */
export const ECHO_WINDOW_MS = 60_000;

/** 보내기 직전에 남기는 쪽지. 오래된 것은 여기서 함께 치운다. */
export function rememberLocalSend(
  sends: readonly LocalSend[],
  prompt: string,
  now: number = Date.now(),
): LocalSend[] {
  return [...sends.filter((item) => now - item.at < ECHO_WINDOW_MS), { prompt, at: now }];
}

/**
 * 이 질문이 내 쪽지와 맞는가. 맞으면 그 쪽지 **하나만** 빼고 돌려준다.
 *
 * 하나만 빼는 것이 중요하다. 같은 문장을 두 번 물으면 쪽지도 두 장이고, 사건도 두
 * 번 온다 — 한 번에 다 지우면 두 번째 질문이 화면에서 사라진다.
 */
export function takeLocalEcho(
  sends: readonly LocalSend[],
  prompt: string,
  now: number = Date.now(),
): { isEcho: boolean; rest: LocalSend[] } {
  const index = sends.findIndex(
    (item) => item.prompt === prompt && now - item.at < ECHO_WINDOW_MS,
  );
  if (index < 0) return { isEcho: false, rest: [...sends] };
  const rest = [...sends];
  rest.splice(index, 1);
  return { isEcho: true, rest };
}

/** 못 보냈을 때 쪽지를 거둔다. 남겨 두면 다음에 같은 문장을 물었을 때 그게 안 보인다. */
export function forgetLocalSend(
  sends: readonly LocalSend[],
  prompt: string,
): LocalSend[] {
  const index = sends.findIndex((item) => item.prompt === prompt);
  if (index < 0) return [...sends];
  const rest = [...sends];
  rest.splice(index, 1);
  return rest;
}
