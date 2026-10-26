// @vitest-environment jsdom
/**
 * Claude Agent 화면 조각 (2026-10-26) — 대화마다 두뇌로 갈라 보내기 · 눈금자의 두 손 · 손 넘김 카드 · 영수증 · 모델 칸 메뉴.
 * 「Claude Code」 글자가 화면 어디에도 없는지도 센다(앤트로픽 상표 · 대표 결정).
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JarvisClient } from "../backend";
import type { ClaudeAgentStatus, ClaudeHandoff, ConversationHistory } from "../types";
import type { StepRow } from "../workspace/observation";
import { StepScrubber } from "../workspace/StepScrubber";
import { LocalModelPicker, type ClaudeChoice } from "../workspace/LocalModelPicker";
import type { SetupApi } from "../setup/setupApi";
import { brainFor, setBrain } from "./brain";
import { ClaudeReceipt, HandoffCard, checkSummary } from "./HandoffCard";
import { ClaudeLane } from "./lane";
import { withClaudeLane } from "./withClaudeLane";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(node); });
  return host;
}

function row(step: number, actor?: "claude" | "local", tool = "browser_read_page"): StepRow {
  return { step, tool, ok: true, status: "completed", error: "", kind: "page", title: "", at: step, took_ms: 1, truncated: false, actor };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("대화마다 두뇌", () => {
  it("고른 적 없는 대화는 내 PC 모델 · 고르면 그 대화만", () => {
    expect(brainFor("a")).toBe("local");
    setBrain("a", "claude-opus-5-5");
    expect(brainFor("a")).toBe("claude-opus-5-5");
    expect(brainFor("b")).toBe("local");
    setBrain("a", "local");
    expect(brainFor("a")).toBe("local");
  });

  it("내 PC 모델 대화는 원래 길, Claude Agent 대화는 갈래로 보낸다", async () => {
    const client = new JarvisClient({ baseUrl: "http://x", controlToken: "t" }, () => undefined, () => undefined);
    const serverSend = vi.spyOn(client, "sendChat").mockResolvedValue({ id: "server-1", status: "queued" });
    const history: ConversationHistory = { session_id: "s", summary: "", has_summary: false, messages: [
      { id: 1, session_id: "s", role: "user", content: "앞 질문", kind: "chat", metadata: {}, created_at: 10 },
    ] };
    vi.spyOn(client, "getConversation").mockResolvedValue(history);
    const lane = new ClaudeLane({
      emit: () => undefined, storage: null, local: null,
      runner: { status: vi.fn(), prepare: vi.fn(), run: vi.fn(() => new Promise(() => undefined)), cancel: vi.fn(), keyFromClipboard: vi.fn() } as never,
    });
    const send = vi.spyOn(lane, "send");
    withClaudeLane(client, lane);

    await client.sendChat("내 PC 로", "local-room");
    expect(serverSend).toHaveBeenCalledTimes(1);
    expect(send).not.toHaveBeenCalled();

    setBrain("claude-room", "claude-sonnet-5-5");
    const job = await client.sendChat("클로드로", "claude-room", [], "screen", "workspace", "code", "C:/repo");
    expect(serverSend).toHaveBeenCalledTimes(1);
    expect(job.id.startsWith("claude-")).toBe(true);
    expect(send.mock.calls[0][0]).toMatchObject({ prompt: "클로드로", sessionId: "claude-room", workspaceMode: "code", codeWorkspace: "C:/repo", model: "claude-sonnet-5-5" });
    // 서버 기록과 갈래 기록이 한 대화로 합쳐진다.
    const merged = await client.getConversation("claude-room");
    expect(merged.messages.map((message) => message.content)).toEqual(["앞 질문", "클로드로"]);
    // 클로드 판의 걸음 · 멈춤은 갈래가 답한다(서버로 가지 않는다).
    const serverSteps = vi.spyOn(JarvisClient.prototype, "listSteps");
    await client.listSteps(job.id);
    expect(serverSteps).not.toHaveBeenCalled();
    await expect(client.steerJob(job.id, "덧붙임")).rejects.toThrow();
  });
});

describe("눈금자의 두 손", () => {
  it("클로드 걸음은 주황 점선 · 손자리 걸음은 보라 · 바뀌는 자리에 「손 넘김」", async () => {
    const host = await mount(<StepScrubber rows={[row(1, "claude", "mcp__sonjari__sonjari_guide"), row(2, "claude", "mcp__sonjari__sonjari_task"), row(3, "local"), row(4, "local"), row(5, "claude", "mcp__sonjari__sonjari_task_status")]} selected={null} live={false} onSelect={() => undefined} />);
    expect(host.querySelectorAll(".tick.actor-claude")).toHaveLength(3);
    expect(host.querySelectorAll(".tick.actor-local")).toHaveLength(2);
    expect(host.querySelectorAll(".scrub-seam")).toHaveLength(2);
    expect(host.textContent).toContain("손자리(내 PC)");
    expect(host.querySelectorAll(".tick.actor-claude u")[1].textContent).toBe("→");
  });

  it("손자리 혼자 한 판은 지금까지와 같다(두 손 표시 없음)", async () => {
    const host = await mount(<StepScrubber rows={[row(1), row(2)]} selected={null} live={false} onSelect={() => undefined} />);
    expect(host.querySelectorAll(".scrub-seam, .scrub-legend, [class*='actor-']")).toHaveLength(0);
  });
});

describe("손 넘김 카드 · 영수증", () => {
  const working: ClaudeHandoff = { localJobId: "l1", task: "일", state: "working", summary: null, steps: 3 };

  it("맡긴 동안: 「손자리가 받았습니다 · 내 PC 모델(○○)이 이어서 합니다」", async () => {
    const host = await mount(<HandoffCard handoffs={[working]} localModel="Qwen3.8 · 27B" />);
    expect(host.textContent).toContain("손자리가 받았습니다");
    expect(host.textContent).toContain("내 PC 모델(Qwen3.8 · 27B)이 이어서 합니다");
  });

  it("끝나면 센 숫자만으로 검사 요약 — 결과가 없으면 지어내지 않는다", async () => {
    const done: ClaudeHandoff = { ...working, state: "done", summary: { status: "needs_review", steps: 7, files: 0, sources: 3, unsupported_numbers: 2, needs_total: 0, needs_met: 0 } };
    const host = await mount(<HandoffCard handoffs={[done]} localModel="" />);
    expect(host.textContent).toContain("손자리가 끝냈습니다");
    expect(host.textContent).toContain("검사: 근거 3곳 · 확인할 숫자 2");
    expect(checkSummary(null)).toBe("");
    const bare = await mount(<HandoffCard handoffs={[{ ...working, state: "done" }]} localModel="" />);
    expect(bare.textContent).not.toContain("검사:");
  });

  it("영수증: 비용이 없으면 「비용 정보 없음」 · 손자리는 0원 · N걸음", async () => {
    const host = await mount(<ClaudeReceipt metadata={{ cost_usd: null, input_tokens: 6100, output_tokens: 900, local_steps: 7, local_jobs: 1 }} />);
    expect(host.textContent).toContain("비용 정보 없음");
    expect(host.textContent).toContain("입력 6.1K");
    expect(host.textContent).toContain("손자리 0원 · 내 PC 7걸음");
    const priced = await mount(<ClaudeReceipt metadata={{ cost_usd: 0.0412, local_jobs: 0 }} />);
    expect(priced.textContent).toContain("$0.04");
    expect(priced.textContent).toContain("손자리에게 맡긴 일 없음");
  });
});

describe("모델 칸 메뉴", () => {
  const api = {
    modelPicker: vi.fn(async () => ({
      satellite: false, budget_gb: 23.5, pulls: {}, current: "qwen3.8:27b",
      models: [{ tag: "qwen3.8:27b", name: "Qwen3.8 27B", current: true, listed: true, installed: true, size_gb: 17, grade: { measured: true, label: "잰 모델", detail: "" } }],
    })),
    contextStatus: vi.fn(async () => ({})),
  } as unknown as SetupApi;

  async function open(choice: ClaudeChoice) {
    const host = await mount(<LocalModelPicker api={api} role="chat" label="Qwen3.8 · 27B · 192K" context="" claude={choice} />);
    await act(async () => { host.querySelector<HTMLButtonElement>(".pilot-model-trigger")!.click(); });
    await act(async () => { await Promise.resolve(); });
    return host;
  }

  const ready: ClaudeAgentStatus = { ready: true, claude_found: true, has_key: true, key_state: "ok", message: "" };

  it("두 무리 — 「내 PC 모델 · 무료」와 「Claude Agent · 내 API 키」 · 「Claude Code」 글자는 없다", async () => {
    const onPick = vi.fn();
    const host = await open({ brain: "local", status: ready, onPick, onKeyIn: async () => "" });
    expect(host.textContent).toContain("내 PC 모델 · 무료");
    expect(host.textContent).toContain("Claude Agent · 내 API 키");
    for (const name of ["Haiku 5.5", "Sonnet 5.5", "Opus 5.5"]) expect(host.textContent).toContain(name);
    expect(host.textContent).not.toMatch(/Claude Code/i);
    const opus = [...host.querySelectorAll<HTMLButtonElement>(".brain-claude-option")].find((button) => button.textContent?.includes("Opus 5.5"))!;
    await act(async () => { opus.click(); });
    expect(onPick).toHaveBeenCalledWith("claude-opus-5-5");
  });

  it("Claude Agent 대화의 버튼은 「Claude Agent · Sonnet 5.5」 · 지금 쓰는 내 PC 모델을 누르면 이 대화만 돌아온다", async () => {
    const onPick = vi.fn();
    const host = await open({ brain: "claude-sonnet-5-5", status: ready, onPick, onKeyIn: async () => "" });
    expect(host.querySelector(".pilot-model-trigger")!.textContent).toContain("Claude Agent · Sonnet 5.5");
    const current = host.querySelector<HTMLButtonElement>(".local-model-options > button")!;
    expect(current.disabled).toBe(false);
    await act(async () => { current.click(); });
    expect(onPick).toHaveBeenCalledWith("local");
  });

  it("키가 없으면 모델은 못 고르고 「키 넣기」 — 넣지 못한 까닭을 그 자리에", async () => {
    const onKeyIn = vi.fn(async () => "복사한 글이 API 키 모양이 아닙니다");
    const host = await open({ brain: "local", status: { ...ready, ready: false, has_key: false, key_state: "none" }, onPick: vi.fn(), onKeyIn });
    expect([...host.querySelectorAll<HTMLButtonElement>(".brain-claude-option")].every((button) => button.disabled)).toBe(true);
    const keyButton = host.querySelector<HTMLButtonElement>(".brain-key-row button")!;
    expect(keyButton.textContent).toBe("키 넣기");
    await act(async () => { keyButton.click(); });
    expect(onKeyIn).toHaveBeenCalled();
    expect(host.querySelector(".brain-key-row")!.textContent).toContain("API 키 모양이 아닙니다");
  });

  it("구독 로그인 토큰이면 그렇다고 말한다", async () => {
    const host = await open({ brain: "local", status: { ...ready, ready: false, key_state: "subscription_token" }, onPick: vi.fn(), onKeyIn: async () => "" });
    expect(host.querySelector(".brain-key-row")!.textContent).toContain("구독 로그인 토큰은 쓸 수 없습니다");
  });
});
