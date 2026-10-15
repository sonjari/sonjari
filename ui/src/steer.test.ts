import { describe, expect, it } from "vitest";

// 작업 도중에 덧붙인 말 (2026-09-26). 배선이 끊기면 말이 다시 「다음 작업으로 줄 서기」로 돌아가도 아무 시험도 안 깨진다 —
// 그래서 **보내는 길·듣는 길·못 닿은 말 돌려보내기** 셋을 소스에서 붙든다.
const files = import.meta.glob(["./WorkspaceApp.tsx", "./backend.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const app = files["./WorkspaceApp.tsx"];
const backend = files["./backend.ts"];

describe("steering a running job", () => {
  it("has a client call for the steer endpoint", () => {
    expect(backend).toContain("steerJob(jobId: string, text: string)");
    expect(backend).toContain("/steer`");
  });

  it("tries the running job before queueing a new one", () => {
    const send = app.slice(app.indexOf("const send = async"), app.indexOf("const sendRef = useRef(send)"));
    const steer = send.indexOf("client.steerJob(steerTarget, prompt)");
    const queue = send.indexOf("client.sendChat(");
    expect(steer).toBeGreaterThan(0);
    expect(queue).toBeGreaterThan(steer);
    // 첨부가 있으면 걸음 사이에 끼울 자리가 없다 — 새 작업이다.
    expect(send).toContain("!sending.length ? activeJobRef.current");
  });

  it("shows the applied note and resends what never reached the model", () => {
    expect(app).toContain('event.event === "agent_steer_applied"');
    expect(app).toContain('event.event === "agent_steer_leftover"');
    expect(app).toContain("sendRef.current(undefined, texts.join(");
  });
});
