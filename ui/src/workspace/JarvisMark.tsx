import type { JarvisState } from "../types";
import "./jarvisMark.css";

/**
 * 자비스의 표식 — **열린 고리와 초점.**
 *
 * 예전에는 `<Sparkles>` 를 보라 그라디언트 라운드 사각에 넣었다. 그건 어느 제품에
 * 붙여도 되는 모양이고(=아무 뜻이 없고), 그래서 어느 제품인지도 말하지 않았다.
 *
 * 이 표식은 자비스가 하는 일 그 자체다: **고리는 지켜보는 눈, 트인 자리는 아직
 * 모르는 것, 점은 지금 보고 있는 곳.** 그래서 상태를 담을 수 있다 —
 *
 *     대기        고리 정지, 은은한 brand
 *     일하는 중   트인 자리가 천천히 돈다 (훑는 중이라는 뜻)
 *     듣는 중     점이 숨 쉰다
 *     승인 대기   signal 로 물들고 점이 숨 쉰다 — 사람이 눌러야 움직인다
 *
 * ★ 2026-09-15 이 표식이 곧 **Ontelic 로고**가 됐다(시안 A). 트레이 아이콘도 같은 규칙으로 색·움직임을
 *   바꾼다(`ui/src-tauri/src/tray_status.rs`) — 규칙을 바꾸면 두 곳을 같이 바꾼다.
 *     오류        stop
 *     연결 끊김   색이 빠진다
 *
 * ★ 이게 화면에서 **상태를 말하는 유일한 자리**다. 그래서 「생각하는 중」 칩과
 * 작성칸 밑 안내 문구를 지웠다. 같은 것을 세 군데서 말하면 셋 다 안 읽힌다 —
 * 사용자가 "너무 많다"고 하신 것이 그것이다.
 *
 * 상자를 없앤 이유: 그라디언트 라운드 사각 + 아이콘은 템플릿의 기본값이다.
 * 표식 자체가 또렷하면 담을 상자가 필요 없다.
 */
export function JarvisMark({
  state,
  connected,
  size = 32,
}: {
  state: JarvisState;
  connected: boolean;
  size?: number;
}) {
  const tone = !connected
    ? "offline"
    : state === "error"
      ? "stop"
      : state === "waiting_approval" || state === "waiting_continuation"
        ? "signal"
        : "brand";
  const motion =
    state === "working" || state === "routing" || state === "transcribing"
      ? "sweeping"
      : state === "listening" || tone === "signal"
        ? "breathing"
        : "still";

  return (
    <span
      className={`jarvis-mark tone-${tone} motion-${motion}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 32 32" width={size} height={size}>
        {/* 고리. 둘레 2πr = 69.1 이므로 55 그리고 14.1 비운다. -33° 회전은 CSS(jarvisMark.css) 한 곳에서만 한다.
            ★ 2026-09-15: 여기 `transform="rotate(-33 16 16)"` 속성과 CSS `transform-origin` 이 **겹쳐 회전 중심이 두 번**
            들어가 고리가 왼쪽 아래로 밀리고 점만 고리 밖에 남았다(로고 시안 페이지는 CSS 가 없어 멀쩡했다). */}
        <g className="mark-body">
          <circle className="mark-ring" cx="16" cy="16" r="11" fill="none" strokeWidth="2.6" strokeLinecap="round"
            strokeDasharray="55 14.1" />
          <circle className="mark-dot" cx="22.4" cy="16" r="2.5" />
        </g>
      </svg>
    </span>
  );
}
