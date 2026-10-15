/**
 * 듣는 중 파형 (2026-09-30, 대표: 「멜로디 음역처럼 보이게 해서, 내 음성을 얘가 알아듣고 있구나」).
 *
 * 녹음은 백엔드가 PC 마이크로 한다 — 화면에는 소리가 없다. 그래서 듣는 동안만 `/v1/voice/level` 을 짧게 물어
 * 최근 크기 24개를 막대로 흘린다(새 값이 오른쪽으로 들어온다). 조용하면 바닥에 붙은 점선이 되고, 말하면 솟는다 —
 * 마이크가 엉뚱한 장치를 잡았을 때 사람이 바로 알아채는 것이 이 줄의 진짜 쓸모다(사고: 마이크 이름 불일치).
 *
 * 색은 듣는 중 마이크와 같은 brand — Sonjari 자신이 듣고 있다는 뜻이다. 움직임은 장식이 아니라 데이터라
 * 줄이기 설정에서도 막대 높이는 바뀐다(애니메이션 전환만 끈다).
 */
import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import type { JarvisClient } from "../backend";

const BARS = 24;
const POLL_MS = 80;

export function VoiceMeter({ client, active }: { client: JarvisClient | null; active: boolean }) {
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));
  const busy = useRef(false);

  useEffect(() => {
    if (!active || !client) {
      setLevels(Array(BARS).fill(0));
      return;
    }
    let alive = true;
    const timer = window.setInterval(() => {
      if (busy.current) return;
      busy.current = true;
      void client.voiceLevel()
        .then((next) => {
          if (alive) setLevels((current) => [...current.slice(1), next.recording ? next.level : 0]);
        })
        .catch(() => undefined)
        .finally(() => { busy.current = false; });
    }, POLL_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, [active, client]);

  if (!active) return null;
  return (
    <span className="voice-meter" role="status" aria-label={t("듣는 중")}>
      {levels.map((level, index) => (
        <i key={index} style={{ height: `${Math.max(2, Math.round(level * 18))}px` }} />
      ))}
    </span>
  );
}
