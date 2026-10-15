// 작업 실패 문구 — 내부 오류 이름을 화면에 그대로 찍지 않는다 (2026-10-04 대표 스크린샷: 입력칸 아래 `coding_verification_missing`).
import { describe, expect, it, vi } from "vitest";
import { isFailureNotice, jobFailureText } from "./jobFailure";

describe("jobFailureText", () => {
  it("운영 기록에 실제로 나온 실패 이름은 어느 것도 날것으로 나가지 않는다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const seen = [
      "coding_verification_missing",
      "timed out",
      "agent_empty_response",
      "ollama_empty_response",
      "code_budget_exhausted",
      "camera_frame_unavailable",
      "Client error '400 Bad Request' for url 'http://127.0.0.1:11434/api/chat'",
      "Server error '500 Internal Server Error' for url 'http://127.0.0.1:11434/api/chat'",
      'ollama_500: {"error":"health resp"}',
      "[WinError 10061] 대상 컴퓨터에서 연결을 거부했으므로 연결하지 못했습니다",
      "[WinError 10054] 현재 연결은 원격 호스트에 의해 강제로 끊겼습니다",
      "cannot access local variable 'observe_pushbacks' where it is not associated with a value",
      "stopped -> idle is not allowed",
      "invalid_delivery_mode:none",
    ];
    for (const raw of seen) {
      const text = jobFailureText(raw);
      expect(text, raw).toMatch(/[가-힣]/);
      expect(text, raw).not.toMatch(/[a-z]+_[a-z_]+/);
      expect(text, raw).not.toContain("WinError");
      expect(text, raw).not.toContain("127.0.0.1");
    }
    warn.mockRestore();
  });

  it("검증 기록이 없어 닫지 못한 판은 파일이 남아 있다는 것과 다음에 할 말을 알려 준다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const text = jobFailureText("coding_verification_missing");
    expect(text).toContain("만든 파일은 그대로 있습니다");
    expect(text).toContain("확인만 다시 해줘");
    warn.mockRestore();
  });

  it("도구가 이미 사람 말로 적어 보낸 이유는 그대로 둔다", () => {
    expect(jobFailureText("엑셀 파일이 다른 프로그램에서 열려 있어 저장하지 못했습니다.")).toBe(
      "엑셀 파일이 다른 프로그램에서 열려 있어 저장하지 못했습니다.",
    );
  });

  it("한 것이 남아 있고 이어갈 수 있는 멈춤은 안내다 — 빨간색으로 띄우지 않는다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(isFailureNotice(jobFailureText("code_budget_exhausted"))).toBe(true);
    expect(isFailureNotice(jobFailureText("coding_verification_missing"))).toBe(true);
    expect(jobFailureText("code_budget_exhausted")).toContain("작업 시간");
    // 모델 서버가 죽은 것·빈 답·모르는 오류는 사고다.
    expect(isFailureNotice(jobFailureText("timed out"))).toBe(false);
    expect(isFailureNotice(jobFailureText("[WinError 10061] 연결 거부"))).toBe(false);
    expect(isFailureNotice(jobFailureText("stopped -> idle is not allowed"))).toBe(false);
    expect(isFailureNotice("되돌리지 못했습니다: 파일이 잠겨 있습니다")).toBe(false);
    expect(isFailureNotice("")).toBe(false);
    warn.mockRestore();
  });

  it("비어 있으면 뭉뚱그린 한 문장", () => {
    expect(jobFailureText(undefined)).toContain("작업을 끝내지 못했습니다");
    expect(jobFailureText("")).toContain("작업을 끝내지 못했습니다");
  });
});
