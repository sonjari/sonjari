/**
 * 설정 › 나에 대한 지침 (2026-10-18).
 *
 * ★ 매 턴 실리는 프로필 파일(`JARVIS_PROFILE.md`)에 화면이 없었다 — 일반 사용자는 쓸 길이 없었고, 개발자는 고쳐도 다시 켜야 먹었다.
 *   이제 파일 **하나**가 진짜이고, 이 칸은 그 위의 껍데기 셋이다:
 *
 *     3분 카드(고르기 · 짧은 칸) → 같은 파일의 카드 칸만 고친다
 *     길이 자(창의 N%)          → 이 글이 매 대화에 먹는 자리
 *     파일 직접 고치기(개발자)    → 같은 파일 원문 · 「파일 열기」
 *
 *   저장은 다음 대화부터 쓰인다(백엔드가 파일이 바뀐 것을 다시 읽는다 — 다시 켤 필요 없음).
 */
import { t } from "../i18n";
import { ExternalLink, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { AboutMeCard, AboutMeMeterLine, aboutMeErrorText } from "../setup/AboutMeCard";
import type { AboutMeView, SetupApi } from "../setup/setupApi";
import "../setup/aboutMe.css";

function reasonText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export function AboutMeSection({ api }: { api: SetupApi | null }) {
  const [view, setView] = useState<AboutMeView | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  // 카드를 저장하면 카드 칸이 바뀐 새 글로 다시 그린다 — 열쇠를 바꿔 카드도 새 답으로 다시 읽게 한다.
  const [cardKey, setCardKey] = useState(0);

  const adopt = useCallback((next: AboutMeView) => {
    setView(next);
    setDraft(next.content_raw);
  }, []);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.aboutMe().then((next) => { if (alive) adopt(next); }).catch((reason) => { if (alive) setError(reasonText(reason)); });
    return () => { alive = false; };
  }, [api, adopt]);

  if (!api || (!view && !error)) {
    return <div className="settings-block"><p className="settings-note"><Loader2 size={14} className="spin" /> {t("나에 대한 지침을 읽는 중입니다")}</p></div>;
  }

  const saveRaw = async () => {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api.aboutMeSave(draft);
      if (!result.ok) {
        setError(aboutMeErrorText(result));
        return;
      }
      adopt(result);
      setCardKey((key) => key + 1);
      setMessage(t("저장했습니다 · 다음 대화부터 씁니다"));
    } catch (reason) {
      setError(reasonText(reason));
    } finally {
      setBusy(false);
    }
  };

  const openFile = async () => {
    setError("");
    try {
      const result = await api.aboutMeOpen();
      if (!result.ok) setError(t("파일을 열지 못했습니다: {0}", result.error ?? "?"));
      else if (view && !view.exists) adopt(await api.aboutMe());
    } catch (reason) {
      setError(reasonText(reason));
    }
  };

  const max = view?.max_chars ?? 0;
  const length = draft.trim().length;
  const dirty = view !== null && draft !== view.content_raw;

  return (
    <div className="settings-block aboutme-section" data-testid="aboutme-section">
      <p className="settings-note">
        {t("Sonjari가 매 대화에 읽는 「나에 대해」 글입니다. 아래 카드로 채우거나 파일을 직접 고칠 수 있습니다 — 둘 다 같은 파일 하나를 고칩니다.")}
      </p>

      <h3>{t("3분 카드")}</h3>
      <AboutMeCard key={cardKey} api={api} onSaved={(next) => { adopt(next); setMessage(""); }} />

      <h3>{t("길이")}</h3>
      {view && <AboutMeMeterLine meter={view} chars={view.chars} maxChars={max} />}
      {view?.truncated && (
        <p className="settings-error" role="alert">{t("파일이 {0}자를 넘어 뒤쪽이 잘린 채 실리고 있습니다. 줄을 덜어 내 주세요.", max)}</p>
      )}
      <p className="settings-note">{t("다른 AI 도구의 지침은 「지침 가져오기」에서 줄을 골라 여기에 더할 수 있습니다.")}</p>

      <h3>{t("파일 직접 고치기")}</h3>
      <details className="aboutme-raw" open={Boolean(view?.content_raw) && !view?.has_card}>
        <summary>{t("개발자용 — 같은 파일의 원문")}</summary>
        {view && <p className="settings-path"><code>{view.path}</code></p>}
        <p className="settings-note">
          {t("꺾쇠 주석(<!-- … -->) 안의 글은 모델에게 가지 않습니다. 카드가 쓰는 칸(sonjari:card)은 카드를 다시 저장하면 바뀝니다.")}
        </p>
        <textarea aria-label={t("나에 대한 지침 원문")} value={draft} spellCheck={false}
          onChange={(event) => { setDraft(event.target.value); setMessage(""); }} />
        <div className="aboutme-actions">
          <span className={`aboutme-count${length > max ? " is-over" : ""}`}>{t("{0}자 / {1}자", length, max)}</span>
          <button type="button" className="setup-btn-go" disabled={busy || !dirty || length > max} onClick={() => void saveRaw()}>
            {busy ? t("저장하는 중…") : t("저장")}
          </button>
          <button type="button" className="setup-btn-quiet" onClick={() => void openFile()}>
            {t("파일 열기")} <ExternalLink size={13} aria-hidden="true" />
          </button>
          {message && <span className="aboutme-saved" role="status">{message}</span>}
        </div>
      </details>
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}
