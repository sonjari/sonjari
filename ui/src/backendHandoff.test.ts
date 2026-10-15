/**
 * 이어오기 캡슐에서 고른 방향이 채팅 요청에 **계약으로** 실리는가 (W0, 2026-09-15).
 *
 * 실리지 않던 동안 서버는 긴 인계문에서 요구를 추측했고, 「남은 일만 정리하기」가
 * 계산·파일 과제로 바뀌어 239.5초·19걸음을 돌고 docx 를 만들었다.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { JarvisClient } from "./backend";

function clientWithFetch() {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 200 });
  }));
  const client = new JarvisClient({ baseUrl: "http://127.0.0.1:1", controlToken: "t" }, () => undefined, () => undefined);
  return { client, bodies };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sendChat handoff_direction", () => {
  it("carries the chosen direction next to the visible sentence", async () => {
    const { client, bodies } = clientWithFetch();
    await client.sendChat("긴 인계문", "s-1", [], "screen", "workspace", "cowork", "", "남은 일로 정리해줘", "tasks");
    expect(bodies[0]).toMatchObject({ prompt: "긴 인계문", display_prompt: "남은 일로 정리해줘", handoff_direction: "tasks" });
  });

  it("leaves ordinary chat without the field", async () => {
    const { client, bodies } = clientWithFetch();
    await client.sendChat("안녕");
    expect(bodies[0]).not.toHaveProperty("handoff_direction");
  });
});
