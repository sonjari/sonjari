import { t } from "../i18n";
import { BriefcaseBusiness, ChevronLeft, Code2, Menu, MessageSquareText, Plus, Settings2, Trash2, Wrench } from "lucide-react";
import { JarvisMark } from "./JarvisMark";
import type { JarvisClient } from "../backend";
import type { ConversationSummary, JarvisState, JobSummary, ScheduleRow, WorkspaceMode } from "../types";
import { timeLabel } from "./format";
import { ScheduleList } from "./JobList";
import { isLive, withLiveRooms } from "./jobs";
import { RAIL_MAX_WIDTH, useNarrow } from "./useNarrow";
import { DELEGATED_PREFIX, callerLabel, originTone, type HandoffOrigin } from "./TakeoverRelay";

/**
 * 사이드바 — **길찾기만** 한다.
 *
 *   위 = 예약           — 걸어 둔 일 (있을 때만)
 *   아래 = 지난 대화     — 무슨 얘기를 했는가. 일이 도는 대화에는 줄 끝에 점이 선다.
 *
 * ★ 2026-09-30: 「일감」 층과 「이 PC에서 실행 중」 카드를 뺐다(대표 요청). 도는 것은 로고가 돌며 말하고,
 *   어느 대화에서 도는지는 그 대화 줄의 점이 말한다 — 같은 사실을 세 번 말하지 않는다.
 *
 * 예전에는 아래층만 있었다. 그래서 143초짜리 일을 시켜 놓고 다른 대화를 열면
 * 그 일이 화면에서 사라졌고, 살아 있는지 확인할 방법이 없었다(R1).
 *
 * ## 층을 둘로 줄였다 (2026-08-19 저녁)
 *
 * 다섯 층이었다: 일감 · 지난 대화 · 할 수 있는 일 · **카메라가 아는 사람(등록 폼까지)**
 * · 이 PC에서 실행 중. 사용자 지적 "한 페이지에 하는 게 너무 많다".
 *
 * 카메라 인물 등록은 **길찾기가 아니라 능력 설정**이다. 그래서 「할 수 있는 일」
 * 서랍으로 옮겼다 — 거기가 "무엇을 할 수 있고 그러려면 무엇이 연결돼야 하나"를
 * 답하는 자리다. 사이드바에는 길찾기만 남긴다: 일감, 그리고 지난 대화.
 */
export function Sidebar(props: {
  open: boolean;
  onToggle: () => void;
  mode: WorkspaceMode;
  onModeChange: (mode: WorkspaceMode) => void;
  sessions: ConversationSummary[];
  sessionId: string;
  connected: boolean;
  state: JarvisState;
  busy: boolean;
  client: JarvisClient | null;
  jobs: JobSummary[];
  schedules: ScheduleRow[];
  now: number;
  onNewConversation: () => void;
  onOpenConversation: (sessionId: string) => void;
  /** 없으면 지우기 단추를 안 그린다(시험판·조종 모드). */
  onDeleteConversation?: (sessionId: string) => void;
  onCancelSchedule: (scheduleId: string) => void;
  onOpenCapabilities: () => void;
  onOpenSettings?: () => void;
  privacyText?: string;
  handoffOrigins?: Record<string, HandoffOrigin>;
}) {
  const { connected } = props;
  // ★ 좁은 창에서는 사람이 펼쳐 둔 설정과 상관없이 **아이콘만** 그린다(2026-09-16 제품 요청: 「최소 창은 글 대신 아이콘」).
  //   CSS 로 글자만 숨기면 버튼 폭 49px 에 「할 수 있는 일」이 세로로 부서졌다(개발 화면 480px 에서 확인).
  const narrow = useNarrow(RAIL_MAX_WIDTH);
  const open = props.open && !narrow;
  const imported = props.sessions.filter((session) => props.handoffOrigins?.[session.session_id]);
  // 지금 도는 판의 방이 아직 목록에 없으면 맨 위에 한 줄을 세운다 — 「도는 중」 점이 붙을 자리다(`withLiveRooms`).
  const regular = withLiveRooms(
    props.sessions.filter((session) => !props.handoffOrigins?.[session.session_id]), props.jobs, t("바깥 AI"),
  ) as ConversationSummary[];
  // 이 대화에서 일이 돌고 있나. 도는 중 = brand(Sonjari 자신), 사람의 승인·계속을 기다림 = signal(사람이 눌러야 움직인다).
  const liveMark = (sessionId: string) => {
    const running = props.jobs.filter((job) => job.session_id === sessionId && isLive(job));
    if (!running.length) return null;
    const waiting = running.some((job) => job.status === "waiting_approval" || job.status === "waiting_continuation");
    return (
      <i
        className={`session-live${waiting ? " waiting" : ""}`}
        title={waiting ? t("이 대화의 일이 승인을 기다립니다") : t("이 대화에서 일하는 중")}
        aria-label={waiting ? t("승인 대기") : t("일하는 중")}
      />
    );
  };
  const sessionButton = (session: ConversationSummary) => {
    const origin = props.handoffOrigins?.[session.session_id];
    // 바깥 AI 가 맡긴 대화(2026-09-30) — 이어온 대화와 같은 출처 이음선을 두른다. 호스트 이름이 없던 옛 과제도 앞머리로 알아본다.
    const delegated = !origin && (session.caller || session.title.startsWith(DELEGATED_PREFIX)) ? session.caller || "" : null;
    const tone = origin ? originTone(origin.tool) : delegated !== null ? originTone(delegated) : "other";
    const sourceName = origin ? origin.toolName : delegated !== null ? callerLabel(delegated) : "";
    const prefixed = origin ? t("{0}에서 이어온 · ", origin.toolName) : delegated !== null ? DELEGATED_PREFIX : "";
    const title = prefixed && session.title.startsWith(prefixed) ? session.title.slice(prefixed.length) : session.title;
    // ★ 지우기 (2026-09-24 사용자 요청: 「채팅창 삭제가 없다」). 버튼 안에 버튼을 넣을 수 없어 줄을 감싼다.
    //   일하는 중인 지금 대화는 못 지운다 — 도는 판의 기록이 사라진다.
    const deletable = open && props.onDeleteConversation && !(props.busy && session.session_id === props.sessionId);
    return (
      <div className="session-row" key={session.session_id}>
        <button
          className={`${session.session_id === props.sessionId ? "active" : ""}${sourceName ? ` handoff-session handoff-${tone}` : ""}`}
          onClick={() => props.onOpenConversation(session.session_id)}
        >
          <MessageSquareText size={15} />
          {open && <span><strong>{sourceName && <em className="handoff-tool">{sourceName}</em>}{title}</strong><small>{timeLabel(session.updated_at)}</small></span>}
          {open && liveMark(session.session_id)}
        </button>
        {deletable && (
          <button
            type="button"
            className="session-delete"
            title={t("이 대화 지우기")}
            aria-label={t("대화 지우기: {0}", title)}
            onClick={(event) => { event.stopPropagation(); props.onDeleteConversation?.(session.session_id); }}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    );
  };
  return (
    <aside className={`workspace-sidebar ${open ? "" : "sidebar-collapsed"}`}>
      <div className="workspace-brand">
        <JarvisMark state={props.state} connected={connected} size={30} />
        {open && <div><strong>Sonjari</strong></div>}
        {!narrow && (
          <button onClick={props.onToggle} aria-label={open ? t("사이드바 접기") : t("사이드바 펼치기")}>
            {open ? <ChevronLeft size={17} /> : <Menu size={17} />}
          </button>
        )}
      </div>
      <div className="workspace-mode-switch" role="tablist" aria-label={t("Sonjari 작업 모드")}>
        <button
          type="button" role="tab" aria-selected={props.mode === "cowork"}
          className={props.mode === "cowork" ? "active" : ""}
          onClick={() => props.onModeChange("cowork")}
          title={t("대화·조사·문서 작업")}
          aria-label="Cowork"
        >
          <BriefcaseBusiness size={15} />{open && <span>Cowork</span>}
        </button>
        <button
          type="button" role="tab" aria-selected={props.mode === "code"}
          className={props.mode === "code" ? "active" : ""}
          onClick={() => props.onModeChange("code")}
          title={t("저장소를 읽고 패치하는 코드 작업")}
          aria-label="Code"
        >
          <Code2 size={16} />{open && <span>Code</span>}
        </button>
      </div>
      <button className="new-chat" onClick={props.onNewConversation} disabled={props.busy} title={t("새 대화")} aria-label={t("새 대화")}>
        <Plus size={17} />{open && t("새 대화")}
      </button>

      {/* 접힌 칸에서는 작업·대화 목록을 그리지 않는다(2026-09-27 요청) — 아이콘만 세로로 늘어서 무엇인지 알 수 없었다.
          작업 중인지는 위 로고가 돌면서 보여 준다. 빈 칸이 아래 단추들을 바닥에 붙인다. */}
      {!open && <div className="sidebar-spacer" aria-hidden="true" />}
      {open && <div className="sidebar-scroll">
        <ScheduleList schedules={props.schedules} now={props.now} onCancelSchedule={props.onCancelSchedule} />

        {imported.length > 0 && <>
          {open && <p className="sidebar-label">{t("이어온 대화")}</p>}
          <nav className="session-list">{imported.map(sessionButton)}</nav>
        </>}
        {open && <p className="sidebar-label">{t("지난 대화")}</p>}
        <nav className="session-list">{regular.map(sessionButton)}</nav>
      </div>}

      {/* 무엇을 할 수 있는지 (R5). 도구 102개·레시피·아는 사이트가 코드 안에만
          있었다 — 쓸 수 있다는 걸 모르면 없는 기능과 같다. */}
      <button className="capabilities-open" onClick={props.onOpenCapabilities} type="button" title={t("할 수 있는 일")} aria-label={t("할 수 있는 일")}>
        <Wrench size={15} />{open && <span>{t("할 수 있는 일")}</span>}
      </button>
      {props.onOpenSettings && (
        <button className="capabilities-open" onClick={props.onOpenSettings} type="button" title={t("설정")} aria-label={t("설정")}>
          <Settings2 size={15} />{open && <span>{t("설정")}</span>}
        </button>
      )}
      {/* 밖으로 나가는 판(파일럿 — Claude API)일 때만 고지한다. 이 PC 에서 도는 판은 로고가 상태를 말한다. */}
      {props.privacyText && open && <p className="sidebar-disclosure">{props.privacyText}</p>}
    </aside>
  );
}
