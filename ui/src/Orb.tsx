import { t } from "./i18n";
import { useRef } from "react";
import { motion } from "framer-motion";
import { Mic, WifiOff } from "lucide-react";
import { startNativeHudDrag } from "./backend";
import type { JarvisState } from "./types";

const stateLabels: Record<JarvisState, string> = {
  idle: t("대기 중"),
  listening: t("듣는 중"),
  transcribing: t("목소리 이해 중"),
  routing: t("할 일을 고르는 중"),
  working: t("생각하는 중"),
  speaking: t("말하는 중"),
  waiting_approval: t("승인 대기"),
  waiting_continuation: t("계속할지 기다리는 중"),
  error: t("확인이 필요합니다"),
  stopped: t("멈춤"),
};

interface OrbProps {
  state: JarvisState;
  connected: boolean;
  disabled?: boolean;
  onPress: () => void;
  compact?: boolean;
}

export function Orb({ state, connected, disabled, onPress, compact = false }: OrbProps) {
  const active = state !== "idle" && state !== "stopped";
  const workingOnSomething = state === "working" || state === "speaking";
  // Only an in-flight request of our own blocks a press. Blocking on
  // "working"/"speaking" made a state that got stuck there -- a denied or
  // expired approval used to do exactly that -- a permanently dead mic with no
  // way out; the backend now decides what a press means and self-heals a stale
  // busy state, so the press has to reach it.
  const pressDisabled = Boolean(disabled);
  const dragOrigin = useRef<{ x: number; y: number } | null>(null);
  const dragStarted = useRef(false);

  const clearDragAfterClick = () => {
    dragOrigin.current = null;
    window.setTimeout(() => {
      dragStarted.current = false;
    }, 0);
  };

  return (
    <motion.button
      type="button"
      className={`jarvis-orb state-${state} ${compact ? "orb-compact" : ""}`}
      aria-label={t("{0}. 클릭해서 음성 입력, 드래그해서 이동", stateLabels[state])}
      title={t("{0} · 드래그해서 이동", stateLabels[state])}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        dragOrigin.current = { x: event.screenX, y: event.screenY };
        dragStarted.current = false;
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const origin = dragOrigin.current;
        if (!origin || dragStarted.current || (event.buttons & 1) === 0) return;
        if (Math.hypot(event.screenX - origin.x, event.screenY - origin.y) < 5) return;
        dragStarted.current = true;
        void startNativeHudDrag().catch(() => {
          dragStarted.current = false;
        });
      }}
      onPointerUp={clearDragAfterClick}
      onPointerCancel={clearDragAfterClick}
      onClick={(event) => {
        if (dragStarted.current) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        if (pressDisabled) return;
        onPress();
      }}
      aria-disabled={pressDisabled}
      aria-busy={workingOnSomething}
      whileTap={{ scale: 0.94 }}
      transition={{ type: "spring", stiffness: 420, damping: 28 }}
    >
      <span className="orb-aura" />
      <span className="orb-ring orb-ring-one" />
      <span className="orb-ring orb-ring-two" />
      <span className="orb-core">
        {connected ? <Mic size={compact ? 15 : 19} strokeWidth={1.8} /> : <WifiOff size={compact ? 15 : 19} />}
      </span>
      {active && (
        <span className="voice-bars" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((bar) => <i key={bar} style={{ animationDelay: `${bar * 85}ms` }} />)}
        </span>
      )}
    </motion.button>
  );
}

export function stateLabel(state: JarvisState, connected: boolean): string {
  return connected ? stateLabels[state] : t("Sonjari와 연결 중");
}
