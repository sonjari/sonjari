/**
 * `agent_looking` 한 건을 「일마다 지금 읽는 그림 조각」 표에 반영한다 (2026-10-10).
 *
 * 그림이 실려 오면 그 일의 칸을 갈아 끼우고, 거두는 알림(`done`)이나 그림 없는 알림이면 칸을 비운다.
 * 바뀐 것이 없으면 **같은 표를 그대로** 돌려준다 — 걸음 알림마다 부르므로, 새 표를 만들면 화면이 까닭 없이 다시 그려진다.
 */
import type { Looking } from "../types";

export function applyLooking(
  rows: Record<string, Looking>,
  jobId: string,
  payload: Record<string, unknown>,
): Record<string, Looking> {
  if (!jobId) return rows;
  const picture = typeof payload.picture === "string" ? payload.picture : "";
  // 그림 주소만 받는다 — 다른 것을 <img src> 에 넣지 않는다.
  if (payload.done || !picture.startsWith("data:image/")) {
    if (!(jobId in rows)) return rows;
    const { [jobId]: _gone, ...rest } = rows;
    return rest;
  }
  const count = (value: unknown, least: number) => Math.max(least, Math.floor(Number(value)) || least);
  return {
    ...rows,
    [jobId]: {
      jobId,
      image: count(payload.image, 1),
      images: count(payload.images, 1),
      tile: count(payload.tile, 1),
      tiles: count(payload.tiles, 1),
      picture,
      ...(payload.kind === "page" ? { kind: "page" as const } : {}),
      width: count(payload.width, 0),
      height: count(payload.height, 0),
    },
  };
}
