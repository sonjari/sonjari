import { Laptop, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { t } from "../i18n";
import type { PairRequestView, PairedDevice, SetupApi } from "./setupApi";
import { OutsideHomePc } from "./OutsideHome";

/**
 * 짝짓기 화면 셋 (설계_짝짓기_모델자리_2026-11-03 §2-1 · §3-2 · 순서 2).
 *
 * 사람이 하는 일은 둘뿐이다: 「집 PC 빌려 쓰기」 누르기, 집 PC 화면에 뜬 숫자 6개를 이 맥에 치기.
 * - `PairRequestBanner` — 집 PC 손자리 창 위 띠. 숫자는 크게 · 셋씩 띄워. 「허락」 단추는 없다(맥에 친 것이 허락) · [거절] 하나.
 * - 이 맥 쪽 찾기 → 코드 넣기는 11-04 부터 모델 자리 [Mac | Satellite] 의 연결 띠 안에서 한다(ModelPlace.tsx).
 * - `PairedDevices` — 집 PC 쪽 설정 › 모델: 이 PC 를 빌려 쓰는 기기 · [끊기].
 * 화면 말: 집 PC · 이 맥 · 짝짓기 · 짝 코드. 「위성 · 본체 · 포트 · 토큰」은 쓰지 않는다(§3-3).
 */

export const PAIR_REQUESTS_EVENT = "sonjari:pair-requests";

function spaced(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

export function PairRequestBanner({ api }: { api: SetupApi | null }) {
  const [rows, setRows] = useState<PairRequestView[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const load = useCallback(async () => {
    if (!api?.pairPending) return;
    try {
      setRows((await api.pairPending()).requests);
    } catch {
      /* 다음 사건 때 다시 읽는다 */
    }
  }, [api]);

  useEffect(() => {
    void load();
    const reload = () => void load();
    window.addEventListener(PAIR_REQUESTS_EVENT, reload);
    return () => window.removeEventListener(PAIR_REQUESTS_EVENT, reload);
  }, [load]);

  useEffect(() => {
    if (!rows.length) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [rows.length]);

  const live = rows.filter((row) => row.expires_at > now);
  if (!live.length) return null;
  const row = live[0];
  return (
    <div className="pair-banner" role="alert">
      <Laptop size={18} aria-hidden="true" />
      <p>
        {t("{0} 이(가) 이 PC 를 빌려 쓰려고 합니다. 그 기기에 이 숫자를 치면 짝이 지어집니다.", row.child_name)}
      </p>
      <b className="pair-code" aria-label={t("짝 코드")}>{spaced(row.code)}</b>
      <button type="button" className="pair-reject" onClick={() => {
        void api?.pairReject?.(row.request_id).then(() => load());
      }}>
        {t("거절")}
      </button>
    </div>
  );
}

function ago(seconds: number): string {
  if (!seconds) return t("아직 안 씀");
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
  if (minutes < 1) return t("방금");
  if (minutes < 60) return t("{0}분 전", minutes);
  const hours = Math.round(minutes / 60);
  return hours < 48 ? t("{0}시간 전", hours) : t("{0}일 전", Math.round(hours / 24));
}

export function PairedDevices({ api }: { api: SetupApi | null }) {
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const load = useCallback(async () => {
    if (!api?.pairDevices) return;
    try {
      setDevices((await api.pairDevices()).devices);
    } catch {
      setDevices([]);
    }
  }, [api]);
  useEffect(() => {
    void load();
    const reload = () => void load();
    window.addEventListener(PAIR_REQUESTS_EVENT, reload);
    return () => window.removeEventListener(PAIR_REQUESTS_EVENT, reload);
  }, [load]);
  if (!devices.length) return null;
  return (
    <div className="model-place">
      <span className="model-place-label">{t("이 PC 를 빌려 쓰는 기기")}</span>
      <ul className="model-place-list">
        {devices.map((device) => (
          <li key={device.device_id} className="pair-device">
            <span><Laptop size={13} /> {device.name} · <small>{t("마지막 사용 {0}", ago(device.last_used))}</small></span>
            <button type="button" className="model-place-option" onClick={() => void api?.pairRevoke?.(device.device_id).then(load)}>
              <X size={13} /> {t("끊기")}
            </button>
          </li>
        ))}
      </ul>
      <OutsideHomePc api={api} />
    </div>
  );
}
