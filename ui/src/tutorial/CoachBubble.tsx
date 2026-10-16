import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { t } from "../i18n";

/**
 * 화면의 한 곳을 짚는 말풍선. 짚은 곳에는 노란 고리(사람이 눌러야 움직인다 — signal)가 둘러진다.
 *
 * - 안내 글은 **고정 글**이다(모델이 쓰지 않는다 · 설계 4절 원칙 2).
 * - 짚을 곳을 못 찾으면 화면 아래 가운데에 그냥 뜬다 — 사라지지 않는다.
 * - 움직임 줄이기를 켠 사람에게는 고리가 깜빡이지 않는다(CSS).
 */
export type CoachStep = {
  /** 짚을 곳의 CSS 선택자. 비우면 아래 가운데. */
  target?: string;
  /** 「몇 번째 걸음 / 모두」 — 진짜 순서가 있을 때만. */
  step?: [number, number];
  title: string;
  body?: string;
  actions?: { label: string; onClick: () => void; primary?: boolean }[];
};

type Place = { top: number; left: number; ring: DOMRect | null; below: boolean };

const GAP = 12;
const WIDTH = 320;

function measure(target?: string, height = 168): Place {
  const el = target ? document.querySelector(target) : null;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!el) return { top: vh - height - 32, left: Math.max(16, (vw - WIDTH) / 2), ring: null, below: true };
  const rect = el.getBoundingClientRect();
  // 화면 높이를 거의 채우는 곳(「Sonjari의 컴퓨터」 칸)은 위 · 아래에 자리가 없다 — 위에 띄우면 칸의 머리말을 가렸다.
  // 그 옆(왼쪽이 되면 왼쪽 · 대화 쪽)에 세운다.
  if (rect.height > vh * 0.6) {
    const leftSide = rect.left - GAP - WIDTH >= 16;
    return { top: Math.min(Math.max(16, rect.top + 72), vh - height - 16), ring: rect, below: true,
      left: leftSide ? rect.left - GAP - WIDTH : Math.min(rect.right + GAP, vw - WIDTH - 16) };
  }
  // 실제 말풍선 높이로 붙인다 — 짐작한 높이로 두면 위에 뜰 때 짚은 곳과 사이가 벌어졌다.
  const below = rect.bottom + GAP + height + 16 < vh;
  const top = below ? rect.bottom + GAP : Math.max(16, rect.top - GAP - height);
  const left = Math.min(Math.max(16, rect.left + rect.width / 2 - WIDTH / 2), vw - WIDTH - 16);
  return { top, left, ring: rect, below };
}

export function CoachBubble({ step, onSkip }: { step: CoachStep; onSkip: () => void }) {
  const bubbleRef = useRef<HTMLDivElement>(null);
  const height = () => bubbleRef.current?.offsetHeight || 168;
  const [place, setPlace] = useState<Place>(() => measure(step.target));

  useLayoutEffect(() => setPlace(measure(step.target, height())), [step]);
  useEffect(() => {
    // 짚은 곳이 늦게 그려지거나(답) 창 크기가 바뀌면 다시 잰다.
    const again = () => setPlace(measure(step.target, height()));
    const timer = window.setInterval(again, 600);
    window.addEventListener("resize", again);
    const esc = (event: KeyboardEvent) => { if (event.key === "Escape") onSkip(); };
    window.addEventListener("keydown", esc);
    return () => { window.clearInterval(timer); window.removeEventListener("resize", again); window.removeEventListener("keydown", esc); };
  }, [step, onSkip]);

  return (
    <>
      {place.ring && (
        <div className="coach-ring" aria-hidden="true"
          style={{ top: place.ring.top - 6, left: place.ring.left - 6, width: place.ring.width + 12, height: place.ring.height + 12 }} />
      )}
      <div ref={bubbleRef} className={`coach-bubble${place.below ? " is-below" : " is-above"}`} role="dialog" aria-live="polite"
        aria-label={step.title} style={{ top: place.top, left: place.left, width: WIDTH }}>
        <div className="coach-head">
          {step.step && <span className="coach-step">{step.step[0]} / {step.step[1]}</span>}
          <button type="button" className="coach-skip" onClick={onSkip}>{t("그만 보기")}</button>
        </div>
        <p className="coach-title">{step.title}</p>
        {step.body && <p className="coach-body">{step.body}</p>}
        {step.actions && step.actions.length > 0 && (
          <div className="coach-actions">
            {step.actions.map((action) => (
              <button type="button" key={action.label} className={action.primary ? "coach-primary" : undefined}
                onClick={action.onClick}>{action.label}</button>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
