/**
 * 사람이 머리말의 「크게/작게」를 누른 뜻 — **어느 판에 대한 뜻인지 같이** 기억한다 (2026-10-30 · 10-29 촬영 「크게 보기가 잘 안 먹음」).
 *
 * 예전에는 뜻 하나(켬 · 끔 · 없음)만 두고 「따라가는 판 번호가 바뀌면 지운다」였다. 그런데 따라가는 판은 잡 목록이 올 때마다 다시
 * 고른다(`jobToFollow`) — 판이 잠깐 기다림이 되거나 맡긴 판이 사람의 판에 비켜 주면 번호가 비었다가 **같은 판으로 돌아온다.**
 * 그때마다 사람이 누른 것이 지워져 무대가 자동으로 되돌아갔다. 이제 같은 판으로 돌아오면 그 뜻이 살아 있고, 다른 판이면 자동이다.
 */
export interface StageChoice {
  jobId: string;
  on: boolean;
}

/** 지금 보는 판에 대한 사람의 뜻. 없으면 null(자동). */
export function stageChoiceFor(choice: StageChoice | null, jobId: string): boolean | null {
  return choice && choice.jobId === jobId ? choice.on : null;
}

/** 지금 보는 판에 뜻을 적는다. null 은 「자동으로」. */
export function chooseStage(jobId: string, on: boolean | null): StageChoice | null {
  return on === null ? null : { jobId, on };
}
