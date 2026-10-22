/**
 * 설정 › 디스코드로 일 시키기 (2026-10-18 대표 결정).
 *
 * 스토어로 깐 사람은 명령 창 마법사(`python -m alture_jarvis.messaging setup`)를 못 쓴다. 같은 단계를 사람 클릭 몇 번으로:
 *
 *     봇 만들기(토큰 복사) → 메시지 읽기 켜기(Intent) → 내 서버에 들이기 → 마무리 → 연결됨
 *
 * ## 지키는 것
 *
 * - **토큰은 화면을 지나지 않는다.** 입력칸이 없다 — 「토큰을 복사했어요」를 누르면 본체가 클립보드를 직접 읽는다.
 * - 어느 단계를 그릴지는 **백엔드의 `stage`** 가 정한다. 화면은 누른 대로 앞서 나가지 않는다.
 * - 단계 문은 실패해도 200 + {ok:false} 다. 백엔드 문장을 먼저 쓰고, 없을 때만 까닭 코드를 사람 말로 바꾼다.
 * - ★ 2026-10-18 실측(나래 계정): 「내 계정에 추가」(사용자 설치)는 승인은 되지만 봇 프로필이 안 떠 DM 을 못 열었다.
 *   그래서 들이는 길은 「내 서버에 초대」 하나만 보인다. 사용자 설치 링크는 띄우지 않는다.
 * - 「연결하는 중」은 몇 초마다 다시 읽되 **횟수에 끝이 있다**(무한 폴링 금지).
 */
import { lang, t } from "../i18n";
import {
  Check, ExternalLink, Loader2, MessageCircle, Plus, RotateCw, Trash2, UserPlus, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { openExternalUrl, type JarvisClient } from "../backend";
import type {
  DiscordAccessRequest, DiscordAliasItem, DiscordStatus, DiscordStepResult, ModelAliasRow,
} from "../types";
import "./discord.css";

/** 허용 요청이 바뀌었다(새 요청 · 허용 · 무시) — 설정 칸과 앱 아래 알림 자리가 서로 다시 읽는다. */
export const DISCORD_REQUESTS_EVENT = "sonjari:discord-requests";

const PORTAL_FALLBACK = "https://discord.com/developers/applications";
const DISCORD_APP = "https://discord.com/channels/@me";
/** 「연결하는 중」을 다시 읽는 간격과 최대 횟수 — 2.5초 × 12번 = 30초. 그 뒤에는 사람이 「다시 확인」을 누른다. */
export const CONNECTING_POLL_MS = 2500;
export const CONNECTING_POLL_MAX = 12;

const ERROR_TEXT: Record<string, string> = {
  clipboard_empty: t("클립보드가 비어 있어요 — Bot 페이지에서 「Reset Token」 → 「Copy」를 누른 뒤 다시 눌러 주세요."),
  clipboard_unavailable: t("클립보드를 읽지 못했어요 — 잠시 뒤 다시 눌러 주세요."),
  application_id: t("General Information 의 숫자가 아니라 Bot 페이지의 토큰을 복사해 주세요."),
  has_spaces: t("복사한 글에 빈칸이나 줄바꿈이 섞여 있어요 — Bot 페이지에서 토큰만 다시 복사해 주세요."),
  not_a_token: t("봇 토큰 모양이 아니에요 — Bot 페이지에서 「Reset Token」 → 「Copy」로 복사해 주세요."),
  token_rejected: t("디스코드가 이 토큰을 받지 않았어요 — 「Reset Token」으로 새 토큰을 받아 복사한 뒤 다시 눌러 주세요."),
  forbidden: t("디스코드가 이 요청을 허락하지 않았어요."),
  rate_limited: t("디스코드가 잠시 요청을 막았어요 — 조금 뒤 다시 눌러 주세요."),
  discord_error: t("디스코드 쪽에서 오류가 났어요 — 잠시 뒤 다시 해 주세요."),
  unreachable: t("디스코드에 닿지 못했어요 — 인터넷 연결을 확인해 주세요."),
  store_failed: t("토큰을 윈도우 자격 증명 관리자에 저장하지 못했어요. 아무것도 저장하지 않았어요."),
  store_unreadable: t("윈도우 자격 증명 관리자에서 봇 토큰을 읽지 못했어요."),
  no_token: t("저장된 봇 토큰이 없어요 — 봇 만들기부터 다시 해 주세요."),
  not_installed: t("이 손자리에는 디스코드 부품이 들어 있지 않아요."),
  intent_off: t("Message Content Intent 가 아직 꺼져 있어요 — 켜고 「Save Changes」를 누른 뒤 다시 확인해 주세요."),
  not_in_server: t("봇이 아직 어느 서버에도 없어요 — 초대 화면에서 서버를 고르고 「승인」을 눌러 주세요."),
  unknown_model_alias: t("모델 별명 표에 없는 이름이에요 — 표를 저장한 뒤 다시 골라 주세요."),
  no_such_request: t("그 요청을 찾지 못했어요 — 목록을 새로 불렀어요."),
};

/** 단계 문 실패를 사람 말로. 백엔드 문장이 먼저 — 다만 영어 화면에 한국어 문장이 오면 우리 사전 쪽을 쓴다. */
export function discordErrorText(result: { error?: string; message?: string }): string {
  const message = String(result.message ?? "").trim();
  const mapped = ERROR_TEXT[result.error ?? ""];
  if (message && !(lang() === "en" && /[가-힣]/.test(message) && mapped)) return message;
  return mapped ?? t("디스코드 연결 중 문제가 생겼어요({0}).", result.error || "?");
}

const ALIAS_ERROR: Record<string, string> = {
  invalid_alias: t("별명은 빈칸 없이 1~12자, 한글 · 영문 · 숫자만 쓸 수 있어요."),
  invalid_tag: t("모델 칸이 비었거나 빈칸이 들어 있어요."),
  duplicate_alias: t("같은 별명이 두 번 있어요."),
  too_many_aliases: t("별명은 20개까지예요."),
};

function reasonText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

type Notice = { kind: "ok" | "warn" | "error"; text: string; code?: string } | null;

function NoticeLine({ notice }: { notice: Notice }) {
  if (!notice) return null;
  if (notice.kind === "error") return <p className="settings-error" role="alert">{notice.text}</p>;
  return <p className={`discord-notice is-${notice.kind}`} role="status">{notice.text}</p>;
}

function OpenButton({ url, children, primary = false, disabled = false }: { url: string; children: ReactNode; primary?: boolean; disabled?: boolean }) {
  return (
    <button type="button" className={primary ? "setup-btn-go discord-open" : "setup-btn-quiet discord-open"}
      disabled={disabled || !url} onClick={() => void openExternalUrl(url)}>
      {children} <ExternalLink size={13} aria-hidden="true" />
    </button>
  );
}

// ── 가족 · 동료 추가 카드 ─────────────────────────────────────────────────────────

function whoLabel(request: DiscordAccessRequest): string {
  const name = request.display_name || request.username || request.user_id;
  return request.username && request.username !== name ? `${name}(@${request.username})` : name;
}

function firstLine(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > 140 ? `${flat.slice(0, 139)}…` : flat;
}

/** 허용 목록 밖 사람이 봇에게 말을 걸었다 — 받을지 사람이 고른다. 설정 칸과 앱 아래 알림 자리가 같은 카드를 쓴다. */
export function DiscordRequestCard({ request, busy, onDecide, onDismiss, more = 0 }: {
  request: DiscordAccessRequest;
  busy: boolean;
  onDecide: (allow: boolean) => void;
  onDismiss?: () => void;
  more?: number;
}) {
  const said = firstLine(request.first_text || "");
  return (
    <div className="discord-request" role="group" aria-label={t("디스코드 허용 요청")} data-testid="discord-request">
      <span className="discord-request-icon"><UserPlus size={15} aria-hidden="true" /></span>
      <div className="discord-request-body">
        <strong>{t("{0} 님이 디스코드로 말을 걸었어요", whoLabel(request))}</strong>
        {said && <q className="discord-request-said">{said}</q>}
        <p>
          {t("이 사람 말도 받을까요? 허용하면 이 사람도 이 PC 의 손자리에게 일을 시킬 수 있어요.")}
          {request.count > 1 ? ` ${t("(메시지 {0}개)", request.count)}` : ""}
          {more > 0 ? ` ${t("· 기다리는 사람 {0}명 더", more)}` : ""}
        </p>
        <div className="discord-request-actions">
          <button type="button" className="setup-btn-go" disabled={busy} onClick={() => onDecide(true)}>
            {busy ? <Loader2 size={14} className="spin" /> : t("허용")}
          </button>
          <button type="button" className="setup-btn-quiet" disabled={busy} onClick={() => onDecide(false)}>{t("무시")}</button>
        </div>
      </div>
      {onDismiss && (
        <button type="button" className="discord-request-close" onClick={onDismiss} aria-label={t("나중에 보기")}><X size={14} /></button>
      )}
    </div>
  );
}

/** 요청 목록을 읽고 허용 · 무시를 보내는 손잡이. 두 자리가 같이 쓴다. */
export function useDiscordRequests(client: JarvisClient | null, active = true) {
  const [requests, setRequests] = useState<DiscordAccessRequest[]>([]);
  const [ignored, setIgnored] = useState(0);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  // 내가 보낸 알림으로 나를 다시 읽지 않게 — 허용 · 무시의 답에 이미 새 목록이 있다.
  const self = useRef(Symbol("discord-requests"));

  const load = useCallback(async () => {
    if (!client || !active) return;
    try {
      const view = await client.discordRequests();
      setRequests(Array.isArray(view.requests) ? view.requests : []);
      setIgnored(Number(view.ignored_count || 0));
    } catch {
      // 디스코드 문이 없는 옛 본체 · 아직 못 붙은 때 — 카드를 안 띄울 뿐이다.
    }
  }, [client, active]);

  useEffect(() => {
    void load();
    const reload = (event: Event) => {
      if ((event as CustomEvent<{ source?: symbol }>).detail?.source !== self.current) void load();
    };
    window.addEventListener(DISCORD_REQUESTS_EVENT, reload);
    return () => window.removeEventListener(DISCORD_REQUESTS_EVENT, reload);
  }, [load]);

  const decide = useCallback(async (request: DiscordAccessRequest, allow: boolean) => {
    if (!client) return;
    setBusy(request.user_id);
    setNotice(null);
    try {
      const result = await client.discordDecideRequest(request.user_id, allow);
      if (Array.isArray(result.requests)) setRequests(result.requests);
      else setRequests((rows) => rows.filter((row) => row.user_id !== request.user_id));
      if (typeof result.ignored_count === "number") setIgnored(result.ignored_count);
      if (result.ok) {
        setNotice({
          kind: "ok",
          text: (result.message && !(lang() === "en" && /[가-힣]/.test(result.message)))
            ? result.message
            : allow ? t("허용했어요 — 이제 그 사람의 말도 받아요.") : t("무시했어요 — 그 사람이 다시 말해도 카드를 띄우지 않아요."),
        });
      } else {
        setNotice({ kind: "error", text: discordErrorText(result) });
        if (result.error === "no_such_request") void load();
      }
      window.dispatchEvent(new CustomEvent(DISCORD_REQUESTS_EVENT, { detail: { source: self.current } }));
    } catch (reason) {
      setNotice({ kind: "error", text: t("요청을 처리하지 못했어요: {0}", reasonText(reason)) });
    } finally {
      setBusy("");
    }
  }, [client, load]);

  return { requests, ignored, busy, notice, decide, setNotice };
}

/**
 * 앱 어디서나 보이는 알림 자리(입력칸 위 · 자동 승인 띠와 같은 곳)의 카드. 한 번에 한 사람만 — 나머지는 「N명 더」.
 * 「나중에 보기」로 접으면 설정 › 디스코드에 남는다.
 */
export function DiscordRequestBanner({ client, connected }: { client: JarvisClient | null; connected: boolean }) {
  const { requests, busy, notice, decide, setNotice } = useDiscordRequests(client, connected);
  const [hidden, setHidden] = useState<string[]>([]);
  const shown = requests.filter((row) => !hidden.includes(row.user_id));

  useEffect(() => {
    if (!notice || notice.kind !== "ok") return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);

  if (!shown.length && !notice) return null;
  return (
    <div className="discord-request-dock">
      {shown[0] && (
        <DiscordRequestCard request={shown[0]} busy={busy === shown[0].user_id} more={shown.length - 1}
          onDecide={(allow) => void decide(shown[0], allow)}
          onDismiss={() => setHidden((rows) => [...rows, shown[0].user_id])} />
      )}
      <NoticeLine notice={notice} />
    </div>
  );
}

/** 「`…`」로 감싼 곳을 코드 글꼴로 — 사전 문장 하나로 두되 디스코드에 칠 말은 칠 말처럼 보이게. */
function withCode(text: string): ReactNode[] {
  return text.split("`").map((part, index) => (index % 2 ? <code key={index}>{part}</code> : part));
}

// ── 모델 별명 표 ────────────────────────────────────────────────────────────────

type AliasDraft = DiscordAliasItem & { key: number; loaded?: boolean };

export function ModelAliasTable({ client, onSaved }: { client: JarvisClient; onSaved?: () => void }) {
  const [pcModel, setPcModel] = useState("");
  const [rows, setRows] = useState<AliasDraft[] | null>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const nextKey = useRef(1);

  const apply = useCallback((aliases: ModelAliasRow[]) => {
    const next = aliases.map((row) => ({ ...row, key: nextKey.current++ }));
    setRows(next);
    setSaved(JSON.stringify(aliases.map(({ alias, tag, note }) => ({ alias, tag, note }))));
  }, []);

  useEffect(() => {
    let alive = true;
    client.getModelAliases()
      .then((view) => { if (!alive) return; setPcModel(view.pc_model); apply(view.aliases); })
      .catch((reason) => alive && setNotice({ kind: "error", text: t("모델 별명 표를 읽지 못했어요: {0}", reasonText(reason)) }));
    return () => { alive = false; };
  }, [client, apply]);

  if (!rows) {
    return notice ? <NoticeLine notice={notice} /> : <p className="settings-note"><Loader2 size={14} className="spin" /> {t("모델 별명 표를 읽는 중이에요")}</p>;
  }

  const items = rows.map(({ alias, tag, note }) => ({ alias: alias.trim(), tag: tag.trim(), note: note.trim() }));
  const dirty = JSON.stringify(items) !== saved;
  const tags = [...new Set([pcModel, ...rows.map((row) => row.tag)].map((tag) => tag.trim()).filter(Boolean))];
  const edit = (key: number, patch: Partial<AliasDraft>) => {
    setNotice(null);
    setRows((list) => (list ?? []).map((row) => (row.key === key ? { ...row, ...patch } : row)));
  };

  const save = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const view = await client.putModelAliases(items);
      setPcModel(view.pc_model);
      apply(view.aliases);
      setNotice({ kind: "ok", text: t("모델 별명 표를 저장했어요.") });
      onSaved?.();
    } catch (reason) {
      const code = reasonText(reason);
      setNotice({ kind: "error", text: ALIAS_ERROR[code] ?? t("저장하지 못했어요: {0}", code) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="discord-aliases" data-testid="model-aliases">
      <p className="settings-note">{withCode(t("디스코드에서 `@빠른 오늘 날씨`처럼 앞에 붙이면 그 한 번만, `/모델` 은 그 대화 계속."))}</p>
      <datalist id="discord-alias-tags">{tags.map((tag) => <option key={tag} value={tag} />)}</datalist>
      {rows.length > 0 ? (
        <table className="discord-alias-table">
          <thead>
            <tr>
              <th scope="col">{t("별명")}</th>
              <th scope="col">{t("모델")}</th>
              <th scope="col">{t("설명")}</th>
              <th scope="col"><span className="discord-sr">{t("빼기")}</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <span className="discord-alias-name">
                    <span className={`discord-dot${row.loaded ? " is-on" : ""}`}
                      title={row.loaded ? t("지금 그래픽카드에 올라가 있음") : t("올라가 있지 않음 — 처음 부를 때 올립니다")}
                      aria-label={row.loaded ? t("지금 그래픽카드에 올라가 있음") : t("올라가 있지 않음 — 처음 부를 때 올립니다")} />
                    <input aria-label={t("별명")} value={row.alias} maxLength={12} placeholder={t("빠른")}
                      onChange={(event) => edit(row.key, { alias: event.target.value, loaded: false })} />
                  </span>
                </td>
                <td>
                  <input aria-label={t("모델")} list="discord-alias-tags" value={row.tag} spellCheck={false}
                    placeholder={pcModel || "qwen3.5:9b"} className="discord-alias-tag"
                    onChange={(event) => edit(row.key, { tag: event.target.value, loaded: false })} />
                  {row.tag.trim() && row.tag.trim() === pcModel && <small className="discord-alias-pc">{t("PC 와 같음")}</small>}
                </td>
                <td>
                  <input aria-label={t("설명")} value={row.note} maxLength={120}
                    onChange={(event) => edit(row.key, { note: event.target.value })} />
                </td>
                <td>
                  <button type="button" className="discord-icon-btn" onClick={() => setRows((list) => (list ?? []).filter((item) => item.key !== row.key))}
                    aria-label={t("{0} 빼기", row.alias || t("빈 줄"))}>
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="settings-note">{t("아직 별명이 없어요. 「별명 추가」로 만들어 보세요.")}</p>}
      <div className="settings-actions">
        <button type="button" className="setup-btn-quiet" disabled={busy || rows.length >= 20}
          onClick={() => setRows((list) => [...(list ?? []), { key: nextKey.current++, alias: "", tag: pcModel, note: "" }])}>
          <Plus size={13} /> {t("별명 추가")}
        </button>
        <button type="button" className="setup-btn-go" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? <Loader2 size={14} className="spin" /> : t("저장")}
        </button>
      </div>
      <NoticeLine notice={notice} />
    </div>
  );
}

// ── 연결 단계 ───────────────────────────────────────────────────────────────────

type StepId = "bot" | "intent" | "invite" | "finish";
const STEPS: { id: StepId; title: string }[] = [
  { id: "bot", title: t("봇 만들기") },
  { id: "intent", title: t("메시지 읽기 켜기") },
  { id: "invite", title: t("내 서버에 들이기") },
  { id: "finish", title: t("마무리") },
];

/** 지금 그릴 단계. 사용자 설치가 켜진 앱은 서버 0곳이어도 백엔드가 `ready_to_finish` 를 주지만, 사용자 설치 길은 안 쓰므로 들이기로 되돌린다. */
export function currentStep(status: DiscordStatus): StepId | null {
  switch (status.stage) {
    case "no_token": return "bot";
    case "need_intent": return "intent";
    case "need_invite": return "invite";
    case "ready_to_finish": return status.servers === 0 ? "invite" : "finish";
    case "connecting": return "finish";
    default: return null;
  }
}

function doneText(step: StepId, status: DiscordStatus): string {
  if (step === "bot") return status.bot_name ? t("봇 「{0}」 확인", status.bot_name) : t("토큰 저장됨");
  if (step === "intent") return t("켜짐");
  if (step === "invite") return status.servers ? t("서버 {0}곳", status.servers) : t("확인됨");
  return "";
}

export function DiscordSection({ client }: { client: JarvisClient }) {
  const [status, setStatus] = useState<DiscordStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [polls, setPolls] = useState(0);
  const [confirmingOff, setConfirmingOff] = useState(false);
  const [modelNote, setModelNote] = useState<Notice>(null);
  const requests = useDiscordRequests(client, Boolean(status?.token_saved));

  const load = useCallback(async () => {
    try {
      setStatus(await client.discordStatus());
      setLoadError("");
    } catch (reason) {
      setLoadError(t("디스코드 연결 상태를 읽지 못했어요: {0}", reasonText(reason)));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  // 「연결하는 중」 — 정해진 횟수까지만 다시 읽는다.
  const connecting = status?.stage === "connecting";
  useEffect(() => {
    if (!connecting) { setPolls(0); return; }
    if (polls >= CONNECTING_POLL_MAX) return;
    const timer = window.setTimeout(() => {
      setPolls((count) => count + 1);
      void load();
    }, CONNECTING_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [connecting, polls, load]);

  /** 단계 문 하나를 부르고 그 답(= status)으로 다시 그린다. */
  const step = async (name: string, call: () => Promise<DiscordStepResult>): Promise<DiscordStepResult | null> => {
    setBusy(name);
    setNotice(null);
    try {
      const result = await call();
      setStatus(result);
      if (!result.ok) setNotice({ kind: "error", text: discordErrorText(result), code: result.error });
      return result;
    } catch (reason) {
      setNotice({ kind: "error", text: t("손자리 본체에 닿지 못했어요: {0}", reasonText(reason)) });
      return null;
    } finally {
      setBusy("");
    }
  };

  const finish = async () => {
    const result = await step("finish", () => client.discordFinish());
    if (!result?.ok) return;
    setPolls(0);
    const lines = [result.connected ? t("연결을 마쳤어요.") : ""];
    if (result.home_channel_auto && result.home_channel_name) lines.push(t("홈 채널을 #{0} 로 정했어요.", result.home_channel_name));
    if (result.welcome_sent) lines.push(t("디스코드로 환영 메시지를 보냈어요."));
    const warn = result.welcome_error ? discordErrorText({ message: result.welcome_error }) : "";
    setNotice(warn ? { kind: "warn", text: [...lines, warn].filter(Boolean).join(" ") } : lines.filter(Boolean).length ? { kind: "ok", text: lines.filter(Boolean).join(" ") } : null);
  };

  const fromClipboard = async () => {
    const result = await step("token", () => client.discordTokenFromClipboard());
    if (!result?.ok) return;
    const lines = [t("토큰을 확인하고 저장했어요.")];
    if (result.owners_added) lines.push(t("앱 주인(나)을 허용한 사람에 넣었어요."));
    if (result.clipboard_cleared === false) lines.push(t("클립보드에 토큰이 남아 있을 수 있어요 — 다른 글을 한 번 복사해 덮어 주세요."));
    setNotice({ kind: result.clipboard_cleared === false ? "warn" : "ok", text: lines.join(" ") });
  };

  const recheckIntent = async () => {
    const result = await step("intent", () => client.discordRecheck());
    if (result?.ok && result.message_content === false) setNotice({ kind: "warn", text: ERROR_TEXT.intent_off });
  };

  const recheckInvite = async () => {
    const result = await step("invite", () => client.discordRecheck());
    if (!result?.ok) return;
    if (!result.servers) {
      // 「사용자 설치면 그대로 마무리해도 된다」는 백엔드 문장은 쓰지 않는다 — 그 길은 실측에서 DM 을 못 열었다.
      setNotice({ kind: "warn", text: ERROR_TEXT.not_in_server });
      return;
    }
    if (result.stage === "ready_to_finish") await finish();
  };

  const disconnect = async () => {
    const result = await step("off", () => client.discordDisconnect());
    setConfirmingOff(false);
    if (result?.ok) {
      setStarted(false);
      setNotice({ kind: "ok", text: t("디스코드 연결을 끊고 저장된 봇 토큰을 지웠어요.") });
    }
  };

  const setDefaultModel = async (alias: string) => {
    setModelNote(null);
    try {
      const result = await client.discordSetDefaultModel(alias);
      setStatus(result);
      setModelNote(result.ok ? { kind: "ok", text: t("저장했어요 — 다음 일부터 적용돼요.") } : { kind: "error", text: discordErrorText(result) });
    } catch (reason) {
      setModelNote({ kind: "error", text: t("저장하지 못했어요: {0}", reasonText(reason)) });
    }
  };

  const lede = (
    <div className="discord-lede">
      <span className="discord-lede-icon"><MessageCircle size={16} aria-hidden="true" /></span>
      <div>
        <p className="discord-lede-title">{t("폰 디스코드로 손자리에게 일을 시킵니다.")}</p>
        <p className="settings-note">
          {t("디스코드로 보낸 답 · 파일 · 사진은 디스코드 서버를 지납니다. 메일 보내기처럼 되돌릴 수 없는 일은 PC 에서 승인합니다.")}
        </p>
      </div>
    </div>
  );

  if (!status) {
    return (
      <div className="settings-block discord" data-testid="discord-section">
        {lede}
        {loadError ? <p className="settings-error" role="alert">{loadError}</p>
          : <p className="settings-note"><Loader2 size={14} className="spin" /> {t("디스코드 연결 상태를 읽는 중이에요")}</p>}
      </div>
    );
  }

  const stepId = currentStep(status);
  const intro = status.stage === "no_token" && !started;
  const pending = requests.requests;

  return (
    <div className="settings-block discord" data-testid="discord-section">
      {lede}

      {status.stage === "not_installed" && (
        <p className="discord-notice is-warn" role="status">
          {t("이 손자리에는 디스코드 부품이 들어 있지 않아요. 새 판으로 올리면 여기서 연결할 수 있어요.")}
        </p>
      )}

      {intro && (
        <div className="settings-actions">
          <button type="button" className="setup-btn-go" onClick={() => { setStarted(true); setNotice(null); }}>{t("연결 시작")}</button>
          <span className="firstrun-fine">{t("5분쯤 걸려요. 디스코드 계정이 있어야 해요.")}</span>
        </div>
      )}

      {status.stage === "other_process" && (
        <div className="discord-state" data-testid="discord-other">
          <p className="discord-state-head"><span className="discord-dot is-warn" aria-hidden="true" /> <b>{t("다른 창에서 다리가 돌고 있어요")}</b></p>
          <p className="settings-note">
            {t("명령 창이나 작업 스케줄러로 따로 띄운 디스코드 다리가 이미 이 봇을 쥐고 있어요. 그쪽을 끄면 손자리가 다리를 맡아요. 그대로 두셔도 디스코드로 일은 시킬 수 있어요.")}
          </p>
          <div className="settings-actions">
            <button type="button" className="setup-btn-quiet" disabled={busy !== ""}
              onClick={() => { setBusy("other"); setNotice(null); void load().finally(() => setBusy("")); }}>
              {busy === "other" ? <Loader2 size={14} className="spin" /> : <><RotateCw size={13} /> {t("다시 확인")}</>}
            </button>
          </div>
          <NoticeLine notice={notice} />
        </div>
      )}

      {stepId && !intro && (
        <ol className="discord-steps" aria-label={t("디스코드 연결 단계")}>
          {STEPS.map((item, index) => {
            const at = STEPS.findIndex((row) => row.id === stepId);
            const state = index < at ? "done" : index === at ? "current" : "next";
            return (
              <li key={item.id} className={`discord-step is-${state}`} aria-current={state === "current" ? "step" : undefined}>
                <span className="discord-step-mark" aria-hidden="true">{state === "done" ? <Check size={12} /> : index + 1}</span>
                <div className="discord-step-body">
                  <p className="discord-step-title">
                    <b>{item.title}</b>
                    {state === "done" && <span className="discord-step-done">{doneText(item.id, status)}</span>}
                  </p>
                  {state === "current" && item.id === "bot" && (
                    <>
                      <ol className="discord-howto">
                        <li>
                          {t("디스코드 개발자 포털을 엽니다.")}
                          <div className="discord-inline-action">
                            <OpenButton url={status.portal_url || PORTAL_FALLBACK}>{t("개발자 포털 열기")}</OpenButton>
                          </div>
                        </li>
                        <li>{t("「New Application」 → 이름 적기 → 약관 체크 → 「Create」")}</li>
                        <li>{t("왼쪽 「Bot」 → 「Reset Token」 → 「Copy」")}</li>
                      </ol>
                      <p className="firstrun-fine discord-tip">{t("처음 가입했다면 이메일 인증을 먼저 해야 앱을 만들 수 있어요.")}</p>
                      <button type="button" className="setup-btn-go discord-big" disabled={busy !== ""} onClick={() => void fromClipboard()}>
                        {busy === "token" ? <Loader2 size={15} className="spin" /> : t("토큰을 복사했어요")}
                      </button>
                      <p className="firstrun-fine">
                        {t("토큰은 붙여 넣지 않아요. 손자리 본체가 클립보드에서 직접 읽어 윈도우 자격 증명 관리자에만 두고, 이 화면에는 나오지 않아요.")}
                      </p>
                    </>
                  )}
                  {state === "current" && item.id === "intent" && (
                    <>
                      <p className="settings-note">{t("봇이 내 메시지를 읽으려면 「Message Content Intent」를 켜야 해요.")}</p>
                      <ol className="discord-howto">
                        <li>
                          {t("포털의 Bot 페이지를 엽니다.")}
                          <div className="discord-inline-action">
                            <OpenButton url={status.portal_bot_url || status.portal_url || PORTAL_FALLBACK}>{t("Bot 페이지 열기")}</OpenButton>
                          </div>
                        </li>
                        <li>{t("아래 「Privileged Gateway Intents」에서 「Message Content Intent」를 켭니다.")}</li>
                        <li>{t("「Save Changes」를 누릅니다.")}</li>
                      </ol>
                      <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void recheckIntent()}>
                        {busy === "intent" ? <Loader2 size={14} className="spin" /> : t("다시 확인")}
                      </button>
                    </>
                  )}
                  {state === "current" && item.id === "invite" && (
                    <>
                      <div className="discord-aside">
                        <p><b>{t("서버가 없으면 먼저 하나 만들기")}</b></p>
                        <p className="settings-note">{t("디스코드 앱 왼쪽 「+」 → 「직접 만들기」 → 「나와 친구들을 위한 서버」 → 「만들기」")}</p>
                        <OpenButton url={DISCORD_APP}>{t("디스코드 열기")}</OpenButton>
                      </div>
                      <ol className="discord-howto">
                        <li>
                          {t("초대 화면을 엽니다.")}
                          <div className="discord-inline-action">
                            <OpenButton url={status.invite_url}>{t("내 서버에 초대")}</OpenButton>
                          </div>
                        </li>
                        <li>{t("서버를 고르고 「승인」을 누릅니다.")}</li>
                      </ol>
                      <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void recheckInvite()}>
                        {busy === "invite" || busy === "finish" ? <Loader2 size={14} className="spin" /> : t("다 했어요")}
                      </button>
                    </>
                  )}
                  {state === "current" && item.id === "finish" && (
                    connecting ? (
                      polls < CONNECTING_POLL_MAX ? (
                        <p className="settings-note" role="status"><Loader2 size={14} className="spin" /> {t("디스코드에 붙는 중이에요…")}</p>
                      ) : (
                        <>
                          <p className="discord-notice is-warn" role="status">
                            {t("30초가 지나도 아직 붙지 못했어요. 인터넷 연결을 확인한 뒤 다시 확인해 주세요.")}
                          </p>
                          <button type="button" className="setup-btn-quiet" disabled={busy !== ""} onClick={() => { setPolls(0); void load(); }}>
                            <RotateCw size={13} /> {t("다시 확인")}
                          </button>
                        </>
                      )
                    ) : (
                      <>
                        <p className="settings-note">
                          {t("마무리하면 손자리가 디스코드 다리를 켜고, 홈 채널을 정하고, 디스코드로 환영 메시지를 보내요.")}
                        </p>
                        <button type="button" className="setup-btn-go" disabled={busy !== ""} onClick={() => void finish()}>
                          {busy === "finish" ? <Loader2 size={14} className="spin" /> : t("연결 마치기")}
                        </button>
                      </>
                    )
                  )}
                  {state === "current" && <NoticeLine notice={notice} />}
                  {state === "current" && item.id === "bot" && notice?.code === "application_id" && notice.text !== ERROR_TEXT.application_id && (
                    <p className="firstrun-fine discord-tip">{ERROR_TEXT.application_id}</p>
                  )}
                  {state === "current" && !notice && status.last_error && item.id !== "bot" && (
                    <p className="firstrun-fine discord-last-error">{status.last_error}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {status.stage === "connected" && (
        <div className="discord-state is-connected" data-testid="discord-connected">
          <p className="discord-state-head">
            <span className="discord-dot is-on" aria-hidden="true" />
            <b>{status.bot_name || t("디스코드 봇")}</b>
            <span className="discord-state-label">{t("연결됨")}</span>
          </p>
          <dl className="discord-facts">
            <div>
              <dt>{t("홈 채널")}</dt>
              <dd>{status.home_channel_name ? `#${status.home_channel_name}` : t("없음 — 봇을 @멘션하거나 DM 으로 말하면 받아요")}</dd>
            </div>
            <div>
              <dt>{t("허용된 사람")}</dt>
              <dd>{t("{0}명", status.allowed_user_ids)}</dd>
            </div>
            {typeof status.servers === "number" && (
              <div>
                <dt>{t("들어간 서버")}</dt>
                <dd>{t("{0}곳", status.servers)}</dd>
              </div>
            )}
          </dl>
          <p className="discord-try">{t("디스코드에서 봇에게 말해 보세요 — 예: 「네이버에서 오늘 서울 날씨 찾아 줘」")}</p>
          {status.home_channel_name && <p className="firstrun-fine">{t("홈 채널에서는 @멘션 없이도 받아요.")}</p>}
          <NoticeLine notice={notice} />

          <div className="settings-row discord-model-row">
            <div className="settings-row-text">
              <label htmlFor="discord-default-model">{t("디스코드 기본 모델")}</label>
              <small>{t("디스코드로 시킨 일에 쓸 모델이에요. 별명은 아래 「모델 별명 표」에서 정해요.")}</small>
            </div>
            <div className="settings-row-control">
              <select id="discord-default-model" value={status.default_model_alias}
                onChange={(event) => void setDefaultModel(event.target.value)}>
                <option value="">{t("PC 와 같음")}</option>
                {status.aliases.map((row) => (
                  <option key={row.alias} value={row.alias}>{row.alias} · {row.tag}</option>
                ))}
                {status.default_model_alias && !status.aliases.some((row) => row.alias === status.default_model_alias) && (
                  <option value={status.default_model_alias}>{t("{0} (표에 없음)", status.default_model_alias)}</option>
                )}
              </select>
              {modelNote && (
                <span className={`settings-field-status ${modelNote.kind === "error" ? "is-error" : "is-saved"}`} role="status">{modelNote.text}</span>
              )}
            </div>
          </div>
        </div>
      )}

      {(pending.length > 0 || requests.notice) && (
        <div className="discord-requests" data-testid="discord-requests">
          <h3>{t("말을 건 사람")}</h3>
          {pending.map((request) => (
            <DiscordRequestCard key={request.user_id} request={request} busy={requests.busy === request.user_id}
              onDecide={(allow) => void requests.decide(request, allow)} />
          ))}
          <NoticeLine notice={requests.notice} />
        </div>
      )}
      {requests.ignored > 0 && <p className="firstrun-fine discord-ignored">{t("무시한 사람 {0}명 — 그 사람이 다시 말해도 카드를 띄우지 않아요.", requests.ignored)}</p>}

      {status.token_saved && (
        <details className="settings-advanced discord-alias-fold">
          <summary>{t("모델 별명 표")}</summary>
          <ModelAliasTable client={client} onSaved={() => void load()} />
        </details>
      )}

      {status.token_saved && (
        <div className="settings-danger">
          <h4>{t("연결 끊기")}</h4>
          <p>
            {t("다리를 멈추고 이 PC 에 저장된 봇 토큰을 지워요. 허용한 사람 목록은 남고, 디스코드 포털의 봇 자체는 지워지지 않아요.")}
          </p>
          {!confirmingOff ? (
            <button type="button" className="settings-stop" disabled={busy !== ""} onClick={() => setConfirmingOff(true)}>{t("연결 끊기…")}</button>
          ) : (
            <div className="settings-actions">
              <button type="button" className="settings-stop" disabled={busy !== ""} onClick={() => void disconnect()}>
                {busy === "off" ? <Loader2 size={14} className="spin" /> : t("정말 끊기")}
              </button>
              <button type="button" className="setup-btn-quiet" onClick={() => setConfirmingOff(false)}>{t("그만두기")}</button>
            </div>
          )}
        </div>
      )}
      {notice && (intro || (!stepId && status.stage !== "connected" && status.stage !== "other_process")) && <NoticeLine notice={notice} />}
    </div>
  );
}
