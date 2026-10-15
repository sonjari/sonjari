import { describe, expect, it } from "vitest";
import type { CoworkTakeoverCard } from "../types";
import { originTone, relayFacts, stopReasonText } from "./TakeoverRelay";

function card(overrides: Partial<CoworkTakeoverCard> = {}): CoworkTakeoverCard {
  return {
    tool: "claude_code", tool_name: "Claude Code", session_path: "s.jsonl", title: "결제 모듈",
    cwd: "C:/work/payments", stop_kind: "rate_limit", stopped_minutes_ago: 2, resets_at: null,
    last_request: "회귀 테스트도 붙여 줘", files: ["a.py", "b.py"], open_tasks: ["테스트 추가"], request_count: 3,
    git: { repo: true, root: "C:/work/payments", branch: "feature/pay", changed_count: 2, untracked_count: 8968 },
    ...overrides,
  };
}

describe("takeover relay origin", () => {
  it("keeps source identity semantic instead of guessing from a display color", () => {
    expect(originTone("claude_code")).toBe("claude");
    expect(originTone("Claude Code")).toBe("claude");
    expect(originTone("codex")).toBe("codex");
    expect(originTone("cursor-vscode")).toBe("cursor");
    expect(originTone("some-new-agent")).toBe("other");
  });
});

describe("takeover relay facts", () => {
  it("counts only tracked changes — untracked files are noise, not evidence", () => {
    const facts = relayFacts(card());
    expect(facts.changed).toBe(2);
    expect(facts.rows.find((row) => row.label === "작업 폴더")?.detail).toBe("feature/pay · 바뀐 파일 2개");
    expect(facts.evidence).toBe(4);
  });

  it("says what is missing instead of claiming it was found", () => {
    const facts = relayFacts(card({ last_request: "", open_tasks: [], files: [], git: { repo: false } }));
    expect(facts.rows.map((row) => row.found)).toEqual([false, true, false]);
    expect(facts.rows[0].detail).toBe("기록에 없음");
    expect(facts.evidence).toBe(0);
    expect(facts.changed).toBe(0);
  });

  it("names the stop by its recorded kind", () => {
    expect(stopReasonText("rate_limit")).toBe("사용량 한도로 멈춤");
    expect(stopReasonText("api_error")).toBe("오류로 멈춤");
    expect(stopReasonText("aborted")).toBe("중간에 멈춤");
    // 2026-10-05: 멈춘 기록 없이 사람이 「이어받자」고 해서 고른 대화 — 「멈췄다」고 지어내지 않는다.
    expect(stopReasonText("none")).toBe("한도로 멈춘 기록 없음");
    expect(stopReasonText(undefined)).toBe("멈춘 이유 기록 없음");
  });
});
