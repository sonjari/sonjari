/**
 * 「나에 대한 지침」 3분 카드 · 길이 자 · 가져온 줄 고르기 (2026-10-18).
 *
 * ★ 왜: 매 턴 실리는 프로필 파일(`JARVIS_PROFILE.md`)이 있었는데 화면이 없었고, 지침 가져오기는 가져온 글을 아무 데도 안 썼다.
 *   남들(OpenClaw · Hermes)은 「파일이 진짜, 화면은 껍데기」이고, ChatGPT 는 빈칸 옆에 「고르기」를 붙였다 — 빈칸은 잘 안 채운다
 *   (조사 `docs/사용자지침_스킬만들기_조사_1018.ko.md`). 그래서 질문 몇 개와 고르기 칩으로 채우고, 같은 파일을 개발자가 직접 고친다.
 *
 * ## 규율
 *
 * - 화면은 줄을 **만들지 않는다.** 답 → 줄은 백엔드 결정론 코드(`about_me.card_lines`) 한 곳이다. 화면이 따로 만들면 두 벌이 되고,
 *   미리보기와 저장된 글이 갈린다. 화면은 백엔드 미리보기를 그대로 보여 주고, 사람이 「이대로 저장」을 눌러야 쓴다.
 * - 무엇이 비밀인지도 백엔드가 정한다. 가져온 줄 중 비밀이 걷힌 줄은 고를 수 없게 그린다(백엔드도 한 번 더 막는다).
 * - 「부르는 이름」은 설정 › 일반의 그 값이다(파일에 따로 적지 않는다 — 값이 두 자리에 살면 갈린다).
 */
import { lang, t } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AboutMeAnswersInput,
  AboutMeCardPreview,
  AboutMeImportLines,
  AboutMeLength,
  AboutMeMeter,
  AboutMeTone,
  AboutMeView,
  SetupApi,
} from "./setupApi";
import "./aboutMe.css";

type Draft = Omit<AboutMeAnswersInput, "sites"> & { sites: string };

const EMPTY: Draft = { user_label: "", work_text: "", length: "", tone: "", sites: "", avoid_text: "" };

/** 백엔드 까닭 코드 → 사람 말. 무엇이 잘못됐고 어떻게 하면 되는지까지. */
export function aboutMeErrorText(result: { error?: string; chars?: number; max_chars?: number }): string {
  switch (result.error) {
    case "too_long":
      return t("「나에 대한 지침」은 {0}자까지입니다(지금 {1}자). 줄을 덜어 낸 뒤 다시 저장해 주세요.", result.max_chars ?? 0, result.chars ?? 0);
    case "answer_too_long":
      return t("답이 너무 깁니다. 조금 줄여 주세요.");
    case "bad_choice":
      return t("고를 수 없는 값입니다. 화면을 다시 열어 주세요.");
    case "secret_in_answer":
      return t("답에 키나 비밀번호처럼 보이는 글이 있어 저장하지 않았습니다.");
    case "user_label_rejected":
      return t("부르는 이름을 저장하지 못했습니다(20자까지).");
    case "nothing_to_add":
      return t("더할 수 있는 줄을 고르지 않았습니다.");
    case "not_found":
      return t("가져온 지침을 찾지 못했습니다. 목록을 새로 고쳐 주세요.");
    default:
      return result.error ? t("저장하지 못했습니다: {0}", result.error) : "";
  }
}

function reasonText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function toInput(draft: Draft): AboutMeAnswersInput {
  return { ...draft, sites: draft.sites };
}

function pctLabel(meter: AboutMeMeter): string {
  return meter.share_pct < 1 && meter.tokens > 0 ? "<1" : String(meter.share_pct);
}

/** 「창의 N%」 — 이 글이 매 대화에 실려 일할 자리를 얼마나 먹는지. 10% 를 넘으면 살짝 경고한다(막지는 않는다). */
export function AboutMeMeterLine({ meter, chars, maxChars, prefix }: {
  meter: AboutMeMeter;
  chars: number;
  maxChars: number;
  prefix?: string;
}) {
  const width = Math.min(100, Math.max(meter.tokens > 0 ? 2 : 0, meter.share * 100 / Math.max(meter.warn_share * 2, 0.0001)));
  return (
    <div className={`aboutme-meter${meter.warn ? " is-warn" : ""}`} data-testid="aboutme-meter">
      <span>
        {prefix ? `${prefix} ` : ""}
        {t("창의 {0}%", pctLabel(meter))}
        {" · "}
        {t("약 {0}토큰 · {1}자 / {2}자", meter.tokens, chars, maxChars)}
      </span>
      <span className="aboutme-meter-bar" aria-hidden="true"><span style={{ width: `${width}%` }} /></span>
      {meter.warn && (
        <p className="aboutme-meter-warn" role="status">
          {t("창의 {0}% 를 넘었습니다. 매 대화에 실려 일할 자리가 줄어듭니다 — 꼭 필요한 줄만 남기면 좋습니다.", Math.round(meter.warn_share * 100))}
        </p>
      )}
    </div>
  );
}

function Chips<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T | "";
  options: { id: T; text: string }[];
  onChange: (next: T | "") => void;
}) {
  return (
    <fieldset className="aboutme-q">
      <legend>{label}</legend>
      <div className="aboutme-chips" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button key={option.id} type="button" role="radio" aria-checked={value === option.id}
            className={`aboutme-chip${value === option.id ? " is-on" : ""}`}
            // 다시 누르면 고르기를 푼다 — 「상관없음」을 칸으로 하나 더 두지 않는다.
            onClick={() => onChange(value === option.id ? "" : option.id)}>
            {option.text}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * 3분 카드. `compact` 면 첫 실행용 세 질문(부르는 이름 · 답 길이 · 하는 일)만 보인다 — 나머지 답은 그대로 둔 채 저장한다.
 */
export function AboutMeCard({ api, compact = false, onSaved }: {
  api: SetupApi | null;
  compact?: boolean;
  onSaved?: (view: AboutMeView) => void;
}) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [preview, setPreview] = useState<AboutMeCardPreview | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.aboutMe()
      .then((view) => {
        if (!alive) return;
        const a = view.answers;
        setDraft({ user_label: a.user_label ?? "", work_text: a.work_text ?? "", length: a.length ?? "", tone: a.tone ?? "",
          sites: (a.sites ?? []).join(", "), avoid_text: a.avoid_text ?? "" });
        setLoaded(true);
      })
      .catch((reason) => { if (alive) setError(reasonText(reason)); });
    return () => { alive = false; };
  }, [api]);

  // 답이 바뀔 때마다 백엔드에 「이렇게 들어갑니다」를 묻는다. 늦게 온 옛 답은 버린다(번호표).
  useEffect(() => {
    if (!api || !loaded) return;
    const mine = ++seq.current;
    api.aboutMeCardPreview(toInput(draft), lang())
      .then((next) => {
        if (mine !== seq.current) return;
        setPreview(next);
        setError(next.ok ? "" : aboutMeErrorText(next));
      })
      .catch((reason) => { if (mine === seq.current) setError(reasonText(reason)); });
  }, [api, loaded, draft]);

  const change = useCallback((patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setSaved(false);
  }, []);

  const save = async () => {
    if (!api) return;
    setSaving(true);
    setError("");
    try {
      const result = await api.aboutMeCardSave(toInput(draft), lang());
      if (!result.ok) {
        setError(aboutMeErrorText(result));
        return;
      }
      setSaved(true);
      onSaved?.(result);
    } catch (reason) {
      setError(reasonText(reason));
    } finally {
      setSaving(false);
    }
  };

  if (!api) return null;
  const lengthOptions: { id: Exclude<AboutMeLength, "">; text: string }[] = [
    { id: "short", text: t("짧게") }, { id: "normal", text: t("보통") }, { id: "long", text: t("자세히") },
  ];
  const toneOptions: { id: Exclude<AboutMeTone, "">; text: string }[] = [
    { id: "casual", text: t("편하게") }, { id: "polite", text: t("정중하게") },
  ];

  return (
    <div className="aboutme" data-testid="aboutme-card">
      <div className="aboutme-q">
        <label htmlFor="aboutme-name">{t("부르는 이름")}</label>
        <input id="aboutme-name" type="text" maxLength={20} value={draft.user_label} disabled={!loaded}
          placeholder={t("예: 가람 님")} onChange={(event) => change({ user_label: event.target.value })} />
        <small>{t("설정 › 일반의 「부르는 이름」과 같은 값입니다. 비우면 호칭 없이 말합니다.")}</small>
      </div>
      <Chips label={t("답 길이")} value={draft.length} options={lengthOptions} onChange={(length) => change({ length })} />
      <div className="aboutme-q">
        <label htmlFor="aboutme-work">{t("하는 일")}</label>
        <input id="aboutme-work" type="text" maxLength={120} value={draft.work_text} disabled={!loaded}
          placeholder={t("예: 학원 운영, 쇼핑몰 마케팅")} onChange={(event) => change({ work_text: event.target.value })} />
      </div>
      {!compact && (
        <>
          <Chips label={t("말투")} value={draft.tone} options={toneOptions} onChange={(tone) => change({ tone })} />
          <div className="aboutme-q">
            <label htmlFor="aboutme-sites">{t("자주 쓰는 사이트")}</label>
            <input id="aboutme-sites" type="text" value={draft.sites} disabled={!loaded}
              placeholder={t("쉼표로 나눠 적기 — 예: 네이버, 사람인")} onChange={(event) => change({ sites: event.target.value })} />
          </div>
          <div className="aboutme-q">
            <label htmlFor="aboutme-avoid">{t("하지 말 것")}</label>
            <input id="aboutme-avoid" type="text" maxLength={200} value={draft.avoid_text} disabled={!loaded}
              placeholder={t("예: 영어로 답하지 말 것")} onChange={(event) => change({ avoid_text: event.target.value })} />
          </div>
        </>
      )}

      <section className="aboutme-preview" aria-live="polite" data-testid="aboutme-preview">
        <h4>{t("이렇게 들어갑니다")}</h4>
        {preview?.card_lines.length ? (
          <ul>{preview.card_lines.map((line) => <li key={line}>{line}</li>)}</ul>
        ) : (
          <p className="is-empty">{t("아직 들어갈 줄이 없습니다. 「보통」 길이는 기본이라 따로 적지 않습니다.")}</p>
        )}
      </section>
      {preview?.ok && (
        <AboutMeMeterLine meter={preview} chars={preview.chars} maxChars={preview.max_chars} prefix={t("저장하면")} />
      )}

      <div className="aboutme-actions">
        <button type="button" className="setup-btn-go" disabled={!loaded || saving || !preview?.ok || preview.fits === false}
          onClick={() => void save()}>
          {saving ? t("저장하는 중…") : t("이대로 저장")}
        </button>
        {saved && <span className="aboutme-saved" role="status">{t("저장했습니다 · 다음 대화부터 씁니다")}</span>}
      </div>
      {error && <p className="aboutme-error" role="alert">{error}</p>}
    </div>
  );
}

const LINE_REASON: Record<string, () => string> = {
  secret: () => t("비밀이 걷힌 줄 · 더할 수 없음"),
  already: () => t("이미 들어 있음"),
};

/**
 * 가져온 지침에서 **줄을 골라** 「나에 대한 지침」에 더한다. 가져온 글 자체는 답에 안 쓰인다 — 고른 줄만 쓰인다.
 * 빈 줄은 그리지 않는다(고를 것이 아니다). 비밀이 걷힌 줄 · 이미 들어 있는 줄은 상자를 끈다.
 */
export function ImportLinePicker({ api, importId }: { api: SetupApi | null; importId: number }) {
  const [data, setData] = useState<AboutMeImportLines | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!api) return;
    try {
      const next = await api.aboutMeImportLines(importId);
      setData(next);
      if (!next.ok) setError(aboutMeErrorText(next));
    } catch (reason) {
      setError(reasonText(reason));
    }
  }, [api, importId]);

  useEffect(() => {
    setPicked(new Set());
    setMessage("");
    setError("");
    void load();
  }, [load]);

  if (!api) return null;
  const toggle = (index: number) => setPicked((current) => {
    const next = new Set(current);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    return next;
  });

  const add = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.aboutMeAppendImport(importId, [...picked].sort((a, b) => a - b));
      if (!result.ok) {
        setError(aboutMeErrorText(result));
        return;
      }
      setMessage(t("{0}줄을 「나에 대한 지침」에 더했습니다 · 창의 {1}%", result.added ?? 0, pctLabel(result)));
      setPicked(new Set());
      await load();
    } catch (reason) {
      setError(reasonText(reason));
    } finally {
      setBusy(false);
    }
  };

  const shown = (data?.lines ?? []).filter((line) => line.reason !== "blank");
  return (
    <div className="aboutme-pick" data-testid="import-line-picker">
      <p className="aboutme-pick-note">
        {t("가져온 지침은 그대로는 답에 쓰이지 않습니다. 아래에서 고른 줄만 「나에 대한 지침」에 더해져 매 대화에 쓰입니다.")}
      </p>
      {data?.ok && (
        <ul className="aboutme-pick-list" aria-label={t("더할 줄 고르기")}>
          {shown.map((line) => (
            <li key={line.index} className={line.allowed ? "" : "is-off"}>
              <label>
                <input type="checkbox" disabled={!line.allowed || busy} checked={picked.has(line.index)}
                  onChange={() => toggle(line.index)} />
                <span>{line.raw}</span>
                {!line.allowed && LINE_REASON[line.reason] && <em>{LINE_REASON[line.reason]()}</em>}
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="aboutme-actions">
        <button type="button" className="setup-btn-go" disabled={busy || picked.size === 0} onClick={() => void add()}>
          {t("고른 {0}줄을 「나에 대한 지침」에 더하기", picked.size)}
        </button>
        {message && <span className="aboutme-saved" role="status">{message}</span>}
      </div>
      {error && <p className="aboutme-error" role="alert">{error}</p>}
    </div>
  );
}
