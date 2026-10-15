/**
 * 리허설 시나리오가 **실제로 화면에 닿는지** 검사한다.
 *
 * 가짜 사건은 조용히 무시된다 — 이름을 하나 틀리면 아무 일도 안 일어나고,
 * 그걸 "디자인이 안 붙었다"로 오해하게 된다. 그래서 시나리오가 쏘는 사건 이름이
 * WorkspaceApp 이 실제로 처리하는 목록 안에 있는지 여기서 못 박는다.
 */
import { describe, expect, it } from "vitest";
import { SCENARIOS } from "./scenarios";

/** WorkspaceApp.onEvent 가 실제로 처리하는 사건. 늘리면 여기도 같이 늘린다. */
const HANDLED = new Set([
  "agent_answer_delta", "agent_answer_reset", "agent_continuation_requested",
  "agent_continuation_resumed", "agent_plan", "agent_progress", "agent_resumed",
  "agent_started", "agent_thinking", "approval_approved", "approval_denied", "approval_requested",
  "attention_required", "google_oauth_connected", "job_cancelled", "job_completed",
  "job_failed", "job_queued", "presentation_ready", "state_changed", "undo_done", "voice_routed",
  "takeover_offered",
  // 2026-09-26: 사람 문(비밀번호·보안 문자·결제 칸)과 그 문이 열려 이어 붙음 — WorkspaceApp 이 안내 띠로 그린다.
  "agent_waiting_for_human", "agent_gate_resumed",
  // 2026-10-07: 본 창의 답은 판 밖에서 칠한다 — 다 칠하면 이 사건이 온다(WorkspaceApp 이 받아 「정리 중」을 푼다).
  //   각본(painting-apart)은 그날 들어왔는데 이 목록이 안 따라와 시험 둘이 떨어져 있었다(2026-10-08 발견).
  "agent_answer_painted",
  // 2026-10-10: 그림으로 된 본문을 읽는 동안 지금 읽는 조각을 비춘다 — 걸음 상자 안의 작은 그림.
  "agent_looking",
  // 일하면서 하는 말 줄 — 그림 조각이 그 줄 아래에 붙으므로 각본에도 같이 둔다.
  "agent_says",
]);

/** 작업(job) 하나에 매이는 사건 — 보내기 이후에만 의미가 있다. */
const JOB_SCOPED = new Set([
  "agent_started", "agent_thinking", "agent_progress", "agent_looking", "agent_says", "agent_answer_delta",
  "agent_answer_reset", "job_completed", "job_failed", "job_cancelled",
]);

describe("리허설 시나리오", () => {
  it("이름이 겹치지 않는다", () => {
    const ids = SCENARIOS.map((row) => row.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("모든 시나리오가 라벨과 확인 사항을 갖는다", () => {
    for (const scenario of SCENARIOS) {
      expect(scenario.label.length, scenario.id).toBeGreaterThan(0);
      expect(scenario.hint.length, scenario.id).toBeGreaterThan(10);
    }
  });

  it("쏘는 사건이 전부 화면이 처리하는 것이다", () => {
    for (const scenario of SCENARIOS) {
      for (const step of [...(scenario.ambient ?? []), ...(scenario.onSend ?? [])]) {
        expect(HANDLED.has(step.event), `${scenario.id}: ${step.event}`).toBe(true);
      }
    }
  });

  it("작업에 매인 사건은 ambient 에 넣지 않는다", () => {
    for (const scenario of SCENARIOS) {
      for (const step of scenario.ambient ?? []) {
        expect(JOB_SCOPED.has(step.event), `${scenario.id}: ${step.event}`).toBe(false);
      }
    }
  });

  it("시간표가 순서대로다", () => {
    for (const scenario of SCENARIOS) {
      for (const steps of [scenario.ambient ?? [], scenario.onSend ?? []]) {
        const times = steps.map((step) => step.at);
        expect(times, scenario.id).toStrictEqual([...times].sort((a, b) => a - b));
      }
    }
  });

  it("보내기 시나리오는 보낼 문장을 갖고, 매달린 채 끝나지 않는다", () => {
    // 판이 끝나는 방법은 둘이다. 스스로 끝나거나(완료·실패·취소), **사람을 기다리며
    // 멈추거나**(승인·계속진행). 뒤엣것도 정당한 종착지다 — 자비스는 실제로 거기서
    // 몇 분씩 서 있고, 그 화면을 리허설로 못 보면 승인 자리를 손볼 수가 없다.
    //
    // 금지하는 것은 **아무 말 없이 끝나는 판**이다. 그건 화면을 영영 "일하는 중"으로
    // 남겨서, 고장인지 리허설인지 구별할 수 없게 만든다.
    const ENDINGS = ["job_completed", "job_failed", "job_cancelled"];
    // 백엔드가 실제로 보내는 이름 — `jobs.py` 의 `agent_continuation_requested`(사람 문·계속진행 모두 여기서 멈춘다).
    const PARKED = ["approval_requested", "agent_continuation_requested"];
    for (const scenario of SCENARIOS) {
      if (!scenario.onSend?.length) continue;
      expect(scenario.prompt, scenario.id).toBeTruthy();
      const events = scenario.onSend.map((step) => step.event);
      const last = events[events.length - 1];
      if (last === "agent_answer_painted") {
        // 답을 판 밖에서 칠하는 판은 **끝난 뒤에** 「다 칠했다」가 한 번 더 온다. 그 앞에 끝이 있어야 한다 —
        // 끝 없이 칠하기만 하고 멎는 각본은 여전히 금지다.
        expect(events.some((event) => ENDINGS.includes(event)), scenario.id).toBe(true);
        continue;
      }
      expect([...ENDINGS, ...PARKED], scenario.id).toContain(last);
    }
  });

  it("도구 걸음은 걸음 번호와 도구 이름을 갖는다", () => {
    for (const scenario of SCENARIOS) {
      for (const step of scenario.onSend ?? []) {
        if (step.event !== "agent_progress") continue;
        expect(step.payload?.step, scenario.id).toBeTypeOf("number");
        expect(String(step.payload?.tool ?? ""), scenario.id).not.toBe("");
      }
    }
  });
});
