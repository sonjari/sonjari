import { describe, expect, it } from "vitest";
import type { JobSummary, ScheduleRow } from "../types";
import type { RoomRow } from "./jobs";
import {
  DONE_KEEP, durationLabel, elapsedSec, groupJobs, isLive, jobMetrics, jobStateLabel,
  jobShownHere, jobToFollow, paneContext, paneWidth, pendingSchedules, riskLabel, routineFailed, routineLine, scheduleLabel, scheduleWhen, toneOf, whereAQueuedJobLands,
  withLiveRooms, withRunningFirst, withYieldedLast,
} from "./jobs";

const NOW = 1_787_000_000;

function job(id: string, status: string, extra: Partial<JobSummary> = {}): JobSummary {
  return {
    id, kind: "chat", title: id, status,
    risk_level: "L0", error: "", build: "test",
    created_at: NOW - 600, updated_at: NOW, started_at: NOW - 600, finished_at: null,
    attempts: 1, session_id: "office-main", origin: "workspace",
    steps: 0, completion_state: "",
    ...extra,
  };
}

function schedule(id: string, status: string, runAt: number): ScheduleRow {
  return {
    id, title: id, prompt: "…", session_id: "office-main",
    run_at: runAt, status, created_at: NOW - 3600, updated_at: NOW - 3600, last_job_id: "",
  };
}

describe("일감 묶기", () => {
  it("사람이 눌러야 움직이는 것이 도는 것보다 위다", () => {
    // 승인을 놓치면 작업이 아무 말 없이 멈춰 있는다. 목록 아래에 있으면 놓친다.
    const { live } = groupJobs([
      job("running", "running"),
      job("queued", "queued", { created_at: NOW - 10 }),
      job("approval", "waiting_approval", { created_at: NOW - 5 }),
      job("continuation", "waiting_continuation", { created_at: NOW - 3 }),
    ]);
    expect(live.map((row) => row.id)).toStrictEqual(["approval", "continuation", "running", "queued"]);
  });

  it("끝난 것은 최근 순으로, 정해진 개수만", () => {
    const rows = Array.from({ length: 12 }, (_, index) =>
      job(`done-${index}`, "completed", { finished_at: NOW - index * 60 }));
    const { done } = groupJobs(rows);
    expect(done).toHaveLength(DONE_KEEP);
    expect(done[0].id).toBe("done-0");
  });

  it("끝난 것에 finished_at 이 없으면 updated_at 으로 세운다", () => {
    // 옛 줄에는 finished_at 이 비어 있다. 없는 값을 0 으로 읽으면 그 줄이 통째로
    // 목록 맨 아래로 밀려 사실상 사라진다.
    const { done } = groupJobs([
      job("old", "cancelled", { finished_at: null, updated_at: NOW - 10 }),
      job("older", "cancelled", { finished_at: NOW - 900 }),
    ]);
    expect(done.map((row) => row.id)).toStrictEqual(["old", "older"]);
  });

  it("살아 있는 상태를 이름이 아니라 목록으로 판정한다", () => {
    expect(isLive(job("a", "running"))).toBe(true);
    expect(isLive(job("b", "waiting_approval"))).toBe(true);
    expect(isLive(job("c", "completed"))).toBe(false);
    // 모르는 상태는 살아 있는 것으로 치지 않는다 — 안 그러면 새 상태가 생길 때마다
    // 목록 위층이 조용히 불어난다.
    expect(isLive(job("d", "quantum"))).toBe(false);
  });
});

describe("소요 시간", () => {
  it("차례를 기다리는 동안은 세지 않는다", () => {
    // 사고 S 셋째: 벤치가 잡을 POST 한 시각부터 재서, 시작도 못 한 판이
    // `421초 · 0걸음` 으로 찍혔다. 일한 시간은 started_at 부터다.
    expect(elapsedSec(job("q", "queued", { started_at: null }), NOW)).toBe(0);
  });

  it("도는 중이면 지금까지, 끝났으면 끝난 시각까지", () => {
    expect(elapsedSec(job("r", "running", { started_at: NOW - 143 }), NOW)).toBe(143);
    expect(elapsedSec(job("d", "completed", { started_at: NOW - 900, finished_at: NOW - 600 }), NOW)).toBe(300);
  });

  it("사람이 읽는 단위로 적는다", () => {
    expect(durationLabel(43)).toBe("43초");
    expect(durationLabel(143)).toBe("2분 23초");
    expect(durationLabel(10_301)).toBe("2시간 51분");
  });
});

describe("한 줄에 적는 계기값", () => {
  it("시도 횟수는 1보다 클 때만 적는다", () => {
    // 모든 줄에 "1번째 시도"가 붙어 있으면 아무도 안 읽는다 — 안 읽히는 경보는
    // 없는 것과 같다(사고 S).
    expect(jobMetrics(job("a", "completed", { started_at: NOW - 42, finished_at: NOW, steps: 7 }), NOW))
      .toStrictEqual(["42초", "7걸음"]);
    expect(jobMetrics(job("b", "failed", { started_at: NOW - 42, finished_at: NOW, steps: 7, attempts: 3 }), NOW))
      .toStrictEqual(["42초", "7걸음", "3번째 시도"]);
  });

  it("아직 시작 안 한 줄에는 0초를 적지 않는다", () => {
    expect(jobMetrics(job("q", "queued", { started_at: null }), NOW)).toStrictEqual([]);
  });
});

describe("색이 뜻하는 것", () => {
  it("네 가지 뜻 밖으로 새지 않는다", () => {
    expect(toneOf(job("a", "waiting_approval"))).toBe("hold");
    expect(toneOf(job("b", "running"))).toBe("agent");
    expect(toneOf(job("c", "completed", { completion_state: "complete" }))).toBe("safe");
    expect(toneOf(job("d", "failed"))).toBe("fail");
    expect(toneOf(job("e", "cancelled"))).toBe("mute");
  });

  it("시킨 것을 다 못 채운 판을 초록으로 칠하지 않는다", () => {
    // completion_state=partial 은 "끝났지만 못 채웠다"는 뜻이다. 초록이면 화면이
    // 다 됐다고 거짓말한다.
    expect(toneOf(job("p", "completed", { completion_state: "partial" }))).toBe("hold");
  });

  it("위험 등급을 숫자로만 두지 않는다", () => {
    expect(riskLabel("L0")).toBe("읽기만");
    expect(riskLabel("L2")).toBe("되돌릴 수 없음");
    expect(riskLabel("L4")).toBe("되돌릴 수 없음");
  });
});

describe("예약", () => {
  it("아직 돌 것만 남기고 이른 것부터", () => {
    const rows = pendingSchedules([
      schedule("late", "pending", NOW + 7200),
      schedule("cancelled", "cancelled", NOW + 60),
      schedule("soon", "pending", NOW + 600),
      schedule("done", "completed", NOW - 60),
    ]);
    expect(rows.map((row) => row.id)).toStrictEqual(["soon", "late"]);
  });

  it("시각이 지났는데 안 돌았으면 숨기지 않는다", () => {
    expect(scheduleLabel(schedule("x", "pending", NOW - 30), NOW)).toBe("곧 시작");
    expect(scheduleLabel(schedule("y", "pending", NOW + 47 * 60), NOW)).toBe("47분 뒤");
    expect(scheduleLabel(schedule("z", "pending", NOW + 3 * 3600), NOW)).toBe("3시간 뒤");
  });
});

describe("루틴 예약 (모델 없이 · 2026-10-23)", () => {
  const routine = (status: string, last: object | null, updated = NOW - 60): ScheduleRow => ({
    ...schedule(`r-${status}`, status, NOW - 120), kind: "routine", updated_at: updated,
    last_result: last ? JSON.stringify(last) : "",
  });

  it("0건과 깨짐을 다른 말로 쓴다 — 깨진 회차를 0건처럼 보이면 「새 공고 없음」으로 읽힌다", () => {
    const empty = routine("pending", { status: "empty", count: 0, at: NOW - 60 });
    const broken = routine("pending", { status: "broken", count: 0, problems: ["career 칸을 10줄 모두에서 못 읽었다"], at: NOW - 60 });
    expect(routineLine(empty, NOW)).toMatch(/^모델 없이 · 0건 · /);
    expect(routineLine(broken, NOW)).toBe("깨짐 · career 칸을 10줄 모두에서 못 읽었다");
    expect(routineFailed(broken)).toBe(true);
    expect(routineFailed(empty)).toBe(false);
  });

  it("아직 안 돈 루틴 · 받기 실패도 그대로 말한다", () => {
    expect(routineLine(routine("pending", null), NOW)).toBe("모델 없이 · 아직 안 돎");
    expect(routineLine(routine("pending", { status: "failed", count: 0, at: NOW - 60 }), NOW)).toMatch(/^못 받음 · /);
  });

  it("한 번만 도는 루틴은 돈 뒤에도 하루 남는다(결과를 볼 자리) · 프롬프트 예약은 그대로 사라진다", () => {
    const rows = pendingSchedules([
      routine("ran", { status: "ok", count: 10, at: NOW - 60 }),
      routine("ran", { status: "ok", count: 3 }, NOW - 2 * 86_400),
      schedule("prompt-done", "dispatched", NOW - 60),
    ], NOW);
    expect(rows.map((row) => row.updated_at)).toStrictEqual([NOW - 60]);
  });
});

describe("덜 채우고 끝난 판", () => {
  it("그냥 '끝'이라고 적지 않는다", () => {
    // 색만 갈라 놓고 글자는 "끝"이면, 색을 못 보는 사람에게는 다 됐다고 말한 것이다.
    expect(jobStateLabel(job("p", "completed", { completion_state: "partial" }))).toBe("덜 채우고 끝");
    expect(jobStateLabel(job("c", "completed", { completion_state: "complete" }))).toBe("끝");
    // 옛 줄에는 completion_state 가 비어 있다. 모른다고 "덜 채웠다"고 하면 안 된다.
    expect(jobStateLabel(job("o", "completed", { completion_state: "" }))).toBe("끝");
    // 대조할 요구가 없는 짧은 대화는 덜 채운 것이 아니다(2026-09-17 E2E 「자기소개」).
    expect(jobStateLabel(job("a", "completed", { completion_state: "answered" }))).toBe("끝");
    expect(jobStateLabel(job("u", "completed", { completion_state: "unmeasured" }))).toBe("끝");
  });
});

describe("예약 시각 표기", () => {
  it("상대 표기와 절대 시각이 같은 말을 하지 않는다", () => {
    // 하루 넘게 남은 예약이 두 칸 모두 "8월 20일"로 나왔다 — 한 칸이 버려진 것이다.
    const far = schedule("far", "pending", NOW + 4 * 86_400);
    expect(scheduleLabel(far, NOW)).toBe("4일 뒤");
    expect(scheduleWhen(far, NOW)).not.toBe(scheduleLabel(far, NOW));
    expect(scheduleWhen(far, NOW)).toMatch(/\d/);
  });
});

describe("jobToFollow", () => {
  it("이 화면에서 보낸 것이 있으면 그것을 따라간다", () => {
    expect(jobToFollow("mine", [job("server", "running")])).toBe("mine");
  });

  it("★ 대기열이 비어도 서버에서 도는 일을 따라간다", () => {
    // 앱을 껐다 켜면 pending 이 비어 있다. 예전에는 그때 화면이 "준비됐습니다"
    // 로 멈춰 있었고, 실제로는 같은 일이 6분 58초째 돌고 있었다.
    const jobs = [
      job("older", "completed", { created_at: NOW - 500 }),
      job("live", "running", { created_at: NOW - 100 }),
    ];
    expect(jobToFollow("", jobs)).toBe("live");
  });

  it("사람이 손대야 하는 것이 도는 것보다 먼저다", () => {
    const jobs = [
      job("running", "running", { created_at: NOW - 10 }),
      job("needs-me", "waiting_approval", { created_at: NOW - 300 }),
    ];
    expect(jobToFollow("", jobs)).toBe("needs-me");
  });

  it("살아 있는 것이 없으면 아무것도 따라가지 않는다", () => {
    expect(jobToFollow("", [job("done", "completed")])).toBe("");
  });

  it("도는 것이 여럿이면 최근 것을 따라간다", () => {
    const jobs = [
      job("old", "running", { created_at: NOW - 900 }),
      job("new", "running", { created_at: NOW - 10 }),
    ];
    expect(jobToFollow("", jobs)).toBe("new");
  });
});

describe("whereAQueuedJobLands — 바깥 AI 가 맡긴 판은 제 방으로", () => {
  const base = { delegated: true, queuedSession: "mcp-abc", viewedSession: "office-main", waitingHere: 0 };

  it("opens the delegated job in its own room instead of the conversation the person is reading", () => {
    expect(whereAQueuedJobLands(base)).toBe("own-room");
  });

  it("does not take the screen while the person waits for their own answer — it only lists it", () => {
    expect(whereAQueuedJobLands({ ...base, waitingHere: 1 })).toBe("listed");
  });

  it("stays put when the person is already looking at that room", () => {
    expect(whereAQueuedJobLands({ ...base, viewedSession: "mcp-abc" })).toBe("here");
  });

  it("keeps the old behaviour for a delegated job that came without a room", () => {
    expect(whereAQueuedJobLands({ ...base, queuedSession: "" })).toBe("here");
  });

  it("leaves the person's own jobs exactly as before", () => {
    const own = { delegated: false, waitingHere: 0 };
    expect(whereAQueuedJobLands({ ...own, queuedSession: "office-main", viewedSession: "office-main" })).toBe("here");
    expect(whereAQueuedJobLands({ ...own, queuedSession: "other", viewedSession: "office-main" })).toBe("elsewhere");
    expect(whereAQueuedJobLands({ ...own, queuedSession: "", viewedSession: "office-main" })).toBe("elsewhere");
  });
});

describe("paneWidth — 작업 창의 폭은 창 틀을 따른다", () => {
  // 2026-10-11 대표 화면: Code 탭을 보는 중에 바깥 AI 가 맡긴 일반 일이 뜨자, 틀은 화면 절반을 내줬는데 칸은 468 로 그려져
  // 오른쪽 절반이 텅 비었다. 폭을 일의 모드로 정하던 것이 원인이었다.
  it("fills the half the Code frame gives, whatever kind of job is shown", () => {
    const person = { mode: "code" as const, codeWorkspace: "C:/person/project" };
    const shown = paneContext(job("d", "running", { origin: "mcp", workspace_mode: "cowork", code_workspace: "" }), person);
    expect(shown.mode).toBe("cowork");
    expect(paneWidth({ frame: person.mode, stage: false })).toBe("100%");
  });

  it("keeps the narrow rail in the Cowork frame, and the stage width when the stage is on", () => {
    expect(paneWidth({ frame: "cowork", stage: false })).toBe(468);
    expect(paneWidth({ frame: "cowork", stage: true, stageWidth: 880 })).toBe(880);
    expect(paneWidth({ frame: "cowork", stage: true })).toBe(468);
  });
});

describe("paneContext — 맡긴 판을 보는 동안은 그 판의 폴더", () => {
  const person = { mode: "code" as const, codeWorkspace: "C:/person/project" };

  it("shows the delegated job's own mode and folder", () => {
    const delegated = job("d", "running", { origin: "mcp", workspace_mode: "code", code_workspace: "C:/copy/repo" });
    expect(paneContext(delegated, person)).toEqual({ mode: "code", codeWorkspace: "C:/copy/repo" });
  });

  it("does not show the person's folder for a delegated research job", () => {
    const delegated = job("d", "running", { origin: "mcp", workspace_mode: "cowork", code_workspace: "" });
    expect(paneContext(delegated, person)).toEqual({ mode: "cowork", codeWorkspace: "" });
  });

  it("leaves the person's own job, no job, and an old server as they were", () => {
    expect(paneContext(job("p", "running", { origin: "chat", workspace_mode: "cowork" }), person)).toBe(person);
    expect(paneContext(undefined, person)).toBe(person);
    expect(paneContext(job("d", "running", { origin: "mcp" }), person)).toBe(person);
  });
});

describe("도는 판은 그 판의 방에서만 그린다 (2026-10-09 낮)", () => {
  const queue = [{ jobId: "delegated", sessionId: "mcp-room" }, { jobId: "mine", sessionId: "my-room" }];

  it("다른 방에서 도는 판은 여기 것이 아니다 — 생각·멈춤 단추·덧붙임 입력창을 그리지 않는다", () => {
    expect(jobShownHere("delegated", "my-room", queue, [])).toBe("");
    expect(jobShownHere("delegated", "mcp-room", queue, [])).toBe("delegated");
    expect(jobShownHere("mine", "my-room", queue, [])).toBe("mine");
  });

  it("줄에 없는 판은 서버가 준 목록에서 방을 찾는다", () => {
    expect(jobShownHere("j1", "my-room", [], [job("j1", "running", { session_id: "mcp-room" })])).toBe("");
    expect(jobShownHere("j1", "mcp-room", [], [job("j1", "running", { session_id: "mcp-room" })])).toBe("j1");
  });

  it("방을 모르는 판은 지금까지처럼 여기 것으로 친다", () => {
    expect(jobShownHere("j1", "my-room", [], [])).toBe("j1");
    expect(jobShownHere("j1", "my-room", [], [job("j1", "running", { session_id: "" })])).toBe("j1");
    expect(jobShownHere("", "my-room", queue, [])).toBe("");
  });

  it("돌기 시작한 판이 맨 앞으로 온다 — 사람의 판이 맡긴 판보다 먼저 돌 때", () => {
    expect(withRunningFirst(queue, "mine").map((item) => item.jobId)).toEqual(["mine", "delegated"]);
    expect(withRunningFirst(queue, "delegated")).toBe(queue);
    expect(withRunningFirst(queue, "unknown")).toBe(queue);
  });

  it("비켜 준 판은 맨 뒤로 간다", () => {
    expect(withYieldedLast(queue, "delegated").map((item) => item.jobId)).toEqual(["mine", "delegated"]);
    expect(withYieldedLast(queue, "mine")).toBe(queue);
    expect(withYieldedLast([{ jobId: "only", sessionId: "r" }], "only")).toHaveLength(1);
    expect(withYieldedLast(queue, "unknown")).toBe(queue);
  });
});

describe("도는 판의 방은 목록에 줄이 있다 (2026-10-09 저녁)", () => {
  const room = (session_id: string, title = session_id): RoomRow => ({
    session_id, title, preview: "", message_count: 2, updated_at: NOW - 900, has_summary: false,
  });

  it("목록에 없는 방에서 판이 돌고 있으면 맨 위에 한 줄을 세운다", () => {
    const rows = withLiveRooms([room("mine")], [job("j1", "running", { session_id: "mcp-room", origin: "mcp", title: "맡긴 일" })]);
    expect(rows.map((row) => row.session_id)).toEqual(["mcp-room", "mine"]);
    expect(rows[0].title).toBe("맡긴 일");
    expect(rows[0].caller).toBeTruthy();
  });

  it("앱 안 Claude 가 맡긴 판(via=app)은 도는 동안에도 제 방을 세우지 않는다 (2026-10-26 대표)", () => {
    const sessions = [room("mine")];
    const rows = withLiveRooms(sessions, [job("j1", "running", { session_id: "mcp-app", origin: "mcp", via: "app" })]);
    expect(rows).toBe(sessions);
    // 바깥 클로드가 맡긴 판은 지금처럼 선다.
    expect(withLiveRooms(sessions, [job("j2", "running", { session_id: "mcp-out", origin: "mcp" })]).map((row) => row.session_id))
      .toEqual(["mcp-out", "mine"]);
  });

  it("이미 목록에 있는 방이면 진짜 줄을 그대로 쓴다 — 두 줄이 되지 않는다", () => {
    const sessions = [room("mcp-room", "진짜 제목"), room("mine")];
    const rows = withLiveRooms(sessions, [job("j1", "running", { session_id: "mcp-room", origin: "mcp" })]);
    expect(rows).toBe(sessions);
  });

  it("끝난 판은 줄을 세우지 않는다 · 한 방에 판이 여럿이어도 한 줄이다", () => {
    expect(withLiveRooms([room("mine")], [job("j1", "completed", { session_id: "mcp-room", origin: "mcp" })])
      .map((row) => row.session_id)).toEqual(["mine"]);
    const rows = withLiveRooms([], [
      job("j1", "running", { session_id: "mcp-room", origin: "mcp" }),
      job("j2", "queued", { session_id: "mcp-room", origin: "mcp" }),
    ]);
    expect(rows).toHaveLength(1);
  });

  it("사람이 시킨 판의 방도 세우되 맡긴 쪽 표시는 붙이지 않는다 · 방이 없는 판은 건너뛴다", () => {
    const rows = withLiveRooms([], [
      job("j1", "running", { session_id: "new-room", origin: "workspace" }),
      job("j2", "running", { session_id: "", origin: "workspace" }),
    ]);
    expect(rows.map((row) => row.session_id)).toEqual(["new-room"]);
    expect(rows[0].caller).toBeUndefined();
  });
});

