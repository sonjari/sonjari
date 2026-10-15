import { t } from "../i18n";
/**
 * 첨부를 **보이는 것**으로 만든다 (2026-09-17).
 *
 * 캡처를 붙였는데 대화에는 `📎 image.png` 두 개만 남아서, 사람은 「내가 올린 게 맞나?」를 확인할 길이 없었다.
 * Claude Desktop 처럼 보낸 말 안에 그림을 그대로 띄운다. 원본은 모델에게만 가고, 기록에는 **작은 미리보기**만
 * 남긴다(긴 글 6개 × 원본 수 MB 를 대화 기록 DB 에 쌓지 않는다).
 *
 * 문서는 그림이 없으니 **무슨 종류인지**가 요점이다 — 확장자를 표식으로 크게, 크기를 옆에.
 */

/** 기록에 남기는 미리보기의 긴 변. 화면에는 240px 로 뜨니 2배 밀도까지 선명하다. */
export const THUMB_MAX_EDGE = 640;

/** 긴 변을 `max` 에 맞춘 크기. 이미 작으면 그대로(키우지 않는다). */
export function fitWithin(width: number, height: number, max = THUMB_MAX_EDGE): { width: number; height: number } {
  if (!(width > 0) || !(height > 0)) return { width: 0, height: 0 };
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

const BADGES: Array<[RegExp, string]> = [
  [/pdf/, "PDF"],
  [/spreadsheet|excel|csv/, "XLSX"],
  [/wordprocessing|msword/, "DOCX"],
  [/presentation|powerpoint/, "PPTX"],
  [/hwp/, "HWP"],
  [/markdown/, "MD"],
  [/json/, "JSON"],
  [/^text\//, "TXT"],
];

/** 문서 표식 — 확장자가 있으면 그것, 없으면 형식에서. 네 글자까지. */
export function fileBadge(name: string, mime: string): string {
  const ext = /\.([a-z0-9]{1,5})$/i.exec(name)?.[1];
  if (ext) return ext.toUpperCase().slice(0, 4);
  const hit = BADGES.find(([pattern]) => pattern.test(mime.toLowerCase()));
  return hit ? hit[1] : t("파일");
}

export function formatBytes(bytes: number): string {
  if (!(bytes > 0)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function isImage(mime: string | undefined): boolean {
  return Boolean(mime && mime.startsWith("image/"));
}

export interface ImagePreview {
  thumbnail: string;
  width: number;
  height: number;
}

/**
 * 그림 파일의 미리보기. 못 만들면 빈 값 — **첨부 자체는 막지 않는다**(모델은 원본을 받는다).
 * HEIC 처럼 웹뷰가 못 여는 형식이 여기로 온다.
 */
export async function makeImagePreview(file: File): Promise<ImagePreview | null> {
  if (!isImage(file.type) || typeof createImageBitmap !== "function") return null;
  try {
    const bitmap = await createImageBitmap(file);
    const size = fitWithin(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d");
    if (!context) return null;
    // 투명 PNG 가 JPEG 에서 검게 뭉개지지 않게 바닥을 깐다.
    context.fillStyle = "#1b1815";
    context.fillRect(0, 0, size.width, size.height);
    context.drawImage(bitmap, 0, 0, size.width, size.height);
    const preview = { thumbnail: canvas.toDataURL("image/jpeg", 0.8), width: bitmap.width, height: bitmap.height };
    bitmap.close?.();
    return preview.thumbnail.startsWith("data:image/") ? preview : null;
  } catch {
    return null;
  }
}
