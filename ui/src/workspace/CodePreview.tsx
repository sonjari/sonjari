import { t } from "../i18n";
import { ArrowRight, RotateCw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

/** 제품 화면은 사용자가 직접 지정한 로컬 개발 서버만 연다. */
export function localPreviewUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) return null;
    if (url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function CodePreview({ workspace, agentUrl, onFeedback }: {
  workspace: string;
  agentUrl?: string;
  onFeedback: (prompt: string) => void;
}) {
  const [input, setInput] = useState("");
  const [url, setUrl] = useState("");
  const [reload, setReload] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [manual, setManual] = useState(false);

  // 다른 저장소로 옮겼을 때 이전 제품 화면을 그 저장소의 결과처럼 보여 주지 않는다.
  useEffect(() => { setInput(""); setUrl(""); setFeedback(""); setError(""); setManual(false); }, [workspace]);

  useEffect(() => {
    const next = localPreviewUrl(agentUrl ?? "");
    if (!next || manual) return;
    setInput(next);
    setUrl(next);
  }, [agentUrl, manual]);

  const open = (event: FormEvent) => {
    event.preventDefault();
    const next = localPreviewUrl(input);
    if (!next) {
      setError(t("http://localhost:포트 또는 http://127.0.0.1:포트 주소를 입력해 주세요."));
      return;
    }
    setError("");
    setManual(true);
    setUrl(next);
    setReload((current) => current + 1);
  };

  const sendFeedback = (event: FormEvent) => {
    event.preventDefault();
    const note = feedback.trim();
    if (!url || !note) return;
    onFeedback(t("현재 저장소의 실행 화면 {0}에서 직접 확인했습니다. {1} 이 문제를 재현하고 원인을 고쳐줘. 수정 후 프로젝트 검사를 실행하고, 화면에서 다시 확인할 방법을 알려줘.", url, note));
    setFeedback("");
  };

  return (
    <section className="code-preview" aria-label={t("제품 화면")}>
      <div className="code-preview-intro">
        <strong>{t("제품을 눌러 확인하기")}</strong>
        <p>{t("Sonjari가 띄운 화면이 여기에 열립니다. 직접 연 로컬 화면도 눌러 보고, 발견한 문제를 다음 수정 요청으로 보낼 수 있습니다.")}</p>
      </div>
      <form className="code-preview-address" onSubmit={open}>
        <input
          aria-label={t("로컬 실행 화면 주소")}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="http://localhost:5173"
          spellCheck={false}
        />
        <button type="submit">{t("화면 열기")}</button>
      </form>
      {error && <p className="code-preview-error" role="alert">{error}</p>}
      {url ? (
        <>
          <div className="code-preview-frame-head">
            <span title={url}>{url}</span>
            <button type="button" onClick={() => setReload((current) => current + 1)} aria-label={t("제품 화면 새로고침")} title={t("새로고침")}><RotateCw size={14} /></button>
          </div>
          <iframe
            key={`${url}-${reload}`}
            className="code-preview-frame"
            src={url}
            title={t("로컬 제품 실행 화면")}
            sandbox="allow-scripts allow-forms allow-same-origin"
            referrerPolicy="no-referrer"
          />
          <form className="code-preview-feedback" onSubmit={sendFeedback}>
            <label htmlFor="code-preview-note">{t("써 보니 무엇이 이상했나요?")}</label>
            <textarea id="code-preview-note" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder={t("예: 저장 버튼을 눌러도 목록이 갱신되지 않아요")} rows={2} />
            <button type="submit" disabled={!feedback.trim()}>{t("수정 요청 작성")} <ArrowRight size={14} /></button>
          </form>
        </>
      ) : (
        <div className="code-preview-empty">
          <strong>{t("실행 화면을 기다리고 있습니다")}</strong>
          <p>{t("Sonjari가 페이지를 미리보기로 띄우거나, 실행 중인 개발 서버 주소를 넣으면 버튼과 흐름을 직접 확인할 수 있습니다.")}</p>
        </div>
      )}
    </section>
  );
}
