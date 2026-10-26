import { describe, expect, it } from "vitest";
import type { AgentProgress, ConversationMessage } from "./types";
import { applyPlan, applyStep, buildTimeline, evidenceLine, finishTrajectory, planProgress, startTrajectory, summarize } from "./trajectory";

const progress = (step: number, tool: string, status: AgentProgress["status"] = "completed"): AgentProgress => ({
  key: `${step}`, jobId: "j1", phase: "act", message: `${tool} 함`, step, tool, status,
});

const message = (id: number, at: number, role: "user" | "assistant" = "user"): ConversationMessage => ({
  id, session_id: "s", role, content: "x", kind: "chat", metadata: {}, created_at: at,
});

describe("작업 궤적", () => {
  it("같은 걸음이 두 번 와도 늘어나지 않는다", () => {
    let t = startTrajectory("j1", "s", "물어본 것", 100);
    t = applyStep(t, progress(1, "browser_open", "running"), 101);
    t = applyStep(t, progress(1, "browser_open", "completed"), 103);
    expect(t.steps).toHaveLength(1);
    expect(t.steps[0].status).toBe("completed");
    // 자리(시각)는 처음 붙은 때를 지킨다 — 순서가 흔들리면 안 된다
    expect(t.steps[0].at).toBe(101);
  });

  it("접힌 한 줄은 실제로 센 값만 말한다", () => {
    let t = startTrajectory("j1", "s", "조사", 100);
    t = applyStep(t, progress(1, "browser_open"), 101);
    t = applyStep(t, progress(2, "browser_extract"), 120);
    t = applyStep(t, progress(3, "evidence_check", "failed"), 140);
    t = finishTrajectory(t, "completed", 142);
    const s = summarize(t);
    expect(s.seconds).toBe(42);
    expect(s.failed).toBe(1);
    expect(s.label).toBe("3걸음 · 42초 · 1실패 · 읽기만 함");
  });

  it("쓰기 도구가 섞이면 읽기만 했다고 말하지 않는다", () => {
    let t = startTrajectory("j2", "s", "메일", 0);
    t = applyStep(t, progress(1, "browser_extract"), 1);
    t = applyStep(t, progress(2, "google_gmail_send"), 2);
    t = finishTrajectory(t, "completed", 5);
    expect(summarize(t).wrote).toBe(true);
    expect(summarize(t).label).toContain("바꾼 것 있음");
  });

  it("Claude 가 파일을 고치거나 명령을 돌린 판도 「읽기만 함」이 아니다 (2026-10-26 대표 판)", () => {
    let t = startTrajectory("claude-1", "s", "price.py 고쳐 줘", 0);
    t = applyStep(t, progress(1, "Glob"), 1);
    t = applyStep(t, progress(2, "Read"), 2);
    t = applyStep(t, progress(3, "Edit"), 3);
    expect(summarize(t).label).toContain("바꾼 것 있음");
    // 맡긴 손자리 판이 장표를 구운 걸음도 쓰기다(실제 판 c81a10dd 의 도구).
    let deck = startTrajectory("claude-2", "s", "장표", 0);
    deck = applyStep(deck, progress(1, "mcp__sonjari__sonjari_task"), 1);
    deck = applyStep(deck, progress(2, "local_make_slide"), 2);
    expect(summarize(deck).wrote).toBe(true);
    // 승인이 없어 거절된 명령만 있었으면 바꾼 것이 없다.
    let denied = startTrajectory("claude-3", "s", "시험", 0);
    denied = applyStep(denied, progress(1, "Read"), 1);
    denied = applyStep(denied, progress(2, "Bash", "failed"), 2);
    expect(summarize(denied).wrote).toBe(false);
    denied = applyStep(denied, progress(3, "PowerShell"), 3);
    expect(summarize(denied).wrote).toBe(true);
  });

  it("대화와 궤적이 한 축에 시간 순으로 꿰인다", () => {
    const messages = [message(1, 100), message(2, 200, "assistant")];
    const t = startTrajectory("j1", "s", "물어본 것", 100);
    const timeline = buildTimeline(messages, [t]);
    expect(timeline.map((e) => e.kind)).toStrictEqual(["message", "trajectory", "message"]);
  });

  it("질문과 답의 시각이 같아도 서버가 준 차례를 지킨다 (2026-09-20 노트북)", () => {
    // 서버는 질문과 답을 **같은 시각**(소수점까지)으로 저장한다. 같은 시각의 메시지끼리 비교가 늘 -1 이라
    // 정렬이 답을 질문 **위로** 올렸다 — 화면에서 첫 질문 뒤에 답 없이 다음 질문이 이어졌다.
    const asked = message(25, 269.306791);
    const answered = message(26, 269.306791, "assistant");
    const next = message(27, 292.47);
    for (const input of [[asked, answered, next], [asked, answered]]) {
      const ids = buildTimeline(input, []).map((e) => (e.kind === "message" ? e.message.id : -1));
      expect(ids).toStrictEqual(input.map((m) => m.id));
    }
  });

  it("몇 분 걸린 판도 작업 기록이 질문 위로 안 올라간다 (2026-10-01 스토어 촬영 18번)", () => {
    // 서버는 질문·답을 작업이 **끝날 때** 저장한다(질문 12:57). 상자는 **시작 시각**(12:52)이라 질문보다 앞섰다.
    const asked = { ...message(10, 1257, "user"), metadata: { job_id: "job-k" } };
    const answered = { ...message(11, 1257, "assistant"), metadata: { job_id: "job-k" } };
    const earlier = message(9, 1000, "assistant");
    const box = startTrajectory("job-k", "s", "교보 3권", 952);
    const order = buildTimeline([earlier, asked, answered], [box]).map((e) =>
      e.kind === "message" ? `m${e.message.id}` : "box");
    expect(order).toStrictEqual(["m9", "m10", "box", "m11"]);
  });

  it("작업 번호가 없는 옛 기록은 예전처럼 시작 시각으로 둔다", () => {
    const order = buildTimeline([message(1, 100), message(2, 200, "assistant")], [startTrajectory("j1", "s", "p", 150)])
      .map((e) => (e.kind === "message" ? `m${e.message.id}` : "box"));
    expect(order).toStrictEqual(["m1", "box", "m2"]);
  });

  it("시각이 같으면 질문이 먼저고 궤적이 뒤다", () => {
    const timeline = buildTimeline([message(1, 50)], [startTrajectory("j", "s", "p", 50)]);
    expect(timeline[0].kind).toBe("message");
    expect(timeline[1].kind).toBe("trajectory");
  });
});

describe("시킨 것 대조 (R3)", () => {
  it("요구가 없으면 아무것도 그리지 않는다", () => {
    // "0/0 채움"은 아무 말도 아니다 — 그리고 사람은 그걸 "아무것도 안 했다"로 읽는다.
    const bare = startTrajectory("j1", "s", "고마워", 100);
    expect(planProgress(bare)).toBeNull();
    expect(planProgress(applyPlan(bare, []))).toBeNull();
  });

  it("채운 개수를 센다", () => {
    const t = applyPlan(startTrajectory("j1", "s", "…", 100), [
      { kind: "count", label: "4개 이상 직접 열어 읽기", met: false, saw: "3개 읽음" },
      { kind: "site", label: "크몽에서 읽기", met: true, saw: "2건" },
      { kind: "site", label: "위시켓에서 읽기", met: true, saw: "1건" },
    ]);
    expect(planProgress(t)).toStrictEqual({ met: 2, total: 3 });
  });

  it("대조표는 통째로 갈아 끼운다", () => {
    // 걸음과 다르다. 서버가 매번 전부 다시 세므로, 합치면 사라진 요구가 남는다.
    let t = applyPlan(startTrajectory("j1", "s", "…", 100), [
      { kind: "count", label: "4개", met: false, saw: "0개 읽음" },
      { kind: "site", label: "크몽에서 읽기", met: false, saw: "한 건도 못 읽음" },
    ]);
    t = applyPlan(t, [{ kind: "count", label: "4개", met: true, saw: "5개 읽음" }]);
    expect(t.plan).toHaveLength(1);
    expect(planProgress(t)).toStrictEqual({ met: 1, total: 1 });
  });

  it("걸음과 대조표는 서로를 지우지 않는다", () => {
    let t = startTrajectory("j1", "s", "…", 100);
    t = applyStep(t, progress(1, "browser_open"), 101);
    t = applyPlan(t, [{ kind: "site", label: "크몽에서 읽기", met: true, saw: "2건" }]);
    t = applyStep(t, progress(2, "browser_extract"), 102);
    expect(t.steps).toHaveLength(2);
    expect(t.plan).toHaveLength(1);
    // 끝나도 남는다 — 답 옆에 근거가 남아 있어야 "했다고 말했는데 안 했다"를 잡는다.
    t = finishTrajectory(t, "completed", 200);
    expect(t.plan).toHaveLength(1);
  });
});

describe("걸음이 남긴 근거 (R4)", () => {
  const step = (evidence?: Record<string, unknown>) => ({
    key: "1", step: 1, tool: "browser_extract", message: "읽음",
    status: "completed" as const, at: 0, evidence,
  });

  it("근거가 없으면 빈 줄이다 — 지어내지 않는다", () => {
    expect(evidenceLine(step())).toBe("");
    expect(evidenceLine(step({}))).toBe("");
  });

  it("주소가 맨 앞에 온다", () => {
    // "했다고 말했는데 안 했다"를 잡는 데 제일 먼저 쓰이는 것이 출처다.
    const line = evidenceLine(step({ char_count: 4820, url: "https://kmong.com/gig/1" }));
    expect(line.startsWith("https://kmong.com/gig/1")).toBe(true);
  });

  it("긴 값과 목록은 한 줄에 못 들어간다", () => {
    // 증거 사전에는 도구마다 칸이 열댓 개씩 들어 있다. 다 그리면 걸음 하나가
    // 화면 한 폭을 먹는다.
    const line = evidenceLine(step({
      url: "https://x", text: "가".repeat(400), items: [1, 2, 3], count: 7,
    }));
    expect(line).toBe("https://x · count=7");
  });

  it("도구가 늘 붙이는 칸은 뺀다", () => {
    // action·instruction 은 모든 결과에 붙는 안내문이라 근거가 아니다.
    expect(evidenceLine(step({ action: "extract", instruction: "…", verified: true })))
      .toBe("verified=예");
  });

  it("마지막 검증 걸음의 내부 점검표는 근거가 아니다 (2026-09-20 노트북)", () => {
    expect(evidenceLine({
      ...step(), tool: "verification",
      evidence: { verified: false, stop_reason: "model_answered", completion_state: "answered" },
    })).toBe("");
  });

  it("칸이 아무리 많아도 세 개까지만", () => {
    const line = evidenceLine(step({ a: 1, b: 2, c: 3, d: 4, e: 5 }));
    expect(line.split(" · ")).toHaveLength(3);
  });

  it("Claude Code 위임 비용은 세션 ID를 숨기고 사람 말로 보인다", () => {
    expect(evidenceLine({
      ...step(), tool: "claude_code_delegate",
      evidence: { total_cost_usd: 0.2054146, session_id: "private-session", resumed: true },
    })).toBe("예상비용 $0.2054 · resumed=예");
  });
});
