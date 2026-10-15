/**
 * 판은 끝났는데 답이 아직 칠해지는 중일 때 (2026-10-07).
 *
 * 확정된 답은 초당 90자로 「스르륵」 칠해진다. 예전에는 그 연출이 판을 도는 스레드에서 돌아, 칠하기가 끝나야 판이
 * 끝났다(답 길이에 따라 3~5초). 이제 백엔드는 이 창이 시킨 판의 답을 **판 밖에서** 칠한다 — 판은 먼저 끝나고
 * 글 조각은 그 뒤에도 얼마 동안 온다. 백엔드는 그럴 때 `agent_answer_reset` 에 `apart: true` 를 싣고, 다 칠하면
 * `agent_answer_painted` 를 보낸다.
 *
 * 화면이 할 일: 판이 끝났다는 사건이 와도 그 답을 끝까지 흘려 보여 주고(「자리 잡는 중」), 다 칠해지면 대화를 다시 읽는다.
 * 뒤에 줄 선 판이 있거나 새 판이 시작되면 기다리지 않고 바로 완성된 답으로 바꾼다.
 *
 * 여기는 **판단만** 한다. 화면 상태를 바꾸는 것은 부르는 쪽(`WorkspaceApp`)이다.
 */

export type PaintState = {
  /** 판 밖에서 칠하는 중인 판(백엔드가 `apart` 라고 알린 뒤, 다 칠했다는 사건이 오기 전). */
  apartJob: string;
  /** 판은 끝났고 답만 마저 칠해지는 판. */
  settlingJob: string;
};

export const NO_PAINT: PaintState = { apartJob: "", settlingJob: "" };

/** 다 칠했다는 사건이 끝내 안 올 때 기다리는 한도(ms). 백엔드의 칠하기 상한(6초)보다 조금 길다. */
export const SETTLE_MAX_MS = 8_000;

export function onAnswerReset(state: PaintState, jobId: string, apart: boolean): PaintState {
  if (apart) return { ...state, apartJob: jobId };
  return state.apartJob === jobId ? { ...state, apartJob: "" } : state;
}

/** 다 칠했다. 자리 잡던 판이면 `finish` — 부르는 쪽이 대화를 다시 읽는다. */
export function onAnswerPainted(state: PaintState, jobId: string): { state: PaintState; finish: boolean } {
  if (state.settlingJob === jobId) return { state: NO_PAINT, finish: true };
  return { state: state.apartJob === jobId ? { ...state, apartJob: "" } : state, finish: false };
}

/**
 * 맨 앞의 판이 끝났다. 답이 아직 칠해지는 중이고 뒤에 줄 선 판이 없으면 `settle` — 흘리던 글을 거두지 않는다.
 * 실패·취소로 끝난 판은 칠할 답이 없다.
 */
export function onHeadJobDone(
  state: PaintState, jobId: string, completed: boolean, queuedBehind: number,
): { state: PaintState; settle: boolean } {
  if (completed && queuedBehind === 0 && state.apartJob === jobId) {
    return { state: { apartJob: "", settlingJob: jobId }, settle: true };
  }
  return { state: state.apartJob === jobId ? { ...state, apartJob: "" } : state, settle: false };
}

/** 이 사건이 자리 잡는 판의 것인가. 그 판의 글 조각은 판이 끝난 뒤에도 받아야 한다. */
export function isSettling(state: PaintState, jobId: string): boolean {
  return Boolean(jobId) && state.settlingJob === jobId;
}
