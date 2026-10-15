import { describe, expect, it } from "vitest";
import { initialHudModel, reduceJarvisEvent } from "./hudMachine";
import { normalizeJarvisMarkdown } from "./MarkdownView";

describe("JARVIS HUD event reducer", () => {
  it("keeps a voice answer collapsed", () => {
    const model = reduceJarvisEvent(initialHudModel, {
      event: "presentation_ready",
      payload: { mode: "voice", spoken_text: "준비 완료.", display_title: "답변", display_content: "준비 완료." },
    });
    expect(model.mode).toBe("orb");
  });

  it("opens a panel for a hybrid answer", () => {
    const model = reduceJarvisEvent(initialHudModel, {
      event: "presentation_ready",
      payload: { mode: "hybrid", spoken_text: "화면에 정리했어요.", display_title: "조사 결과", display_content: "# 결과" },
    });
    expect(model.mode).toBe("panel");
    expect(model.presentation?.display_title).toBe("조사 결과");
  });

  it("uses a dedicated card for approval", () => {
    const model = reduceJarvisEvent(initialHudModel, {
      event: "approval_requested",
      payload: { nonce: "abc", tool_name: "send_email", arguments: { to: "test@example.com" } },
    });
    expect(model.mode).toBe("approval");
    expect(model.state).toBe("waiting_approval");
  });

  it("loads an external action preview only for the matching action_id", () => {
    const requested = reduceJarvisEvent(initialHudModel, {
      event: "approval_requested",
      payload: {
        nonce: "abc",
        tool_name: "google_gmail_send",
        arguments: { action_id: "action-1" },
      },
    });
    expect(requested.approvalPreview).toBeNull();

    const stale = reduceJarvisEvent(requested, {
      event: "external_action_preview_loaded",
      payload: {
        action_id: "action-stale",
        kind: "gmail_send",
        preview: { subject: "stale" },
        status: "prepared",
        created_at: 0,
        expires_at: 0,
      },
    });
    expect(stale.approvalPreview).toBeNull();

    const loaded = reduceJarvisEvent(requested, {
      event: "external_action_preview_loaded",
      payload: {
        action_id: "action-1",
        kind: "gmail_send",
        preview: { subject: "안녕하세요" },
        status: "prepared",
        created_at: 0,
        expires_at: 0,
      },
    });
    expect(loaded.approvalPreview?.preview.subject).toBe("안녕하세요");

    const decided = reduceJarvisEvent(loaded, { event: "approval_approved", payload: {} });
    expect(decided.approvalPreview).toBeNull();
    expect(decided.approval).toBeNull();
  });

  it("keeps text chat open and records agent progress", () => {
    const started = reduceJarvisEvent(initialHudModel, {
      event: "agent_started",
      payload: { job_id: "job-1", origin: "chat", goal: "검색" },
    });
    const progressed = reduceJarvisEvent(started, {
      event: "agent_progress",
      payload: {
        job_id: "job-1",
        phase: "tool",
        step: 1,
        tool: "browser_search",
        message: "웹 검색 중",
        status: "running",
      },
    });

    expect(progressed.mode).toBe("panel");
    expect(progressed.activeJobId).toBe("job-1");
    expect(progressed.progress[0].message).toBe("웹 검색 중");
  });

  it("streams answer text and opens a continuation card", () => {
    const started = reduceJarvisEvent(initialHudModel, {
      event: "agent_started",
      payload: { job_id: "job-2", origin: "chat" },
    });
    const delta = reduceJarvisEvent(started, {
      event: "agent_answer_delta",
      payload: { job_id: "job-2", delta: "실시간 답변" },
    });
    const waiting = reduceJarvisEvent(delta, {
      event: "agent_continuation_requested",
      payload: { job_id: "job-2", reason: "time_budget", steps: 8, sources: 3 },
    });

    expect(delta.streamingContent).toBe("실시간 답변");
    expect(waiting.mode).toBe("continuation");
    expect(waiting.state).toBe("waiting_continuation");
    expect(waiting.continuation?.steps).toBe(8);
  });
});

describe("HUD suppression for full-screen workspace jobs", () => {
  const queueWorkspaceJob = (jobId: string) =>
    reduceJarvisEvent(initialHudModel, {
      event: "job_queued",
      payload: { job_id: jobId, kind: "chat", title: "질문", origin: "workspace" },
    });

  it("stays an orb through a whole workspace answer", () => {
    const queued = queueWorkspaceJob("job-w1");
    const started = reduceJarvisEvent(queued, {
      event: "agent_started",
      payload: { job_id: "job-w1", origin: "workspace", goal: "조사" },
    });
    const ready = reduceJarvisEvent(started, {
      event: "presentation_ready",
      payload: {
        job_id: "job-w1",
        origin: "workspace",
        mode: "screen",
        spoken_text: "",
        display_title: "조사 결과",
        display_content: "# 결과",
      },
    });

    expect(started.mode).toBe("orb");
    expect(ready.mode).toBe("orb");
    expect(ready.presentation).toBeNull();
    expect(ready.activeJobId).toBe("");
  });

  it("keeps workspace streaming out of the HUD using the remembered origin", () => {
    // agent_answer_delta and agent_progress carry no origin of their own -- the
    // job_queued lookup is the only thing that can place them.
    const queued = queueWorkspaceJob("job-w2");
    const delta = reduceJarvisEvent(queued, {
      event: "agent_answer_delta",
      payload: { job_id: "job-w2", delta: "워크스페이스 답변" },
    });
    const progressed = reduceJarvisEvent(delta, {
      event: "agent_progress",
      payload: { job_id: "job-w2", phase: "tool", step: 1, tool: "browser_search", message: "검색 중", status: "running" },
    });

    expect(delta.streamingContent).toBe("");
    expect(progressed.progress).toHaveLength(0);
  });

  it("still raises the approval card for a workspace job", () => {
    // The workspace window has no approval UI, so this is the one popup that
    // must survive -- without it an L2 action started there is unapprovable.
    const queued = queueWorkspaceJob("job-w3");
    const approval = reduceJarvisEvent(queued, {
      event: "approval_requested",
      payload: {
        nonce: "nonce-w3",
        job_id: "job-w3",
        tool_name: "google_gmail_send",
        arguments: { action_id: "action-w3" },
      },
    });
    const decided = reduceJarvisEvent(approval, {
      event: "approval_approved",
      payload: { nonce: "nonce-w3", job_id: "job-w3" },
    });

    expect(approval.mode).toBe("approval");
    expect(approval.state).toBe("waiting_approval");
    expect(decided.mode).toBe("orb");
  });

  it("collapses back to the orb after a workspace continuation resumes", () => {
    const queued = queueWorkspaceJob("job-w4");
    const waiting = reduceJarvisEvent(queued, {
      event: "agent_continuation_requested",
      payload: { job_id: "job-w4", reason: "time_budget", steps: 6, sources: 2 },
    });
    const resumed = reduceJarvisEvent(waiting, {
      event: "agent_continuation_resumed",
      payload: { job_id: "job-w4", action: "extend_3m" },
    });

    expect(waiting.mode).toBe("continuation");
    expect(resumed.mode).toBe("orb");
    expect(resumed.continuation).toBeNull();
  });

  it("removes a stale workspace continuation when that job is cancelled", () => {
    const queued = queueWorkspaceJob("job-w5");
    const waiting = reduceJarvisEvent(queued, {
      event: "agent_continuation_requested",
      payload: { job_id: "job-w5", reason: "step_budget", steps: 24 },
    });
    const cancelled = reduceJarvisEvent(waiting, {
      event: "job_cancelled",
      payload: { job_id: "job-w5" },
    });

    expect(waiting.continuation?.job_id).toBe("job-w5");
    expect(cancelled.mode).toBe("continuation");
    expect(cancelled.continuation).toBeNull();
    expect(cancelled.state).toBe("idle");
  });

  it("leaves the HUD's own chat untouched", () => {
    const queued = reduceJarvisEvent(initialHudModel, {
      event: "job_queued",
      payload: { job_id: "job-c1", kind: "chat", title: "질문", origin: "chat" },
    });
    const ready = reduceJarvisEvent(queued, {
      event: "presentation_ready",
      payload: {
        job_id: "job-c1",
        origin: "chat",
        mode: "screen",
        spoken_text: "",
        display_title: "답변",
        display_content: "본문",
      },
    });

    expect(ready.mode).toBe("panel");
    expect(ready.presentation?.display_title).toBe("답변");
  });
});

describe("사람이 화면에서 처리해야 하는 상황", () => {
  const notice = {
    job_id: "job-1",
    code: "bot_check",
    tool: "browser_search",
    title: "봇 확인 화면이 떴습니다",
    message: "브라우저에서 직접 통과시켜 주세요.",
  };

  it("전용 카드를 연다", () => {
    const model = reduceJarvisEvent(initialHudModel, { event: "attention_required", payload: notice });

    expect(model.mode).toBe("attention");
    expect(model.attention?.title).toBe("봇 확인 화면이 떴습니다");
  });

  it("전체화면이 하는 작업이어도 뜬다", () => {
    // 승인과 같은 급이다. 브라우저가 앞에 떠 있으면 이 창이 유일하게 보이는 창이다.
    const queued = reduceJarvisEvent(initialHudModel, {
      event: "job_queued",
      payload: { job_id: "job-1", kind: "chat", title: "블로그", origin: "workspace" },
    });

    const model = reduceJarvisEvent(queued, { event: "attention_required", payload: notice });

    expect(model.mode).toBe("attention");
  });

  it("승인창은 덮지 않는다", () => {
    // 사람이 결정을 내리는 중이다. 그 위에 안내를 띄우면 결정이 사라진다.
    const approving = reduceJarvisEvent(initialHudModel, {
      event: "approval_requested",
      payload: { nonce: "abc", tool_name: "naver_blog_publish", arguments: {} },
    });

    const model = reduceJarvisEvent(approving, { event: "attention_required", payload: notice });

    expect(model.mode).toBe("approval");
    expect(model.attention?.code).toBe("bot_check");
  });

  it("확인하면 오브로 돌아간다", () => {
    const raised = reduceJarvisEvent(initialHudModel, { event: "attention_required", payload: notice });

    const model = reduceJarvisEvent(raised, { event: "attention_cleared" });

    expect(model.mode).toBe("orb");
    expect(model.attention).toBeNull();
  });
});

describe("JARVIS markdown normalization", () => {
  it("repairs a streamed GFM table boundary", () => {
    const value = "| 항목 | 내용 ||---|---| 값 | 설명 |";
    expect(normalizeJarvisMarkdown(value)).toContain("| 내용 |\n|---|---|\n");
  });
});
