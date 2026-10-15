import { useEffect, useState } from "react";

/**
 * 창이 좁은가 (인수인계 H2-C, 2026-09-16). 작업 화면을 옆에 좁게 띄워 두고 쓰는 경우를 위해 —
 * CSS 만으로는 **그리는 내용**(글자 대신 아이콘, 칸을 자동으로 열지 않기)을 못 바꾼다.
 */
export function useNarrow(maxWidth: number): boolean {
  const query = `(max-width: ${maxWidth}px)`;
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return narrow;
}

/** 사이드바를 아이콘만 남기는 폭. `workspace.css` 의 같은 값과 맞춘다. */
export const RAIL_MAX_WIDTH = 820;
/** 오른쪽 컴퓨터 칸이 옆에 설 자리가 없는 폭 — 이하에서는 눌렀을 때만 위에 덮는다. */
export const OVERLAY_MAX_WIDTH = 1180;
