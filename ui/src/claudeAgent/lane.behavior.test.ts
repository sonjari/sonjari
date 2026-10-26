// @vitest-environment jsdom
/**
 * Claude 갈래 (2026-10-26) — 진짜 클로드 · 진짜 서버 없이, 손으로 만든 흐름(`fixtures/claudeHands.ts` 의 시간표)으로 잰다.
 *
 * 지키는 것:
 * - 클로드 걸음(actor=claude)과 맡긴 손자리 판의 걸음(actor=local)이 **한 눈금자에 시간순**으로 잇는다.
 * - 맡기기 결과보다 먼저 온 손자리 사건도 잃지 않는다.
 * - 영수증 숫자는 CLI 결과에 있는 값만(없으면 null) · 손자리 걸음 수는 눈금자에 선 칸 수.
 * - 마지막 말이 클로드 답이면 그 클로드 대화를 이어받고, 그 뒤 내 PC 모델과 말했으면 글로 넘긴다.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentChatResult, AgentStreamEvent, ConversationMessage, JarvisEvent } from "../types";
import type { Observation, StepRow } from "../workspace/observation";
import { CLAUDE_HANDS_LOCAL_JOB, claudeHandsBeats } from "../fixtures/claudeHands";
import { ClaudeLane, agentToolMessage, livePreview, type AgentRunRequest, type ClaudeRunner, type LocalSource } from "./lane";

function memoryStorage() {
  const rows = new Map<string, string>();
  return { getItem: (key: string) => rows.get(key) ?? null, setItem: (key: string, value: string) => void rows.set(key, value) };
}

const BASE: AgentStreamEvent = {
  job_id: "", kind: "thinking", delta: "", step: 0, tool: "", tool_use_id: "", message: "", ok: true, evidence: {}, local_job_id: "", summary: null,
};

function result(extra: Partial<AgentChatResult> = {}): AgentChatResult {
  return {
    answer: "장표 6장을 만들었습니다.", cost_usd: 0.0412, duration_ms: 10_600, session_id: "s-1", model: "claude-sonnet-5-5",
    input_tokens: 6100, output_tokens: 900, cache_read_tokens: 2048, cache_creation_tokens: 512, num_turns: 5,
    trace: [], delegations: [], ...extra,
  };
}

class Local implements LocalSource {
  rows: Observation[] = [];
  cancelled: string[] = [];
  async listSteps(jobId: string): Promise<{ items: StepRow[] }> {
    return { items: this.rows.filter((row) => row.job_id === jobId).map(({ job_id: _j, arguments: _a, payload: _p, truncation: _t, ...row }) => row) };
  }
  async getStep(jobId: string, step: number) {
    return this.rows.find((row) => row.job_id === jobId && row.step === step) ?? null;
  }
  async listOutputs() {
    return { items: [] };
  }
  async cancelJob(jobId: string) {
    this.cancelled.push(jobId);
    return { ok: true };
  }
}

/** 시간표를 **순서대로 한 번에** 흘리는 실행기 — 시각은 시간표의 것을 쓴다. */
function scriptedRunner(lane: () => ClaudeLane, local: Local, final = result()): ClaudeRunner & { requests: AgentRunRequest[] } {
  const requests: AgentRunRequest[] = [];
  return {
    requests,
    async status() { return { ready: true, claude_found: true, has_key: true, key_state: "ok", message: "" }; },
    async prepare() {},
    async cancel() {},
    async keyFromClipboard() { return { ok: true }; },
    async run(request, onStream) {
      requests.push(request);
      const start = 1_000;
      for (const beat of claudeHandsBeats(start)) {
        vi.setSystemTime((start * 1000) + beat.at);
        if ("claude" in beat) onStream({ ...BASE, job_id: request.job_id, ...beat.claude });
        else {
          if (beat.row) local.rows.push(beat.row);
          lane().observe(beat.local);
        }
      }
      return final;
    },
  };
}

function setup(final?: AgentChatResult) {
  const events: JarvisEvent[] = [];
  const local = new Local();
  let lane!: ClaudeLane;
  const runner = scriptedRunner(() => lane, local, final);
  lane = new ClaudeLane({ emit: (event) => events.push(event), runner, local, storage: memoryStorage(), lang: () => "ko" });
  return { lane, events, local, runner };
}

async function sendAndFinish(lane: ClaudeLane, history: ConversationMessage[] = []) {
  const job = lane.send({ prompt: "소식 5개 → 장표", sessionId: "room", attachments: [], workspaceMode: "cowork", codeWorkspace: "", model: "claude-sonnet-5-5", history });
  await vi.runAllTimersAsync();
  return job.id;
}

describe("Claude 갈래", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("클로드 걸음과 손자리 걸음을 한 눈금자에 시간순으로 잇는다", async () => {
    const { lane } = setup();
    const jobId = await sendAndFinish(lane);
    const { items } = await lane.listSteps(jobId);
    // 클로드 3걸음(사용법 · 맡김 · 결과 기다림) 뒤에 손자리 7걸음 — 결과를 기다리는 사이 손자리 걸음이 끼어든 그대로.
    expect(items.map((row) => row.actor)).toEqual(["claude", "claude", "claude", "local", "local", "local", "local", "local", "local", "local"]);
    expect(items.map((row) => row.step)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(items[1].tool).toBe("mcp__sonjari__sonjari_task");
    expect(items[9].tool).toBe("local_make_slide");
    // 4번 칸을 열면 손자리 판의 1번 걸음이 나온다.
    const opened = await lane.getStep(jobId, 4);
    expect(opened?.actor).toBe("local");
    expect(opened?.payload?.url).toBe("https://news.example.kr/ai-agent");
    expect(opened?.job_id).toBe(jobId);
  });

  it("맡긴 판의 진행 사건을 클로드 판의 사건으로 바꿔 흘린다(누가 · 몇 번째 칸)", async () => {
    const { lane, events } = setup();
    const jobId = await sendAndFinish(lane);
    const progress = events.filter((event) => event.event === "agent_progress");
    expect(progress.every((event) => event.payload!.job_id === jobId)).toBe(true);
    const local = progress.filter((event) => event.payload!.actor === "local");
    expect(local.map((event) => event.payload!.step)).toEqual([4, 5, 6, 7, 8, 9, 10]);
    // 원래 손자리 판 번호의 사건은 갈래가 다시 내보내지 않는다(그건 원래 길로 이미 흐른다).
    expect(events.some((event) => event.payload!.job_id === CLAUDE_HANDS_LOCAL_JOB)).toBe(false);
    // 시킨 것 대조도 클로드 판으로.
    expect(events.filter((event) => event.event === "agent_plan").every((event) => event.payload!.job_id === jobId)).toBe(true);
  });

  it("「손자리가 받았습니다」 → 끝나면 검사 요약", async () => {
    const { lane, events } = setup();
    const jobId = await sendAndFinish(lane);
    const handoffs = events.filter((event) => event.event === "claude_handoff").map((event) => (event.payload!.handoffs as Array<{ state: string }>)[0].state);
    expect(handoffs[0]).toBe("received");
    expect(handoffs).toContain("working");
    expect(handoffs[handoffs.length - 1]).toBe("done");
    const [done] = lane.handoffs(jobId);
    expect(done.summary).toEqual({ status: "done", steps: 7, files: 1, sources: 5, unsupported_numbers: 0, needs_total: 2, needs_met: 2 });
    expect(done.task).toBe("국내 AI 에이전트 소식 5개 읽기 → 장표 6장");
    expect(done.steps).toBe(7);
  });

  it("맡기기 결과보다 먼저 온 손자리 사건도 잃지 않는다", async () => {
    const events: JarvisEvent[] = [];
    const local = new Local();
    let lane!: ClaudeLane;
    const runner: ClaudeRunner = {
      ...scriptedRunner(() => lane, local),
      async run(request, onStream) {
        // 손자리가 맡기기 결과보다 먼저 한 걸음을 알린다.
        lane.observe({ event: "agent_progress", payload: { job_id: "early-1", step: 1, tool: "browser_search", status: "completed" } });
        local.rows.push({ job_id: "early-1", step: 1, tool: "browser_search", ok: true, status: "completed", error: "", kind: "page", title: "검색", at: Date.now() / 1000, took_ms: 1, truncated: false, arguments: {}, payload: {}, truncation: {} });
        onStream({ ...BASE, job_id: request.job_id, kind: "tool", step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", evidence: { task: "일" } });
        onStream({ ...BASE, job_id: request.job_id, kind: "delegated", step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", local_job_id: "early-1" });
        return result();
      },
    };
    lane = new ClaudeLane({ emit: (event) => events.push(event), runner, local, storage: memoryStorage() });
    const jobId = await sendAndFinish(lane);
    const replayed = events.filter((event) => event.event === "agent_progress" && event.payload!.actor === "local");
    expect(replayed).toHaveLength(1);
    expect(replayed[0].payload!.job_id).toBe(jobId);
    expect((await lane.listSteps(jobId)).items.map((row) => row.actor)).toContain("local");
  });

  it("영수증은 CLI 결과의 값만 — 비용이 없으면 null 로 둔다", async () => {
    const { lane } = setup(result({ cost_usd: null }));
    await sendAndFinish(lane);
    const answer = lane.messages("room").find((row) => row.role === "assistant")!;
    expect(answer.metadata).toMatchObject({
      brain: "claude", cost_usd: null, input_tokens: 6100, output_tokens: 900, local_steps: 7, local_jobs: 1, claude_session_id: "s-1",
    });
  });

  it("마지막 말이 클로드 답이면 이어받고, 그 뒤 내 PC 모델과 말했으면 글로 넘긴다", async () => {
    const { lane, runner } = setup();
    await sendAndFinish(lane);
    const afterClaude = lane.messages("room");
    await sendAndFinish(lane, afterClaude);
    expect(runner.requests[1].resume_session_id).toBe("s-1");
    expect(runner.requests[1].history).toEqual([]);
    const localTurn: ConversationMessage = { id: 1, session_id: "room", role: "assistant", content: "내 PC 모델의 답", kind: "chat", metadata: {}, created_at: Date.now() / 1000 + 5 };
    await sendAndFinish(lane, [...lane.messages("room"), localTurn]);
    expect(runner.requests[2].resume_session_id).toBe("");
    expect(runner.requests[2].history.at(-1)).toEqual({ role: "assistant", content: "내 PC 모델의 답" });
  });

  it("멈추면 맡긴 손자리 판도 멈춘다", async () => {
    const events: JarvisEvent[] = [];
    const local = new Local();
    let release!: () => void;
    let lane!: ClaudeLane;
    const runner: ClaudeRunner = {
      ...scriptedRunner(() => lane, local),
      async run(request, onStream) {
        onStream({ ...BASE, job_id: request.job_id, kind: "tool", step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", evidence: {} });
        onStream({ ...BASE, job_id: request.job_id, kind: "delegated", step: 1, tool: "mcp__sonjari__sonjari_task", tool_use_id: "t1", local_job_id: "busy-1" });
        await new Promise<void>((resolve) => { release = resolve; });
        return result();
      },
    };
    lane = new ClaudeLane({ emit: (event) => events.push(event), runner, local, storage: memoryStorage() });
    const job = lane.send({ prompt: "일", sessionId: "room", attachments: [], workspaceMode: "cowork", codeWorkspace: "", model: "claude-sonnet-5-5", history: [] });
    await vi.advanceTimersByTimeAsync(10);
    await lane.cancel(job.id);
    release();
    await vi.runAllTimersAsync();
    expect(local.cancelled).toEqual(["busy-1"]);
    expect(events.some((event) => event.event === "job_cancelled")).toBe(true);
    expect(events.some((event) => event.event === "job_completed")).toBe(false);
  });

  it("실패하면 job_failed 로 까닭을 그대로", async () => {
    const events: JarvisEvent[] = [];
    let lane!: ClaudeLane;
    lane = new ClaudeLane({
      emit: (event) => events.push(event), storage: memoryStorage(), local: new Local(),
      runner: { ...scriptedRunner(() => lane, new Local()), async run() { throw new Error("API 키가 없습니다."); } },
    });
    await sendAndFinish(lane);
    expect(events.find((event) => event.event === "job_failed")?.payload!.error).toBe("API 키가 없습니다.");
  });

  it("코드 모드에서 고치는 동안 「바뀐 줄」을 인자로 먼저 보이고, 줄 번호는 지어내지 않는다(0)", () => {
    const preview = livePreview("Edit", { file_path: "C:/repo/a.py", old_string: "x = 1", new_string: "x = 2\ny = 3" });
    expect(preview).toMatchObject({ path: "C:/repo/a.py", edit_preview: { start_line: 0, removed: ["x = 1"], added: ["x = 2", "y = 3"], added_count: 2 } });
    expect(livePreview("Read", { file_path: "C:/repo/a.py" })).toEqual({ text: "" });
  });

  it("명령 걸음은 도는 동안 명령을, 끝나면 명령 + 출력을 본문으로 연다 (2026-10-26 대표: 줄 번호 1 만 보였다)", async () => {
    const events: JarvisEvent[] = [];
    let lane!: ClaudeLane;
    let seenWhileRunning: Observation | null = null;
    const runner: ClaudeRunner = {
      ...scriptedRunner(() => lane, new Local()),
      async run(request, onStream) {
        onStream({ ...BASE, job_id: request.job_id, kind: "tool", step: 1, tool: "Bash", tool_use_id: "b1", evidence: { command: "python -m pytest -q test_price.py" } });
        seenWhileRunning = await lane.getStep(request.job_id, 1);
        onStream({
          ...BASE, job_id: request.job_id, kind: "tool_done", step: 1, tool: "Bash", tool_use_id: "b1", ok: true,
          message: "..   [100%]\n2 passed in 0.01s",
          evidence: { command: "python -m pytest -q test_price.py", text: "$ python -m pytest -q test_price.py\n..   [100%]\n2 passed in 0.01s", language: "bash" },
        });
        return result({ answer: "고쳤습니다." });
      },
    };
    lane = new ClaudeLane({ emit: (event) => events.push(event), runner, local: new Local(), storage: memoryStorage() });
    const jobId = await sendAndFinish(lane);
    expect(seenWhileRunning!.payload).toMatchObject({ text: "$ python -m pytest -q test_price.py" });
    expect(seenWhileRunning!.kind).toBe("code");
    // 끝난 판의 기록(trace)이 비어 있어도(옛 판) 흐름에서 받은 본문이 남는다.
    const opened = await lane.getStep(jobId, 1);
    expect(String(opened?.payload?.text)).toBe("$ python -m pytest -q test_price.py\n..   [100%]\n2 passed in 0.01s");
    expect(livePreview("PowerShell", { command: "dir" })).toMatchObject({ text: "PS> dir" });
    expect(agentToolMessage("PowerShell")).toBe("명령을 실행하는 중");
  });

  it("도구 이름 대신 하는 일을 말한다", () => {
    expect(agentToolMessage("mcp__sonjari__sonjari_task")).toBe("손자리에게 맡기는 중");
    expect(agentToolMessage("mcp__sonjari__sonjari_task_status")).toBe("손자리가 하는 일을 기다리는 중");
    expect(agentToolMessage("Edit")).toBe("파일을 고치는 중");
  });
});
