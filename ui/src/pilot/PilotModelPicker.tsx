import { t } from "../i18n";
import { Brain, Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { userLabel } from "../workspace/userLabel";

export const PILOT_MODEL_KEY = "jarvis.pilot.model.v1";

export const PILOT_MODELS = [
  {
    id: "claude-haiku-5-5",
    label: "Haiku 5.5",
    description: t("빠른 답과 가벼운 정리"),
    character: t("가장 빠름"),
    context: 200_000,
  },
  {
    id: "claude-sonnet-5-5",
    label: "Sonnet 5.5",
    description: t("{0} 일상 작업친구", userLabel()),
    character: t("균형"),
    context: 1_000_000,
  },
  {
    id: "claude-opus-5-5",
    label: "Opus 5.5",
    description: t("{0}의 비싼 교수님", userLabel()),
    character: t("최고 성능"),
    context: 1_000_000,
  },
] as const;

export type PilotModelId = typeof PILOT_MODELS[number]["id"];

export function savedPilotModel(): PilotModelId {
  const saved = window.localStorage.getItem(PILOT_MODEL_KEY);
  return PILOT_MODELS.some((model) => model.id === saved)
    ? saved as PilotModelId
    : "claude-sonnet-5-5";
}

export function pilotModel(modelId: string) {
  return PILOT_MODELS.find((model) => model.id === modelId) ?? PILOT_MODELS[1];
}

export function savePilotModel(modelId: PilotModelId) {
  window.localStorage.setItem(PILOT_MODEL_KEY, modelId);
}

export function PilotModelPicker({ value, onChange }: {
  value: PilotModelId;
  onChange: (value: PilotModelId) => void;
}) {
  const [open, setOpen] = useState(false);
  const shell = useRef<HTMLDivElement>(null);
  const selected = pilotModel(value);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!shell.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", closeOutside);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOutside);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="pilot-model-picker" ref={shell}>
      <button
        type="button"
        className={`model-chip pilot-model-trigger ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="listbox"
        title={t("{0} · 높은 추론 · {1} 컨텍스트", selected.label, selected.context >= 1_000_000 ? "1M" : "200K")}
      >
        <span>{selected.label}</span>
        <span className="pilot-model-context">· {selected.context >= 1_000_000 ? "1M" : "200K"}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <div className="pilot-model-popover" role="listbox" aria-label={t("Claude 모델 선택")}>
          <div className="pilot-model-popover-head">
            <div>
              <strong>{t("응답 모델")}</strong>
              <small>{t("다음 질문부터 적용됩니다")}</small>
            </div>
            <span><Brain size={12} /> {t("High 추론")}</span>
          </div>
          <div className="pilot-model-options">
            {PILOT_MODELS.map((model) => {
              const current = model.id === value;
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={current}
                  className={current ? "selected" : ""}
                  key={model.id}
                  onClick={() => {
                    onChange(model.id);
                    setOpen(false);
                  }}
                >
                  <span className="pilot-model-copy">
                    <strong>{model.label}</strong>
                    <small>{model.description}</small>
                  </span>
                  <span className="pilot-model-meta">
                    <small>{model.character} · {model.context >= 1_000_000 ? "1M" : "200K"}</small>
                    {current && <Check size={15} aria-label={t("선택됨")} />}
                  </span>
                </button>
              );
            })}
          </div>
          <p>{t("같은 대화는 Claude 세션을 이어 받아 캐시를 재사용합니다.")}</p>
        </div>
      )}
    </div>
  );
}
