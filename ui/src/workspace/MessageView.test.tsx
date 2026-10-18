/**
 * 출처 도장 (2026-09-30) — 찾아보지 않고 쓴 답에는 답이 무슨 말을 하든 도장이 찍힌다.
 * 09-30 새벽 도구 0회로 「레딧·GitHub 까지 확인했습니다」가 나갔다. 화면은 낱말이 아니라 서버가 센 걸음 수만 본다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "../types";
import { MessageView } from "./MessageView";

const answer = (metadata: Record<string, unknown>, role: "user" | "assistant" = "assistant"): ConversationMessage => ({
  id: 1, session_id: "s", role, content: "레딧·GitHub 까지 확인했습니다.", kind: "chat", metadata, created_at: 0,
});
const html = (message: ConversationMessage, withButton = true) =>
  renderToStaticMarkup(<MessageView message={message} onObserveAgain={withButton ? () => undefined : undefined} />);

describe("grounding stamp", () => {
  it("stamps an answer written without looking, even when it claims it checked", () => {
    const out = html(answer({ grounding: { basis: "memory", observed_steps: 0 } }));
    expect(out).toContain("0걸음 · 기억으로 답함");
    expect(out).toContain("찾아보고 다시 답하기");
  });

  it.each(["observed", "attachment", "camera", "takeover"])("leaves a %s answer unstamped", (basis) => {
    expect(html(answer({ grounding: { basis, observed_steps: basis === "observed" ? 2 : 0 } }))).not.toContain("기억으로 답함");
  });

  it("does not stamp old answers that never recorded grounding", () => {
    expect(html(answer({}))).not.toContain("기억으로 답함");
  });

  it("never stamps the user's own message", () => {
    expect(html(answer({ grounding: { basis: "memory" } }, "user"))).not.toContain("기억으로 답함");
  });

  it("keeps the stamp when there is nowhere to resend from", () => {
    const out = html(answer({ grounding: { basis: "memory" } }), false);
    expect(out).toContain("기억으로 답함");
    expect(out).not.toContain("찾아보고 다시 답하기");
  });
});

describe("unfinished turn note", () => {
  // 2026-10-04: 실패·멈춘 판은 대화에 아무것도 안 남았다. 이제 서버가 「어디까지 했는지」 한 줄을 남긴다 — 답이 아니다.
  const note = (unfinished?: string): ConversationMessage => ({
    id: 3, session_id: "s", role: "assistant", kind: "chat", created_at: 0,
    content: "(정해 둔 작업 시간을 다 써서 멈췄습니다 — 검증은 통과하지 못했습니다. 그때까지 만든·고친 파일(검증되지 않음): index.html.)",
    metadata: unfinished ? { unfinished, job_id: "j1" } : {},
  });
  const shown = (message: ConversationMessage, onContinue?: () => void) =>
    renderToStaticMarkup(<MessageView message={message} onContinue={onContinue} />);

  it("shows the note quietly, without the brackets, and offers to continue", () => {
    const out = shown(note("failed"), () => undefined);
    expect(out).toContain("message-unfinished");
    expect(out).toContain("검증되지 않음");
    expect(out).not.toContain("(정해 둔");
    expect(out).not.toContain("index.html.)");
    expect(out).toContain("이어서 하기");
    expect(out).not.toContain("workspace-markdown"); // 답처럼 그리지 않는다
  });

  it("offers no button on an older note (only the last message gets one)", () => {
    const out = shown(note("cancelled"));
    expect(out).toContain("message-unfinished");
    expect(out).not.toContain("이어서 하기");
  });

  it("leaves an ordinary answer in brackets alone", () => {
    const out = shown(note(), () => undefined);
    expect(out).not.toContain("message-unfinished");
    expect(out).toContain("workspace-markdown");
    expect(out).not.toContain("이어서 하기");
  });
});

describe("delegated message", () => {
  const asked = (content: string, caller?: string): ConversationMessage => ({
    id: 2, session_id: "mcp-1", role: "user", content, kind: "chat",
    metadata: caller ? { caller } : {}, created_at: 0,
  });

  it.each([
    ["claude-code", "Claude Code가 맡긴 일", "origin-claude"],
    ["codex-mcp-client", "Codex가 맡긴 일", "origin-codex"],
    ["cursor-vscode", "Cursor가 맡긴 일", "origin-cursor"],
  ])("names %s and wears its origin seam", (caller, label, tone) => {
    const out = html(asked("바깥 AI 가 맡긴 일 · 교보에서 책 찾기", caller));
    expect(out).toContain(label);
    expect(out).toContain(tone);
    expect(out).toContain("교보에서 책 찾기");
    expect(out).not.toContain("바깥 AI 가 맡긴 일 · ");
  });

  it("marks an old task without a host name as an unknown outside AI, never in Sonjari's own color", () => {
    const out = html(asked("바깥 AI 가 맡긴 일 · 제목 읽기"));
    expect(out).toContain("바깥 AI가 맡긴 일");
    expect(out).toContain("origin-other");
  });

  it("leaves the person's own message alone", () => {
    expect(html(asked("안녕"))).not.toContain("message-delegated");
  });
});

describe("outbound receipt (§55-32)", () => {
  const outbound = {
    host: "claude-code", needs: [{ label: "가격", met: true }, { label: "리뷰 수", met: false }],
    refined: [{ kind: "전화번호", count: 1 }], needs_total: 2, needs_met: 1, refined_count: 1,
  };

  it("shows one quiet line with what was needed and refined", () => {
    const out = html(answer({ outbound }));
    expect(out).toContain("Claude Code에게 보냄 · 필요한 것 1/2 · 정제 1");
    expect(out).toContain("리뷰 수");
    expect(out).toContain("전화번호 1개");
    expect(out).not.toContain("원문 ");
  });

  it("is absent on answers nobody outside asked for", () => {
    expect(html(answer({}))).not.toContain("에게 보냄");
  });

  it("does not print a fraction when some needs could not be checked (2026-10-19)", () => {
    // 이름으로 자리를 못 찾은 항목(met=null)은 「확인 못 함」 — 「0/3」으로 나가면 「셋 다 없다」로 읽힌다.
    const unchecked = {
      host: "claude-code",
      needs: [{ label: "default value", met: null }, { label: "source URL", met: null }, { label: "가격", met: true }],
      refined: [], needs_total: 3, needs_met: 1, needs_missing: 0, needs_unknown: 2, refined_count: 0,
    };
    const out = html(answer({ outbound: unchecked }));
    expect(out).toContain("Claude Code에게 보냄 · 필요한 것 3개 · 채움 1 · 확인 못 함 2 · 정제 0");
    expect(out).not.toContain("1/3");
    expect(out).toContain("확인 못 함");
    expect(out).not.toContain("비어 있음");
  });
});
