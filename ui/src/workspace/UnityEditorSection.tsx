/**
 * 게임 팩 2단계 (2026-09-27) — 열린 유니티 에디터를 온텔릭 화면에서 같이 본다.
 *
 * - 「에디터 잇기」: 프로젝트의 Packages/manifest.json 에 온텔릭 사본(MCP for Unity) 한 줄. 풀면 원래대로.
 * - 무대: 유니티 창을 **앞으로 가져오지 않고** 그림만 비춘다. 모델·기록으로 보내지 않는다. 「직접 하기」만 창을 앞으로.
 * - 우리 방: 에디터 다리를 지난 명령 기록은 이 PC 에만 쌓인다. 원본 제작사에 같이 보내는 것은 사람이 켤 때만.
 * - 정기 점검: 등록한 레시피를 정해 둔 시각에 모델 없이 돌리고, 지난번보다 늘었을 때만 알린다.
 */
import { t } from "../i18n";
import { CalendarClock, Hand, Link2, Loader2, MonitorPlay, Play, Trash2, Unlink } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { JarvisClient } from "../backend";
import type { UnityEditorView, UnitySchedule } from "../types";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

const STAGE_PROBLEM: Record<string, string> = {
  minimized: t("유니티 창이 최소화돼 있어 비출 수 없습니다. 「직접 하기」를 누르면 창을 되살립니다."),
  no_editor: t("떠 있는 유니티 에디터가 없습니다."),
  backend_unreachable: t("Sonjari 백엔드에 닿지 않습니다."),
};

/** 유니티 창 한 장씩(롱 폴). 보는 동안만 당긴다 — 칸이 닫히면 백엔드도 6초 뒤 찍기를 멈춘다. */
export function UnityStageView({ client, project = "", compact = false }: { client: JarvisClient; project?: string; compact?: boolean }) {
  const [src, setSrc] = useState("");
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState("");
  const [note, setNote] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    let alive = true;
    let url = "";
    const pull = async () => {
      while (alive) {
        const frame = await client.getUnityStageFrame(seq.current, 1, project);
        if (!alive) break;
        if (frame.blob) {
          seq.current = frame.seq;
          const next = URL.createObjectURL(frame.blob);
          if (url) URL.revokeObjectURL(url);
          url = next;
          setSrc(next);
          setTitle(frame.title);
          setProblem("");
        } else if (frame.problem) {
          setProblem(frame.problem);
          await new Promise((resolve) => window.setTimeout(resolve, 1500));
        }
      }
    };
    void pull();
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [client, project]);

  const takeOver = async () => {
    setNote("");
    try {
      const out = await client.unityTakeOver(project);
      setNote(out.ok ? t("유니티 창을 앞으로 가져왔습니다.") : t("창을 앞으로 가져오지 못했습니다 — 작업 표시줄에서 유니티를 눌러 주세요."));
    } catch (reason) {
      setNote(t("창을 앞으로 가져오지 못했습니다: {0}", message(reason)));
    }
  };

  return (
    <figure className={`unity-stage${compact ? " is-compact" : ""}`} data-testid="unity-stage">
      <div className="unity-stage-frame">
        {src && !problem ? <img src={src} alt={title ? t("유니티 화면 — {0}", title) : t("유니티 화면")} /> : (
          <p className="unity-stage-empty">{STAGE_PROBLEM[problem] ?? (problem ? t("화면을 받지 못했습니다({0})", problem) : t("유니티 화면을 받는 중…"))}</p>
        )}
      </div>
      <figcaption>
        <span className="unity-stage-title"><MonitorPlay size={14} aria-hidden="true" /> {title || t("유니티 에디터")}</span>
        <button type="button" className="setup-btn-quiet" onClick={() => void takeOver()}>
          <Hand size={13} /> {t("직접 하기")}
        </button>
      </figcaption>
      <p className="firstrun-fine">
        {t("유니티 창을 앞으로 가져오지 않고 그림만 비춥니다. 이 화면은 모델에게 보내지 않습니다.")}{note ? ` ${note}` : ""}
      </p>
    </figure>
  );
}

export function EditorBlock({ client }: { client: JarvisClient }) {
  const [view, setView] = useState<UnityEditorView | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setView(await client.unityEditor());
    } catch (reason) {
      setError(t("에디터 상태를 읽지 못했습니다: {0}", message(reason)));
    }
  }, [client]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const link = async (path: string, on: boolean) => {
    setBusy(path);
    setError("");
    setNotice("");
    try {
      const out = await client.unityEditorLink(path, on);
      setNotice(on ? out.next ?? t("이었습니다.") : t("풀었습니다. 프로젝트의 manifest.json 이 원래대로 돌아갔습니다."));
      await load();
    } catch (reason) {
      setError(t("{0} 못했습니다: {1}", on ? t("잇지") : t("풀지"), message(reason)));
    } finally {
      setBusy("");
    }
  };

  const share = async (on: boolean) => {
    setBusy("share");
    try {
      await client.unityShareWithCoplay(on);
      await load();
    } catch (reason) {
      setError(t("설정을 바꾸지 못했습니다: {0}", message(reason)));
    } finally {
      setBusy("");
    }
  };

  const connected = view?.projects.find((row) => row.connected);
  const room = view?.room;
  const failed = room ? Object.values(room.by_tool).reduce((sum, row) => sum + row.failed, 0) : 0;
  return (
    <div className="unity-editor" data-testid="unity-editor">
      <div className="unity-collab-head">
        <MonitorPlay size={16} aria-hidden="true" />
        <b>{t("열린 에디터 — 보면서 같이")}</b>
      </div>
      <p className="unity-collab-line">
        {t("에디터를 닫지 않아도 됩니다. 이은 프로젝트는 Sonjari가 열린 에디터 안에서 계층·콘솔·선택을 읽고, 바꾸는 일은 승인을 받아 에디터 Undo 에 남깁니다. 씬 저장은 따로 묻습니다.")}
      </p>
      {/* ★ 2026-10-12 「잇기」가 프로젝트에 무엇을 하는지 · 되돌릴 수 있는지를 누르기 전에 말한다. */}
      <p className="firstrun-fine">
        {t("「에디터 잇기」는 프로젝트의 패키지 목록(Packages/manifest.json)에 연결 부품 한 줄을 적습니다. 「풀기」를 누르면 그 줄을 원래대로 돌려 놓습니다.")}
      </p>
      {view && view.projects.length === 0 && <p className="firstrun-fine">{t("위에서 프로젝트를 허락하면 여기서 이을 수 있습니다.")}</p>}
      <ul className="unity-links">
        {view?.projects.map((row) => (
          <li key={row.path} className="unity-link">
            <span className="unity-project-name" title={row.path}>{row.name}</span>
            <span className="unity-project-meta">
              {row.connected ? <em className="pack-okay">{t("이어짐 · 에디터 열림")}</em>
                // ★ 2026-10-12: 「에디터가 패키지를 읽는 중」은 기다리면 되는 것처럼 읽혔다 — 실제로는 유니티 창을 눌러 줘야
                //   읽기 시작하거나(매니페스트만 바꾸면 창이 앞에 올 때까지 옛 것을 쓴다 · 09-27), 유니티가 사본을 아예 못 찾는
                //   것이었다(스토어판의 예전 판). 무엇을 하면 되는지를 적는다.
                : row.installed ? (row.broken ? <em className="pack-warn">{t("유니티가 연결 부품을 못 찾습니다 — 「다시 잇기」를 눌러 주세요")}</em>
                  : row.editor_open ? <em className="pack-warn">{t("유니티 창을 한 번 눌러 주세요 — 그때 연결 부품을 읽습니다")}</em> : <em>{t("이음 · 에디터 닫힘")}</em>)
                  : row.other_version ? <em className="pack-warn">{t("원본 판이 깔려 있음")}</em> : <em>{t("안 이음")}</em>}
            </span>
            {row.installed && row.broken && (
              <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void link(row.path, true)}>
                {busy === row.path ? <Loader2 size={14} className="spin" /> : <><Link2 size={13} /> {t("다시 잇기")}</>}
              </button>
            )}
            <button type="button" className={row.installed ? "setup-btn-quiet" : "setup-btn-go"} disabled={busy !== ""}
              onClick={() => void link(row.path, !row.installed)}>
              {busy === row.path ? <Loader2 size={14} className="spin" /> : row.installed ? <><Unlink size={13} /> {t("풀기")}</> : <><Link2 size={13} /> {t("에디터 잇기")}</>}
            </button>
          </li>
        ))}
      </ul>
      {view?.projects.some((row) => row.other_version) && (
        <p className="firstrun-fine">{t("원본 판이 깔린 프로젝트는 잇기를 누르면 Sonjari 사본으로 바꾸고, 풀면 원래 줄로 돌려 놓습니다.")}</p>
      )}
      {notice && <p className="firstrun-fine" role="status">{notice}</p>}
      {view && view.projects.length > 0 && (
        <details className="unity-help" data-testid="unity-help">
          <summary>{t("이었는데 안 될 때")}</summary>
          <ul>
            <li><b>{t("「이어짐」이 안 뜬다")}</b>{t(" — 유니티 창을 한 번 눌러 앞으로 가져와 주세요. 유니티는 창이 앞에 올 때 새 부품을 읽습니다.")}</li>
            <li><b>{t("유니티 아래쪽에 빨간 오류가 뜬다")}</b>{t(" — 유니티 메뉴의 Window › General › Console 을 열어 맨 위 빨간 줄을 복사해 Sonjari에게 보여 주세요. 급하면 「풀기」를 누르면 원래대로 돌아갑니다.")}</li>
            <li><b>{t("「유니티가 연결 부품을 못 찾습니다」가 뜬다")}</b>{t(" — 「다시 잇기」를 누르면 유니티가 읽을 수 있는 자리로 고쳐 적습니다.")}</li>
          </ul>
        </details>
      )}
      {/* 처음 보는 사람에게 「MCP for Unity 10.2.0-…」는 제목 옆에 둘 말이 아니다 — 무엇인지와 함께 작은 글로. */}
      {view?.package_version && <p className="firstrun-fine">{t("연결 부품: MCP for Unity {0} (Sonjari 사본)", view.package_version)}</p>}

      {(connected || view?.stage.status === "ready" || view?.stage.status === "minimized") && (
        <UnityStageView client={client} project={connected?.path ?? ""} />
      )}

      {room && (
        <div className="unity-room" data-testid="unity-room">
          <span>
            <b>{t("우리 방")}</b> {t("— 에디터 명령")} {room.calls}{t("번 · 실패")} {failed}{t("번 · 기록은 이 PC 에만 있습니다")}
            {room.share_with_coplay ? t(" · 원본 제작사에 보낸 기록 {0}건", room.shared_count) : t(" · 밖으로 보낸 것 0건")}
          </span>
          <label className="unity-share">
            <input type="checkbox" checked={room.share_with_coplay} disabled={busy === "share"}
              onChange={(event) => void share(event.target.checked)} />
            {t("원본 제작사(Coplay)에도 사용 기록 보내기")}
          </label>
          <p className="firstrun-fine">
            {t("켜면 명령마다 도구 이름·성공 여부·걸린 시간·오류 앞 200자와 이 설치의 무작위 ID 가 api-prod.coplay.dev 로 갑니다. 에셋·코드·씬 내용은 보내지 않습니다. 기본은 꺼짐입니다.")}
          </p>
        </div>
      )}
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}

const DAYS_LABEL = { daily: t("매일"), weekday: t("평일"), weekly: t("매주") } as const;

function when(at: number): string {
  const date = new Date(at * 1000);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function ScheduleBlock({ client, projects }: { client: JarvisClient; projects: string[] }) {
  const [rows, setRows] = useState<UnitySchedule[] | null>(null);
  const [recipes, setRecipes] = useState<string[]>([]);
  // 고르기 칸에는 파일 이름(`missing_references`)이 아니라 제목(「빠진 참조 찾기」)을 보인다 — 값은 이름 그대로 보낸다.
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [recipe, setRecipe] = useState("");
  const [project, setProject] = useState("");
  const [at, setAt] = useState("03:00");
  const [days, setDays] = useState<"daily" | "weekday" | "weekly">("daily");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setRows((await client.unitySchedules()).schedules);
      const drafts = await client.unityDrafts();
      setRecipes(drafts.recipes);
      setTitles(Object.fromEntries((drafts.recipe_cards ?? []).map((card) => [card.name, card.title])));
    } catch (reason) {
      setError(t("정기 점검을 읽지 못했습니다: {0}", message(reason)));
    }
  }, [client]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);

  const add = async () => {
    setBusy("add");
    setError("");
    try {
      await client.unityScheduleAdd({ recipe: recipe || recipes[0], project: project || projects[0], at, days });
      await load();
    } catch (reason) {
      setError(t("정기 점검을 만들지 못했습니다: {0}", message(reason)));
    } finally {
      setBusy("");
    }
  };

  const act = async (row: UnitySchedule, action: "run" | "enable" | "disable" | "remove") => {
    setBusy(`${row.id}:${action}`);
    setError("");
    try {
      await client.unityScheduleAction(row.id, action);
      await load();
    } catch (reason) {
      setError(`${row.title}: ${message(reason)}`);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="unity-schedule" data-testid="unity-schedule">
      <div className="unity-collab-head">
        <CalendarClock size={16} aria-hidden="true" />
        <b>{t("정기 점검 — 모델 없이, 공짜로")}</b>
      </div>
      <p className="unity-collab-line">
        {t("등록한 레시피를 정해 둔 시각에 Sonjari가 혼자 돌립니다. 모델도 토큰도 쓰지 않고, 지난번보다 숫자가 늘었을 때만 알려 드립니다. 그 시각에 에디터가 열려 있으면 닫힐 때까지 미룹니다.")}
      </p>
      {rows && rows.length > 0 && (
        <ul className="unity-drafts" aria-label={t("정기 점검")}>
          {rows.map((row) => (
            <li key={row.id} className={`unity-draft${row.enabled ? "" : " is-off"}`}>
              <div className="unity-draft-head">
                <span className="unity-draft-title"><b>{row.title}</b> <code>{row.project.split(/[\\/]/).pop()}</code></span>
                <span className="unity-draft-meta">
                  {DAYS_LABEL[row.days]} {row.at}{row.enabled ? "" : t(" · 꺼짐")}{row.running ? t(" · 도는 중") : ""}
                </span>
              </div>
              {row.deferred && <p className="unity-draft-desc pack-warn">{row.deferred}</p>}
              {row.last ? (
                <p className="unity-draft-desc">
                  {t("마지막")} {when(row.last.at)} · {Object.entries(row.last.numbers).map(([key, value]) => {
                    const worse = row.last?.worse[key];
                    const label = row.watch_labels[key] ?? key;
                    return worse
                      ? <em key={key} className="pack-warn">{label} {worse[0]}→{worse[1]} </em>
                      : <span key={key}>{label} {value} </span>;
                  })}
                </p>
              ) : row.history[0] && !row.history[0].verified ? (
                <p className="unity-draft-desc pack-warn">{t("마지막 실행 실패:")} {row.history[0].failure || t("결과 없음")}</p>
              ) : <p className="unity-draft-desc">{t("아직 돌지 않았습니다 — 첫 판은 기준만 잡습니다.")}</p>}
              <div className="firstrun-actions">
                <button type="button" className="setup-btn-quiet" disabled={busy !== "" || row.running} onClick={() => void act(row, "run")}>
                  {busy === `${row.id}:run` ? <Loader2 size={14} className="spin" /> : <><Play size={13} /> {t("지금 한 번")}</>}
                </button>
                <button type="button" className="setup-btn-quiet" disabled={busy !== ""} onClick={() => void act(row, row.enabled ? "disable" : "enable")}>
                  {row.enabled ? t("끄기") : t("켜기")}
                </button>
                <button type="button" className="setup-btn-quiet" disabled={busy !== ""} onClick={() => void act(row, "remove")} aria-label={t("{0} 정기 점검 빼기", row.title)}>
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {recipes.length > 0 && projects.length > 0 ? (
        <div className="unity-schedule-form">
          <select aria-label={t("레시피")} value={recipe || recipes[0]} onChange={(event) => setRecipe(event.target.value)}>
            {recipes.map((name) => <option key={name} value={name}>{titles[name] || name}</option>)}
          </select>
          <select aria-label={t("프로젝트")} value={project || projects[0]} onChange={(event) => setProject(event.target.value)}>
            {projects.map((path) => <option key={path} value={path}>{path.split(/[\\/]/).pop()}</option>)}
          </select>
          <select aria-label={t("요일")} value={days} onChange={(event) => setDays(event.target.value as typeof days)}>
            {Object.entries(DAYS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          <input aria-label={t("시각")} type="time" value={at} onChange={(event) => setAt(event.target.value)} />
          <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void add()}>
            {busy === "add" ? <Loader2 size={14} className="spin" /> : t("정기 점검 추가")}
          </button>
        </div>
      ) : (
        <p className="firstrun-fine">{t("허락한 프로젝트와 레시피가 있어야 정기 점검을 만들 수 있습니다.")}</p>
      )}
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}
