import { Check, CircleDot, Loader2, X } from "lucide-react";
import { lang, t } from "../i18n";
import { stepSentence, type LearnState, type SlashItem } from "../recipeLearn";

/**
 * 「배우는 중」 칸 (2026-10-28 · `/레시피`). 손자리 크롬에서 사람이 해 보이는 동안 **적힌 걸음이 하나씩 쌓이고**, 저장 전 「한 번 해 보기」가
 * 도는 동안은 걸음마다 맞음 · 틀림이 쌓인다. 입력한 글은 보이지 않는다(칸 이름과 곳만) — 백엔드가 애초에 안 보낸다.
 * 끝내는 단추는 손자리 크롬의 빨간 띠에도 같은 것이 있다.
 */
export function RecipeLearnPanel({ state, onDone, onCancel }: { state: LearnState; onDone: () => void; onCancel: () => void }) {
  if (state.phase === "idle") return null;
  const language = lang();
  if (state.phase === "replaying") {
    const finished = state.replay.filter((row) => row.state !== "run").length;
    return (
      <section className="recipe-learn is-replay" role="status" aria-live="polite" aria-label={t("한 번 해 보는 중")}>
        <header>
          <Loader2 size={14} className="spin" aria-hidden />
          <strong>{t("한 번 해 보는 중")}</strong>
          <span>{state.total ? `${finished}/${state.total}` : ""}</span>
        </header>
        <ol>
          {state.replay.map((row) => (
            <li key={row.n} className={`is-${row.state}`}>
              <span className="recipe-learn-mark" aria-hidden>
                {row.state === "ok" ? <Check size={13} /> : row.state === "bad" ? <X size={13} /> : <Loader2 size={13} className="spin" />}
              </span>
              <span>{row.text}{row.note ? <em> — {row.note}</em> : null}</span>
            </li>
          ))}
        </ol>
      </section>
    );
  }
  return (
    <section className="recipe-learn" role="status" aria-live="polite" aria-label={t("배우는 중")}>
      <header>
        <CircleDot size={14} aria-hidden />
        <strong>{t("배우는 중")}</strong>
        {state.label ? <span>{state.label}</span> : null}
      </header>
      <p className="recipe-learn-hint">{t("앞으로 나온 손자리 크롬에서 한 번 해 보여 주세요. 누르거나 칠 때마다 아래에 쌓입니다.")}</p>
      {state.steps.length === 0 ? (
        <p className="recipe-learn-empty">{t("아직 적힌 걸음이 없습니다")}</p>
      ) : (
        <ol>
          {state.steps.map((step) => (
            <li key={step.n}>
              <span className="recipe-learn-mark" aria-hidden>{step.n}</span>
              <span>{stepSentence(step, language)}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="recipe-learn-actions">
        <button type="button" className="is-primary" onClick={onDone}>{t("다 했어")}</button>
        <button type="button" onClick={onCancel}>{t("취소")}</button>
      </div>
    </section>
  );
}

/** 입력창에 `/` 를 치면 뜨는 작은 명령 목록. 고르는 키는 입력창이 처리하고(`slashKey`), 여기는 그리기만 한다. */
export function SlashMenu({ items, index, onPick }: { items: SlashItem[]; index: number; onPick: (item: SlashItem) => void }) {
  if (!items.length) return null;
  return (
    <ul className="slash-menu" role="listbox" aria-label={t("명령")}>
      {items.map((item, position) => (
        <li key={item.command} role="option" aria-selected={position === index}>
          <button type="button" className={position === index ? "is-on" : ""} onMouseDown={(event) => { event.preventDefault(); onPick(item); }}>
            <code>{item.command}</code>
            <span>{item.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
