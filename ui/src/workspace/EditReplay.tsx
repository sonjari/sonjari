import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";

/**
 * 방금 무엇을 바꿨는지 **되짚어** 보여 준다.
 *
 * ★ 생중계가 아니다. 사용자가 "쓰는 건 토큰이 있으니 커서처럼 보여줄 수 있지
 * 않나"라고 하셨고, 확인해 보니 아니었다 — Ollama 는 tool_calls 를 통째로 한 번에
 * 주고 파일 내용은 도구 **인자** 안에 있다. 토큰으로 흘러오지 않는다.
 *
 * 그래서 흘러오는 척하지 않는다. 이름부터 「방금 이렇게 바꿨습니다」다. 되짚기라고
 * 말하고 되짚으면 그건 사실이고, 생중계라고 말하고 흉내 내면 그건 거짓이다.
 * 이 저장소가 하루 종일 잡은 병이 후자다.
 *
 * 그래도 값이 있다: 바뀐 줄이 순서대로 그려지면 **무엇이 달라졌는지가 눈에 남는다.**
 * 덩어리로 던지면 읽히지 않고, 읽히지 않는 증거는 없는 것과 같다.
 */
export function EditReplay({
  preview,
  path,
}: {
  preview: {
    start_line?: number;
    removed?: string[];
    added?: string[];
    truncated?: boolean;
    added_count?: number;
  };
  path?: string;
}) {
  const added = preview.added ?? [];
  const removed = preview.removed ?? [];
  // 0 = 몇 번째 줄인지 모른다(앱 안 Claude Agent 가 고친 자리를 파일에서 못 찾음) — 번호를 지어내지 않고 비운다.
  const startLine = preview.start_line ?? 1;

  // 움직임을 줄여 달라고 한 사람에게는 처음부터 다 그려 둔다.
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const [shown, setShown] = useState(reduced ? added.length : 0);
  const timer = useRef<number>();

  useEffect(() => {
    if (reduced || shown >= added.length) return;
    // 한 줄씩. 글자 단위로 치면 진짜 타이핑처럼 보여서 다시 거짓이 된다 —
    // 줄 단위는 "되짚는 중"으로 읽힌다.
    timer.current = window.setTimeout(() => setShown((n) => n + 1), 55);
    return () => window.clearTimeout(timer.current);
  }, [shown, added.length, reduced]);

  if (!added.length && !removed.length) return null;
  const done = shown >= added.length;

  return (
    <div className="edit-replay">
      <div className="edit-replay-head">
        <span className="edit-replay-title">{t("방금 이렇게 바꿨습니다")}</span>
        {path && <code className="edit-replay-path">{path.split(/[\/]/).pop()}</code>}
        <span className="edit-replay-count">
          −{removed.length} +{preview.added_count ?? added.length}
        </span>
        {done && added.length > 1 && (
          <button type="button" onClick={() => setShown(0)} title={t("다시 보기")}>
            <RotateCcw size={12} /> {t("다시")}
          </button>
        )}
      </div>
      <pre className="edit-replay-body">
        {removed.map((line, index) => (
          <span key={`r${index}`} className="edit-line removed">
            <em>{startLine > 0 ? startLine + index : ""}</em>
            <span>{line || " "}</span>
          </span>
        ))}
        {added.slice(0, shown).map((line, index) => (
          <span key={`a${index}`} className="edit-line added">
            <em>{startLine > 0 ? startLine + index : ""}</em>
            <span>{line || " "}</span>
            {!done && index === shown - 1 && <i className="edit-caret" />}
          </span>
        ))}
      </pre>
      {preview.truncated && (
        <p className="edit-replay-more">
          {t("바뀐 줄이 더 있습니다 — 여기 보이는 것은 앞부분입니다.")}
        </p>
      )}
    </div>
  );
}
