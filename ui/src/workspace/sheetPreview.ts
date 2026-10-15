/**
 * 엑셀 미리보기 글을 표로 — 백엔드는 엑셀을 `[시트: 이름]` 줄과 **탭으로 나뉜 줄**로 보낸다.
 *
 * ★ 2026-10-13 영상 촬영 판: 가격표 엑셀의 미리보기가 글자 덩어리로 나왔다. 값은 다 들어 있는데 어느 값이 어느 칸인지
 *   읽을 수 없었다 — 결과물이 눈에 보여야 하는 바로 그 자리다.
 *
 * 표로 볼 수 없는 글(워드 · 한글 · 메모)은 `null` 을 돌려준다. 그때는 예전처럼 글 그대로 보여 준다.
 */
export type SheetPreview = {
  title: string;
  rows: string[][];
};

export type ParsedPreview = {
  sheets: SheetPreview[];
  /** 「…(이 뒤로 더 있음)」처럼 표 밖에 남은 말. 잘림을 말없이 넘기지 않는다. */
  note: string;
};

const SHEET_LINE = /^\[시트:\s*(.*)\]$/;

export function parseSheetPreview(text: string): ParsedPreview | null {
  if (!text.includes("[시트:")) return null;
  const sheets: SheetPreview[] = [];
  let note = "";
  let current: SheetPreview | null = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) continue;
    const head = SHEET_LINE.exec(line.trim());
    if (head) {
      current = { title: head[1].trim(), rows: [] };
      sheets.push(current);
      continue;
    }
    if (!current) return null; // 시트 줄 앞에 다른 글이 있으면 표로 단정하지 않는다
    if (line.startsWith("…") || line.startsWith("[행 제한")) {
      note = line.trim();
      continue;
    }
    current.rows.push(line.split("\t").map((cell) => cell.trim()));
  }
  const tabular = sheets.filter((sheet) => sheet.rows.some((row) => row.length >= 2));
  if (!tabular.length) return null;
  for (const sheet of tabular) {
    const width = Math.max(...sheet.rows.map((row) => row.length));
    sheet.rows = sheet.rows.map((row) => (row.length < width ? [...row, ...Array<string>(width - row.length).fill("")] : row));
  }
  return { sheets: tabular, note };
}
