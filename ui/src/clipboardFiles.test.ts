import { describe, expect, it } from "vitest";
import { filesFromTransfer, roomFor } from "./clipboardFiles";

/**
 * 붙여넣기·드롭에서 파일을 꺼내는 규칙.
 *
 * ## 무엇이 고장이었나 (2026-08-23)
 *
 * 처음 만든 붙여넣기 처리가 두 가지를 놓쳤다:
 *
 *     이미지만 받았다   `type.startsWith("image/")` 로 걸러 pdf·xlsx 가 튕겼다
 *     `items` 만 봤다   엔진에 따라 `files` 에만 채워 주는 경우가 있다
 *
 * 그래서 사용자 화면에서 **스크린샷도 파일도 안 붙었다.** 코드는 배포돼 있었는데
 * 조건이 좁아서 아무것도 안 걸린 것 — 화면 안에 인라인으로 있으니 아무도 못 쟀다.
 */

function fakeFile(name: string, type: string, size = 10): File {
  const file = new File([new Uint8Array(size)], name, { type });
  return file;
}

function transfer(options: { items?: File[]; files?: File[] }): DataTransfer {
  const items = (options.items ?? []).map((file) => ({
    kind: "file" as const,
    type: file.type,
    getAsFile: () => file,
  }));
  return {
    items: items as unknown as DataTransferItemList,
    files: (options.files ?? []) as unknown as FileList,
  } as DataTransfer;
}

describe("filesFromTransfer", () => {
  it("스크린샷을 items 통로에서 꺼낸다", () => {
    const shot = fakeFile("screenshot.png", "image/png");
    expect(filesFromTransfer(transfer({ items: [shot] }))).toEqual([shot]);
  });

  it("★ 이미지가 아닌 파일도 받는다 — 이게 원래 고장이었다", () => {
    const pdf = fakeFile("단가표.pdf", "application/pdf");
    const xlsx = fakeFile("반별성적.xlsx", "application/vnd.ms-excel");
    expect(filesFromTransfer(transfer({ items: [pdf, xlsx] }))).toHaveLength(2);
  });

  it("★ files 통로만 채워 줘도 받는다", () => {
    const doc = fakeFile("보고서.docx", "application/msword");
    expect(filesFromTransfer(transfer({ files: [doc] }))).toEqual([doc]);
  });

  it("양쪽에 같은 파일이 오면 하나만 남긴다", () => {
    const same = fakeFile("같은.png", "image/png");
    expect(filesFromTransfer(transfer({ items: [same], files: [same] }))).toHaveLength(1);
  });

  it("★ 같은 캡처가 양쪽 통로로 오면 만든 시각이 달라도 하나만 (2026-09-17)", () => {
    const fromItems = new File([new Uint8Array(40)], "image.png", { type: "image/png", lastModified: 1000 });
    const fromFiles = new File([new Uint8Array(40)], "image.png", { type: "image/png", lastModified: 1003 });
    expect(filesFromTransfer(transfer({ items: [fromItems], files: [fromFiles] }))).toHaveLength(1);
  });

  it("한 통로 안의 이름·크기가 같은 두 파일은 둘 다 남긴다", () => {
    const a = new File([new Uint8Array(40)], "image.png", { type: "image/png", lastModified: 1 });
    const b = new File([new Uint8Array(40)], "image.png", { type: "image/png", lastModified: 2 });
    expect(filesFromTransfer(transfer({ items: [a, b], files: [a, b] }))).toHaveLength(2);
  });

  it("글자만 붙여넣으면 빈 배열 — 가로채지 않는다", () => {
    expect(filesFromTransfer(transfer({}))).toEqual([]);
    expect(filesFromTransfer(null)).toEqual([]);
    expect(filesFromTransfer(undefined)).toEqual([]);
  });

  it("종류를 여기서 가리지 않는다", () => {
    // 첨부가 이미 가린다(32MB·서버 형식 판정). 두 곳에서 가리면 갈린다.
    const odd = fakeFile("무엇인가", "");
    expect(filesFromTransfer(transfer({ items: [odd] }))).toHaveLength(1);
  });
});

describe("roomFor", () => {
  it("남은 자리만큼만 받는다", () => {
    const many = Array.from({ length: 9 }, (_, at) => fakeFile(`${at}.png`, "image/png"));
    expect(roomFor(many, 0)).toHaveLength(6);
    expect(roomFor(many, 4)).toHaveLength(2);
  });

  it("자리가 없으면 아무것도 안 받는다", () => {
    const many = Array.from({ length: 3 }, (_, at) => fakeFile(`${at}.png`, "image/png"));
    expect(roomFor(many, 6)).toEqual([]);
    expect(roomFor(many, 9)).toEqual([]);
  });
});
