/**
 * 설정 › 팩 (0판, 2026-09-27 · 전략안 §50).
 *
 * 온텔릭의 규칙 그대로 — Ollama 설치 줄과 같은 결:
 * - **켜기 전에 무엇을 하는지 먼저 보여 준다**(읽는 것·쓰는 것·실행하는 것·인터넷). 누른 것이 동의다.
 * - 줄마다 상태 한 줄 + 단추 하나. 막힌 첫 칸의 「다음 할 일」 하나만 크게.
 * - 화면은 계산하지 않는다 — 팩 목록·유니티 상태·다음 할 일은 백엔드가 판정한 것을 그린다.
 */
import { t } from "../i18n";
import { Box, CheckCircle2, Circle, Copy, FolderOpen, Gamepad2, KeyRound, ListChecks, Loader2, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { pickNativeCodeWorkspace, type JarvisClient } from "../backend";
import type { PackInfo, PacksView, UnityDraft, UnityRecipeCard, UnitySetupView } from "../types";
import { EditorBlock, ScheduleBlock } from "./UnityEditorSection";

const PACK_ICON: Record<string, ReactNode> = {
  game: <Gamepad2 size={18} strokeWidth={1.6} />,
};

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export function permissionLines(pack: PackInfo): { label: string; value: string }[] {
  const join = (items: string[]) => (items.length ? items.join(" · ") : t("없음"));
  const network = typeof pack.permissions.network === "string"
    ? pack.permissions.network
    : pack.permissions.network ? t("씁니다") : t("쓰지 않습니다");
  return [
    { label: t("읽는 것"), value: join(pack.permissions.reads) },
    { label: t("쓰는 것"), value: join(pack.permissions.writes) },
    { label: t("실행하는 것"), value: join(pack.permissions.runs) },
    { label: t("인터넷"), value: network },
  ];
}

/** 팩이 들고 온 낱말 — 어떤 말에 이 스킬팩이 붙는지. 켜기 전에 보여 준다. */
export function packWords(pack: PackInfo): string[] {
  return [...new Set(Object.values(pack.triggers ?? {}).flat())];
}

/** 팩이 사람의 말 뒤에 붙이는 문장들. 켜기 전에 보여 준다 — 모르는 사이에 요청이 바뀌면 안 된다. */
export function packAsks(pack: PackInfo): string[] {
  return [...new Set(Object.values(pack.asks ?? {}))];
}

/** 팩이 그 스킬의 일을 「웹을 보고 와서 정리하는 일」로 적어 왔는가. 켜기 전에 보여 준다 — 쓰는 도구와 검사가 달라진다. */
export function packWorksOnTheWeb(pack: PackInfo): boolean {
  return Object.values(pack.work ?? {}).includes("web");
}

export function PacksSection({ client }: { client: JarvisClient }) {
  const [packs, setPacks] = useState<PackInfo[] | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [userDir, setUserDir] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const show = (view: PacksView) => {
    setPacks(view.packs);
    setProblems(view.problems);
    setUserDir(view.user_dir ?? "");
  };

  const load = useCallback(async () => {
    try {
      show(await client.listPacks());
    } catch (reason) {
      setError(t("팩 목록을 읽지 못했습니다: {0}", message(reason)));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  // 받은 폴더를 끌어다 놓을 자리를 연다. 경로는 백엔드가 정해 둔 한 곳이다 — 여기서 고르지 않는다.
  const openMine = async () => {
    setBusy("mine-open");
    setError("");
    try {
      const out = await client.openFolder("skillpacks");
      if (!out.ok) throw new Error(out.error ?? "open_failed");
      if (out.path) setUserDir(out.path);
    } catch (reason) {
      setError(t("스킬팩 폴더를 열지 못했습니다: {0}", message(reason)));
    } finally {
      setBusy("");
    }
  };

  const rescan = async () => {
    setBusy("mine-rescan");
    setError("");
    try {
      show(await client.rescanPacks());
    } catch (reason) {
      setError(t("스킬팩 폴더를 다시 읽지 못했습니다: {0}", message(reason)));
    } finally {
      setBusy("");
    }
  };

  const toggle = async (pack: PackInfo) => {
    setBusy(pack.id);
    setError("");
    try {
      const next = await client.setPack(pack.id, !pack.enabled);
      setPacks((rows) => (rows ?? []).map((row) => (row.id === next.id ? next : row)));
    } catch (reason) {
      setError(t("{0}을 {1} 못했습니다: {2}", pack.name, pack.enabled ? t("끄지") : t("켜지"), message(reason)));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="settings-block packs">
      <p className="settings-note">
        {t("팩은 Sonjari 위에 얹는 분야별 능력입니다. 켜기 전에는 아무것도 하지 않고, 끄면 도구와 스킬이 바로 빠집니다.")}
      </p>
      <section className="pack-mine" aria-labelledby="pack-mine-title" data-testid="pack-mine">
        <div className="pack-mine-text">
          <b id="pack-mine-title">{t("내 스킬팩")}</b>
          <span>{t("받은 스킬팩 폴더를 통째로 이 폴더에 넣고 「다시 읽기」를 누르면 아래 목록에 나타납니다. 넣기만 해서는 켜지지 않습니다.")}</span>
          {userDir && <code className="pack-mine-path">{userDir}</code>}
        </div>
        <div className="pack-mine-actions">
          <button type="button" className="setup-btn-go" onClick={() => void openMine()} disabled={busy === "mine-open"}>
            {busy === "mine-open" ? <Loader2 size={14} className="spin" /> : <FolderOpen size={14} aria-hidden="true" />} {t("내 스킬팩 넣기")}
          </button>
          <button type="button" className="setup-btn-quiet" onClick={() => void rescan()} disabled={busy === "mine-rescan"}>
            {busy === "mine-rescan" ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} aria-hidden="true" />} {t("다시 읽기")}
          </button>
        </div>
      </section>
      {error && <p className="settings-error" role="alert">{error}</p>}
      {!packs && !error && <p className="settings-note"><Loader2 size={14} className="spin" /> {t("팩을 읽는 중입니다")}</p>}
      {packs?.map((pack) => (
        <PackCard key={pack.id} pack={pack} busy={busy === pack.id} onToggle={() => void toggle(pack)} client={client} />
      ))}
      {problems.length > 0 && (
        <p className="firstrun-fine" role="note">{t("읽지 못한 팩:")} {problems.join(" / ")}</p>
      )}
    </div>
  );
}

function PackCard({ pack, busy, onToggle, client }: {
  pack: PackInfo;
  busy: boolean;
  onToggle: () => void;
  client: JarvisClient;
}) {
  const mine = pack.origin === "user";
  const words = packWords(pack);
  const asks = packAsks(pack);
  return (
    <section className={`pack-card${pack.enabled ? " is-on" : ""}`} aria-labelledby={`pack-${pack.id}`} data-testid={`pack-${pack.id}`}>
      <header className="pack-head">
        <span className="firstrun-logo" aria-hidden="true">{PACK_ICON[pack.id] ?? <Box size={18} strokeWidth={1.6} />}</span>
        <span className="firstrun-text">
          <b id={`pack-${pack.id}`}>
            {pack.name} <span className="pack-version">{pack.version}</span>
            {mine && <span className="pack-origin">{t("직접 넣은 스킬팩")}</span>}
          </b>
          <span>{pack.summary}</span>
        </span>
        <button type="button" className={pack.enabled ? "setup-btn-quiet" : "setup-btn-go"} onClick={onToggle} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : pack.enabled ? t("끄기") : t("켜기")}
        </button>
      </header>

      {words.length > 0 && (
        <p className="pack-words">
          <span>{t("이런 말에 붙습니다")}</span> {words.join(" · ")}
        </p>
      )}

      {asks.length > 0 && (
        <p className="pack-words pack-asks">
          <span>{t("내 말 뒤에 이 문장을 붙입니다")}</span> {asks.map((ask) => <q key={ask}>{ask}</q>)}
        </p>
      )}

      {packWorksOnTheWeb(pack) && (
        <p className="pack-words pack-work">
          <span>{t("이런 일로 다룹니다")}</span>{" "}
          {t("웹을 보고 와서 정리하는 일 — 그 일에 쓰는 도구만 쓰고, 파일을 쓰기 전에 숫자를 읽은 자료와 대조합니다")}
        </p>
      )}

      {!pack.enabled && (
        <>
          <dl className="pack-perms" aria-label={t("켜면 이렇게 됩니다")}>
            {permissionLines(pack).map((line) => (
              <div key={line.label}><dt>{line.label}</dt><dd>{line.value}</dd></div>
            ))}
          </dl>
          <p className="firstrun-fine">
            {t("켜기를 누르면 위 내용에 동의하는 것입니다. 도구")} {pack.tools.length}{t("개와 스킬")} {pack.skills.length}{t("개가 더해지고, 언제든 끌 수 있습니다 — 끄면 바로 빠집니다.")}
          </p>
        </>
      )}

      {pack.enabled && pack.id === "game" && <UnityWizard client={client} />}
    </section>
  );
}

function Mark({ ok }: { ok: boolean }) {
  return ok
    ? <CheckCircle2 size={16} className="pack-ok" aria-label={t("됨")} />
    : <Circle size={16} className="pack-todo" aria-label={t("아직")} />;
}

const NEXT_BUTTON: Record<string, string> = {
  install_hub: t("허브 받기"),
  open_hub: t("허브 열기"),
  pick_project: t("프로젝트 폴더 고르기"),
  allow_project: t("이 프로젝트 허락"),
  close_editor: t("다시 확인"),
  ready: t("다시 찾기"),
};

export function UnityWizard({ client }: { client: JarvisClient }) {
  const [view, setView] = useState<UnitySetupView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const scan = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setView(await client.unitySetup());
    } catch (reason) {
      setError(t("유니티를 찾지 못했습니다: {0}", message(reason)));
    } finally {
      setBusy(false);
    }
  }, [client]);

  useEffect(() => { void scan(); }, [scan]);

  const allow = async (path: string) => {
    setBusy(true);
    setError("");
    try {
      setView(await client.unityPickProject(path));
    } catch (reason) {
      setError(t("그 폴더를 쓸 수 없습니다: {0}", message(reason)));
    } finally {
      setBusy(false);
    }
  };

  const act = async () => {
    const kind = view?.next.kind;
    if (kind === "install_hub" || kind === "open_hub") {
      try {
        await client.unityOpenHub();
      } catch (reason) {
        setError(t("허브를 열지 못했습니다: {0}", message(reason)));
      }
      return;
    }
    if (kind === "allow_project" && view?.next.path) {
      await allow(view.next.path);
      return;
    }
    if (kind === "pick_project") {
      const picked = await pickNativeCodeWorkspace(view?.projects[0]?.path ?? "").catch(() => null);
      if (picked) await allow(picked);
      return;
    }
    await scan();
  };

  const editors = view?.editors ?? [];
  return (
    <div className="unity-wizard" data-testid="unity-wizard">
      {/* ★ 2026-10-12 게임 팩을 처음 켠 사람은 이 화면에서 「이게 뭘 해 주는지」부터 몰랐다 — 허브·에디터·라이선스 줄이
          먼저 나오고, 할 수 있는 일은 파일 이름 넷으로만 맨 아래 있었다. 무엇을 해 주는지를 맨 위에 세 줄로 둔다. */}
      <div className="unity-intro" data-testid="unity-intro">
        <b>{t("이 팩으로 할 수 있는 일")}</b>
        <ul>
          <li><b>{t("프로젝트 점검")}</b>{t(" — 빠진 참조 · 무거운 씬 · 큰 텍스처 · 안 쓰는 에셋을 찾습니다. 읽기만 하고 아무것도 바꾸지 않습니다.")}</li>
          <li><b>{t("열어 둔 유니티와 같이 보기")}</b>{t(" — 씬 계층과 콘솔 오류를 읽고, 바꾸는 일은 하나씩 물어보고 합니다.")}</li>
          <li><b>{t("새 점검 만들기")}</b>{t(" — 여기 없는 점검은 클로드·코덱스가 짜고, Sonjari가 이 PC에서 돌려 확인합니다.")}</li>
        </ul>
        <p className="firstrun-fine">{t("아래 네 줄에 초록 표시가 다 켜지면 준비 끝입니다. 안 켜진 줄이 있으면 그 아래 상자가 지금 할 일을 알려 줍니다.")}</p>
      </div>
      <div className="firstrun-row">
        <Mark ok={Boolean(view?.hub.installed)} />
        <span className="firstrun-text">
          <b>Unity Hub</b>
          <span>{!view ? t("찾는 중…") : view.hub.installed ? t("설치돼 있습니다") : t("설치돼 있지 않습니다")}</span>
        </span>
      </div>
      <div className="firstrun-row">
        <Mark ok={editors.length > 0} />
        <span className="firstrun-text">
          <b>{t("에디터")}</b>
          <span>{!view ? t("찾는 중…") : editors.length ? editors.map((row) => row.version).join(" · ") : t("설치된 에디터가 없습니다")}</span>
        </span>
      </div>
      <div className="firstrun-row">
        <Mark ok={Boolean(view?.license)} />
        <span className="firstrun-text">
          <b><KeyRound size={13} aria-hidden="true" /> {t("라이선스")}</b>
          <span>{!view ? t("찾는 중…") : view.license ? t("활성화돼 있습니다 (파일 내용은 열어 보지 않습니다)") : t("안 보입니다")}</span>
        </span>
      </div>
      <div className="firstrun-row unity-projects">
        <Mark ok={Boolean(view?.projects.some((row) => row.allowed && row.editor_installed))} />
        <span className="firstrun-text">
          <b>{t("프로젝트")}</b>
          {!view && <span>{t("찾는 중…")}</span>}
          {view && view.projects.length === 0 && <span>{t("찾은 프로젝트가 없습니다")}</span>}
          {view?.projects.map((row) => (
            <span key={row.path} className="unity-project">
              <span className="unity-project-name" title={row.path}>{row.name}</span>
              <span className="unity-project-meta">
                Unity {row.version || "?"}
                {!row.editor_installed && <em className="pack-warn"> {t("· 이 버전 에디터 없음")}</em>}
                {row.editor_open && <em className="pack-warn"> {t("· 에디터가 열고 있음")}</em>}
                {row.allowed ? <em className="pack-okay"> {t("· 허락됨")}</em> : null}
              </span>
              {!row.allowed && (
                <button type="button" className="setup-btn-quiet" onClick={() => void allow(row.path)} disabled={busy}>
                  {t("이 폴더 허락")}
                </button>
              )}
            </span>
          ))}
        </span>
      </div>

      {view && (
        <div className={`unity-next is-${view.next.kind}`} role="status">
          {view.next.kind === "ready" ? <CheckCircle2 size={16} aria-hidden="true" /> : <TriangleAlert size={16} aria-hidden="true" />}
          <span>{view.next.text}</span>
          <button type="button" className={view.next.kind === "ready" ? "setup-btn-quiet" : "setup-btn-go"} onClick={() => void act()} disabled={busy}>
            {busy ? <Loader2 size={14} className="spin" /> : view.next.kind === "pick_project" ? <><FolderOpen size={14} /> {NEXT_BUTTON[view.next.kind]}</> : view.next.kind === "ready" ? <><RefreshCw size={14} /> {NEXT_BUTTON.ready}</> : NEXT_BUTTON[view.next.kind]}
          </button>
        </div>
      )}
      {error && <p className="settings-error" role="alert">{error}</p>}
      {/* 처음 쓰는 사람의 순서대로: 바로 시킬 수 있는 것 → 열어 둔 유니티와 잇기 → 새 점검 만들기 → 정기 점검. */}
      <ReadyChecks client={client} ready={view?.next.kind === "ready"} />
      <EditorBlock client={client} />
      <CollabBlock client={client} />
      <ScheduleBlock client={client} projects={(view?.projects ?? []).filter((row) => row.allowed).map((row) => row.path)} />
      <p className="firstrun-fine">
        {t("점검은 유니티 창을 띄우지 않고 뒤에서 돌립니다. 프로젝트와 같은 버전의 유니티만 쓰고, 유니티가 그 프로젝트를 열고 있으면 이은 유니티 안에서 읽거나 닫힐 때까지 기다립니다.")}
      </p>
    </div>
  );
}

/**
 * 바로 시킬 수 있는 점검 — 제목 · 사람이 읽는 한 줄 · 대화창에 그대로 말하면 되는 문장.
 *
 * ★ 2026-10-12 전에는 `missing_references · scene_stats …` 같은 파일 이름만 한 줄로 보였다. 무엇을 해 주는지도
 *   뭐라고 말하면 되는지도 없어서, 준비를 다 마친 사람이 그다음에 할 일을 몰랐다. 문장은 백엔드가 준다 — 계획 층이
 *   유니티 점검으로 알아보는 문장인지 시험이 지킨다(여기서 지어 적지 않는다).
 */
export function ReadyChecks({ client, ready }: { client: JarvisClient; ready: boolean }) {
  const [cards, setCards] = useState<UnityRecipeCard[]>([]);
  const [copied, setCopied] = useState("");

  const load = useCallback(async () => {
    try {
      setCards((await client.unityDrafts()).recipe_cards ?? []);
    } catch {
      // 못 읽으면 이 칸만 비운다 — 같은 주소를 읽는 아래 칸이 까닭을 말한다.
    }
  }, [client]);

  useEffect(() => {
    void load();
    // 아래에서 초안을 등록하면 여기 늘어난다 — 이 칸이 열려 있는 동안만 가끔 다시 본다.
    const timer = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  const copy = async (card: UnityRecipeCard) => {
    try {
      await navigator.clipboard.writeText(card.ask);
      setCopied(card.name);
      window.setTimeout(() => setCopied(""), 1600);
    } catch {
      setCopied("");
    }
  };

  if (cards.length === 0) return null;
  return (
    <div className="unity-checks" data-testid="unity-checks">
      <div className="unity-collab-head">
        <ListChecks size={16} aria-hidden="true" />
        <b>{t("바로 시킬 수 있는 점검")}</b>
      </div>
      <p className="unity-collab-line">
        {t("Sonjari 대화창에 아래 문장을 그대로 말하면 됩니다. 프로젝트가 여럿이면 「유니티 ○○ 프로젝트 …」처럼 이름을 넣어 주세요.")}
        {!ready && <> <em className="pack-warn">{t("바로 위 상자에 적힌 일을 마치면 쓸 수 있습니다.")}</em></>}
      </p>
      <ul className="unity-check-list">
        {cards.map((card) => (
          <li key={card.name} className="unity-check">
            <b>{card.title}</b>
            {card.description && <span>{card.description}</span>}
            {card.ask && (
              <div className="unity-collab-example">
                <span>「{card.ask}」</span>
                <button type="button" className="setup-btn-quiet" onClick={() => void copy(card)} aria-label={t("{0} 문장 복사", card.title)}>
                  <Copy size={13} /> {copied === card.name ? t("복사됨") : t("복사")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const COLLAB_EXAMPLE = t("유니티 프로젝트에서 폴리곤이 10만 개 넘는 메시를 찾는 레시피를 만들어서, Sonjari로 내 프로젝트에 돌려 봐 줘");

/**
 * 클로드·코덱스와 같이 쓰기. 레시피가 없는 일은 억지로 온텔릭 혼자 하지 않는다 —
 * 그쪽이 스크립트를 짜고(MCP `unity_try_script`), 온텔릭이 이 PC 의 프로젝트에서 돌려 확인하고, **사람이 여기서 등록**한다.
 */
export function CollabBlock({ client }: { client: JarvisClient }) {
  const [drafts, setDrafts] = useState<UnityDraft[] | null>(null);
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const view = await client.unityDrafts();
      setDrafts(view.drafts);
    } catch (reason) {
      setError(t("초안을 읽지 못했습니다: {0}", message(reason)));
    }
  }, [client]);

  useEffect(() => {
    void load();
    // 바깥 AI 가 돌려 본 초안이 들어오면 보이게 — 이 칸이 열려 있는 동안만 가끔 다시 본다.
    const timer = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  const act = async (draft: UnityDraft, action: "promote" | "discard") => {
    setBusy(`${draft.name}:${action}`);
    setError("");
    try {
      await client.unityDraftAction(draft.name, action);
      await load();
    } catch (reason) {
      setError(t("{0}을 {1} 못했습니다: {2}", draft.title, action === "promote" ? t("등록하지") : t("버리지"), message(reason)));
    } finally {
      setBusy("");
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(COLLAB_EXAMPLE);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="unity-collab" data-testid="unity-collab">
      <div className="unity-collab-head">
        <Sparkles size={16} aria-hidden="true" />
        <b>{t("클로드·코덱스와 같이 쓰기")}</b>
      </div>
      <p className="unity-collab-line">
        {t("위 점검에 없는 새 일은 클로드 코드·코덱스가 스크립트를 짜고, Sonjari가")} <b>{t("이 PC의 실제 프로젝트에서")}</b> {t("돌려 확인합니다. 에셋은 밖으로 나가지 않습니다. 결과가 맞으면 아래에서 등록하세요 — 그다음부터는 Sonjari 혼자, 공짜로 합니다.")}
      </p>
      <div className="unity-collab-example">
        <span>「{COLLAB_EXAMPLE}」</span>
        <button type="button" className="setup-btn-quiet" onClick={() => void copy()} aria-label={t("예시 문장 복사")}>
          <Copy size={13} /> {copied ? t("복사됨") : t("복사")}
        </button>
      </div>
      <p className="firstrun-fine">{t("클로드 코드·코덱스에 Sonjari를 잇는 것은 설정 › 연결에서 합니다.")}</p>

      {drafts && drafts.length > 0 && (
        <ul className="unity-drafts" aria-label={t("돌려 본 초안")}>
          {drafts.map((draft) => (
            <li key={draft.name} className="unity-draft">
              <div className="unity-draft-head">
                <span className="unity-draft-title">
                  <b>{draft.title}</b> <code>{draft.name}</code>
                </span>
                <span className="unity-draft-meta">
                  {draft.author || t("바깥 AI")} · {draft.verified ? <em className="pack-okay">{t("돌려 봄 · 성공")}</em> : <em className="pack-warn">{t("실패")}{draft.failure ? `(${draft.failure})` : ""}</em>}
                  {" · "}{draft.findings.length ? <em className="pack-warn">{t("바꾸는 코드")} {draft.findings.length}{t("줄")}</em> : <em className="pack-okay">{t("읽기만 함")}</em>}
                </span>
              </div>
              {draft.description && <p className="unity-draft-desc">{draft.description}</p>}
              {draft.findings.length > 0 && (
                <ul className="unity-draft-findings">
                  {draft.findings.slice(0, 5).map((row) => (
                    <li key={`${row.line}:${row.code}`}><span>{row.line}{t("줄 ·")} {row.what}</span> <code>{row.code}</code></li>
                  ))}
                </ul>
              )}
              <div className="firstrun-actions">
                <button type="button" className="setup-btn-go" disabled={!draft.verified || busy !== ""}
                  title={draft.verified ? t("이 초안을 레시피로 등록") : t("성공한 초안만 등록할 수 있습니다")}
                  onClick={() => void act(draft, "promote")}>
                  {busy === `${draft.name}:promote` ? <Loader2 size={14} className="spin" /> : t("레시피로 등록")}
                </button>
                <button type="button" className="setup-btn-quiet" disabled={busy !== ""} onClick={() => void act(draft, "discard")}>
                  {busy === `${draft.name}:discard` ? <Loader2 size={14} className="spin" /> : t("버리기")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}
