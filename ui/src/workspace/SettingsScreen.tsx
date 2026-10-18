/**
 * 설정 (W3) — Claude 설정처럼 **왼쪽 분류 / 오른쪽 한 주제.**
 *
 *   설정       일반 · 모델 · 음성 · 메모리 · 권한·안전 · 이어받기 · 스킬 · 실험실   ← 칸 목록은 백엔드 허용 목록이 준다
 *   사용자 지정 연결(Claude·Cursor·Codex) · 지침 가져오기                          ← 첫 실행 부품을 옮겨 담았다
 *   데스크톱 앱 데이터와 백업 · 진단·첫 실행 다시 하기·자동 시작
 *
 * ## 규율
 *
 * - 화면은 칸을 **지어내지 않는다.** 무엇을 바꿀 수 있는지·범위·「다시 시작해야 적용」은 `GET /v1/settings` 가 말한다.
 * - 저장 결과를 **백엔드가 돌려준 값으로** 다시 그린다. 누른 대로 그리면 거절된 값이 저장된 것처럼 보인다.
 * - 되돌릴 수 없는 것(「백업까지 지우기」)은 한 번 더 확인하고, 무엇이 지워지고 무엇이 남는지 적는다.
 */
import { lang, setLang, t, type Lang } from "../i18n";
import { invoke } from "@tauri-apps/api/core";
import {
  Archive, Brain, Cpu, FlaskConical, Link2, Loader2, MessagesSquare, Mic, RotateCcw, Settings2, ShieldCheck,
  Sparkles, Stethoscope, Undo2, Workflow, X, FileInput, Package, MessageCircle, UserRound,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { isTauri, loadBootstrap, type JarvisClient } from "../backend";
import { ConnectPanel } from "../setup/ConnectPanel";
import { ImportPanel } from "../setup/ImportPanel";
import { ImportPreview } from "../setup/ImportPreview";
import { SkillDomainPicker } from "../setup/SkillDomainPicker";
import { createSetupApi, type SetupApi } from "../setup/setupApi";
import { ModelSection } from "./ModelSection";
import { useInstructionImport } from "../setup/useInstructionImport";
import "../setup/setup.css";
import type { BackupSummary, SettingRow, SettingValue, SettingsView } from "../types";
import { LearnedPanel } from "./LearnedPanel";
import { PacksSection } from "./PacksSection";
import { DiscordSection } from "./DiscordSection";
import { AboutMeSection } from "./AboutMeSection";

type Section = string;
type FieldStatus = { state: "saving" | "saved" | "error"; message: string };

const GROUP_ICON: Record<string, ReactNode> = {
  general: <Settings2 size={15} />, model: <Cpu size={15} />, voice: <Mic size={15} />, memory: <Brain size={15} />,
  permissions: <ShieldCheck size={15} />, takeover: <Workflow size={15} />, skills: <Sparkles size={15} />,
  labs: <FlaskConical size={15} />,
};

const EXTRA_SECTIONS: { id: Section; label: string; heading: string; icon: ReactNode }[] = [
  // ★ 2026-10-18: 매 턴 실리는 프로필 파일에 화면이 없었다. 사용자 지침은 이 한 곳(파일 하나)에 모은다 — 「지침 가져오기」도
  //   여기로 줄을 골라 올린다. 맨 위에 둔다: 손자리가 「나」를 어떻게 대하는지가 사용자 지정의 첫 칸이다.
  { id: "about_me", label: t("나에 대한 지침"), heading: t("사용자 지정"), icon: <UserRound size={15} /> },
  { id: "packs", label: t("팩"), heading: t("사용자 지정"), icon: <Package size={15} /> },
  { id: "connect", label: t("연결"), heading: t("사용자 지정"), icon: <Link2 size={15} /> },
  // ★ 2026-10-18: 폰 디스코드로 일 시키기 — 명령 창 마법사를 쓸 수 없는 스토어판 사람이 클릭 몇 번으로 잇는다.
  { id: "discord", label: t("디스코드로 일 시키기"), heading: t("사용자 지정"), icon: <MessageCircle size={15} /> },
  { id: "import", label: t("지침 가져오기"), heading: t("사용자 지정"), icon: <FileInput size={15} /> },
  { id: "data", label: t("데이터와 백업"), heading: t("데스크톱 앱"), icon: <Archive size={15} /> },
  { id: "app", label: t("진단·다시 시작"), heading: t("데스크톱 앱"), icon: <Stethoscope size={15} /> },
];

export function describeSource(row: SettingRow): string {
  if (row.restart_required) return t("저장됨 · 다시 시작하면 적용");
  if (row.source === "user") return row.live ? t("직접 바꿈 · 바로 적용됨") : t("직접 바꿈");
  return row.live ? t("기본값") : t("기본값 · 바꾸면 다시 시작해야 적용");
}

export function SettingsScreen({ client, open, onClose, initialSection = "general" }: {
  client: JarvisClient | null;
  open: boolean;
  onClose: () => void;
  initialSection?: Section;
}) {
  const [section, setSection] = useState<Section>(initialSection);
  const [view, setView] = useState<SettingsView | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<Record<string, FieldStatus>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftRef = useRef<Record<string, string>>({});
  const viewRef = useRef(view);
  viewRef.current = view;
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const inFlight = useRef(new Map<string, Promise<boolean>>());
  const closing = useRef(false);
  const [isClosing, setIsClosing] = useState(false);
  const [setupApi, setSetupApi] = useState<SetupApi | null>(null);

  useEffect(() => {
    if (open) {
      setSection(initialSection);
      setError("");
      setStatus({});
      draftRef.current = {};
      setDrafts({});
    }
  }, [open, initialSection]);

  useEffect(() => {
    if (!open || !client) return;
    let alive = true;
    client.getSettings()
      .then((next) => alive && setView(next))
      .catch((reason) => alive && setError(settingErrorText(reason instanceof Error ? reason.message : String(reason))));
    loadBootstrap().then((bootstrap) => alive && bootstrap.controlToken && setSetupApi(createSetupApi(bootstrap))).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [open, client]);

  const clearDraft = useCallback((key: string) => {
    const next = { ...draftRef.current };
    delete next[key];
    draftRef.current = next;
    setDrafts(next);
  }, []);

  // 요청을 순서대로 보낸다. 응답의 전체 설정 표가 다른 칸의 새 값을 덮어쓰지 않게 한다.
  const perform = useCallback((key: string, work: () => Promise<string>): Promise<boolean> => {
    const running = inFlight.current.get(key);
    if (running) return running;
    setStatus((previous) => ({ ...previous, [key]: { state: "saving", message: t("저장하는 중입니다") } }));
    const operation = queue.current.then(async () => {
      try {
        const message = await work();
        clearDraft(key);
        setStatus((previous) => ({ ...previous, [key]: { state: "saved", message } }));
        return true;
      } catch (reason) {
        clearDraft(key);
        setStatus((previous) => ({ ...previous, [key]: { state: "error", message: settingErrorText(reason instanceof Error ? reason.message : String(reason)) } }));
        return false;
      } finally {
        inFlight.current.delete(key);
      }
    });
    inFlight.current.set(key, operation);
    queue.current = operation;
    return operation;
  }, [clearDraft]);

  const save = useCallback((key: string, value: SettingValue): Promise<boolean> => {
    if (!client) return Promise.resolve(false);
    return perform(key, async () => {
      const next = await client.patchSettings({ [key]: value });
      viewRef.current = next;
      setView(next);
      if (key === "google_write_enabled" && value === true) {
        try {
          await client.startGoogleOAuth();
        } catch {
          throw new Error(SAVED_BUT_GOOGLE_FAILED());
        }
        return t("저장됨 · 브라우저에서 Google 권한 연결을 완료해 주세요");
      }
      return next.settings.find((row) => row.key === key)?.restart_required ? t("저장됨 · 다시 시작하면 적용") : t("저장됨");
    });
  }, [client, perform]);

  const reset = useCallback((key: string): Promise<boolean> => {
    if (!client) return Promise.resolve(false);
    return perform(key, async () => {
      const next = await client.resetSettings([key]);
      viewRef.current = next;
      setView(next);
      return next.settings.find((row) => row.key === key)?.restart_required ? t("기본값으로 돌렸습니다 · 다시 시작하면 적용") : t("기본값으로 돌렸습니다");
    });
  }, [client, perform]);

  const saveDraft = useCallback((key: string): Promise<boolean> => {
    const row = viewRef.current?.settings.find((candidate) => candidate.key === key);
    const text = draftRef.current[key];
    if (!row || text === undefined || text === draftOf(row)) return Promise.resolve(true);
    try {
      return save(key, settingDraftValue(row, text));
    } catch (reason) {
      clearDraft(key);
      setStatus((previous) => ({ ...previous, [key]: { state: "error", message: settingErrorText(String(reason)) } }));
      return Promise.resolve(false);
    }
  }, [save, clearDraft]);

  const requestClose = useCallback(async () => {
    if (closing.current) return;
    closing.current = true;
    setIsClosing(true);
    try {
      const results = await Promise.all([...Object.keys(draftRef.current).map(saveDraft), ...inFlight.current.values()]);
      if (results.every(Boolean)) onClose();
      else setError(t("저장하지 못한 설정이 있습니다. 해당 칸의 안내를 확인해 주세요."));
    } finally {
      closing.current = false;
      setIsClosing(false);
    }
  }, [saveDraft, onClose]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); void requestClose(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, requestClose]);

  const control = (row: SettingRow) => <SettingControl key={row.key} row={row} status={status[row.key]}
    draft={drafts[row.key] ?? draftOf(row)} onDraft={(text) => {
      const next = { ...draftRef.current, [row.key]: text };
      draftRef.current = next;
      setDrafts(next);
    }} onSave={(value) => void save(row.key, value)} onSaveDraft={() => void saveDraft(row.key)} onReset={() => void reset(row.key)} />;

  const changeSection = (next: string) => { setSection(next); setError(""); };

  const rows = useMemo(() => (view?.settings ?? []).filter((row) => row.group === section), [view, section]);
  const restartCount = (view?.settings ?? []).filter((row) => row.restart_required).length;

  if (!open) return null;
  const groupLabel = view?.groups.find((group) => group.id === section)?.label
    ?? EXTRA_SECTIONS.find((item) => item.id === section)?.label ?? "";

  return (
    <div className="settings-veil" role="dialog" aria-modal="true" aria-label={t("설정")}>
      <div className="settings-screen">
        <nav className="settings-nav" aria-label={t("설정 분류")}>
          <header>
            <strong>{t("설정")}</strong>
          </header>
          <p className="settings-nav-label">{t("설정")}</p>
          {(view?.groups ?? []).map((group) => (
            <button key={group.id} type="button" className={`settings-nav-item${section === group.id ? " active" : ""}`} onClick={() => changeSection(group.id)}>
              {GROUP_ICON[group.id] ?? <Settings2 size={15} />}<span>{group.label}</span>
            </button>
          ))}
          {[t("사용자 지정"), t("데스크톱 앱")].map((heading) => (
            <div key={heading}>
              <p className="settings-nav-label">{heading}</p>
              {EXTRA_SECTIONS.filter((item) => item.heading === heading).map((item) => (
                <button key={item.id} type="button" className={`settings-nav-item${section === item.id ? " active" : ""}`} onClick={() => changeSection(item.id)}>
                  {item.icon}<span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        <section className="settings-body" aria-labelledby="settings-title">
          <header className="settings-head">
            <h2 id="settings-title">{groupLabel}</h2>
            {restartCount > 0 && (
              <span className="settings-restart"><RotateCcw size={13} /> {t("다시 시작해야 적용되는 값")} {restartCount}{t("개")}</span>
            )}
            <button className="settings-close" type="button" onClick={() => void requestClose()} disabled={isClosing} aria-label={t("설정 닫기")}><X size={16} /></button>
          </header>
          {error && <p className="settings-error" role="alert">{error}</p>}
          {!view && !error && <p className="settings-note"><Loader2 size={14} className="spin" /> {t("설정을 읽는 중입니다")}</p>}

          {section === "skills" && client && (
            <div className="settings-block">
              <h3>{t("주로 무엇에 쓰시나요")}</h3>
              <SkillDomainPicker
                load={() => client.getSkillDomains()}
                apply={async (domains) => {
                  const next = await client.applySkillDomains(domains);
                  setView(await client.getSettings());
                  return next;
                }}
              />
            </div>
          )}
          {section === "model" && (
            // 목록이 먼저다 — 태그를 적는 칸 세 개가 위에 있어 새 목록이 화면 밖으로 밀렸다(2026-09-17 E2E 캡처).
            <ModelSection api={setupApi} onChanged={() => window.dispatchEvent(new Event("ontelic:model-changed"))} />
          )}
          {view && rows.length > 0 && section === "model" && (
            <details className="settings-advanced">
              <summary>{t("모델 이름을 직접 적기 (고급)")}</summary>
              <ul className="settings-rows">
                {rows.map(control)}
              </ul>
            </details>
          )}
          {/* 언어는 맨 위 「일반」에 — 「앱」 구역은 영어로 「Diagnostics · restart」라 거기서 찾지 않는다. */}
          {section === "general" && <LanguageBlock />}
          {view && rows.length > 0 && section !== "model" && (
            <ul className="settings-rows">
              {rows.filter((row) => !(section === "skills" && row.key === "skills_domains")).map(control)}
            </ul>
          )}
          {section === "permissions" && client && <GrantedPaths client={client} />}
          {section === "memory" && (
            <div className="settings-block"><LearnedPanel client={client} open /></div>
          )}

          {section === "about_me" && <AboutMeSection api={setupApi} />}
          {section === "packs" && client && <PacksSection client={client} />}
          {section === "connect" && <div className="settings-block"><ConnectPanel api={setupApi} /></div>}
          {section === "discord" && client && <DiscordSection client={client} />}
          {section === "import" && <ImportSection api={setupApi} />}
          {section === "data" && client && <DataSection client={client} />}
          {section === "app" && client && <AppSection client={client} onClose={() => void requestClose()} />}
        </section>
      </div>
    </div>
  );
}

function GrantedPaths({ client }: { client: JarvisClient }) {
  const [paths, setPaths] = useState<{ read: string[]; write: string[] } | null>(null);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState("");

  useEffect(() => {
    let alive = true;
    client.getGrantedPaths()
      .then((next) => { if (alive) setPaths(next); })
      .catch(() => { if (alive) setError(t("승인된 폴더 목록을 읽지 못했습니다.")); });
    return () => { alive = false; };
  }, [client]);

  const revoke = async (path: string, mode: "read" | "write") => {
    setRemoving(`${mode}:${path}`);
    setError("");
    try {
      const result = await client.revokeGrantedPath(path, mode);
      if (!result.ok) throw new Error(t("이미 승인 목록에서 사라졌습니다."));
      setPaths(result.granted_paths);
    } catch {
      setError(t("승인을 지우지 못했습니다. 다시 열어 확인해 주세요."));
    } finally {
      setRemoving("");
    }
  };

  return <div className="settings-block">
    <h3>{t("승인해 준 폴더")}</h3>
    <p className="settings-note">{t("승인 카드로 추가한 폴더만 표시합니다. 위의 직접 설정한 폴더와는 별개입니다. 지우면 다음 접근부터 막힙니다.")}</p>
    {error && <p className="settings-error" role="alert">{error}</p>}
    {!paths && !error && <p className="settings-note">{t("목록을 읽는 중입니다")}</p>}
    {paths && (paths.read.length || paths.write.length ? (["read", "write"] as const).map((mode) =>
      <div key={mode}>
        <h4>{mode === "read" ? t("읽기 승인") : t("쓰기 승인")}</h4>
        <ul className="settings-list">
          {paths[mode].map((path) => <li key={path}>
            <code>{path}</code>{" "}
            <button type="button" className="setup-btn-quiet" disabled={Boolean(removing)}
              aria-label={t("{0} 승인 지우기: {1}", mode === "read" ? t("읽기") : t("쓰기"), path)}
              onClick={() => void revoke(path, mode)}>{t("승인 지우기")}</button>
          </li>)}
        </ul>
      </div>
    ) : <p className="settings-note">{t("승인 카드로 추가한 폴더가 없습니다.")}</p>)}
  </div>;
}

const SAVED_BUT_GOOGLE_FAILED = () => t("설정은 저장했습니다. Google 권한 연결을 완료하지 못했습니다. 연결 메뉴에서 다시 연결해 주세요.");

export function settingErrorText(message: string): string {
  if (/Failed to fetch|NetworkError|Load failed|fetch failed|ECONNREFUSED|network request failed/i.test(message)) {
    return t("Sonjari 서버에 연결하지 못했습니다. 앱이 실행 중인지 확인한 뒤 다시 저장해 주세요.");
  }
  // 이미 사람이 읽을 문장(저장은 됐고 구글만 못 이음)은 그대로 — 화면 언어에 따라 글이 달라서 같은 문장과 비교한다.
  if (message === SAVED_BUT_GOOGLE_FAILED()) return message;
  message = message.replace(/^Error:\s*/, "");
  const code = message.replace(/^\d+\s*/, "").replace(/^\{"detail":"?|"?\}$/g, "");
  const [kind] = code.split(":");
  switch (kind) {
    case "too_small": return t("허용 범위보다 작습니다.");
    case "too_large": return t("허용 범위보다 큽니다.");
    case "expected_int": return t("숫자로 적어 주세요.");
    case "too_long": return t("너무 깁니다.");
    case "empty_model": return t("모델 이름을 비울 수 없습니다.");
    case "not_allowed": return t("이 화면에서는 바꿀 수 없는 값입니다.");
    default: return t("저장하지 못했습니다: {0}", message);
  }
}

export function settingDraftValue(row: SettingRow, draft: string): SettingValue {
  if (row.kind === "int") {
    if (!draft.trim() || !Number.isFinite(Number(draft)) || !Number.isInteger(Number(draft))) throw new Error("expected_int");
    return Number(draft);
  }
  if (row.kind === "list") return draft.split("\n").map((line) => line.trim()).filter(Boolean);
  return draft.trim();
}

function SettingControl({ row, status, draft, onDraft, onSaveDraft, onSave, onReset }: {
  row: SettingRow;
  status?: FieldStatus;
  draft: string;
  onDraft: (text: string) => void;
  onSaveDraft: () => void;
  onSave: (value: SettingValue) => void;
  onReset: () => void;
}) {
  const busy = status?.state === "saving";
  const id = `setting-${row.key}`;
  // 이 판에 그 기능이 안 실려 있으면 **켜짐으로 보이면 안 된다.** 사람은 자기가 뭘 잘못한 줄 안다
  // (2026-09-18 노트북: 「소리 내어 답하기 켜짐」인데 한마디도 못 했다).
  const unavailable = String(row.unavailable || "");
  return (
    <li className={`settings-row${row.restart_required ? " is-pending" : ""}${unavailable ? " is-unavailable" : ""}`}>
      <div className="settings-row-text">
        <label htmlFor={id}>{row.label}{row.lab && <em className="settings-lab">{t("실험실")}</em>}</label>
        {row.help && <small>{row.help}</small>}
        {unavailable && <small className="settings-unavailable">{unavailable}</small>}
        <span className="settings-source">
          {unavailable ? t("이 판에서는 못 씁니다") : describeSource(row)}
          {row.source === "user" && !unavailable && (
            <button type="button" className="settings-reset" onClick={onReset} disabled={busy}><Undo2 size={12} /> {t("기본값으로")}</button>
          )}
        </span>
      </div>
      <div className="settings-row-control">
        {busy && <Loader2 size={14} className="spin" aria-label={t("저장하는 중")} />}
        {row.kind === "bool" && (
          <button id={id} type="button" role="switch" aria-checked={unavailable ? false : Boolean(row.value)} disabled={busy || !!unavailable}
            className={`settings-switch${!unavailable && row.value ? " is-on" : ""}`} onClick={() => onSave(!row.value)}>
            <span />
          </button>
        )}
        {row.kind === "choice" && (
          <select id={id} value={String(row.value)} disabled={busy || !!unavailable} onChange={(event) => onSave(event.target.value)}>
            {row.choices.map((choice) => <option key={choice} value={choice}>{choiceLabel(row.key, choice)}</option>)}
          </select>
        )}
        {(row.kind === "str" || row.kind === "model" || row.kind === "int") && (
          <input id={id} type={row.kind === "int" ? "number" : "text"} value={draft} disabled={busy || !!unavailable}
            min={row.min ?? undefined} max={row.max ?? undefined}
            aria-describedby={status ? `${id}-status` : undefined}
            onChange={(event) => onDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onSaveDraft(); } }} />
        )}
        {row.kind === "list" && (
          <textarea id={id} value={draft} rows={Math.min(6, Math.max(2, draft.split("\n").length))} disabled={busy || !!unavailable}
            aria-describedby={status ? `${id}-status` : undefined}
            onChange={(event) => onDraft(event.target.value)} placeholder={t("한 줄에 하나씩")} />
        )}
        {["str", "model", "int", "list"].includes(row.kind) && (
          <button type="button" className="settings-save" disabled={busy || !!unavailable || draft === draftOf(row)} onClick={onSaveDraft}>{t("저장")}</button>
        )}
        {status && <span id={`${id}-status`} className={`settings-field-status is-${status.state}`}
          role={status.state === "error" ? "alert" : "status"} aria-live="polite">{status.message}</span>}
      </div>
    </li>
  );
}

function draftOf(row: SettingRow): string {
  if (Array.isArray(row.value)) return row.value.join("\n");
  return row.value === null || row.value === undefined ? "" : String(row.value);
}

function choiceLabel(key: string, choice: string): string {
  if (key === "ollama_num_ctx") return `${Math.round(Number(choice) / 1024)}K`;
  if (key === "agent_thinking_policy") return THINKING_LABELS[choice] ?? choice;
  return choice;
}

const THINKING_LABELS: Record<string, string> = {
  off: t("빠르게"),
  adaptive: t("보통"),
  always: t("깊게"),
};

function ImportSection({ api }: { api: SetupApi | null }) {
  const imp = useInstructionImport(api);
  return (
    <div className="settings-block settings-import">
      <ImportPanel imp={imp} />
      <ImportPreview imp={imp} />
    </div>
  );
}

export function DataSection({ client }: { client: JarvisClient }) {
  const [backup, setBackup] = useState<BackupSummary | null>(null);
  const [message, setMessage] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => client.getBackup().then(setBackup).catch((reason) => setMessage(String(reason))), [client]);
  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    try {
      setMessage(await work());
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-block">
      <h3>{t("기억 복제본")}</h3>
      <p className="settings-note">
        {t("앱을 지워도 대화와 배운 사실이 남도록 사용자 폴더에 복제본을 둡니다(최근")} {backup?.keep ?? 3}{t("개). 토큰·구글 연결·브라우저 기록·모델은 담지 않습니다.")}
      </p>
      {backup && !backup.enabled && <p className="settings-note">{t("지금은 꺼져 있습니다. 「메모리 › 기억 복제본 두기」에서 켤 수 있습니다.")}</p>}
      {backup?.enabled && (
        <>
          <p className="settings-path"><code>{backup.root}</code></p>
          <ul className="settings-generations">
            {backup.generations.length === 0 && <li>{t("아직 복제본이 없습니다.")}</li>}
            {backup.generations.map((row) => (
              <li key={row.generation}>
                <span className="tabular">{new Date(row.created_at * 1000).toLocaleString()}</span>
                <span>{reasonLabel(row.reason)}</span>
                <span className="tabular">{t("대화")} {row.tables.conversation_messages ?? 0}{t("줄 · 사실")} {row.tables.facts ?? 0}{t("개")}</span>
              </li>
            ))}
          </ul>
          <div className="settings-actions">
            <button type="button" className="setup-btn-go" disabled={busy}
              onClick={() => void run(async () => ((await client.backupNow()).ok ? t("지금 복제본을 만들었습니다.") : t("만들지 못했습니다.")))}>
              {t("지금 백업")}
            </button>
            <button type="button" className="setup-btn-quiet" onClick={() => void client.openFolder("backup")}>{t("폴더 열기")}</button>
          </div>
          <div className="settings-danger">
            <h4>{t("백업까지 지우기")}</h4>
            <p>
              {t("앱을 지울 때 스토어는 앱 안의 데이터만 지웁니다. 사용자 폴더의 복제본까지 없애려면 여기서 지우세요. 지우면 되살릴 수 없습니다. 지금 대화 기록은 그대로 남습니다.")}
            </p>
            {!confirming ? (
              <button type="button" className="settings-stop" disabled={busy || !backup.generations.length} onClick={() => setConfirming(true)}>
                {t("복제본")} {backup.generations.length}{t("개 지우기…")}
              </button>
            ) : (
              <div className="settings-actions">
                <button type="button" className="settings-stop" disabled={busy}
                  onClick={() => void run(async () => {
                    const done = await client.deleteBackups(backup.delete_confirmation);
                    setConfirming(false);
                    return done.ok ? t("복제본 {0}개를 지웠습니다.", done.removed?.length ?? 0) : t("지우지 못했습니다.");
                  })}>
                  {t("정말 지우기")}
                </button>
                <button type="button" className="setup-btn-quiet" onClick={() => setConfirming(false)}>{t("그만두기")}</button>
              </div>
            )}
          </div>
        </>
      )}
      <h3>{t("데이터 폴더")}</h3>
      <div className="settings-actions">
        <button type="button" className="setup-btn-quiet" onClick={() => void client.openFolder("data")}>{t("데이터 폴더 열기")}</button>
      </div>
      {message && <p className="settings-note" aria-live="polite">{message}</p>}
    </div>
  );
}

function reasonLabel(reason: string): string {
  return { shutdown: t("앱 닫을 때"), daily: t("하루 한 번"), manual: t("직접") }[reason] ?? reason;
}

function AppSection({ client, onClose }: { client: JarvisClient; onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [diagnostic, setDiagnostic] = useState("");
  const [startup, setStartup] = useState<string>("");
  const [build, setBuild] = useState("");

  useEffect(() => {
    client.getHealth().then((health) => setBuild(health.build ?? "")).catch(() => setBuild(""));
  }, [client]);

  useEffect(() => {
    if (!isTauri()) {
      setStartup("unpackaged");
      return;
    }
    invoke<{ state: string }>("startup_task", { enable: null }).then((next) => setStartup(next.state)).catch(() => setStartup("error"));
  }, []);

  return (
    <div className="settings-block">
      <h3>{t("진단 내보내기")}</h3>
      <p className="settings-note">{t("문제를 알릴 때 쓸 파일을 이 PC 에 만듭니다. 어디로도 보내지 않습니다. 대화·파일·토큰은 담지 않고 사용자 폴더 이름은 가립니다.")}</p>
      <div className="settings-actions">
        <button type="button" className="setup-btn-go" onClick={() => void client.exportDiagnostics()
          .then((made) => setDiagnostic(made.path)).catch((reason) => setMessage(String(reason)))}>
          {t("진단 파일 만들기")}
        </button>
        {diagnostic && <button type="button" className="setup-btn-quiet" onClick={() => void client.openFolder("diagnostics")}>{t("폴더 열기")}</button>}
      </div>
      {diagnostic && <p className="settings-path"><code>{diagnostic}</code></p>}

      <h3>{t("첫 실행 다시 하기")}</h3>
      <p className="settings-note">{t("PC 확인 · 모델 · 쓰임 · 연결을 처음부터 다시 봅니다. 대화·기억·설정은 지우지 않습니다.")}</p>
      <div className="settings-actions">
        <button type="button" className="setup-btn-quiet" onClick={() => void client.resetSetupState().then(async () => {
          if (isTauri()) {
            await invoke("open_setup");
            onClose();
          } else {
            window.location.search = "?mode=setup";
          }
        }).catch((reason) => setMessage(String(reason)))}>
          {t("첫 실행 다시 하기")}
        </button>
      </div>

      {/* F2 · G4 — 제거가 제품 흐름의 마지막 칸이다. 무엇이 남는지 말하지 않으면 수 GB 가 조용히 남는다. */}
      <h3>{t("앱을 지우면")}</h3>
      <ul className="settings-note settings-list">
        <li>{t("스토어가 앱 안의 데이터(대화·설정·Sonjari가 설치한 Ollama)를 지웁니다.")}</li>
        <li>{t("남는 것 ①")} <strong>{t("기억 복제본")}</strong> {t("— 사용자 폴더에 둡니다. 「데이터」에서 지울 수 있습니다.")}</li>
        <li>{t("남는 것 ②")} <strong>{t("받은 AI 모델 파일")}</strong> {t("— Ollama 모델 폴더(보통")} <code>%USERPROFILE%\.ollama\models</code>{t("), 모델마다 수 GB 입니다. 다른 앱과 같이 쓰는 폴더라 Sonjari가 지우지 않습니다.")}</li>
        <li>{t("따로 설치해 쓰던 Ollama 는 그대로입니다.")}</li>
      </ul>

      <h3>{t("Windows 시작 시 켜기")}</h3>
      {startup === "unpackaged" && <p className="settings-note">{t("이 설치는 스토어 패키지가 아니라서 시작 프로그램을 여기서 바꾸지 않습니다.")}</p>}
      {startup && startup !== "unpackaged" && (
        <div className="settings-actions">
          <span className="settings-note">{startupLabel(startup)}</span>
          {(startup === "disabled" || startup === "enabled") && (
            <button type="button" className="setup-btn-quiet" onClick={() => void invoke<{ state: string }>("startup_task", { enable: startup !== "enabled" })
              .then((next) => setStartup(next.state)).catch(() => setStartup("error"))}>
              {startup === "enabled" ? t("끄기") : t("켜기")}
            </button>
          )}
        </div>
      )}
      {/* F2 · G7 — 앱 정보. 목록은 packaging/THIRD_PARTY_NOTICES.md 와 같은 순서·같은 라이선스로 둔다. */}
      <h3>{t("정보")}</h3>
      <dl className="settings-about">
        <div><dt>{t("앱")}</dt><dd>Sonjari · RoboMetaFit</dd></div>
        <div><dt>{t("빌드")}</dt><dd><code>{build || t("확인 중")}</code></dd></div>
        <div><dt>{t("제3자 구성요소")}</dt><dd>
          {t("Ollama(MIT, 첫 실행에서 받음) · CPython(PSF) · Tauri(Apache-2.0/MIT) · WebView2(Microsoft) · 스킬 묶음(각 폴더의 LICENSE·SOURCE.json — MIT·Apache-2.0·CC-BY-4.0)")}
        </dd></div>
      </dl>
      {message && <p className="settings-error" role="alert">{message}</p>}
      <p className="settings-foot"><MessagesSquare size={13} /> {t("설정 파일은")} <code>data/settings.json</code> {t("한 곳에 삽니다.")}</p>
    </div>
  );
}

export function startupLabel(state: string): string {
  return {
    enabled: t("켜져 있습니다."),
    disabled: t("꺼져 있습니다."),
    disabled_by_user: t("작업 관리자 › 시작 앱에서 꺼 두셨습니다. 거기서 켜야 합니다."),
    disabled_by_policy: t("회사 정책으로 꺼져 있습니다."),
    enabled_by_policy: t("회사 정책으로 켜져 있습니다."),
    error: t("상태를 읽지 못했습니다."),
  }[state] ?? state;
}


/** 화면 언어 — 고르면 화면을 다시 띄운다(모듈이 읽힐 때 만든 문구까지 새 언어로). 처음 값은 윈도우 언어를 따른다. */
function LanguageBlock() {
  const current = lang();
  const choose = (next: Lang) => {
    if (next !== current) setLang(next);
  };
  return <div className="settings-block">
    <h3>{t("화면 언어")}</h3>
    <p className="settings-note">{t("바꾸면 화면을 다시 엽니다. 처음에는 윈도우 언어를 따릅니다.")}</p>
    <div className="settings-lang" role="radiogroup" aria-label={t("화면 언어")}>
      {(["ko", "en"] as const).map((code) => (
        <button key={code} type="button" role="radio" aria-checked={current === code}
          className={`settings-lang-option${current === code ? " active" : ""}`} onClick={() => choose(code)}>
          {code === "ko" ? "한국어" : "English"}
        </button>
      ))}
    </div>
  </div>;
}
