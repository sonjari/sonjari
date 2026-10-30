/**
 * 쇼 장면 공용 부품 (2026-10-27) — 「바뀐 것」 쇼와 「쓰는 법」 쇼가 같이 쓴다.
 *
 * - `useBeats`   박자표. 정한 시각마다 한 단계씩 올라가고 `loop` 뒤 처음부터. 움직임을 줄였으면 마지막 단계 그대로.
 * - `useThreads` 실. 칸 둘의 가장자리를 재서 곡선 길이를 만든다. 칸 크기가 바뀌면(ResizeObserver) 다시 잰다.
 */
import { useReducedMotion } from "framer-motion";
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

/**
 * 개발용 — 스크린샷을 찍을 때 장면을 한 박자에 세워 둔다(연습 화면 `?freeze=N`). 제품에서는 늘 비어 있다.
 * 움직임을 줄인 사람의 「마지막 모습」과 같은 길(타이머 없이 그 단계 그대로)을 쓴다.
 */
let frozenPhase: number | null = null;
export function freezeBeats(phase: number | null): void {
  frozenPhase = phase;
}
export function frozenAt(): number | null {
  return frozenPhase;
}

/** 박자: `beats` 의 시각(ms)마다 한 단계씩 올라가고 `loop` 뒤 처음부터. 움직임을 줄였으면 마지막 단계 그대로. */
export function useBeats(beats: number[], loop: number): [number, number] {
  const still = Boolean(useReducedMotion());
  const frozen = frozenPhase === null ? null : Math.max(0, Math.min(beats.length, frozenPhase));
  const [phase, setPhase] = useState(frozen ?? (still ? beats.length : 0));
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (frozen !== null) { setPhase(frozen); return; }
    if (still) { setPhase(beats.length); return; }
    const timers: number[] = [];
    const run = () => {
      setPhase(0);
      setRound((value) => value + 1);
      beats.forEach((at, i) => timers.push(window.setTimeout(() => setPhase(i + 1), at)));
      timers.push(window.setTimeout(run, loop));
    };
    run();
    return () => timers.forEach((id) => window.clearTimeout(id));
    // 박자표는 장면마다 고정이다 — 다시 돌릴 까닭은 움직임 설정뿐.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [still, frozen]);
  return [phase, round];
}

export type ThreadEnd = { ref: RefObject<HTMLElement | null>; side: "left" | "right" | "top" | "bottom" };
export type ThreadSpec = { from: ThreadEnd; to: ThreadEnd };
export type Thread = { d: string; x1: number; x2: number };

function anchor(rect: DOMRect, base: DOMRect, side: ThreadEnd["side"]): [number, number] {
  const x = rect.left - base.left, y = rect.top - base.top;
  if (side === "left") return [x + 2, y + rect.height / 2];
  if (side === "right") return [x + rect.width - 6, y + rect.height / 2];
  if (side === "top") return [x + rect.width / 2, y + 2];
  return [x + rect.width / 2, y + rect.height - 2];
}

/** 실의 모양 — 칸 `box` 안에서 `specs` 마다 한 가닥. 가로로 가면 가로 곡선, 세로로 가면 세로 곡선. 칸이 바뀌면 다시 잰다. */
export function useThreads(boxRef: RefObject<HTMLElement | null>, specs: ThreadSpec[]): Thread[] {
  const [threads, setThreads] = useState<Thread[]>([]);
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => {
      const base = box.getBoundingClientRect();
      const next: Thread[] = [];
      for (const spec of specs) {
        const a = spec.from.ref.current?.getBoundingClientRect();
        const b = spec.to.ref.current?.getBoundingClientRect();
        if (!a || !b) continue;
        const [x1, y1] = anchor(a, base, spec.from.side);
        const [x2, y2] = anchor(b, base, spec.to.side);
        const horizontal = Math.abs(x2 - x1) >= Math.abs(y2 - y1);
        const bend = horizontal ? Math.max(30, Math.abs(x2 - x1) * 0.55) : Math.max(24, Math.abs(y2 - y1) * 0.5);
        const sx = Math.sign(x2 - x1) || 1, sy = Math.sign(y2 - y1) || 1;
        const c1 = horizontal ? [x1 + sx * bend, y1] : [x1, y1 + sy * bend];
        const c2 = horizontal ? [x2 - sx * bend, y2] : [x2, y2 - sy * bend];
        const f = (n: number) => n.toFixed(1);
        next.push({ d: `M ${f(x1)} ${f(y1)} C ${f(c1[0])} ${f(c1[1])}, ${f(c2[0])} ${f(c2[1])}, ${f(x2)} ${f(y2)}`, x1, x2 });
      }
      setThreads((before) => (JSON.stringify(before) === JSON.stringify(next) ? before : next));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    for (const spec of specs) {
      for (const end of [spec.from, spec.to]) if (end.ref.current) observer.observe(end.ref.current);
    }
    return () => observer.disconnect();
    // specs 의 ref 는 바뀌지 않는다 — 칸 크기만 다시 잰다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxRef]);
  return threads;
}
