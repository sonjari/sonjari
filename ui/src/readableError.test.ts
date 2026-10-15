import { describe, expect, it } from "vitest";
import { readableError } from "./backend";

// 2026-09-16 밤 스크린샷: 채팅 칸 밑에 `400 {"detail":"path_outside_allowed_roots: …"}` 가 날것으로 찍혔다.
describe("readableError", () => {
  it("shows the human sentence inside detail, without the code name", () => {
    const body = JSON.stringify({ detail: "code_workspace_too_broad: C:\ — 드라이브 전체는 받지 않습니다." });
    expect(readableError(400, body)).toBe("C:\ — 드라이브 전체는 받지 않습니다.");
  });

  it("falls back to a plain sentence when the body has nothing readable", () => {
    expect(readableError(502, "")).toBe("Sonjari가 요청을 처리하지 못했습니다 (오류 502).");
  });

  it("reads structured detail codes", () => {
    const body = JSON.stringify({ detail: { code: "code_workspace_ambiguous", candidates: [] } });
    expect(readableError(409, body)).toBe("code_workspace_ambiguous");
  });
});
