/**
 * 사이드바의 **예약** 줄. 아래층이 지난 대화다.
 *
 * ## 「일감」 층을 뺐다 (2026-09-30, 대표 요청)
 *
 * 원래 이 파일은 도는 일감·끝난 일감을 대화 목록 위에 따로 늘어놓았다(R1 — 143초짜리 일을 시켜 놓고
 * 다른 대화를 열면 그 일이 화면에서 통째로 사라졌다). 그런데 같은 사실이 세 군데에서 말해지고 있었다:
 * 일감 줄 · 대화 줄 · 도는 로고. 끝난 일감은 곧 지난 대화의 한 턴이라 목록이 둘로 겹쳤다.
 *
 * R1 은 그대로 지킨다 — 다른 대화에서 일이 돌면 **그 대화 줄**에 점이 선다(`Sidebar` 의 `liveMark`).
 * 예약만 여기 남는다. 예약은 다른 어디에도 없는 정보다 — 걸어 놓고 잊는 것이 예약의 쓸모인데,
 * 잊은 뒤에 확인할 자리가 없으면 그냥 못 미더운 기능이다.
 */
import { t } from "../i18n";
import { AlarmClock, X } from "lucide-react";
import type { JobSummary, ScheduleRow } from "../types";
import { durationLabel, elapsedSec, pendingSchedules, routineFailed, routineLine, routineResult, scheduleLabel, scheduleWhen } from "./jobs";

/** 줄에 손을 올리면 보이는 글 — 루틴이면 깨진 까닭 · 결과 파일까지(근거를 숨기지 않는다). */
function scheduleTip(row: ScheduleRow): string {
  const result = routineResult(row);
  if (!result) return row.prompt;
  return [row.prompt, ...(result.problems ?? []), ...(result.notes ?? []), result.out ? t("파일: {0}", result.out) : ""]
    .filter(Boolean).join("\n");
}

export function ScheduleList(props: {
  schedules: ScheduleRow[];
  now: number;
  onCancelSchedule: (scheduleId: string) => void;
}) {
  const waiting = pendingSchedules(props.schedules, props.now);
  if (!waiting.length) return null;
  return (
    <div className="job-list">
      <p className="sidebar-label">{t("예약")}</p>
      {waiting.map((row) => {
        const routine = row.kind === "routine";
        const pending = row.status === "pending" || row.status === "dispatching";
        return (
          <div className={`job-row schedule ${routine && routineFailed(row) ? "tone-fail" : "tone-mute"}`} key={row.id}>
            {/* 예약은 아직 열 것이 없다(잡이 안 생겼다). 그래서 버튼이 아니라
                그냥 줄이다 — 눌러도 아무 일 없는 버튼을 두지 않는다. */}
            <span className="job-open" title={scheduleTip(row)}>
              <span className="job-mark"><AlarmClock size={13} /></span>
              <span className="job-text">
                <strong>{row.title}</strong>
                <small>
                  <span className="job-metric">{pending ? scheduleLabel(row, props.now) : t("돎")}</span>
                  <span className="job-state">{pending ? scheduleWhen(row, props.now) : ""}</span>
                </small>
                {routine && (
                  <small>
                    <span className="job-state">{routineLine(row, props.now)}</span>
                  </small>
                )}
              </span>
            </span>
            {pending && (
              <button
                type="button"
                className="job-cancel"
                onClick={() => props.onCancelSchedule(row.id)}
                title={t("이 예약을 지우기")}
                aria-label={t("이 예약 지우기")}
              >
                <X size={12} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** 목록 밖에서도 쓰는 계기값 — 헤더가 도는 일감의 소요를 그릴 때. */
export function jobElapsedLabel(job: JobSummary, now: number): string {
  return durationLabel(elapsedSec(job, now));
}
