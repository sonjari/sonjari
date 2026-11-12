/**
 * 설정 › 모델 — 그래픽카드 쓰는 법 (2026-11-11 대표: 「램 부스트를 사용자가 하고 안 하고 고르게」).
 *
 *   ○ 속도 우선        모델을 그래픽카드에 다 올립니다. 가장 빠르지만 다른 프로그램이 쓸 여유가 줄어듭니다.
 *   ● 자동 (기본)      평소엔 속도 우선, 그래픽카드가 모자라면 그때 램 부스트로 넘어갑니다.
 *   ○ 그래픽카드 비워 두기  처음부터 램 부스트로, 3ds Max · 유니티가 쓸 6GB 를 비워 둡니다.
 *
 * 고르는 것만 이 화면이 하고, 언제 무엇을 거는지는 백엔드(`gpu_mode` · `model_fallback`)가 정한다.
 * 이 PC 에서 램 부스트를 못 쓰면(맥 · 위성) 칸을 안 보인다 — 누를 수 없는 단추를 보이지 않는다.
 */
import { t } from "../i18n";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { GpuMode, GpuModeView, SetupApi } from "../setup/setupApi";

const ORDER: GpuMode[] = ["speed", "auto", "keep_free"];

function title(mode: GpuMode): string {
  if (mode === "speed") return t("속도 우선");
  if (mode === "auto") return t("자동");
  return t("그래픽카드 비워 두기");
}

function detail(mode: GpuMode, keepFreeGb: number): string {
  if (mode === "speed") return t("모델을 그래픽카드에 다 올립니다. 가장 빠르지만 다른 프로그램이 쓸 그래픽 메모리 여유가 줄어듭니다.");
  if (mode === "auto") return t("평소엔 그래픽카드에 다 올리고, 모자라면 그때 남는 램으로 옮깁니다(램 부스트).");
  return t("3ds Max · 유니티처럼 그래픽카드를 쓰는 프로그램과 같이 쓸 때. 처음부터 램 부스트로 그래픽카드를 {0}GB 비워 둡니다 — 조금 느려집니다.",
    keepFreeGb.toFixed(0));
}

export function GpuModeSection({ api }: { api: SetupApi | null }) {
  const [view, setView] = useState<GpuModeView | null>(null);
  const [busy, setBusy] = useState<GpuMode | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!api?.gpuMode) return;
    let alive = true;
    api.gpuMode().then((next) => { if (alive) setView(next); }).catch(() => undefined);
    return () => { alive = false; };
  }, [api]);

  if (!api?.setGpuMode || !view || !view.available) return null;

  const choose = async (mode: GpuMode) => {
    if (mode === view.mode || busy) return;
    setBusy(mode);
    setError("");
    try {
      setView(await api.setGpuMode!(mode));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="gpu-mode" role="radiogroup" aria-label={t("그래픽카드 쓰는 법")}>
      <h3>{t("그래픽카드 쓰는 법")}</h3>
      {ORDER.map((mode) => (
        <button key={mode} type="button" role="radio" aria-checked={view.mode === mode}
          className={`gpu-mode-option${view.mode === mode ? " is-on" : ""}`} disabled={Boolean(busy)}
          onClick={() => void choose(mode)}>
          <span className="gpu-mode-dot" aria-hidden="true" />
          <span className="gpu-mode-text">
            <b>{title(mode)}{mode === "auto" ? <span className="gpu-mode-default"> · {t("기본")}</span> : null}
              {busy === mode ? <Loader2 size={12} className="spin" /> : null}</b>
            <span>{detail(mode, view.keep_free_gb)}</span>
          </span>
        </button>
      ))}
      {view.boost_active && <p className="settings-note" role="status">{t("지금 램 부스트가 켜져 있습니다.")}</p>}
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}
