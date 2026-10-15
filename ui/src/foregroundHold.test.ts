/**
 * 콜드스타트 크롬의 앞창 줄다리기 (2026-09-26) — 보낼 때 온텔릭이 앞창을 잠그고, 「크롬 창 보기」 전에는 푼다.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const invoked: { cmd: string; args?: unknown }[] = [];
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string, args?: unknown) => { invoked.push({ cmd, args }); return true; }),
}));

import { FOREGROUND_HOLD_MS, JarvisClient } from "./backend";

function client() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ id: "job-1", status: "queued", ok: true }), { status: 200 })));
  vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
  return new JarvisClient({ baseUrl: "http://127.0.0.1:1", controlToken: "t" }, () => undefined, () => undefined);
}

afterEach(() => {
  vi.unstubAllGlobals();
  invoked.length = 0;
});

describe("foreground hold", () => {
  it("holds the foreground when a message is sent", async () => {
    await client().sendChat("다나와에서 무선마우스 찾아줘");
    expect(invoked).toContainEqual({ cmd: "hold_foreground", args: { ms: FOREGROUND_HOLD_MS } });
  });

  it("releases it before bringing chrome forward for the human", async () => {
    await client().showBrowser();
    expect(invoked.map((row) => row.cmd)).toEqual(["release_foreground"]);
  });
});
