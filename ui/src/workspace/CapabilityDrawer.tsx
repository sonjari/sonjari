/**
 * 할 수 있는 일 — 서랍 (R5).
 *
 * 도구 102개(L0 35 · L1 53 · L2 14), 사이트 레시피, 자비스가 이름으로 아는 사이트.
 * 전부 코드 안에만 있었다. **쓸 수 있다는 걸 모르면 없는 기능과 같다.**
 *
 * 여기서부터 화면이 채팅봇이 아니라 플랫폼으로 보인다 — 그리고 레시피와 사이트
 * 지도는 마누스에 없는 우리 자산이다.
 *
 * 서랍은 **사용자가 직접 연 것**이라 덮어도 된다(결정 카드가 화면을 덮지 않는 것과
 * 다른 경우다 — 저쪽은 아무도 안 불렀는데 나타나는 것이다). 대신 Esc 와 바깥
 * 누르기로 언제든 닫힌다.
 */
import { t } from "../i18n";
import { Cloud, Loader2, Route, ShieldAlert, ShieldCheck, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import { PeoplePanel } from "../PeoplePanel";
import { LearnedPanel } from "./LearnedPanel";
import type { Capabilities, GoogleStatus } from "../types";
import { disabledCount, groupKeyOf, groupTools, riskMeaning, RISK_ORDER } from "./capabilities";
import { userLabel } from "./userLabel";

/**
 * 드라이브에서 파일 고르기 (인수인계 H4). 공개판은 드라이브 전체를 읽는 권한(제한 권한 — Google 연례 보안 평가
 * 대상)을 요청하지 않는다. 대신 사람이 고른 파일만 온텔릭이 읽는다. 고르는 화면은 Google 것이라 브라우저에서 뜬다.
 */
function DrivePicker({ client, initial }: { client: JarvisClient; initial: number }) {
  const [count, setCount] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => setCount(initial), [initial]);

  const pick = async () => {
    if (busy) return;
    setBusy(true);
    setNote("");
    try {
      const started = await client.startGooglePicker();
      if (!started.opened_browser) throw new Error(t("브라우저를 열지 못했습니다."));
      for (let attempt = 0; attempt < 150; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const status = await client.getGoogleStatus(false);
        if ((status.picked_files ?? 0) !== count) {
          setCount(status.picked_files ?? 0);
          setNote(t("골랐습니다. 이제 Sonjari에게 그 파일 이름으로 부탁하세요."));
          return;
        }
        if (status.last_error) throw new Error(status.last_error);
      }
      setNote(t("고르기를 기다리다 멈췄습니다. 다시 눌러 주세요."));
    } catch (reason) {
      setNote(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drive-picker">
      <button type="button" className="connect-card" onClick={() => void pick()} disabled={busy}>
        <span className="connect-mark">{busy ? <Loader2 size={14} className="spin" /> : <Cloud size={14} />}</span>
        <span className="connect-text">
          <strong>{t("드라이브에서 파일 고르기")}</strong>
          <small>
            {busy
              ? t("브라우저에서 파일을 고르는 중입니다")
              : t("Sonjari는 고른 파일만 읽습니다 · 지금 {0}개", count)}
          </small>
        </span>
      </button>
      {note && <p className="drive-picker-note">{note}</p>}
    </div>
  );
}

export function CapabilityDrawer(props: {
  client: JarvisClient | null;
  open: boolean;
  onClose: () => void;
  connected: boolean;
  google: GoogleStatus | null;
  googleBusy: boolean;
  onConnectGoogle: () => void;
}) {
  const { client, open } = props;
  const [data, setData] = useState<Capabilities | null>(null);
  const [error, setError] = useState("");
  const [risk, setRisk] = useState("");

  // 열었을 때만 가져온다. 한 번 가져오면 다시 안 부른다 — 도구 목록은 자비스를
  // 다시 띄우기 전에는 안 바뀐다.
  useEffect(() => {
    if (!open || !client || data) return;
    let alive = true;
    client.getCapabilities()
      .then((next) => { if (alive) setData(next); })
      .catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { alive = false; };
  }, [open, client, data]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") props.onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, props]);

  if (!open) return null;

  // ★ 구글 연결 설정이 없는 빌드(공개판)에는 구글을 진열하지 않는다 (2026-10-01).
  //   공개판 패키지엔 OAuth 클라이언트가 없어 구글 도구가 처음부터 꺼져 있는데, 화면엔 회색 카드와
  //   「이 빌드에는 Google 연결 설정이 포함되지 않았습니다」, 회색 도구 묶음이 그대로 보였다 —
  //   못 쓰는 기능을 진열대에 올리면 베타 사용자·스토어 심사자는 「고장」으로 읽는다.
  //   예전에 연결해 둔 사람(connected)은 계속 보인다.
  const googleShown = Boolean(props.google?.configured || props.google?.connected);
  const tools = data ? (googleShown ? data.tools : data.tools.filter((tool) => groupKeyOf(tool) !== "google")) : [];
  const groups = data ? groupTools(tools, risk) : [];
  const off = data ? disabledCount(tools) : 0;

  return (
    <div className="capability-veil" onClick={props.onClose}>
      <aside className="capability-drawer" onClick={(event) => event.stopPropagation()} role="dialog" aria-label={t("Sonjari가 할 수 있는 일")}>
        <header>
          <span className="capability-icon"><Wrench size={15} /></span>
          <div>
            <strong>{t("할 수 있는 일")}</strong>
            <small>{data ? t("도구 {0}개 · 사이트 절차 {1}개 · 아는 사이트 {2}곳", data.tool_count, data.recipes.length, data.sites.length) : t("가져오는 중")}</small>
          </div>
          <button type="button" onClick={props.onClose} aria-label={t("닫기")}><X size={15} /></button>
        </header>

        {error && <p className="capability-error">{error}</p>}
        {!data && !error && <p className="capability-loading"><Loader2 size={14} className="spin" /> {t("Sonjari에게 물어보는 중입니다")}</p>}

        {data && (
          <div className="capability-body">
            {/* 위험 등급은 **뜻으로** 말한다. L2 를 "14개"라고만 적으면 아무 말도 안 한 것이다. */}
            <div className="risk-row">
              <button type="button" className={risk === "" ? "on" : ""} onClick={() => setRisk("")}>
                {t("전부")} <b>{data.tool_count}</b>
              </button>
              {RISK_ORDER.map((level) => {
                const meaning = riskMeaning(level);
                return (
                  <button
                    key={level}
                    type="button"
                    className={`tone-${meaning.tone} ${risk === level ? "on" : ""}`}
                    onClick={() => setRisk(risk === level ? "" : level)}
                    title={meaning.detail}
                  >
                    {level === "L2" && <ShieldAlert size={12} />}
                    {meaning.label} <b>{data.by_risk[level] ?? 0}</b>
                  </button>
                );
              })}
            </div>
            <p className="risk-note">{risk ? riskMeaning(risk).detail : t("되돌릴 수 없는 것은 실행 전에 반드시 {0} 승인을 받습니다.", userLabel())}</p>
            {/* 꺼져 있는 도구가 있으면 목록에 있어도 못 쓴다. 숨기지 않는다. */}
            {off > 0 && <p className="risk-note off">{off}{t("개는 지금 꺼져 있어 부를 수 없습니다.")}</p>}

            {groups.map((group) => (
              <section className="capability-group" key={group.key}>
                <h4>{group.label}<span>{group.tools.length}</span></h4>
                <ul>
                  {group.tools.map((tool) => (
                    <li key={tool.name} className={tool.enabled ? "" : "off"}>
                      <code>{tool.name}</code>
                      <span>{tool.description}</span>
                      <em className={`risk-${tool.risk_level}`}>{riskMeaning(tool.risk_level).label}</em>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            {/* 배운 것 (P5) — **사람이 볼 수 없는 기억은 고칠 수도 없다.**
                자동 추출이 도는 순간부터 틀린 사실이 쌓이고, 그건 매 턴
                시스템 프롬프트에 실려 모든 답을 조금씩 물들인다. */}
            <section className="capability-group learned-group">
              <h4>{t("배운 것")}<span title={t("대화에서 뽑은 사실. 매 턴 실려 간다")}>{t("기억")}</span></h4>
              <LearnedPanel client={props.client} open={open} />
            </section>

            {/* 사이트 절차 — 사람이 한 번 뚫으면 다음부터 안 막힌다. 자율이 저절로
                늘어나는 유일한 축인데 몇 개인지 아무 데도 안 보였다. */}
            {data.recipes.length > 0 && (
              <section className="capability-group recipes">
                <h4>{t("검토된 사이트 절차")}<span>{data.recipes.length}</span></h4>
                {data.recipes.map((recipe) => (
                  <div className="recipe-card" key={recipe.site}>
                    <strong>{recipe.site}</strong>
                    <small>{recipe.hosts.join(" · ")}</small>
                    <p>{recipe.description}</p>
                    <div className="recipe-actions">
                      {recipe.actions.map((action) => (
                        <span key={action.action} className={`risk-${action.risk}`} title={action.description}>
                          {action.action}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </section>
            )}

            {/* ── 연결 (2026-08-19 저녁에 이리로 옮겨 왔다) ─────────────────
                구글 계정 카드는 우측 레일에, 카메라 인물은 사이드바에 상주했다.
                둘 다 **능력의 상태**지 지금 도는 일도 길찾기도 아니다. 게다가
                구글 도구 13개는 그 연결이 없으면 목록에 있어도 못 쓴다 — 능력을
                진열하는 자리에서 그 사실을 같이 말하는 것이 맞다. */}
            {(googleShown || props.connected) && <section className="capability-group connections">
              <h4>{t("연결")}<span>{(props.google?.connected ? 1 : 0) + (props.connected ? 1 : 0)}</span></h4>
              {googleShown && <button
                className={`connect-card ${props.google?.connected ? "on" : ""}`}
                type="button"
                onClick={props.onConnectGoogle}
                disabled={props.googleBusy || !props.google?.configured
                  // ★ 연결돼 있어도 **권한이 모자라면** 다시 승인받을 수 있어야 한다
                  //   (2026-09-01). 새 권한(drive.file)을 더했는데 이 버튼이
                  //   `connected` 면 죽어 있어서, 재승인할 길이 화면에 없었다.
                  //   기능을 만들어 놓고 켤 방법이 없는 것과 같다.
                  || (Boolean(props.google?.connected) && !props.google?.scope_mismatch)}
              >
                <span className="connect-mark">
                  {props.google?.connected ? <ShieldCheck size={14} /> : <Cloud size={14} />}
                </span>
                <span className="connect-text">
                  <strong>{t("구글 · Drive · Gmail · Calendar")}</strong>
                  <small>
                    {props.google?.connected && props.google?.scope_mismatch
                      ? t("권한이 모자랍니다. 눌러서 다시 허용해 주세요 (드라이브에 올리기)")
                      : props.google?.connected
                      ? t("{0} · 이 PC에 암호화 저장", props.google.email || t("연결됨"))
                      : props.googleBusy
                        ? t("브라우저에서 로그인을 기다리는 중입니다")
                        : props.google?.configured
                          ? t("누르면 브라우저가 열립니다. 한 번만 허용하면 됩니다.")
                          : props.google?.enabled
                            ? t("이 빌드에는 Google 연결 설정이 포함되지 않았습니다.")
                            : t("설정에서 Google 연결을 먼저 켜 주세요.")}
                  </small>
                </span>
              </button>}
              {props.client && props.google?.configured && !props.google.restricted_scopes && (
                <DrivePicker client={props.client} initial={props.google.picked_files ?? 0} />
              )}
              {props.connected && props.client && <PeoplePanel client={props.client} />}
            </section>}

            {/* 이름↔주소. 씨앗은 사람이 심었고 나머지는 자비스가 가 보고 배운 것이다. */}
            <section className="capability-group sites">
              <h4>{t("이름으로 아는 사이트")}<span>{data.sites.length}</span></h4>
              <ul className="site-list">
                {data.sites.map((site) => (
                  <li key={`${site.name}:${site.host}`}>
                    <Route size={11} />
                    <b>{site.name}</b>
                    <code>{site.host}</code>
                    {!site.seeded && <em>{t("배운 것")}</em>}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

export default CapabilityDrawer;
