import { t } from "../i18n";
import { Send, X } from "lucide-react";
import { useEffect, useState } from "react";
import "./problemReport.css";

/** 백엔드 `/v1/report/preview` · `/v1/report/send` (problem_report.py). */
export interface ProblemReportApi {
  reportPreview(jobId?: string): Promise<{ id: string; text: string; to: string }>;
  reportSend(id: string, note: string, consent: boolean): Promise<{ ok: boolean; id?: string; error?: string }>;
}

const ERRORS: Record<string, string> = {
  consent_required: t("보내기 전에 동의해 주셔야 합니다."),
  preview_expired: t("미리보기가 오래됐습니다. 창을 닫고 다시 열어 주세요."),
  http_429: t("짧은 시간에 너무 많이 보냈습니다. 잠시 뒤에 다시 보내 주세요."),
  http_413: t("보낼 내용이 너무 큽니다."),
};

/**
 * 「문제 보내기」(2026-09-29, 베타 전 필수). **보낼 내용을 그대로 보여 주고, 동의를 받은 뒤, 보여 준 그대로** 보낸다.
 * 가림(경로·메일·전화·긴 토큰)은 백엔드가 이미 했다 — 그래도 사람이 눈으로 본 뒤에만 나간다.
 */
export function ProblemReportDialog({ api, jobId, onClose }: { api: ProblemReportApi | null; jobId?: string; onClose: () => void }) {
  const [preview, setPreview] = useState<{ id: string; text: string; to: string } | null>(null);
  const [note, setNote] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sentId, setSentId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!api) { setError(t("Sonjari 백엔드에 연결되지 않았습니다.")); return; }
    api.reportPreview(jobId)
      .then((value) => { if (alive) setPreview(value); })
      .catch(() => { if (alive) setError(t("보낼 내용을 만들지 못했습니다. 잠시 뒤 다시 열어 주세요.")); });
    return () => { alive = false; };
  }, [api, jobId]);

  const send = async () => {
    if (!api || !preview || !consent) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.reportSend(preview.id, note, consent);
      if (result.ok) setSentId(result.id || "");
      else setError(ERRORS[result.error ?? ""] ?? t("보내지 못했습니다({0}). 인터넷 연결을 확인해 주세요.", result.error ?? t("알 수 없음")));
    } catch {
      setError(t("보내지 못했습니다. 인터넷 연결을 확인해 주세요."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-veil report-veil" role="dialog" aria-modal="true" aria-label={t("문제 보내기")} onClick={onClose}>
      <section className="report-dialog" onClick={(event) => event.stopPropagation()}>
        <header>
          <strong>{t("문제 보내기")}</strong>
          <button type="button" className="settings-close report-close" onClick={onClose} aria-label={t("닫기")}><X size={16} /></button>
        </header>
        {sentId !== null ? (
          <div className="report-done" role="status">
            <p>{t("보냈습니다. 고맙습니다.")}</p>
            {sentId && <small>{t("접수 번호")} {sentId}</small>}
            <button type="button" className="report-send" onClick={onClose}>{t("닫기")}</button>
          </div>
        ) : (
          <>
            <p className="report-lead">
              {t("아래 내용이")} <b>{t("그대로")}</b> {t("Sonjari 개발팀에 보내집니다")}{preview ? ` (${preview.to})` : ""}{t(". 사용자 폴더 경로·메일·전화번호·긴 키는 가렸지만, 더 빼고 싶은 것이 있으면 보내지 마세요.")}
            </p>
            <pre className="report-preview" aria-label={t("보낼 내용")}>{preview ? preview.text : error ? "" : t("만드는 중…")}</pre>
            <label className="report-note">
              {t("무엇이 이상했나요? (선택)")}
              <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} maxLength={2000}
                placeholder={t("예: 새로고침했는데 제품 화면이 하얗게 떠요")} />
              {/* 코덱스 교차 검사(09-29): 메모는 보낼 때 가려져서 적은 그대로 나가지 않는다 — 그 사실을 말한다. */}
              <small>{t("적은 글도 보낼 때 같은 규칙으로 가립니다(사용자 폴더·메일·전화번호·비밀번호 값).")}</small>
            </label>
            <label className="report-consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} disabled={!preview} />
              {t("위 내용과 적은 글을 Sonjari 개발팀에 보내는 데 동의합니다.")}
            </label>
            {error && <p className="report-error" role="alert">{error}</p>}
            <button type="button" className="report-send" disabled={!preview || !consent || busy} onClick={() => void send()}>
              <Send size={14} /> {busy ? t("보내는 중…") : t("보내기")}
            </button>
          </>
        )}
      </section>
    </div>
  );
}
