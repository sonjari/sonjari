import { t } from "../i18n";
import { useEffect, useState } from "react";

/** `/v1/model/loading` 응답. 막대는 **카드 메모리 실측**이고, 못 재면 `fraction` 이 null 이다. */
export type ModelLoading = {
  ok?: boolean;
  loading?: boolean;
  resident?: boolean;
  elapsed_s?: number;
  last_seconds?: number | null;
  loaded_gb?: number;
  expected_gb?: number;
  fraction?: number | null;
  basis?: "measured" | "estimated" | "unmeasured";
};

type Source = { getModelLoading(): Promise<ModelLoading> };

const gb = (value: number) => value.toFixed(1);

/**
 * 모델을 그래픽카드에 올리는 동안의 막대 (2026-10-01, 헤르메스 비교에서 배움).
 *
 * 전엔 「올리는 중입니다 — 1분쯤 걸립니다」 문구 한 줄이었다. 헤르메스는 같은 자리에 퍼센트 막대를 보여 줬고,
 * 사람은 그걸 보고서야 멈춘 게 아니라는 걸 안다. 다만 Ollama 는 진행률을 안 주므로 **시간으로 채우지 않는다** —
 * 백엔드가 카드 메모리를 재서 준 값만 그린다. 못 재는 PC 는 띠만 오가고 「지난번 N초」를 적는다.
 */
export function ModelLoadLine({ client, onResident }: { client: Source | null; onResident: () => void }) {
  const [state, setState] = useState<ModelLoading | null>(null);
  useEffect(() => {
    if (!client) return undefined;
    let alive = true;
    const tick = () => {
      void client.getModelLoading().then((next) => {
        if (!alive) return;
        if (next.resident) {
          onResident();
          return;
        }
        setState(next);
      }).catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [client, onResident]);

  const fraction = typeof state?.fraction === "number" ? state.fraction : null;
  const seconds = Math.round(state?.elapsed_s ?? 0);
  const last = typeof state?.last_seconds === "number" ? Math.round(state.last_seconds) : null;
  const detail = [
    fraction !== null && state?.loaded_gb !== undefined && state?.expected_gb !== undefined
      ? t("{0} / {1}GB{2}", gb(state.loaded_gb), gb(state.expected_gb), state.basis === "estimated" ? t("(처음이라 크기는 추정)") : "")
      : "",
    state ? t("{0}초째", seconds) : "",
    last !== null ? t("지난번 {0}초", last) : "",
  ].filter(Boolean).join(" · ");
  return (
    <div className="workspace-load" role="progressbar" aria-label={t("모델을 그래픽카드에 올리는 중")}
      aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={fraction !== null ? Math.round(fraction * 100) : undefined}>
      <p>
        {t("모델을 그래픽카드에 올리는 중")}{fraction !== null ? ` ${Math.round(fraction * 100)}%` : ""}
        {detail && <span className="workspace-load-detail num">{detail}</span>}
      </p>
      <div className={`workspace-load-track${fraction === null ? " is-waiting" : ""}`}>
        <span style={fraction !== null ? { width: `${Math.max(2, fraction * 100)}%` } : undefined} />
      </div>
      {last === null && fraction === null && (
        <p className="workspace-load-note">{t("켠 뒤나 모델을 바꾼 뒤 처음 한 번은 1분쯤 걸립니다.")}</p>
      )}
    </div>
  );
}
