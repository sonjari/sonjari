/**
 * 입력창 옆 **추론 칩** — 자동·빠르게·보통·깊게 (2026-09-28 사장님 제안).
 *
 * 헤르메스 입력창의 「Med」 칩을 보고 나왔다. 설정 › 생각 깊이까지 들어가지 않고, 일을 시키는 자리에서 그 판의 생각 깊이를 고른다.
 *
 *     자동     보통으로 시작해 막히면 깊게 — 요청 문장으로 난이도를 미리 맞히지 않는다(전략안: 싼 것부터 → 실패하면 승급)
 *     빠르게   생각 없이 바로
 *     보통     막힌 자리에서만 생각
 *     깊게     걸음마다 생각
 *
 * 권한 칩의 색(되돌릴 수 있는가)은 빌리지 않는다 — 생각 깊이는 위험과 다른 축이다.
 * 고른 값은 이 PC 에만 기억한다(보는 사람 편의). 못 읽으면 자동.
 */
import { t } from "../i18n";
import { Brain, Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export type ReasoningChoice = "auto" | "fast" | "normal" | "deep";

export const REASONING_OPTIONS: { id: ReasoningChoice; label: string; help: string }[] = [
  { id: "auto", label: t("자동"), help: t("보통으로 시작해 막히면 깊게 생각합니다") },
  { id: "fast", label: t("빠르게"), help: t("생각 없이 바로 합니다") },
  { id: "normal", label: t("보통"), help: t("막힌 자리에서만 생각합니다") },
  { id: "deep", label: t("깊게"), help: t("걸음마다 생각합니다 — 느리지만 꼼꼼합니다") },
];

const STORAGE_KEY = "ontelic.reasoning";

export function loadReasoningChoice(): ReasoningChoice {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (REASONING_OPTIONS.some((row) => row.id === saved)) return saved as ReasoningChoice;
  } catch {
    // 저장소를 못 읽으면 기본값으로 간다.
  }
  return "auto";
}

export function saveReasoningChoice(choice: ReasoningChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // 기억을 못 해도 이번 선택은 그대로 쓴다.
  }
}

export function ReasoningPicker({ value, onChoose, disabled }: {
  value: ReasoningChoice;
  onChoose: (choice: ReasoningChoice) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const shell = useRef<HTMLDivElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const current = REASONING_OPTIONS.find((row) => row.id === value) ?? REASONING_OPTIONS[0];

  const choose = (choice: ReasoningChoice) => {
    onChoose(choice);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const at = Math.max(0, REASONING_OPTIONS.findIndex((row) => row.id === value));
    setCursor(at);
    options.current[at]?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!shell.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", closeOutside);
    return () => window.removeEventListener("pointerdown", closeOutside);
  }, [open, value]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open) return;
    const count = REASONING_OPTIONS.length;
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = (cursor + (event.key === "ArrowDown" ? 1 : count - 1)) % count;
      setCursor(next);
      options.current[next]?.focus();
      return;
    }
    const digit = Number(event.key);
    if (Number.isInteger(digit) && digit >= 1 && digit <= count) {
      event.preventDefault();
      choose(REASONING_OPTIONS[digit - 1].id);
    }
  };

  return (
    <div className="permission-picker reasoning-picker" ref={shell} onKeyDown={onKeyDown}>
      <button
        type="button"
        className={`permission-chip reasoning-chip ${open ? "open" : ""}`}
        onClick={() => setOpen((shown) => !shown)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={t("추론 — {0}", current.help)}
      >
        <Brain size={13} aria-hidden />
        <span>{current.label}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <div className="permission-popover" role="listbox" aria-label={t("추론")}>
          <div className="permission-popover-head">
            <strong>{t("추론")}</strong>
            <small>{t("이번 일을 얼마나 깊게 생각할지 정합니다")}</small>
          </div>
          <div className="permission-options">
            {REASONING_OPTIONS.map((row, index) => {
              const selected = row.id === value;
              return (
                <button
                  key={row.id}
                  ref={(node) => { options.current[index] = node; }}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={selected ? "selected" : ""}
                  onClick={() => choose(row.id)}
                  onFocus={() => setCursor(index)}
                >
                  <Brain size={14} aria-hidden />
                  <span className="permission-copy">
                    <strong>{row.label}</strong>
                    <small>{row.help}</small>
                  </span>
                  <span className="permission-meta">
                    {selected ? <Check size={15} aria-label={t("지금 고른 것")} /> : <kbd aria-hidden>{index + 1}</kbd>}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
