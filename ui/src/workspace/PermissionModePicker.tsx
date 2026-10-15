/**
 * 입력창 옆 **권한 모드 단추** — 클로드 코드처럼 눌러서 바로 고른다 (2026-09-23 사장님 요청).
 *
 * 예전에는 모드를 바꾸려면 설정 › 권한까지 들어가거나, 승인 카드의 「승인하고 풀기」를 눌러야 했다.
 * 사람은 귀찮은 **그 순간**에 손이 닿아야 실제로 바꾼다 — 일을 시키는 자리(입력창) 바로 옆에 둔다.
 *
 * ## 점 하나가 말하는 것
 *
 * 색은 새로 고르지 않았다. 이 앱의 색은 이미 「되돌릴 수 있는가」로 뜻이 정해져 있다(tokens.css).
 * 그 뜻을 그대로 빌려, **입력창만 봐도** 지금 온텔릭이 얼마나 묻지 않고 하는지 보이게 한다.
 *
 *     계획            초록   아무것도 안 바꾼다
 *     수동            호박   사람이 눌러야 움직인다
 *     자동·편집 자동   보라   온텔릭이 알아서 한다
 *     권한 무시        빨강   되돌릴 수 없는 것까지 묻지 않는다
 *
 * 이름·설명·순서는 서버(`permissions.MODES`)가 준다 — 두 곳에 적으면 갈린다.
 */
import { t } from "../i18n";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PermissionModes } from "../types";

type Tone = "plan" | "ask" | "auto" | "open" | "custom";

const TONE: Record<string, Tone> = {
  read_only: "plan",
  ask: "ask",
  reversible: "auto",
  workspace: "auto",
  bypass: "open",
};

function toneOf(mode: string): Tone {
  return TONE[mode] ?? "custom";
}

export function PermissionModePicker({ modes, onChoose, disabled }: {
  modes: PermissionModes;
  /** 서버에 바꿔 달라고 하고, 된 모드 목록을 돌려받는다. 실패는 던진다. */
  onChoose: (mode: string) => Promise<PermissionModes>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState(0);
  const shell = useRef<HTMLDivElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);

  const current = modes.modes.find((row) => row.id === modes.mode);
  const label = current?.label ?? t("사용자 지정");

  const choose = async (mode: string) => {
    if (busy) return;
    if (mode === modes.mode) {
      setOpen(false);
      return;
    }
    setBusy(mode);
    setError("");
    try {
      await onChoose(mode);
      setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  // 열리면 지금 모드에 초점을 둔다 — 화살표로 옮기고 숫자로 바로 고른다(클로드와 같은 손버릇).
  useEffect(() => {
    if (!open) return;
    const at = Math.max(0, modes.modes.findIndex((row) => row.id === modes.mode));
    setCursor(at);
    options.current[at]?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!shell.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", closeOutside);
    return () => window.removeEventListener("pointerdown", closeOutside);
  }, [open, modes.mode, modes.modes]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open) return;
    const count = modes.modes.length;
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
      void choose(modes.modes[digit - 1].id);
    }
  };

  const neverBypass = modes.never_bypass ?? [];

  return (
    <div className="permission-picker" ref={shell} onKeyDown={onKeyDown}>
      <button
        type="button"
        className={`permission-chip tone-${toneOf(modes.mode)} ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current ? t("권한 모드 — {0}", current.help) : t("권한 모드 — 설정에서 손으로 바꾼 상태입니다")}
      >
        <span className="permission-dot" aria-hidden />
        <span>{label}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <div className="permission-popover" role="listbox" aria-label={t("권한 모드")}>
          <div className="permission-popover-head">
            <strong>{t("권한 모드")}</strong>
            <small>{t("Sonjari가 무엇을 묻지 않고 할지 정합니다")}</small>
          </div>
          <div className="permission-options">
            {modes.modes.map((row, index) => {
              const selected = row.id === modes.mode;
              return (
                <button
                  key={row.id}
                  ref={(node) => { options.current[index] = node; }}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={`tone-${toneOf(row.id)} ${selected ? "selected" : ""}`}
                  onClick={() => void choose(row.id)}
                  onFocus={() => setCursor(index)}
                  disabled={busy !== "" && busy !== row.id}
                >
                  <span className="permission-dot" aria-hidden />
                  <span className="permission-copy">
                    <strong>{row.label}</strong>
                    <small>{row.help}</small>
                  </span>
                  <span className="permission-meta">
                    {busy === row.id
                      ? <Loader2 size={14} className="spin" aria-label={t("바꾸는 중")} />
                      : selected
                        ? <Check size={15} aria-label={t("지금 모드")} />
                        : <kbd aria-hidden>{index + 1}</kbd>}
                  </span>
                </button>
              );
            })}
          </div>
          {modes.mode === "custom" && (
            <p className="permission-note">{t("지금은 설정에서 손으로 바꾼 상태입니다. 여기서 고르면 그 모드로 맞춥니다.")}</p>
          )}
          {neverBypass.length > 0 && (
            <p className="permission-note">{t("결제·메일 보내기·블로그 발행은 어느 모드에서도 묻습니다.")}</p>
          )}
          {error && <p className="permission-error" role="alert">{t("모드를 바꾸지 못했습니다 —")} {error}</p>}
        </div>
      )}
    </div>
  );
}
