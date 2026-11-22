import { t } from "../i18n";

/**
 * 처음 보는 종류의 일에서 모델이 쓸 도구와 지침을 읽는 동안의 막대 (2026-11-18 대표 「모델 올릴 때처럼 화면에」).
 *
 * 모델 올리기 막대(`ModelLoadLine`)와 같은 모양 · 같은 원칙이다 — **시간으로 채우지 않는다.** 막대는 백엔드가 이 기기 모델 서버
 * 기록에서 읽은 실제 진행률(`prefill_fraction`)만 그린다. 글은 백엔드가 만든 한 줄(`first_token_wait.wait_message`)을 나눠 쓴다:
 * 「쓸 도구와 지침을 읽는 중 · 62% · 30초쯤 남음 · 처음 한 번만 걸려요」 → 제목 · 남은 시간 · 아래 한 줄.
 * 디자인 검토(11-18): 토큰 수 · 경과 초 · 퍼센트 숫자는 화면에서 뺐다 — 막대가 진행을, 「남음」이 시간을 말한다.
 */
export type Prefill = { fraction: number; message: string };

export function splitPrefillMessage(message: string): { title: string; left: string; note: string } {
  const parts = message.split(" · ").map((part) => part.trim()).filter(Boolean);
  const title = parts[0] ?? "";
  const left = parts.find((part) => part.endsWith("남음") || part.endsWith("left")) ?? "";
  const tail = parts.length > 1 ? parts[parts.length - 1] : "";
  const isNumber = /%$|초째$|남음$|left$|s$/.test(tail);
  return { title, left, note: tail && !isNumber && tail !== title ? tail : "" };
}

export function PrefillLine({ prefill }: { prefill: Prefill }) {
  const fraction = Math.max(0, Math.min(1, prefill.fraction));
  const { title, left, note } = splitPrefillMessage(prefill.message);
  return (
    <div className="workspace-load" role="progressbar" aria-label={title || t("쓸 도구와 지침을 읽는 중")}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction * 100)}>
      <p>
        {title || t("쓸 도구와 지침을 읽는 중")}
        {left && <span className="workspace-load-detail num">{left}</span>}
      </p>
      <div className="workspace-load-track">
        <span style={{ width: `${Math.max(2, fraction * 100)}%` }} />
      </div>
      {note && <p className="workspace-load-note">{note}</p>}
    </div>
  );
}
