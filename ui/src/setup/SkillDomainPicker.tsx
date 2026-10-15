/**
 * 「주로 무엇에 쓰시나요」 — 분야 버튼 (W4). 첫 실행 마법사와 설정 > 스킬이 같은 부품을 쓴다.
 *
 * 누르면 **바로 켜지 않는다.** 「이 스킬들로 세팅하겠습니다」 목록을 먼저 보여 주고, 한 번 더 눌러야 저장한다 —
 * 무엇이 켜지는지 모르고 켜는 것은 켠 척이다.
 *
 * 분야는 트리거가 아니라 **후보 범위**다. 그래서 문구도 「이 분야의 요청에 맞는 스킬을 골라 붙입니다」라고 말한다 —
 * 「이제 마케팅을 잘합니다」 같은 약속을 하지 않는다.
 */
import { t } from "../i18n";
import { Check, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SkillDomainsView } from "../types";

export function SkillDomainPicker(props: {
  load: () => Promise<SkillDomainsView>;
  apply: (domains: string[]) => Promise<SkillDomainsView>;
  compact?: boolean;
  onApplied?: (view: SkillDomainsView) => void;
}) {
  const [view, setView] = useState<SkillDomainsView | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  // 부르는 쪽이 매 렌더마다 새 함수를 넘겨도 한 번만 읽는다(안 그러면 저장 뒤 부모가 다시 그릴 때마다 다시 읽는다).
  const loadRef = useRef(props.load);

  useEffect(() => {
    let alive = true;
    loadRef.current()
      .then((next) => {
        if (!alive) return;
        setView(next);
        setPicked(next.selected);
      })
      .catch((reason) => alive && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      alive = false;
    };
  }, []);

  const chosen = useMemo(() => {
    if (!view) return [];
    const names = new Map<string, string[]>();
    for (const row of view.domains) {
      if (!picked.includes(row.id)) continue;
      for (const skill of row.skills) names.set(skill.name, skill.triggers ?? []);
    }
    return [...names.entries()].map(([name, triggers]) => ({ name, triggers }));
  }, [view, picked]);

  const dirty = view ? [...picked].sort().join(",") !== [...view.selected].sort().join(",") : false;

  const toggle = (id: string) => {
    setSaved(false);
    setPicked((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await props.apply(picked);
      setView(next);
      setPicked(next.selected);
      setSaved(true);
      props.onApplied?.(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (error && !view) return <p className="skill-domain-error" role="alert">{t("스킬 목록을 가져오지 못했습니다:")} {error}</p>;
  if (!view) return <p className="skill-domain-note"><Loader2 size={13} className="spin" /> {t("스킬 목록을 가져오는 중입니다")}</p>;

  return (
    <div className={`skill-domains${props.compact ? " is-compact" : ""}`}>
      <div className="skill-domain-grid" role="group" aria-label={t("주로 쓰는 분야")}>
        {view.domains.map((row) => {
          const on = picked.includes(row.id);
          return (
            <button key={row.id} type="button" className={`skill-domain${on ? " is-on" : ""}`} aria-pressed={on}
              onClick={() => toggle(row.id)}>
              <span className="skill-domain-head">
                <b>{row.label}</b>
                {on && <Check size={14} aria-hidden="true" />}
              </span>
              <span className="skill-domain-blurb">{row.blurb}</span>
              <span className="skill-domain-count">{t("스킬")} {row.skills.length}{t("개")}</span>
            </button>
          );
        })}
      </div>

      <div className="skill-domain-plan" aria-live="polite">
        {picked.length === 0 ? (
          <p className="skill-domain-note">
            {t("분야를 고르지 않으면 스킬")} {view.total_served}{t("개 전부가 후보입니다. 고르면 그 분야의 요청에 맞는 것만 골라 붙입니다.")}
          </p>
        ) : (
          <>
            <p className="skill-domain-note">{t("이 스킬")} {chosen.length}{t("개로 세팅하겠습니다. 요청에 맞는 것이 있을 때만 붙습니다.")}</p>
            <ul className="skill-domain-list">
              {chosen.map((skill) => (
                <li key={skill.name}>
                  <code>{skill.name}</code>
                  <span>{skill.triggers.length ? t("「{0}」 같은 요청에 붙습니다", skill.triggers.join("」「")) : t("요청 낱말로는 안 붙습니다 — 이름으로 지목하면 씁니다")}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="skill-domain-actions">
          <button type="button" className="setup-btn-go" disabled={busy || (!dirty && view.route_enabled === picked.length > 0)}
            onClick={() => void save()}>
            {busy ? t("저장하는 중…") : picked.length ? t("이대로 세팅하기") : t("분야 없이 쓰기")}
          </button>
          {saved && !dirty && <span className="skill-domain-saved">{t("저장했습니다")}{view.route_enabled ? t(" · 스킬 붙이기 켜짐") : ""}</span>}
          {error && <span className="skill-domain-error" role="alert">{error}</span>}
        </div>
      </div>
    </div>
  );
}
