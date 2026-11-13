/**
 * 설정 › 연결 맨 위 — 클로드가 손자리의 옛 연결을 쓰고 있을 때만 (2026-11-13 · 설계_MCP도구목록_자동갱신 5-1).
 *
 * 실측: 클로드 데스크톱 앱은 「도구 목록이 바뀌었다」 신호를 받아도 새로 고치지 않는다. 그래서 손자리를 업데이트하면
 * 클로드를 다시 켜야 새 기능이 보인다. 짐작하지 않으려고 연결 프로그램이 자기 판을 알리고, 본체가 「옛 판」을 가른다.
 * 단추는 기존 「닫고 · 잇고 · 다시 켜기」 대화상자를 연다 — 묻기 전에는 아무것도 끄지 않는다.
 */
import { t } from "../i18n";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import { ClaudeRestartDialog } from "../setup/ConnectPanel";
import type { SetupApi } from "../setup/setupApi";
import "./strata.css";

export function ClaudeFreshCard({ client, setupApi }: { client: Pick<JarvisClient, "claudeMcpFreshness">; setupApi: SetupApi | null }) {
  const [stale, setStale] = useState(false);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setStale((await client.claudeMcpFreshness()).stale);
    } catch {
      setStale(false);   // 못 물으면 띄우지 않는다 — 틀린 「다시 켜라」가 더 나쁘다
    }
  }, [client]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!stale) return null;
  return (
    <div className="claude-fresh" role="status">
      <p className="gh-now-title">{t("클로드가 손자리의 옛 연결을 쓰고 있습니다")}</p>
      <p className="settings-note">{t("손자리가 업데이트됐습니다. 클로드를 다시 켜야 새 기능이 보입니다.")}</p>
      {setupApi && (
        <button type="button" className="setup-btn-go" onClick={() => setOpen(true)}>
          <RefreshCw size={14} aria-hidden="true" /> {t("클로드 다시 켜기")}
        </button>
      )}
      {open && setupApi && (
        <ClaudeRestartDialog api={setupApi} doneLabel={t("닫기")} onClose={() => setOpen(false)}
          onDone={() => { setOpen(false); void load(); }} />
      )}
    </div>
  );
}
