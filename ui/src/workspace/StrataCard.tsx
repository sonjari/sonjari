/**
 * 설정 › 모델 › Strata (2026-11-13 · 설계 docs/설계_Strata_앱이켜고지키기_2026-11-13.ko.md · frontend-design).
 *
 * 대표 PC 개인용 큰 모델(Strata)을 손자리가 켜고 지킨다. **깔린 PC 에서만** 보인다(손님 판에는 없다 · 11-07 결정).
 * 대표 결정 11-13 「3D 할 땐 묶자」 — 3D 작업 땐 Strata 를 내리고 27B 로 바꿔 손자리가 계속 일한다.
 *
 * ## 이 칸의 얼굴
 * 두 갈래(Strata · 3D 작업용 27B) 중 지금 쓰는 쪽에 불이 켜진다. 옮기는 단추는 하나 — 다른 갈래로.
 * 바꾸면 손자리가 1~2분 다시 켜지므로(맥 손자리도 쉰다) 누르면 한 번 묻는다. 일하는 중이면 서버가 거절한다.
 */
import { t } from "../i18n";
import { Cpu, Loader2, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import type { StrataStatus } from "../types";
import "./strata.css";

type Lane = "strata" | "ollama";

const SWITCH_ERROR: Record<string, string> = {
  busy: t("손자리가 일하는 중입니다. 끝난 뒤에 바꿔 주세요."),
  already: t("이미 그 모델을 쓰고 있습니다."),
  not_installed: t("이 PC 에는 Strata 가 없습니다."),
  no_script: t("Strata 를 켜는 스크립트를 찾지 못했습니다."),
};

/** 지금 갈래의 상태 한 줄 — 선택 · 응답 · 포기로 가른다. */
export function strataState(s: StrataStatus): "on" | "starting" | "gave_up" | "idle" {
  if (!s.selected) return "idle";
  if (s.gave_up) return "gave_up";
  return s.strata && s.bridge ? "on" : "starting";
}

export function StrataCard({ client }: { client: Pick<JarvisClient, "strataStatus" | "strataSwitch" | "strataRetry"> }) {
  const [status, setStatus] = useState<StrataStatus | null>(null);
  const [confirming, setConfirming] = useState<Lane | null>(null);
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      setStatus(await client.strataStatus());
    } catch {
      setStatus(null);
    }
  }, [client]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!status?.available) return null;   // 손님 PC — 아무것도 그리지 않는다

  const current: Lane = status.selected ? "strata" : "ollama";
  const other: Lane = current === "strata" ? "ollama" : "strata";
  const state = strataState(status);

  const doSwitch = async (to: Lane) => {
    setWorking(true);
    setNote("");
    try {
      const done = await client.strataSwitch(to);
      setNote(done.ok ? t("바꾸는 중입니다. 손자리가 1~2분 다시 켜집니다.")
        : SWITCH_ERROR[done.error ?? ""] ?? done.message ?? t("바꾸지 못했습니다."));
    } catch {
      setNote(t("바꾸지 못했습니다. 손자리가 켜져 있는지 확인해 주세요."));
    } finally {
      setWorking(false);
      setConfirming(null);
    }
  };

  const retry = async () => {
    setWorking(true);
    try {
      setStatus(await client.strataRetry());
    } finally {
      setWorking(false);
    }
  };

  return (
    <section className="strata-card settings-block" aria-labelledby="strata-title">
      <div className="gh-lede">
        <span className="gh-lede-icon"><Cpu size={16} aria-hidden="true" /></span>
        <div>
          <h3 id="strata-title" className="gh-title">{t("이 PC 의 큰 모델 · Strata")}</h3>
          <p className="settings-note">{t("손자리가 Strata 를 켜 두고, 꺼지면 다시 켭니다. 3D 작업을 할 땐 27B 로 바꿔 메모리를 비워 주세요.")}</p>
        </div>
      </div>

      <div className="strata-lanes" role="group" aria-label={t("지금 쓰는 모델")}>
        <Lane active={current === "strata"} name={t("Strata")} detail={t("큰 모델 · {0} 창", status.context)}
          state={current === "strata" ? state : undefined} />
        <Lane active={current === "ollama"} name={t("27B")} detail={t("3D 작업할 때 · 메모리를 덜 씀")} />
      </div>

      {state === "gave_up" && (
        <div className="gh-warn strata-gaveup">
          <p>{status.last_error || t("Strata 가 계속 꺼집니다. 메모리가 모자란지 확인해 주세요.")}</p>
          <button type="button" className="setup-btn-quiet" onClick={() => void retry()} disabled={working}>
            <RotateCcw size={14} aria-hidden="true" /> {t("다시 켜기")}
          </button>
        </div>
      )}

      {confirming ? (
        <div className="gh-now strata-confirm" role="alertdialog" aria-labelledby="strata-confirm-title">
          <p id="strata-confirm-title" className="gh-now-title">
            {confirming === "strata" ? t("Strata 로 바꿀까요?") : t("3D 작업용으로 27B 로 바꿀까요?")}
          </p>
          <p className="settings-note">{t("손자리가 1~2분 다시 켜집니다. 맥 손자리도 그동안 쉽니다.")}</p>
          <div className="gh-row">
            <button type="button" className="setup-btn-go" onClick={() => void doSwitch(confirming)} disabled={working}>
              {working ? <Loader2 size={14} className="gh-spin" aria-hidden="true" /> : null}
              {confirming === "strata" ? t("Strata 로 바꾸기") : t("27B 로 바꾸기")}
            </button>
            <button type="button" className="setup-btn-quiet" onClick={() => setConfirming(null)} disabled={working}>{t("그대로 두기")}</button>
          </div>
        </div>
      ) : (
        <div className="gh-row">
          <button type="button" className="setup-btn-go" onClick={() => setConfirming(other)} disabled={working}>
            {other === "strata" ? t("Strata 로 바꾸기") : t("3D 작업 — 27B 로 바꾸기")}
          </button>
        </div>
      )}
      {note && <p className="gh-quiet strata-note" role="status">{note}</p>}
    </section>
  );
}

function Lane({ active, name, detail, state }: { active: boolean; name: string; detail: string; state?: string }) {
  const label = state === "starting" ? t("켜는 중") : state === "gave_up" ? t("멈춤") : active ? t("사용 중") : "";
  return (
    <div className={`strata-lane${active ? " is-active" : ""}`} aria-current={active ? "true" : undefined}>
      <span className={`gh-dot${active && state !== "starting" && state !== "gave_up" ? " is-on" : ""}${state === "starting" ? " is-wait" : ""}`} aria-hidden="true" />
      <span className="strata-lane-name">{name}</span>
      <span className="strata-lane-detail">{detail}</span>
      {label && <span className="strata-lane-state">{label}</span>}
    </div>
  );
}
