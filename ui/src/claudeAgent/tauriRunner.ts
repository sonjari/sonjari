/**
 * 앱에서 Claude Agent 를 돌리는 손 — Rust `claude_agent_chat`(앤트로픽 CLI 를 띄워 중계) (2026-10-26).
 * 키는 여기 없다: Rust 가 본체의 DPAPI 키 파일을 직접 풀어 CLI 환경 변수로만 넘긴다.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { JarvisClient } from "../backend";
import type { AgentChatResult, AgentStreamEvent, ClaudeAgentStatus } from "../types";
import type { AgentRunRequest, ClaudeRunner } from "./lane";

export function createTauriRunner(client: () => JarvisClient | null): ClaudeRunner {
  return {
    status: () => invoke<ClaudeAgentStatus>("claude_agent_status"),
    async prepare(lang: string) {
      const target = client();
      if (!target) throw new Error("Sonjari 본체에 연결되지 않았습니다.");
      await target.prepareClaudeAgent(lang);
    },
    async run(request: AgentRunRequest, onStream: (event: AgentStreamEvent) => void) {
      const stop = await listen<AgentStreamEvent>("claude-agent-stream", ({ payload }) => {
        if (payload.job_id === request.job_id) onStream(payload);
      });
      try {
        return await invoke<AgentChatResult>("claude_agent_chat", { request });
      } finally {
        stop();
      }
    },
    async cancel(jobId: string) {
      // 파일럿과 같은 프로세스 장부(`PilotState`)를 쓴다 — 멈춤 명령도 같은 것.
      await invoke<boolean>("pilot_cancel", { jobId });
    },
    async keyFromClipboard() {
      const target = client();
      if (!target) return { ok: false, error: "not_connected" };
      return target.apiKeyFromClipboard();
    },
  };
}
