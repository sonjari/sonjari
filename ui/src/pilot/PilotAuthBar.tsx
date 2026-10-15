import { t } from "../i18n";
import { invoke } from "@tauri-apps/api/core";
import { CheckCircle2, KeyRound, Loader2, ShieldAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { PilotAuthStatus } from "../types";

export function PilotAuthBar({ enabled }: { enabled: boolean }) {
  const [status, setStatus] = useState<PilotAuthStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    if (!enabled) return;
    setStatus(await invoke<PilotAuthStatus>("pilot_auth_status"));
  };

  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason))); }, [enabled]);
  if (!enabled) return null;
  if (status?.ready && !error) return null;

  const choose = async () => {
    setBusy(true);
    setError("");
    try {
      setStatus(await invoke<PilotAuthStatus>("pilot_choose_api_key_file"));
    } catch (reason) {
      const message = String(reason);
      if (!message.includes("취소")) setError(message);
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setError("");
    try {
      setStatus(await invoke<PilotAuthStatus>("pilot_clear_api_key"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const ready = Boolean(status?.ready);
  return (
    <div className={`pilot-auth-bar ${ready ? "ready" : "needs-key"}`}>
      {busy ? <Loader2 size={15} className="spin" /> : ready ? <CheckCircle2 size={15} /> : <ShieldAlert size={15} />}
      <div>
        <strong>{ready ? t("Claude 연결됨") : t("Claude 연결이 필요합니다")}</strong>
        <span>{error || status?.message || t("상태를 확인하는 중입니다")}</span>
      </div>
      {status?.method === "api_key_file" && status.key_file_name && <code>{status.key_file_name}</code>}
      <button type="button" onClick={() => void choose()} disabled={busy}>
        <KeyRound size={14} /> {status?.method === "api_key_file" ? t("키 바꾸기") : t("API 키 파일 연결")}
      </button>
      {status?.method === "api_key_file" && (
        <button type="button" className="pilot-auth-clear" onClick={() => void clear()} disabled={busy} aria-label={t("API 키 연결 해제")}>
          <X size={14} />
        </button>
      )}
    </div>
  );
}
