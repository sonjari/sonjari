import { describe, expect, it } from "vitest";
import { parseSheetPreview } from "./sheetPreview";

describe("엑셀 미리보기를 표로", () => {
  it("시트 줄과 탭으로 나뉜 줄을 표로 읽는다", () => {
    const text = "[시트: 가격비교]\n가게\t판매 가격\t읽은 주소\n가람상회\t41,200원\thttps://shop.example/a\n솔빛마켓\t39,800원\thttps://shop.example/b";
    const parsed = parseSheetPreview(text);
    expect(parsed?.sheets).toHaveLength(1);
    expect(parsed?.sheets[0].title).toBe("가격비교");
    expect(parsed?.sheets[0].rows).toEqual([
      ["가게", "판매 가격", "읽은 주소"],
      ["가람상회", "41,200원", "https://shop.example/a"],
      ["솔빛마켓", "39,800원", "https://shop.example/b"],
    ]);
  });

  it("칸 수가 모자란 줄은 빈 칸으로 채운다", () => {
    const parsed = parseSheetPreview("[시트: 표]\n가\t나\t다\n1\t2");
    expect(parsed?.sheets[0].rows[1]).toEqual(["1", "2", ""]);
  });

  it("잘렸다는 말은 표 밖에 남긴다", () => {
    const parsed = parseSheetPreview("[시트: 표]\n가\t나\n1\t2\n…(이 뒤로 더 있음)");
    expect(parsed?.note).toBe("…(이 뒤로 더 있음)");
    expect(parsed?.sheets[0].rows).toHaveLength(2);
  });

  it("시트 여러 장을 따로 읽는다", () => {
    const parsed = parseSheetPreview("[시트: 하나]\n가\t나\n[시트: 둘]\n다\t라\n1\t2");
    expect(parsed?.sheets.map((sheet) => sheet.title)).toEqual(["하나", "둘"]);
  });

  it("표가 아닌 글은 표로 단정하지 않는다", () => {
    expect(parseSheetPreview("회의록\n\n오늘 정한 것 세 가지")).toBeNull();
    expect(parseSheetPreview("머리말\n[시트: 표]\n가\t나")).toBeNull();
    expect(parseSheetPreview("[시트: 메모]\n한 줄짜리 글")).toBeNull();
  });
});
