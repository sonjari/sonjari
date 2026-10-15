/**
 * 코드 일을 시키는 순간 「이 일에 더 큰 코드 모델을 써 볼 수 있습니다」 (2026-10-01 밤 대표: 「일이 들어올 때 먼저 권해라」).
 * 10-02: 「낫습니다」는 잰 적 없는 주장이라 「써 볼 수 있습니다」로 낮췄다 — 측정이 나오면 근거와 함께 올린다.
 *
 * 막지 않는다 — 일은 그대로 돈다. 판단은 백엔드 규칙 한 곳(`hf_catalog.code_upgrade`: 코드 모델 20B 미만 · 이 카드에 더 큰 것이
 * 여유 있게 들어감)이고, 작은 모델에게 「너보다 나은 모델」을 묻지 않는다(지어낼 수 있다). 받으면 **코드 역할에만** 적용한다.
 */
import { t } from "../i18n";
import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { pullFailureText, type CodeUpgrade, type SetupApi } from "../setup/setupApi";

export function CodeUpgradeCard({ api, offer, onClose, onChanged }: {
  api: SetupApi;
  offer: CodeUpgrade;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "pulling" | "done" | "failed">("idle");
  const [pct, setPct] = useState(0);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (phase !== "pulling") return;
    const timer = window.setInterval(async () => {
      try {
        const view = await api.modelPicker("code");
        const pull = view.pulls[offer.tag];
        if (!pull) return;
        if (pull.total) setPct(Math.round((pull.completed / pull.total) * 100));
        if (pull.status === "done") {
          const applied = pull.applied;
          setPhase(applied && !applied.ok ? "failed" : "done");
          setNote(applied && !applied.ok ? t("바꾸지 못했습니다: {0}", applied.error) : "");
          if (!applied || applied.ok) onChanged?.();
        } else if (pull.status === "failed") {
          setPhase("failed");
          setNote(pullFailureText(pull));
        }
      } catch {
        /* 다음 차례에 다시 읽는다 */
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [api, offer.tag, phase, onChanged]);

  const start = async () => {
    setPhase("pulling");
    setNote("");
    try {
      const started = await api.pullTag(offer.tag, 65536, "code");
      if (!started.ok) throw new Error(started.error || t("받기를 시작하지 못했습니다"));
    } catch (reason) {
      setPhase("failed");
      setNote(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <aside className="code-upgrade-card" role="note" aria-label={t("코드 모델 권고")}>
      <div className="code-upgrade-card-text">
        <strong>{t("이 일에 더 큰 코드 모델을 써 볼 수 있습니다")}</strong>
        <span>
          {t("지금 코드 모델은")} {offer.current}({offer.current_params_b}{t("B)입니다. 이 PC 에는")} {offer.name}({offer.size_gb.toFixed(1)}{t("GB)가 들어갑니다 — 대화·브라우저 모델은 그대로 두고 코드 탭만 바꿉니다. 지금 일은 그대로 진행됩니다.")}
        </span>
        <small>{offer.basis}</small>
        {phase === "pulling" && <span className="code-upgrade-card-progress"><Loader2 size={13} className="spin" /> {t("받는 중")} {pct}{t("% — 다 받으면 실제로 한 번 돌려 보고 바꿉니다")}</span>}
        {phase === "done" && <span className="code-upgrade-card-done">{t("코드 모델을 바꿨습니다 — 다음 코드 일부터 씁니다.")}</span>}
        {phase === "failed" && <span className="code-upgrade-card-error" role="alert">{note}</span>}
      </div>
      <div className="code-upgrade-card-actions">
        {phase === "idle" && (
          <button type="button" className="code-upgrade-go" onClick={() => void start()}>
            {offer.installed ? t("코드 모델로 쓰기") : t("받기 · {0}GB", offer.size_gb.toFixed(1))}
          </button>
        )}
        <button type="button" className="code-upgrade-card-close" onClick={onClose} aria-label={t("그냥 진행하고 닫기")}>
          {phase === "idle" ? t("그냥 진행") : <X size={14} />}
        </button>
      </div>
    </aside>
  );
}
