import { useCallback, useRef } from "react";

/**
 * 그릴 때마다 새로 만들어지는 함수를 **같은 함수 하나**로 감싼다. 부르면 늘 가장 최근의 것을 부른다.
 *
 * 「바뀐 게 없으면 다시 그리지 않는」 자식(memo)에게 함수를 넘길 때 쓴다 — 새 함수를 넘기면 자식은 매번 「바뀌었다」로 읽는다.
 */
export function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const latest = useRef(fn);
  latest.current = fn;
  return useCallback((...args: A) => latest.current(...args), []);
}
