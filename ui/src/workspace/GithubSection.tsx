/**
 * 설정 › 연결 › 깃허브 연결 (2026-11-12 · 설계 docs/설계_깃허브연결_2026-11-12.ko.md).
 *
 * 순서는 백엔드(`github_link.py`)가 쥔다 — 화면은 상태를 그리고 단추만 누른다:
 *
 *     gh 없음 → 받기(공식 배포 · 지문 · 서명) → 로그인(일회용 코드) → 사람이 깃허브에서 승인 → 연결됨
 *
 * ## 지키는 것
 * - 토큰은 화면에 오지 않는다. 「어디에 있나」(키 보관소 / 파일)만 보인다 — 파일이면 숨기지 않고 알린다.
 * - 깃허브의 「Authorize」는 사람이 누른다. 이 카드는 코드를 보여 주고 깃허브 창을 열 뿐이다.
 * - 코드를 기다리는 동안 다시 읽기는 **끝이 있다**(백엔드가 15분에 끊는다 · 여기도 같은 한도).
 *
 * ## 이 칸의 얼굴
 * 사람이 정확히 옮겨 쳐야 하는 것은 8자리 코드 하나다. 그래서 그것만 크게 · 한 글자씩 칸에 · 고정폭으로(0 과 O 를 안 헷갈리게),
 * 그 아래 남은 시간이 줄어드는 가는 선. 나머지는 설정 화면의 면 · 선 · 단추를 그대로 쓴다.
 */
import { t } from "../i18n";
import { Check, Copy, ExternalLink, GitBranch, Loader2, LogOut, Unplug } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { openExternalUrl, type JarvisClient } from "../backend";
import type { GithubStatus } from "../types";
import "./github.css";

/** 코드를 기다리며 다시 읽는 간격 · 최대 횟수 — 3초 × 300번 = 15분(백엔드 한도와 같다). */
export const GITHUB_POLL_MS = 3000;
export const GITHUB_POLL_MAX = 300;
const CODE_LIFETIME_SEC = 15 * 60;

const ERROR_TEXT: Record<string, string> = {
  gh_checksum_mismatch: t("받은 파일이 깃허브 공식 지문과 달라 넣지 않았습니다. 잠시 뒤 다시 받아 주세요."),
  gh_asset_not_found: t("이 컴퓨터에 맞는 gh 배포 파일을 찾지 못했습니다."),
  gh_binary_not_in_zip: t("받은 파일 안에 gh 가 없었습니다. 넣지 않았습니다."),
  gh_missing: t("gh 가 아직 없습니다. 먼저 gh 를 받아 주세요."),
  login_code_not_found: t("깃허브 로그인을 시작하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 눌러 주세요."),
  expired: t("코드 시간이 지났습니다. 다시 연결해 주세요."),
  failed: t("로그인이 끝나지 않았습니다. 다시 연결해 주세요."),
};

export function githubErrorText(code: string): string {
  if (code.startsWith("gh_not_signed")) return t("받은 gh 의 서명이 깃허브 공식 서명이 아니라 넣지 않았습니다.");
  if (code.startsWith("download_failed")) return t("깃허브에 닿지 못했습니다. 인터넷이나 회사 방화벽을 확인해 주세요.");
  return ERROR_TEXT[code] ?? t("깃허브 연결 중 문제가 생겼습니다({0}).", code || "?");
}

const isMac = () => typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent);

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 8자리 코드 — 한 글자씩 칸에, 가운데 줄표. 읽기 프로그램에는 한 번에 읽힌다. */
function CodeCells({ code }: { code: string }) {
  const [left, right] = code.split("-");
  return (
    <div className="gh-code" role="text" aria-label={t("일회용 코드 {0}", code.split("").join(" "))}>
      {[left, right].map((half, index) => (
        <span key={index} className="gh-code-half" aria-hidden="true">
          {(half ?? "").split("").map((ch, i) => <span key={i} className="gh-code-cell">{ch}</span>)}
          {index === 0 && <span className="gh-code-dash">–</span>}
        </span>
      ))}
    </div>
  );
}

export function GithubSection({ client }: { client: JarvisClient }) {
  const [state, setState] = useState<GithubStatus | null>(null);
  const [busy, setBusy] = useState<"" | "install" | "login" | "logout">("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [left, setLeft] = useState(0);
  const polls = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const next = await client.githubStatus();
      setState(next);
      setLeft(next.pending?.expires_in ?? 0);
    } catch {
      setError(t("손자리 본체에 닿지 못했습니다."));
    }
  }, [client]);

  useEffect(() => { void refresh(); }, [refresh]);

  const pending = state?.pending ?? null;

  // 코드를 기다리는 동안만 다시 읽는다 — 끝이 있다.
  useEffect(() => {
    if (!pending) return;
    polls.current = 0;
    const timer = window.setInterval(async () => {
      polls.current += 1;
      setLeft((value) => Math.max(0, value - GITHUB_POLL_MS / 1000));
      if (polls.current > GITHUB_POLL_MAX) { window.clearInterval(timer); return; }
      try {
        const poll = await client.githubLoginPoll();
        if (poll.state === "waiting") return;
        window.clearInterval(timer);
        if (poll.state === "expired" || poll.state === "failed") setError(githubErrorText(poll.state));
        await refresh();
      } catch { /* 다음 차례에 다시 */ }
    }, GITHUB_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending?.code, client, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (kind: "install" | "login" | "logout") => {
    setBusy(kind);
    setError("");
    try {
      if (kind === "install") {
        const out = await client.githubInstall();
        if (!out.ok) setError(githubErrorText(out.error ?? ""));
      } else if (kind === "login") {
        const out = await client.githubLoginStart();
        if (!out.ok) setError(githubErrorText(out.error ?? ""));
      } else {
        await client.githubLogout();
      }
      await refresh();
    } catch {
      setError(t("손자리 본체에 닿지 못했습니다."));
    } finally {
      setBusy("");
    }
  };

  const copy = async () => {
    if (!pending) return;
    try {
      await navigator.clipboard.writeText(pending.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { /* 복사가 막혀도 코드는 화면에 있다 */ }
  };

  const login = state?.login;
  const vault = isMac() ? t("맥 키체인") : t("Windows 자격 증명 관리자");

  return (
    <section className="gh-card" aria-labelledby="gh-title">
      <div className="gh-lede">
        <span className="gh-lede-icon" aria-hidden="true"><GitBranch size={16} /></span>
        <div>
          <h3 id="gh-title" className="gh-title">{t("깃허브 연결")}</h3>
          <p className="settings-note">
            {t("손자리가 내 깃허브 저장소를 받고, 고친 것을 PR 로 올릴 수 있게 합니다. 로그인 승인은 깃허브 화면에서 직접 하고, 손자리는 비밀번호를 보지 않습니다.")}
          </p>
        </div>
      </div>

      {!state && <p className="gh-quiet"><Loader2 size={14} className="gh-spin" /> {t("확인하는 중…")}</p>}

      {state && !state.supported && <p className="settings-note">{t("이 컴퓨터에서는 아직 깃허브 연결을 쓸 수 없습니다(Windows · macOS 만).")}</p>}

      {state?.supported && !state.gh && (
        <div className="gh-now">
          <p className="gh-now-title">{t("이 컴퓨터에 깃허브 도구(gh)가 없습니다.")}</p>
          <p className="settings-note">{t("깃허브 공식 배포에서 받아, 지문과 서명이 맞을 때만 넣습니다. 내 컴퓨터의 다른 설정은 바꾸지 않습니다.")}</p>
          <button type="button" className="setup-btn-go gh-big" disabled={!!busy} onClick={() => void run("install")}>
            {busy === "install" ? <Loader2 size={15} className="gh-spin" /> : null}{t("gh 받기")}
          </button>
        </div>
      )}

      {state?.gh && pending && (
        <div className="gh-now gh-waiting">
          <p className="gh-now-title">{t("깃허브 창에 이 코드를 넣고 「Authorize」를 눌러 주세요.")}</p>
          <CodeCells code={pending.code} />
          <div className="gh-timer" aria-hidden="true">
            <span className="gh-timer-fill" style={{ width: `${Math.min(100, (left / CODE_LIFETIME_SEC) * 100)}%` }} />
          </div>
          <div className="gh-row">
            <button type="button" className="setup-btn-quiet" onClick={() => void copy()}>
              {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? t("복사했습니다") : t("코드 복사")}
            </button>
            <button type="button" className="setup-btn-quiet" onClick={() => void openExternalUrl(pending.url)}>
              <ExternalLink size={14} /> {t("깃허브 창 다시 열기")}
            </button>
            <span className="gh-left" aria-live="polite">{t("남은 시간 {0}", clock(left))}</span>
          </div>
        </div>
      )}

      {state?.gh && !pending && login?.logged_in && (
        <div className="gh-linked">
          <p className="gh-status-line">
            <span className="gh-dot is-on" aria-hidden="true" />
            <span>{t("{0} 계정으로 연결됨", login.user)}</span>
            <span className="gh-meta">gh {state.gh.version}</span>
          </p>
          {login.config === "user" && (
            <p className="settings-note">{t("이 컴퓨터의 gh 가 이미 이 계정으로 로그인돼 있어 그대로 씁니다.")}</p>
          )}
          {login.storage === "keyring" && <p className="settings-note">{t("로그인 정보는 {0}에 있습니다.", vault)}</p>}
          {login.storage === "file" && (
            <p className="gh-warn">{t("로그인 정보가 암호화되지 않은 파일에 있습니다. {0}에 넣지 못했습니다.", vault)}</p>
          )}
          <div className="gh-row">
            {login.config === "ours" ? (
              <button type="button" className="setup-btn-quiet gh-stop" disabled={!!busy} onClick={() => void run("logout")}>
                <LogOut size={14} /> {t("연결 끊기")}
              </button>
            ) : (
              <button type="button" className="setup-btn-quiet" disabled={!!busy} onClick={() => void run("login")}>
                <Unplug size={14} /> {t("다른 계정으로 연결")}
              </button>
            )}
          </div>
        </div>
      )}

      {state?.gh && !pending && !login?.logged_in && (
        <div className="gh-now">
          <p className="gh-now-title">{t("깃허브 계정을 연결해 주세요.")}</p>
          <p className="settings-note">{t("누르면 깃허브 창이 열리고, 여기에 일회용 코드가 뜹니다.")}</p>
          <button type="button" className="setup-btn-go gh-big" disabled={!!busy} onClick={() => void run("login")}>
            {busy === "login" ? <Loader2 size={15} className="gh-spin" /> : null}{t("깃허브로 로그인")}
          </button>
        </div>
      )}

      {state?.supported && !state.git && (
        <p className="gh-warn">
          {isMac()
            ? t("git 이 없습니다. 저장소를 받으려면 필요합니다 — 터미널에서 「xcode-select --install」로 개발자 도구를 깔아 주세요.")
            : t("git 이 없습니다. 저장소를 받으려면 필요합니다 — Git for Windows 를 깔아 주세요.")}
        </p>
      )}

      {state?.gh?.old && <p className="settings-note">{t("이 컴퓨터의 gh({0})가 오래된 판입니다. 새 판으로 올리면 더 안정적입니다.", state.gh.version)}</p>}
      {error && <p className="settings-error" role="alert">{error}</p>}
    </section>
  );
}
