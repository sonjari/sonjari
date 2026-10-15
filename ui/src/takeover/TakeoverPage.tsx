/**
 * 이어받기 — 한도로 멈춘 클로드·코덱스 대화를 보고, 이어받고, 가지를 검토·버리는 곳 (전략안 §44).
 *
 * 기본 길은 대화다(「다 썼어」라고 말하면 자비스가 찾아 묻는다). 이 화면은 그 옆에서
 * **무엇이 멈춰 있고 자비스가 무엇을 하고 있는지 보이게** 하고, 가지를 버릴 수 있게 한다 —
 * 되돌릴 수 있어야 맡길 수 있다.
 *
 * 모양은 첫 실행 화면과 같다: 왼쪽 따뜻한 흑연(사람이 고르고 누르는 쪽), 오른쪽 찬 흑연(기록·가지).
 */
import { t } from "../i18n";
import { useCallback, useEffect, useMemo, useState } from "react";
import { loadBootstrap } from "../backend";
import "../setup/setup.css";
import "./takeover.css";
import { createTakeoverApi, type AcceptResult, type TakeoverApi, type TakeoverCard, type TakeoverRecord } from "./takeoverApi";

const STATUS_LABEL: Record<string, { text: string; tone: "quiet" | "ok" | "signal" }> = {
  offered: { text: t("물어봄"), tone: "quiet" },
  card_only: { text: t("이어서 할 지시문 만듦"), tone: "ok" },
  continuing: { text: t("가지에서 이어 작업 중"), tone: "signal" },
  review_pending: { text: t("검토 대기"), tone: "signal" },
  discarded: { text: t("가지 버림"), tone: "quiet" },
  dismissed: { text: t("안 하기로 함"), tone: "quiet" },
  expired: { text: t("지나감"), tone: "quiet" },
};

async function openApi(): Promise<TakeoverApi> {
  if (import.meta.env.DEV && new URLSearchParams(window.location.search).get("takeoverFixture")) {
    const fixtures = await import("./fixtureTakeoverApi");
    return fixtures.createFixtureTakeoverApi();
  }
  return createTakeoverApi(await loadBootstrap());
}

function stopText(card: TakeoverCard): string {
  const ago = card.stopped_minutes_ago === null ? "" : card.stopped_minutes_ago < 60
    ? t("{0}분 전", card.stopped_minutes_ago)
    : t("{0}시간 전", Math.round(card.stopped_minutes_ago / 60));
  const why = { rate_limit: t("사용량 한도로 멈춤"), api_error: t("오류로 멈춤"), aborted: t("도중에 끊김"), none: t("정상 종료") }[card.stop_kind];
  return [ago, why].filter(Boolean).join(" · ");
}

function resetText(card: TakeoverCard): string {
  if (!card.resets_at) return "";
  return t("한도 풀림 {0}", new Date(card.resets_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
}

export default function TakeoverPage() {
  const [api, setApi] = useState<TakeoverApi | null>(null);
  const [cards, setCards] = useState<TakeoverCard[] | null>(null);
  const [records, setRecords] = useState<TakeoverRecord[]>([]);
  const [picked, setPicked] = useState<string>("");
  const [busy, setBusy] = useState("");
  const [outcome, setOutcome] = useState<AcceptResult | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async (client: TakeoverApi) => {
    const [found, list] = await Promise.all([client.sessions(12), client.list()]);
    setCards(found.sessions);
    setRecords(list.items);
  }, []);

  useEffect(() => {
    openApi()
      .then(async (client) => {
        setApi(client);
        await refresh(client);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [refresh]);

  const stopped = useMemo(() => (cards ?? []).filter((c) => c.stop_kind !== "none"), [cards]);
  const others = useMemo(() => (cards ?? []).filter((c) => c.stop_kind === "none"), [cards]);
  const selected = (cards ?? []).find((c) => c.session_path === picked) ?? stopped[0] ?? null;

  const takeOver = async (card: TakeoverCard) => {
    if (!api) return;
    setBusy(card.session_path);
    setOutcome(null);
    setError("");
    try {
      const made = await api.pick(card.session_path);
      if (!made.ok || !made.takeover_id) throw new Error(made.error === "session_not_found" ? t("그 대화를 최근 기록에서 다시 찾지 못했습니다. 새로 고쳐 주세요.") : String(made.error));
      setOutcome(await api.accept(made.takeover_id));
      await refresh(api);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const discard = async (id: number) => {
    if (!api) return;
    setBusy(`discard-${id}`);
    try {
      await api.discard(id);
      setConfirming(null);
      await refresh(api);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="setup">
      <section className="setup-human" aria-live="polite">
        <div className="setup-say">
          <h1>{t("멈춘 대화를 Sonjari가 이어받습니다")}</h1>
          <p className="setup-lead">
            {t("Claude Code·Codex 가 사용량 한도로 멈추면, 이 PC 에 남은 기록에서 어디까지 했는지 찾습니다. Sonjari에게 「다 썼어」처럼 말해도 되고, 여기서 골라도 됩니다. 원래 폴더는 건드리지 않습니다.")}
          </p>
        </div>

        {error && (
          <p className="setup-error" role="alert">
            {error}
          </p>
        )}

        <div className="imp">
          <div className="imp-group">
            <h3>{t("멈춘 대화")}</h3>
            {cards === null ? (
              <p className="imp-hint">{t("기록을 찾는 중입니다…")}</p>
            ) : stopped.length === 0 ? (
              <p className="imp-hint">{t("최근 12시간 안에 멈춘 대화가 없습니다.")}</p>
            ) : (
              <ul className="imp-list">
                {stopped.map((card) => (
                  <CardRow key={card.session_path} card={card} picked={selected?.session_path === card.session_path} onPick={() => setPicked(card.session_path)} />
                ))}
              </ul>
            )}
          </div>
          {others.length > 0 && (
            <details className="tk-more">
              <summary>{t("정상으로 끝난 최근 대화")} {others.length}{t("개")}</summary>
              <ul className="imp-list">
                {others.map((card) => (
                  <CardRow key={card.session_path} card={card} picked={selected?.session_path === card.session_path} onPick={() => setPicked(card.session_path)} />
                ))}
              </ul>
            </details>
          )}
          <p className="imp-hint">{t("Cursor 는 대화가 공개 형식으로 저장되지 않아 아직 읽지 않습니다.")}</p>
        </div>

        {selected && (
          <div className="setup-actions">
            <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void takeOver(selected)}>
              {busy === selected.session_path ? t("이어받는 중…") : selected.git.repo ? t("가지를 만들어 이어받기") : t("이어서 할 지시문 만들기")}
            </button>
          </div>
        )}
        {outcome && <p className={outcome.kind === "started" ? "setup-done" : "setup-reason"}>{outcome.kind === "started" ? t("가지에서 이어 작업을 시작했습니다. 오른쪽에서 진행을 볼 수 있습니다.") : t("이어서 할 지시문을 만들었습니다 — 오른쪽에 있습니다.")}</p>}
      </section>

      <section className="setup-machine">
        {selected ? <CardDetail card={selected} prompt={outcome?.kind === "card" ? outcome.answer : ""} /> : <p className="setup-nocard">{t("고른 대화가 없습니다.")}</p>}

        {records.some((r) => r.branch) && (
          <div className="imp-manifest">
            <h2>{t("Sonjari가 만든 가지")}</h2>
            <ul>
              {records
                .filter((r) => r.branch)
                .map((record) => {
                  const label = STATUS_LABEL[record.status] ?? { text: record.status, tone: "quiet" as const };
                  return (
                    <li key={record.id} className="tk-branch">
                      <span className="imp-m-tool">{record.card.tool_name}</span>
                      <span className="tk-branch-main">
                        <code>{record.branch}</code>
                        {record.result.changed_files && (
                          <span className="imp-m-hint">
                            {t("바뀐 파일")} {record.result.changed_files.length}{t("개")}{record.result.diffstat_tail ? ` · ${record.result.diffstat_tail}` : ""}
                          </span>
                        )}
                        {record.result.summary && <span className="tk-summary">{record.result.summary}</span>}
                        {record.status === "review_pending" && record.base_ref && (
                          <span className="imp-m-hint">
                            {t("검토:")} <code>git diff {record.base_ref.slice(0, 12)}..{record.branch}</code>
                          </span>
                        )}
                      </span>
                      <span className="tk-branch-side">
                        <span className={`tk-status is-${label.tone}`}>{label.text}</span>
                        {record.status !== "discarded" &&
                          (confirming === record.id ? (
                            <span className="imp-confirm">
                              {t("가지와 작업 자리만 지웁니다. 원래 폴더는 그대로입니다.")}
                              <button type="button" className="imp-link is-stop" onClick={() => void discard(record.id)} disabled={busy !== ""}>
                                {t("버리기")}
                              </button>
                              <button type="button" className="imp-link is-quiet" onClick={() => setConfirming(null)}>
                                {t("그만두기")}
                              </button>
                            </span>
                          ) : (
                            <button type="button" className="imp-link is-stop" onClick={() => setConfirming(record.id)}>
                              {t("가지 버리기")}
                            </button>
                          ))}
                      </span>
                    </li>
                  );
                })}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}

function CardRow({ card, picked, onPick }: { card: TakeoverCard; picked: boolean; onPick: () => void }) {
  return (
    <li className={`imp-row tk-row${picked ? " is-picked" : ""}`}>
      <button type="button" className="tk-pick" aria-pressed={picked} onClick={onPick}>
        <span className="imp-name">
          <b>
            {card.tool_name} · {card.title || t("(제목 없음)")}
          </b>
          <span className="imp-path-text">{card.git.root || card.cwd}</span>
        </span>
        <span className={`imp-note ${card.stop_kind === "rate_limit" ? "is-signal" : "is-quiet"}`}>{stopText(card)}</span>
      </button>
    </li>
  );
}

function CardDetail({ card, prompt }: { card: TakeoverCard; prompt: string }) {
  return (
    <div className="imp-view">
      <header className="imp-doc-head">
        <b>
          {card.tool_name} · {card.title || t("(제목 없음)")}
        </b>
        <code>{card.git.root || card.cwd}</code>
      </header>
      <p className={`imp-sum ${card.stop_kind === "rate_limit" ? "is-signal" : "is-quiet"}`}>
        {stopText(card)}
        {resetText(card) ? ` · ${resetText(card)}` : ""}
      </p>
      {card.resumed_from_earlier_session && (
        <p className="imp-sum is-quiet">{t("멈춘 대화는 한도 뒤 다시 해 본 빈 대화라, 같은 폴더에서 실제로 일하던 앞 대화에서 이어갈 자리를 가져왔습니다.")}</p>
      )}
      <dl className="setup-facts">
        <div>
          <dt>{t("마지막 요청")}</dt>
          <dd>{card.last_request || t("기록에 없음")}</dd>
        </div>
        <div>
          <dt>{t("남은 할 일(기록 기준)")}</dt>
          <dd>{card.open_tasks.length ? card.open_tasks.join(" · ") : t("없음")}</dd>
        </div>
        <div>
          <dt>git</dt>
          <dd>
            {card.git.repo
              ? t("{0} · 바뀐 추적 파일 {1}개 · 추적 안 한 파일 {2}개", card.git.branch, card.git.changed_count, card.git.untracked_count)
              : t("git 저장소가 아님 — 가지를 만들 수 없어 지시문만 만듭니다")}
          </dd>
        </div>
      </dl>
      {card.files.length > 0 && (
        <div className="tk-block">
          <h3>{t("만지던 파일")}</h3>
          <ul className="tk-files">
            {card.files.slice(0, 12).map((f) => (
              <li key={f}>
                <code>{f}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {card.last_reply && (
        <div className="tk-block">
          <h3>{t("멈추기 직전 답")}</h3>
          <p className="tk-reply">{card.last_reply}</p>
        </div>
      )}
      {prompt && (
        <div className="tk-block">
          <h3>{t("이어서 할 지시문")}</h3>
          <pre className="imp-doc" tabIndex={0}>
            {prompt}
          </pre>
        </div>
      )}
    </div>
  );
}
