/**
 * 성공한 왕복이 지난 에러를 지운다.
 *
 * 2026-08-12 실측. 자비스 UI 에 "TypeError: Failed to fetch" 가 떠 있는데 왼쪽 아래는
 * "로컬 연결됨" 초록불이었다. 둘 다 사실이었다:
 *
 *     17:08:31  UI(alture-jarvis-hud) 시작
 *     17:08:52  백엔드 시작 · 8091 리슨      ← 21초 늦게
 *
 * UI 가 먼저 떠서 첫 `getState()` 가 연결 거부로 넘어졌고, 그 문구가 화면에 박혔다.
 * 웹소켓은 재연결을 하니 뒤늦게 붙어 초록불이 켜졌는데 **에러를 지우는 코드가
 * 없어서** 영원히 남았다. 백엔드는 그 순간에도 200 을 돌려주고 있었다.
 *
 * 연결 플래그가 아니라 **성공한 왕복**으로 판정한다 — 이 저장소가 NAS·브라우저·
 * Ollama 에서 세 번 배운 규칙이 화면에도 똑같이 맞다.
 */

import { describe, expect, it } from "vitest";

import { applyStateSnapshot, initialHudModel } from "./hudMachine";

describe("applyStateSnapshot", () => {
  it("기동 순서 때문에 박힌 에러를 성공한 왕복이 지운다", () => {
    const broken = { ...initialHudModel, error: "TypeError: Failed to fetch" };

    const next = applyStateSnapshot(broken, "idle");

    expect(next.error).toBe("");
    expect(next.state).toBe("idle");
  });

  it("백엔드가 준 상태를 그대로 쓴다 — 화면에 남은 옛 상태가 아니라", () => {
    const stuck = { ...initialHudModel, state: "working" as const };

    expect(applyStateSnapshot(stuck, "idle").state).toBe("idle");
  });

  it("나머지 화면 상태는 건드리지 않는다", () => {
    const model = { ...initialHudModel, mode: "panel" as const, error: "옛 에러" };

    const next = applyStateSnapshot(model, "listening");

    expect(next.mode).toBe("panel");
    expect(next.error).toBe("");
  });
});
