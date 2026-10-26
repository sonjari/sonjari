// @vitest-environment jsdom
/**
 * 왼쪽 목록 (2026-10-26 대표 첫 실제 판) — 앱 안 Claude 가 맡긴 손자리 판의 방은 따로 세우지 않고, 대화 제목은 본체가 지은 것을 쓴다.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { JarvisClient } from "../backend";
import type { AgentChatResult, AgentStreamEvent, ConversationSummary } from "../types";
import { ClaudeLane, type ClaudeRunner } from "./lane";
import { withClaudeLane } from "./withClaudeLane";

function memoryStorage() {
  const rows = new Map<string, string>();
  return { getItem: (key: string) => rows.get(key) ?? null, setItem: (key: string, value: string) => void rows.set(key, value) };
}

const BASE: AgentStreamEvent = {
  job_id: "", kind: "tool", delta: "", step: 0, tool: "", tool_use_id: "", message: "", ok: true, evidence: {}, local_job_id: "", summary: null,
};

const RESULT: AgentChatResult = {
  answer: "장표 4장을 만들었습니다.", cost_usd: 0.08, duration_ms: 1000, session_id: "s-1", model: "claude-sonnet-5-5",
  input_tokens: 1, output_tokens: 1, cache_read_tokens: 0, cache_creation_tokens: 0, num_turns: 2, trace: [], delegations: [],
};

function room(session_id: string, extra: Partial<ConversationSummary> = {}): ConversationSummary {
  return { session_id, title: session_id, preview: "", message_count: 2, updated_at: 10, has_summary: false, ...extra };
}

function fakeClient(rows: ConversationSummary[], titles: Record<string, { title: string; source: string }>) {
  const named: Array<[string, string, string]> = [];
  const empty = async () => ({ items: [] });
  const client = {
    sendChat: async () => ({ id: "x", status: "queued" }),
    getConversations: async () => rows,
    getConversation: async (sessionId: string) => ({ session_id: sessionId, summary: "", has_summary: false, messages: [] }),
    deleteConversation: async () => ({ ok: true }),
    listJobs: async () => [],
    getJob: async () => ({}),
    listSteps: empty,
    getStep: async () => null,
    cancelJob: async () => ({}),
    listOutputs: empty,
    fetchOutput: async () => new Blob(),
    previewOutput: async () => ({}),
    steerJob: async () => ({}),
    permissionMode: async () => ({ mode: "reversible" }),
    conversationTitles: async () => ({ items: titles }),
    nameConversation: async (sessionId: string, user: string, answer: string) => {
      named.push([sessionId, user, answer]);
      return { scheduled: true, title: "" };
    },
  };
  return { client: client as unknown as JarvisClient, named };
}

describe("Claude 갈래와 왼쪽 목록", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("앱 안 Claude 가 맡긴 판의 방은 빼고, 바깥 클로드가 맡긴 방 · 내 대화는 남긴다", async () => {
    const runner: ClaudeRunner = {
      async status() { return { ready: true, claude_found: true, has_key: true, key_state: "ok", message: "" }; },
      async prepare() {},
      async cancel() {},
      async keyFromClipboard() { return { ok: true }; },
      async run(request, onStream) {
        onStream({ ...BASE, job_id: request.job_id, step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", evidence: { task: "장표" } });
        // via 칸이 생기기 전 기록(서버가 못 빼는 방)도 갈래가 아는 판 번호로 뺀다.
        onStream({ ...BASE, job_id: request.job_id, kind: "delegated", step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", local_job_id: "c81a10dd" });
        return RESULT;
      },
    };
    const lane = new ClaudeLane({ emit: () => undefined, runner, storage: memoryStorage(), lang: () => "ko" });
    const { client, named } = fakeClient(
      [
        room("mcp-old", { caller: "Claude Code", job_id: "c81a10dd" }),
        room("mcp-app", { caller: "claude-code", via: "app" }),
        room("mcp-outside", { caller: "claude-code", job_id: "d9" }),
        room("jarvis-mine", { title: "안녕", job_id: "e1" }),
      ],
      { "jarvis-claude": { title: "국내 AI 에이전트 소식 장표", source: "model" } },
    );
    withClaudeLane(client, lane);
    lane.send({ prompt: "국내 AI 에이전트 소식 3개 찾아서 장표 4장으로 만들어 줘", sessionId: "jarvis-claude", attachments: [], workspaceMode: "cowork", codeWorkspace: "", model: "claude-sonnet-5-5", history: [] });
    await vi.runAllTimersAsync();

    const rows = await client.getConversations();
    expect(rows.map((row) => row.session_id).sort()).toEqual(["jarvis-claude", "jarvis-mine", "mcp-outside"]);
    // Claude 대화의 제목은 본체가 지은 것.
    expect(rows.find((row) => row.session_id === "jarvis-claude")?.title).toBe("국내 AI 에이전트 소식 장표");
    // 첫 답이 끝나면 제목을 짓게 한 번 부른다(내 PC 모델 · 본체가 쉴 때).
    expect(named).toEqual([["jarvis-claude", "국내 AI 에이전트 소식 3개 찾아서 장표 4장으로 만들어 줘", "장표 4장을 만들었습니다."]]);

    // 같은 대화의 둘째 판은 다시 짓지 않는다.
    lane.send({ prompt: "하나 더", sessionId: "jarvis-claude", attachments: [], workspaceMode: "cowork", codeWorkspace: "", model: "claude-sonnet-5-5", history: lane.messages("jarvis-claude") });
    await vi.runAllTimersAsync();
    expect(named).toHaveLength(1);
  });
});
