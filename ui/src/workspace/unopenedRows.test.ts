// 한 번도 안 연 곳의 줄 — 판 기록에서 꺼내기 · 그 판의 답만 보기 · 옛 ⚠ 문단과 두 번 말하지 않기 (2026-10-24).
import { describe, expect, it } from "vitest";
import { applyVerification, startTrajectory } from "../trajectory";
import type { AgentProgress, ConversationMessage } from "../types";
import { unopenedRowsForJob, unopenedRowsOf, withoutUnopenedCheck } from "./unopenedRows";

const ROW = { name: "Brief AI", url: "https://brief.example.tech/ai", place: "brief.example.tech", values: ["매일", "예"], unknown: 1 };

function answer(id: number, jobId: string, verification: unknown): ConversationMessage {
  return { id, session_id: "s", role: "assistant", content: "답", kind: "chat", created_at: id,
    metadata: { job_id: jobId, agent_verification: verification } };
}

describe("unopenedRowsOf", () => {
  it("판 기록의 줄을 그대로 꺼낸다", () => {
    expect(unopenedRowsOf({ unopened_place_rows: [ROW] })).toEqual([ROW]);
  });

  it("칸이 없거나 모양이 어긋나면 비운다 — 이름 · 곳이 없는 줄은 버린다", () => {
    expect(unopenedRowsOf({})).toEqual([]);
    expect(unopenedRowsOf(null)).toEqual([]);
    expect(unopenedRowsOf({ unopened_place_rows: "x" })).toEqual([]);
    expect(unopenedRowsOf({ unopened_place_rows: [{ name: "", place: "a.com" }, { name: "A" }, 3] })).toEqual([]);
  });
});

describe("unopenedRowsForJob", () => {
  it("그 판의 답 메타데이터에서만 꺼낸다 — 뒤에 온 다른 판의 답은 보지 않는다", () => {
    const messages = [answer(1, "j1", { unopened_place_rows: [ROW] }), answer(2, "j2", { unopened_place_rows: [] })];
    expect(unopenedRowsForJob(messages, "j1")).toEqual([ROW]);
    expect(unopenedRowsForJob(messages, "j2")).toEqual([]);
    expect(unopenedRowsForJob(messages, "j3")).toEqual([]);
    expect(unopenedRowsForJob(messages, "")).toEqual([]);
  });
});

describe("withoutUnopenedCheck", () => {
  const old = { title: "이번에 열어 보지 않은 곳의 줄 1개에 값이 채워져 있습니다", what: "", detail: "…" };
  const other = { title: "읽은 자료에 없는 비율이 있습니다", what: "10%", detail: "…" };

  it("줄이 있으면 같은 사실을 말하는 옛 노란 줄은 뺀다(다른 경고는 남긴다)", () => {
    expect(withoutUnopenedCheck([old, other], [ROW])).toEqual([other]);
  });

  it("줄이 없으면 아무것도 안 뺀다 — 옛 답의 경고를 잃지 않게", () => {
    expect(withoutUnopenedCheck([old, other], [])).toEqual([old, other]);
  });
});

describe("applyVerification", () => {
  const base = startTrajectory("j1", "s", "물음", 0);
  const progress = (phase: string, evidence?: Record<string, unknown>): AgentProgress =>
    ({ key: "k", jobId: "j1", phase, message: "", step: 3, tool: "", status: "completed", evidence }) as AgentProgress;

  it("판 끝 검사 알림이면 줄을 궤적에 붙든다", () => {
    expect(applyVerification(base, progress("verification", { unopened_place_rows: [ROW] })).unopened).toEqual([ROW]);
  });

  it("다른 걸음 알림은 건드리지 않는다", () => {
    expect(applyVerification(base, progress("tool", { unopened_place_rows: [ROW] }))).toBe(base);
  });
});
