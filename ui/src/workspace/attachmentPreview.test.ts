import { describe, expect, it } from "vitest";
import { fileBadge, fitWithin, formatBytes, isImage } from "./attachmentPreview";

describe("첨부 미리보기 (2026-09-17)", () => {
  it("긴 변을 맞추고 비율은 지킨다", () => {
    expect(fitWithin(1920, 1080)).toEqual({ width: 640, height: 360 });
    expect(fitWithin(1080, 1920)).toEqual({ width: 360, height: 640 });
  });

  it("작은 그림은 키우지 않는다", () => {
    expect(fitWithin(120, 80)).toEqual({ width: 120, height: 80 });
  });

  it("크기를 모르면 0 — 그림을 그리지 않는다", () => {
    expect(fitWithin(0, 100)).toEqual({ width: 0, height: 0 });
  });

  it("문서 표식은 확장자가 먼저, 없으면 형식에서", () => {
    expect(fileBadge("반별성적.xlsx", "application/octet-stream")).toBe("XLSX");
    expect(fileBadge("계약서.hwpx", "")).toBe("HWPX");
    expect(fileBadge("보고서", "application/pdf")).toBe("PDF");
    expect(fileBadge("무엇", "")).toBe("파일");
  });

  it("크기는 읽히는 단위로", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(42_000)).toBe("41 KB");
    expect(formatBytes(3_500_000)).toBe("3.3 MB");
    expect(formatBytes(0)).toBe("");
  });

  it("그림 판정", () => {
    expect(isImage("image/png")).toBe(true);
    expect(isImage("application/pdf")).toBe(false);
    expect(isImage(undefined)).toBe(false);
  });
});
