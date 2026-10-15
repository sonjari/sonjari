import { t } from "./i18n";
import { Loader2, UserPlus, UserX, Users } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import type { JarvisClient } from "./backend";
import type { DiscoverPersonResult, PeopleStatus } from "./types";

/**
 * Who the office camera can recognise, and how to add somebody.
 *
 * "신규 인원 등록" does not ask the new person to come and stand in front of the
 * lens: it types a name, then the gimbal sweeps the room, and whoever it finds
 * that matches nobody on file gets registered under that name.
 *
 * Two things this deliberately does not do:
 *
 *  - It never says "등록했습니다" without the similarity score that decided it.
 *    Face recognition returning a name is a claim, and this project has already
 *    had a model announce an action it never took.
 *  - It does not show a bare spinner. The sweep physically turns a camera and
 *    stops to look at each position; it takes the best part of a minute, and a
 *    spinner with no explanation reads as a hang.
 */
export function PeoplePanel({ client }: { client: JarvisClient }) {
  const [status, setStatus] = useState<PeopleStatus | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<DiscoverPersonResult | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setStatus(await client.listPeople());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const discover = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const wanted = name.trim();
      if (!wanted || busy) return;
      setBusy(true);
      setError("");
      setOutcome(null);
      try {
        const result = await client.discoverPerson(wanted);
        setOutcome(result);
        if (result.registered) setName("");
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
      }
    },
    [busy, client, name, refresh],
  );

  const forget = useCallback(
    async (who: string) => {
      try {
        await client.forgetPerson(who);
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [client, refresh],
  );

  if (status && !status.enabled) return null;

  const modelsMissing = status ? status.models_present === false : false;

  return (
    <section className="people-panel">
      <header className="people-header">
        <Users size={15} />
        <span>{t("카메라가 아는 사람")}</span>
      </header>

      {modelsMissing ? (
        <p className="people-note people-warn">
          {t("얼굴 인식 모델이 없습니다 (")}{(status?.missing_models ?? []).join(", ")}).
        </p>
      ) : (
        <ul className="people-list">
          {(status?.registered ?? []).map((who) => (
            <li key={who}>
              <span>{who}</span>
              <button type="button" onClick={() => void forget(who)} title={t("{0} 등록 삭제", who)}>
                <UserX size={13} />
              </button>
            </li>
          ))}
          {status && status.registered.length === 0 ? (
            <li className="people-empty">{t("아직 등록된 사람이 없습니다")}</li>
          ) : null}
        </ul>
      )}

      <form className="people-add" onSubmit={discover}>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("새로 등록할 이름")}
          maxLength={40}
          disabled={busy || modelsMissing}
        />
        <button type="submit" disabled={busy || modelsMissing || !name.trim()}>
          {busy ? <Loader2 size={14} className="spin" /> : <UserPlus size={14} />}
          {busy ? t("찾는 중") : t("신규 인원 등록")}
        </button>
      </form>

      {busy ? (
        // Say what it is doing. The camera is physically turning and stopping
        // to look, which takes about a minute -- silence here reads as a hang.
        <p className="people-note">{t("카메라가 방을 둘러보는 중입니다. 1분쯤 걸립니다.")}</p>
      ) : null}

      {outcome ? <PeopleOutcome outcome={outcome} /> : null}
      {error ? <p className="people-note people-warn">{error}</p> : null}
    </section>
  );
}

function PeopleOutcome({ outcome }: { outcome: DiscoverPersonResult }) {
  if (outcome.registered) {
    return (
      <p className="people-note people-ok">
        {t("신규 인물 등록 완료:")} <strong>{outcome.name}</strong>
        <br />
        {t("기존 인원과 가장 닮은 정도")} {outcome.similarity_to_known?.toFixed(3)} {t("(기준")}{" "}
        {outcome.threshold?.toFixed(3)} {t("미만이면 새 인물) · 얼굴")} {outcome.embeddings}{t("장")}
      </p>
    );
  }
  if (outcome.reason === "several_unfamiliar_faces") {
    return (
      <p className="people-note people-warn">
        {t("모르는 얼굴이")} {outcome.count}{t("명 동시에 보입니다. 누구를 등록할지 알 수 없어 아무것도 저장하지 않았습니다. 한 명만 남기고 다시 시도해 주세요.")}
      </p>
    );
  }
  return (
    <p className="people-note">
      {t("방을 다 둘러봤지만 새로운 얼굴은 없었습니다 (확인한 위치")} {outcome.steps}{t("곳). 아무것도 등록하지 않았습니다.")}
    </p>
  );
}
