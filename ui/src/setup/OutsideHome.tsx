import { Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { openExternalUrl } from "../backend";
import { t } from "../i18n";
import { HERE } from "./ModelPlace";
import type { OutsideSide, OutsideStatus, OutsideStepName, SetupApi } from "./setupApi";
import "./modelPlace.css";

/**
 * 밖에서도 쓰기 — 테일스케일을 몰라도 되는 체크 목록 (설계_밖에서도쓰기_테일스케일_2026-11-04 §2 · §4 · §8).
 *
 * 대표(11-04): 「일반 사용자는 테일스케일을 모르는 경우가 많다 · 디스코드 연결한 것처럼 거의 떠먹여 주는 게 필요하다」.
 * - 단계는 백엔드 `stage` 가 정한다. 화면은 누른다고 앞서 가지 않는다(디스코드 연결 화면과 같은 짜임).
 * - 두 기기 화면에 같은 목록이 뜬다: 맥은 짝지은 집 PC 와, 집 PC 는 시작한 맥과 맞춰 본다(3초마다).
 * - 사람 몫은 설치 누르기 · 로그인뿐. 페이지는 열어 주기만 한다(손자리가 설치 · 로그인을 대신하지 않는다).
 * - 화면 말: Outside home · Tailscale · Mac · PC 이름. 「포트 · 토큰 · 노드」는 쓰지 않는다.
 */

const POLL_MS = 3000;

function useOutside(api: SetupApi | null, poll: (status: OutsideStatus | null) => boolean) {
  const [status, setStatus] = useState<OutsideStatus | null>(null);
  const pollRef = useRef(poll);
  pollRef.current = poll;
  const load = useCallback(async () => {
    if (!api?.outsideStatus) return;
    try {
      setStatus(await api.outsideStatus());
    } catch {
      /* 다음 차례에 다시 묻는다 */
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!pollRef.current(status)) return;
    const timer = window.setTimeout(() => void load(), POLL_MS);
    return () => window.clearTimeout(timer);
  }, [status, load]);
  return { status, load };
}

function reasonText(status: OutsideStatus): string {
  const mine = status.role;
  const other = status.other_name || (mine === "mac" ? t("집 PC") : "Mac");
  switch (status.reason) {
    case "not_installed_mac":
    case "not_installed_pc":
      return status.reason.endsWith(mine)
        ? t("Tailscale 이 아직 없습니다. [설치 열기] 를 누르면 공식 페이지가 열립니다.")
        : t("{0} 에서 Tailscale 을 설치해 주세요. 그쪽 손자리 창에도 같은 목록이 떠 있습니다.", other);
    case "sign_in_mac":
    case "sign_in_pc":
      return status.reason.endsWith(mine)
        ? t("[로그인] 을 누르면 로그인 페이지가 열립니다. 두 기기 모두 같은 계정(예: 같은 구글 계정)으로 해 주세요.")
        : t("{0} 에서 Tailscale 에 로그인해 주세요. 이 기기와 같은 계정으로.", other);
    case "turn_on_mac":
    case "turn_on_pc":
      return status.reason.endsWith(mine) ? t("Tailscale 이 꺼져 있습니다. [켜기] 를 눌러 주세요.") : t("{0} 의 Tailscale 이 꺼져 있습니다.", other);
    case "different_account":
      return t("{0} 와 이 {1} 가 서로 다른 계정으로 로그인돼 있습니다. 한쪽을 다른 쪽 계정으로 다시 로그인해 주세요.", other, HERE);
    case "serve_failed":
      return t("집 PC 에서 문을 여는 데 실패했습니다. [다시 시도] 를 눌러 주세요.");
    case "pc_unknown":
      return t("집 PC 에 닿지 못했습니다. 집에서(같은 와이파이) 집 PC 손자리가 켜져 있을 때 해 주세요.");
    default:
      return "";
  }
}

function stepErrorText(error: string): string {
  if (error === "not_installed") return t("Tailscale 이 아직 없습니다.");
  if (error === "no_login_page") return t("로그인 페이지를 열지 못했습니다. Tailscale 앱에서 직접 로그인해 주세요.");
  if (error === "turn_on_failed") return t("켜지 못했습니다. Tailscale 앱에서 켜 주세요.");
  return t("하지 못했습니다. 잠시 뒤 다시 눌러 주세요.");
}

/** 한 기기 칸의 한 줄 — ✓ · 지금 할 차례(단추) · 그쪽 차례 · 아직. */
function SideCell({ side, step, mine, turn, busy, onStep }: {
  side: OutsideSide | null;
  step: 0 | 1;
  mine: boolean;
  turn: "" | "install" | "sign_in" | "turn_on";
  busy: string;
  onStep: (step: OutsideStepName) => void;
}) {
  const done = step === 0 ? Boolean(side?.installed) : Boolean(side?.signed_in);
  if (done) return <span className="outside-cell is-done"><Check size={12} aria-hidden /> {step === 0 ? t("설치됨") : t("로그인됨")}</span>;
  if (!turn) return <span className="outside-cell is-wait" aria-label={t("아직")}>·</span>;
  if (!mine) return <span className="outside-cell is-theirs">{t("그쪽 차례")}</span>;
  const name: OutsideStepName = turn === "install" ? "install" : turn === "turn_on" ? "turn_on" : "login";
  const label = turn === "install" ? t("설치 열기") : turn === "turn_on" ? t("켜기") : t("로그인");
  return (
    <button type="button" className="place-act is-primary outside-cell-btn" disabled={busy !== ""} onClick={() => onStep(name)}>
      {busy === name && <Loader2 size={11} className="spin" aria-hidden />}{label}
    </button>
  );
}

export function OutsideChecklist({ api, status, onChanged }: {
  api: SetupApi | null;
  status: OutsideStatus;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const mine = status.role;
  const order = status.stage === "install" ? 0 : status.stage === "login" ? 1 : 2;

  async function step(name: OutsideStepName) {
    if (!api?.outsideStep) return;
    setBusy(name); setError("");
    try {
      const done = await api.outsideStep(name);
      if (!done.ok) setError(stepErrorText(done.error || ""));
      else if (done.url) await openExternalUrl(done.url);
    } catch {
      setError(stepErrorText(""));
    } finally {
      setBusy("");
      onChanged();
    }
  }

  const turnOf = (who: "mac" | "pc", row: 0 | 1): "" | "install" | "sign_in" | "turn_on" => {
    if (row !== order) return "";
    if (status.reason === `not_installed_${who}`) return "install";
    if (status.reason === `sign_in_${who}`) return "sign_in";
    if (status.reason === `turn_on_${who}`) return "turn_on";
    return "";
  };
  const macName = mine === "mac" ? "Mac" : status.other_name || "Mac";
  const pcName = mine === "pc" ? "PC" : status.other_name || t("집 PC");
  const shared: [string, number][] = [[t("같은 계정인지"), 2], [t("집 PC 문 열기"), 3], [t("밖에서 이어지나"), 4]];
  const sharedAt = { same_account: 2, door: 3, reach: 4, done: 5 } as Record<string, number>;
  const now = sharedAt[status.stage] ?? 0;
  const why = reasonText(status);
  const stepLabels = [t("Tailscale 설치"), t("로그인")];

  return (
    <div className="outside" aria-live="polite">
      <div className="outside-head">
        <b>Outside home</b>
        <small>{t("두 기기 모두 자동 확인")}</small>
      </div>
      <div className="outside-grid">
        <span />
        <span className="outside-col">{macName}</span>
        <span className="outside-col">{pcName}</span>
        {stepLabels.map((label, row) => (
          <div key={label} className={`outside-row${row === order ? " is-now" : ""}`}>
            <span className="outside-step">{row === 0 ? "①" : "②"} {label}</span>
            <SideCell side={status.mac} step={row as 0 | 1} mine={mine === "mac"} turn={turnOf("mac", row as 0 | 1)} busy={busy} onStep={(n) => void step(n)} />
            <SideCell side={status.pc} step={row as 0 | 1} mine={mine === "pc"} turn={turnOf("pc", row as 0 | 1)} busy={busy} onStep={(n) => void step(n)} />
          </div>
        ))}
      </div>
      <ol className="outside-shared">
        {shared.map(([label, at]) => (
          <li key={label} className={now > at ? "is-done" : now === at ? "is-now" : ""}>
            <span>{at === 2 ? "③" : at === 3 ? "④" : "⑤"} {label}</span>
            {now > at ? <Check size={12} aria-hidden />
              : now === at && !status.reason ? <Loader2 size={11} className="spin" aria-hidden /> : <i aria-hidden>·</i>}
          </li>
        ))}
      </ol>
      {why && <p className="outside-why">{why}</p>}
      {status.reason === "different_account" && (
        <button type="button" className="place-act is-primary" disabled={busy !== ""} onClick={() => void step("switch_account")}>
          {busy === "switch_account" && <Loader2 size={11} className="spin" aria-hidden />}
          {t("이 {0} 를 다른 계정으로 다시 로그인", HERE)}
        </button>
      )}
      {status.reason === "serve_failed" && (
        <button type="button" className="place-act is-primary" disabled={busy !== ""} onClick={() => void step("recheck")}>{t("다시 시도")}</button>
      )}
      {mine === "pc" && status.stage === "door" && (
        <p className="place-note">{t("윈도우가 「액세스를 허용하시겠습니까?」 를 물으면 [허용](개인 네트워크) 을 눌러 주세요.")}</p>
      )}
      {error && <p className="settings-error">{error}</p>}
    </div>
  );
}

function DoneLine() {
  return (
    <p className="outside-done"><Check size={12} aria-hidden /> Outside home · <span>{t("카페나 회사에서도 이 PC 를 씁니다.")}</span></p>
  );
}

/** 맥(자식): 짝짓기 뒤 권하기 → 체크 목록 → 끝난 한 줄. 「나중에」면 작은 한 줄로 남고 다시 조르지 않는다. */
export function OutsideHomeMac({ api }: { api: SetupApi | null }) {
  const { status, load } = useOutside(api, (now) => Boolean(now?.started) && now?.stage !== "done");
  const [busy, setBusy] = useState(false);
  if (!api?.outsideStatus || !status || status.role !== "mac") return null;

  const choose = async (name: "start" | "later") => {
    setBusy(true);
    try {
      await api.outsideStep?.(name);
    } finally {
      setBusy(false);
      void load();
    }
  };

  if (status.stage === "done") return <DoneLine />;
  if (status.offer) {
    return (
      <div className="outside outside-offer">
        <b>{t("집 밖에서도 이 PC 를 쓰시겠어요?")}</b>
        <p>{t("지금 집에 계실 때 하면 2~3분이면 끝납니다. 무료 프로그램 Tailscale 을 두 기기에 깔고 같은 계정으로 로그인하면 됩니다.")}</p>
        <div className="place-link-actions">
          <button type="button" className="place-act is-primary" disabled={busy} onClick={() => void choose("start")}>{t("지금 하기")}</button>
          <button type="button" className="place-act" disabled={busy} onClick={() => void choose("later")}>{t("나중에")}</button>
        </div>
      </div>
    );
  }
  if (status.later && !status.started) {
    return (
      <p className="outside-off">
        Outside home: Off
        <button type="button" className="place-forget" disabled={busy} onClick={() => void choose("start")}>{t("설정하기")}</button>
      </p>
    );
  }
  return <OutsideChecklist api={api} status={status} onChanged={() => void load()} />;
}

/** 집 PC(부모): 맥이 체크 목록을 시작했을 때만 같은 목록을 띄운다. */
export function OutsideHomePc({ api }: { api: SetupApi | null }) {
  const { status, load } = useOutside(api, (now) => now?.stage !== "done");
  if (!api?.outsideStatus || !status || status.role !== "pc" || status.stage === "idle") return null;
  if (status.stage === "done") return <DoneLine />;
  return <OutsideChecklist api={api} status={status} onChanged={() => void load()} />;
}
