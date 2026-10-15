/**
 * 첫 실행 3단계 — 클로드·코덱스·커서에서 자비스를 쓰게 잇는다 (전략안 §43 P5).
 *
 * 다른 프로그램의 설정 파일에 한 줄을 더하는 일이라, 무엇을 하는지 먼저 말하고 사람이 누른다.
 * 원래 설정은 백업하고, 풀기 버튼으로 되돌린다. 토큰은 어느 설정에도 넣지 않는다.
 * 모양은 가져오기 칸(`imp-*`)을 그대로 쓴다 — 같은 화면 안에서 두 칸이 달라 보이면 안 된다.
 */
import { t } from "../i18n";
import { Plug } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { pollUnlessBusy } from "./poll";
import type {
  ConnectClient,
  ConnectClientId,
  ConnectRestartResult,
  ConnectResult,
  ConnectScan,
  GuideSkillAction,
  GuideSkillResult,
  GuideSkillStatus,
  SetupApi,
} from "./setupApi";

function errorText(result: ConnectResult): string {
  switch (result.error) {
    case "claude_desktop_did_not_close":
      return t("Claude 가 꺼지지 않았습니다. 작업 표시줄 오른쪽 구석의 Claude 아이콘을 오른쪽 클릭해 「종료」를 누른 뒤 다시 눌러 주세요.");
    case "claude_desktop_running":
      return t("Claude Desktop 이 켜져 있어 지금 바꾸면 앱이 종료하면서 덮어씁니다. 앱을 완전히 종료(트레이 아이콘까지)한 뒤 「다시 확인」을 눌러 주세요.");
    case "cli_missing":
      return t("claude 명령을 찾지 못했습니다. Claude Code 를 쓰지 않는다면 이 줄은 건너뛰어도 됩니다. 쓰신다면 설치한 뒤 다시 누르거나, 아래 설정을 직접 붙여 넣으세요.");
    case "config_not_json":
      return t("설정 파일이 올바른 JSON 이 아니라 손대지 않았습니다. 그 파일을 먼저 고친 뒤 다시 눌러 주세요.");
    case "config_not_toml":
    case "would_break_toml":
      return t("Codex 설정 파일(config.toml)을 읽을 수 없어 손대지 않았습니다. 파일을 먼저 고친 뒤 다시 눌러 주세요.");
    case "not_installed":
      return t("이 PC 에 설치되어 있지 않습니다.");
    case "msix_new_file_hidden":
      // 스토어 앱이 AppData 에 새로 만든 파일은 앱 전용 칸으로 가서 Claude 가 못 본다(W1-5 실측).
      return t("Claude Desktop 설정 파일이 아직 없어 Sonjari가 만들면 Claude 에 보이지 않습니다. Claude Desktop 을 한 번 켰다 끈 뒤 다시 누르거나, 아래 설정을 직접 붙여 넣으세요.");
    case "cli_failed":
      return t("명령이 실패했습니다: {0}", result.detail ?? "");
    default:
      return result.error ? t("잇지 못했습니다: {0}", result.error) : "";
  }
}

function statusNote(client: ConnectClient): { tone: "quiet" | "ok" | "signal"; text: string } {
  if (!client.installed) return { tone: "quiet", text: t("설치 안 됨") };
  if (client.registered) return { tone: "ok", text: t("연결됨") };
  if (client.waiting_for_close) return { tone: "signal", text: t("Claude Desktop 을 닫으면 바로 잇습니다") };
  if (client.running) return { tone: "quiet", text: t("켜져 있음 · 누르면 닫는 순간 잇습니다") };
  if (client.reason === "cli_missing") return { tone: "signal", text: t("명령을 찾지 못함 · 직접 붙여 넣기") };
  if (client.reason === "msix_new_file_hidden") return { tone: "signal", text: t("설정 파일이 아직 없음 · 직접 붙여 넣기") };
  return { tone: "quiet", text: t("아직 안 이음") };
}

/** 켜져 있어서 아직 못 이은 Claude Desktop — 「닫고 · 잇고 · 다시 켜기」를 권할 자리. */
export function desktopAwaitingRestart(scan: ConnectScan | null): ConnectClient | null {
  const client = scan?.clients.find((item) => item.id === "claude_desktop");
  if (!client || !client.installed || client.registered || !client.can_apply) return null;
  return client.running || client.waiting_for_close ? client : null;
}

/**
 * 「Claude 를 다시 켤까요?」 (2026-10-12).
 *
 * 처음 깐 두 사람이 같은 자리에서 헤맸다 — 「Claude 를 껐다 켜라」는 글로만 있었고, 창의 X 는 앱을 끄지 않고 작업 표시줄
 * 구석에 남긴다. 글로 시키지 않고 손자리가 대신 한다. 다만 그 앱에서 돌던 일이 끊기니 **묻고, 누른 뒤에만** 한다.
 * `doneLabel` 은 이은 뒤의 단추 이름이다 — 첫 설정에서는 「Sonjari 시작하기」, 설정 화면에서는 「닫기」.
 */
export function ClaudeRestartDialog({ api, doneLabel, onDone, onClose }: {
  api: SetupApi; doneLabel: string; onDone: (result: ConnectRestartResult) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ConnectRestartResult | null>(null);
  const [failed, setFailed] = useState("");

  const go = async () => {
    setBusy(true);
    setFailed("");
    try {
      setResult(await api.connectRestartDesktop());
    } catch (err) {
      setFailed(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const reopened = result?.desktop === "restarted";
  return (
    <div className="settings-veil report-veil" role="dialog" aria-modal="true" aria-label={t("Claude 를 다시 켤까요?")}
      onClick={busy ? undefined : onClose}>
      <section className="report-dialog cx-restart" onClick={(event) => event.stopPropagation()}>
        <header>
          {/* 끝난 뒤에도 묻는 제목이 남아 있으면 또 눌러야 하는 줄 안다 — 된 일을 제목으로 바꾼다. */}
          <strong>{result?.ok ? t("Claude 에 이었습니다") : t("Claude 를 다시 켤까요?")}</strong>
        </header>
        {result?.ok ? (
          <>
            <p className="setup-done" role="status">
              {reopened
                ? t("이었습니다. Claude 가 다시 켜지고 있습니다.")
                : result.desktop === "closed_only"
                  ? t("이었습니다. Claude 는 직접 다시 켜 주세요.")
                  : t("이었습니다. Claude 를 켜면 Sonjari가 보입니다.")}
            </p>
            <div className="cx-restart-actions">
              <button type="button" className="setup-btn-go" onClick={() => onDone(result)}>{doneLabel}</button>
            </div>
          </>
        ) : (
          <>
            <p className="report-lead">
              {t("Sonjari를 이으려면 Claude 앱을 완전히 껐다가 다시 켜야 합니다. 누르면 Sonjari가 Claude 를 닫고, 잇고, 다시 켭니다.")}
            </p>
            <p className="cx-restart-warn">
              {t("Claude 가 지금 답을 쓰는 중이거나 코드 작업을 돌리고 있으면 끊깁니다. 끝난 뒤에 눌러 주세요.")}
            </p>
            {result && !result.ok && (
              <p className="setup-warn" role="alert">
                {errorText(result)}
                {result.desktop === "restarted" ? ` ${t("Claude 는 다시 켜 두었습니다.")}` : ""}
              </p>
            )}
            {result?.manual && <pre className="cx-manual">{result.manual}</pre>}
            {failed && <p className="setup-warn" role="alert">{t("하지 못했습니다: {0}", failed)}</p>}
            <div className="cx-restart-actions">
              <button type="button" className="setup-btn-go" disabled={busy} onClick={() => void go()}>
                {busy ? t("Claude 를 닫고 잇는 중입니다…") : t("닫고 · 잇고 · 다시 켜기")}
              </button>
              <button type="button" className="setup-btn-quiet" disabled={busy} onClick={onClose}>{t("나중에")}</button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

/**
 * 가이드 스킬 (인수인계 H1-b). 연결만 하면 Claude 는 도구 이름만 보고 온텔릭이 뭔지 추측한다 —
 * 스킬이 「언제 맡기고 결과를 어떻게 전하는지」를 알려 준다. Claude Code 는 폴더에 넣으면 끝,
 * Claude Desktop 은 사용자가 zip 을 올려야 한다(앱이 폴더를 안 읽는다) — 올린 척하지 않고 올릴 곳을 말한다.
 */
function GuideSkillRow({ api, busy, setBusy, auto = false }: {
  api: SetupApi; busy: string; setBusy: Dispatch<SetStateAction<string>>; auto?: boolean;
}) {
  const [status, setStatus] = useState<GuideSkillStatus | null>(null);
  const [result, setResult] = useState<GuideSkillResult | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.guideSkillStatus());
    } catch {
      setStatus(null);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  // 첫 실행에서는 Claude Code 가이드를 알아서 넣는다 — 폴더에 넣는 것이 곧 설치라 사람이 누를 이유가 없다.
  const autoGuide = useRef(false);
  useEffect(() => {
    if (!auto || !status || autoGuide.current) return;
    autoGuide.current = true;
    const code = status.claude_code;
    if (code.available && !code.installed && !code.foreign) void run("install_claude_code");
  }, [auto, status]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (action: GuideSkillAction) => {
    setBusy(`guide:${action}`);
    try {
      const done = await api.guideSkill(action);
      setResult(done);
      if (done.ok && action === "build_zip") await api.openGuideSkillFolder();
      await load();
    } finally {
      // ★ 자기 것일 때만 푼다 — 가이드 넣기가 끝나며 잇기의 「잇는 중…」까지 지워 버렸다(2026-09-17 E2E).
      setBusy((current) => (current === `guide:${action}` ? "" : current));
    }
  };

  if (!status) return null;
  const code = status.claude_code;
  return (
    <div className="cx-guide">
      <h3>{t("가이드 스킬 ·")} {status.name}</h3>
      <p className="imp-hint">
        {t("Claude 가 Sonjari에게 언제 일을 맡기고, 결과의 확인 안 된 숫자를 어떻게 전하는지 알려 주는 스킬입니다. 지금 켜진 도구 목록으로 만듭니다.")}
      </p>
      <ul className="imp-list">
        <li className={`imp-row${code.available ? "" : " is-off"}`}>
          <span className="imp-name">
            <b>Claude Code</b>
            <span className={`imp-note is-${code.installed ? "ok" : code.foreign ? "signal" : "quiet"}`}>
              {/* ★ 이 줄은 **안내 파일**의 상태다. 「설치됨」이라 적었더니 바로 위의 「Claude Code — 명령을 찾지 못함」과
                  나란히 떠서 「설치됐다면서 왜 못 찾나」로 읽혔다(2026-10-06 첫 설치). 프로그램의 설치와 다른 말을 쓴다. */}
              {code.installed ? t("안내 파일 넣음") : code.foreign ? t("같은 이름의 다른 스킬이 있어 건드리지 않습니다") : code.available ? t("아직 안 넣음") : t("Claude Code 없음 · 넣을 곳 없음")}
            </span>
          </span>
          <span className="imp-row-actions">
            {code.installed && (
              <button type="button" className="imp-link is-stop" onClick={() => void run("remove_claude_code")} disabled={busy !== ""}>
                {t("빼기")}
              </button>
            )}
            {code.available && !code.foreign && (
              <button type="button" className="imp-link" onClick={() => void run("install_claude_code")} disabled={busy !== ""}>
                {busy === "guide:install_claude_code" ? t("넣는 중…") : code.installed ? t("새 도구로 다시 만들기") : t("넣기")}
              </button>
            )}
          </span>
        </li>
        <li className="imp-row">
          <span className="imp-name">
            <b>Claude Desktop</b>
            <span className="imp-note is-quiet">
              {t("Sonjari를 연결하면 언제·어떻게 부르는지 요약은 자동으로 들어갑니다. 자세한 가이드는 Claude 가 PC 폴더를 읽지 않아 계정에 올려야 합니다 — zip 을 만들고 폴더를 열어 드리면, Claude Desktop 의 사용자 지정 › 스킬 › + › 스킬 업로드에서 그 zip 을 고르세요.")}
            </span>
          </span>
          <span className="imp-row-actions">
            <button type="button" className="imp-link" onClick={() => void run("build_zip")} disabled={busy !== ""}>
              {busy === "guide:build_zip" ? t("만드는 중…") : t("zip 만들기")}
            </button>
          </span>
        </li>
      </ul>
      {result && !result.ok && (
        <p className="setup-warn">
          {result.error === "foreign_skill_exists" ? t("같은 이름의 스킬이 이미 있어 덮지 않았습니다.") : t("하지 못했습니다: {0}", result.error ?? "")}
        </p>
      )}
    </div>
  );
}

/**
 * `autoConnect` — 첫 실행에서는 **Claude(Desktop·Code)를 알아서 잇는다**(2026-09-16 제품 요청: 「클로드에 온텔릭 지침
 * 넣기까지 한 번에」). 설치돼 있고 아직 안 이었으면 누른 것처럼 잇는다. Desktop 이 켜져 있으면 닫히는 순간 잇는다.
 * 원래 설정은 백업하고 「풀기」로 되돌린다 — 사람 대신 누른 것이라 되돌리는 길이 같은 자리에 있어야 한다.
 */
export function ConnectPanel({ api, autoConnect = false, onScan }: {
  api: SetupApi | null; autoConnect?: boolean;
  /** 찾은 것이 바뀔 때마다 — 첫 설정의 금색 단추가 「잇고 시작하기」로 바뀔지 여기서 안다. */
  onScan?: (scan: ConnectScan) => void;
}) {
  const [scan, setScan] = useState<ConnectScan | null>(null);
  const [restartOpen, setRestartOpen] = useState(false);
  const [busy, setBusy] = useState<string>("");
  // ★ 2026-09-17 E2E 2판: 뒤에서 Claude Code 를 잇는 동안 가이드 넣기가 같은 바쁨 칸을 덮어써 「잇기」로 보였다 —
  //   사람이 또 누르면 두 번 잇는다. 잇는 중인 도구는 따로 들고 있는다.
  const [connecting, setConnecting] = useState<ConnectClientId[]>([]);
  const [messages, setMessages] = useState<Partial<Record<ConnectClientId, ConnectResult>>>({});
  const [verify, setVerify] = useState<{ ok: boolean; tool_count?: number; error?: string } | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!api) return;
    try {
      setScan(await api.connectScan());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (scan) onScan?.(scan);
  }, [scan]); // eslint-disable-line react-hooks/exhaustive-deps

  const autoDone = useRef(false);
  useEffect(() => {
    if (!autoConnect || !api || !scan || autoDone.current) return;
    autoDone.current = true;
    const targets = scan.clients.filter(
      (client) => (client.id === "claude_desktop" || client.id === "claude_code")
        && client.installed && !client.registered && client.can_apply && !client.waiting_for_close,
    );
    void (async () => {
      for (const client of targets) await change(client, true);
    })();
  }, [autoConnect, api, scan]); // eslint-disable-line react-hooks/exhaustive-deps

  // 닫히기를 기다리는 동안은 몇 초마다 다시 본다 — 이어지면 「연결됨」으로 바뀐다.
  const waiting = scan?.clients.some((client) => client.waiting_for_close) ?? false;
  useEffect(() => {
    if (!waiting) return;
    return pollUnlessBusy(refresh, 3000);
  }, [waiting, refresh]);

  const change = async (client: ConnectClient, add: boolean) => {
    if (!api || connecting.includes(client.id)) return;
    setConnecting((current) => [...current, client.id]);
    setBusy(client.id);
    try {
      const result = add ? await api.connectApply(client.id) : await api.connectRemove(client.id);
      setMessages((current) => ({ ...current, [client.id]: result }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy((current) => (current === client.id ? "" : current));
      setConnecting((current) => current.filter((id) => id !== client.id));
    }
  };

  const runVerify = async () => {
    if (!api) return;
    setBusy("verify");
    try {
      setVerify(await api.connectVerify());
    } finally {
      setBusy("");
    }
  };

  const toggleHook = async (enabled: boolean) => {
    if (!api) return;
    setBusy("hook");
    try {
      await api.connectHook(enabled);
      await refresh();
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="imp" aria-labelledby="cx-title">
      <header className="imp-head">
        <h2 id="cx-title">{t("클로드·코덱스·커서에서 Sonjari 쓰기")}</h2>
        <p>
          {t("고른 도구의 설정 파일에 Sonjari 한 줄을 더합니다. 원래 설정은 백업하고, 「풀기」로 되돌립니다. 비밀번호·토큰은 설정에 넣지 않습니다.")}
        </p>
      </header>

      {!scan ? (
        <p className="imp-hint">{t("설치된 도구를 찾는 중입니다…")}</p>
      ) : (
        <ul className="imp-list">
          {scan.clients.map((client) => {
            const note = statusNote(client);
            const message = messages[client.id];
            return (
              <li key={client.id} className={`imp-row${client.installed ? "" : " is-off"}`}>
                {/* 로고 자리. 실제 로고는 각 사의 브랜드 가이드를 확인한 뒤에 넣는다(스토어 정책 11.2).
                    그 전까지는 이름 + 중립 아이콘 — 「공식 제휴」로 읽히지 않게 「연결」 문구만 쓴다. */}
                <span className="firstrun-logo" data-logo-slot={client.id} aria-hidden="true">
                  <Plug size={16} strokeWidth={1.6} />
                </span>
                <span className="imp-name">
                  <b>{client.name}</b>
                  <span className={`imp-note is-${note.tone}`}>{note.text}</span>
                  {message && !message.ok && <span className="imp-note is-signal">{errorText(message)}</span>}
                  {message?.ok && message.backups && message.backups.length > 0 && (
                    <span className="imp-note is-quiet">{t("원래 설정 백업")} {message.backups.length}{t("개 · 그 도구를 다시 켜야 보입니다")}</span>
                  )}
                  {message?.manual && <pre className="cx-manual">{message.manual}</pre>}
                </span>
                <span className="imp-row-actions">
                  {/* 켜져 있어 못 이은 Claude Desktop — 닫히기를 기다리게만 두지 않는다(2026-10-12). */}
                  {client.id === "claude_desktop" && desktopAwaitingRestart(scan) && (
                    <button type="button" className="imp-link" onClick={() => setRestartOpen(true)} disabled={busy !== ""}>
                      {t("지금 닫고 잇기")}
                    </button>
                  )}
                  {client.installed && client.registered && (
                    <button type="button" className="imp-link is-stop" onClick={() => void change(client, false)} disabled={busy !== ""}>
                      {t("풀기")}
                    </button>
                  )}
                  {client.installed && !client.registered && (client.can_apply || client.reason === "cli_missing" || client.reason === "msix_new_file_hidden") && (
                    !client.waiting_for_close && (
                      connecting.includes(client.id)
                        ? <span className="imp-note is-signal">{t("잇는 중…")}</span>
                        : (
                          <button type="button" className="imp-link" onClick={() => void change(client, true)} disabled={busy !== ""}>
                            {client.running ? t("닫으면 잇기") : t("잇기")}
                          </button>
                        )
                    )
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {scan && (
        <>
          <div className="imp-actions">
            <button type="button" className="setup-btn-quiet" onClick={() => void runVerify()} disabled={busy !== ""}>
              {busy === "verify" ? t("Sonjari 연결을 띄워 보는 중…") : t("실제로 띄워 확인")}
            </button>
            {verify?.ok && <span className="setup-done">{t("Sonjari 도구")} {verify.tool_count}{t("개가 보입니다.")}</span>}
            {verify && !verify.ok && <span className="setup-warn">{t("띄우지 못했습니다:")} {verify.error}{t(". Sonjari가 켜져 있는지 확인해 주세요.")}</span>}
          </div>
          <label className="imp-check">
            <input
              type="checkbox"
              checked={scan.hooks.claude_code_session_start}
              disabled={!scan.hooks.can_apply || busy !== ""}
              onChange={(event) => void toggleHook(event.target.checked)}
            />
            {t("Claude Code 가 한도가 풀려 다시 열리면, 그동안 Sonjari가 이어서 한 일을 알려 주기")}
          </label>
          {api && <GuideSkillRow api={api} busy={busy} setBusy={setBusy} auto={autoConnect} />}
          {scan.not_supported.map((item) => (
            <p key={item.name} className="imp-hint">
              {item.name}: {item.reason}
            </p>
          ))}
        </>
      )}
      {error && (
        <p className="setup-error" role="alert">
          {error}
        </p>
      )}
      {restartOpen && api && (
        <ClaudeRestartDialog api={api} doneLabel={t("닫기")}
          onDone={() => { setRestartOpen(false); void refresh(); }}
          onClose={() => { setRestartOpen(false); void refresh(); }} />
      )}
    </section>
  );
}
