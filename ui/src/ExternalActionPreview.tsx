import { t } from "./i18n";
import { CalendarClock, FileText, Image as ImageIcon, Mail, ShieldAlert, UploadCloud } from "lucide-react";

// 승인 화면에 무엇을 보여줄지 — 작은 HUD 와 전체화면이 같은 것을 보여야 한다.
// 2026-08-06: 팝업을 없애고 전부 메인 창으로 합치면서, 두 벌로 갈라지지 않도록
// 여기로 옮겼다. 승인 화면이 창마다 다르면 무엇을 승인했는지가 창마다 달라진다.

export const APPROVE_LABELS: Record<string, string> = {
  google_gmail_send: t("승인 후 메일 보내기"),
  google_drive_write: t("승인 후 드라이브에 올리기"),
  google_calendar_create: t("승인 후 일정 등록"),
  google_calendar_update: t("승인 후 일정 수정"),
  google_calendar_delete: t("승인 후 일정 삭제"),
  naver_blog_save_draft: t("승인 후 임시저장"),
  naver_blog_publish: t("승인 후 블로그 발행"),
};

function field(label: string, value: string) {
  return (
    <div className="approval-field">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ExternalActionPreviewBody({ toolName, data }: { toolName: string; data: Record<string, unknown> }) {
  const list = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);
  const text = (value: unknown, fallback = t("(없음)")): string => {
    const trimmed = String(value ?? "").trim();
    return trimmed || fallback;
  };

  if (toolName === "google_gmail_send") {
    const attachments = Array.isArray(data.attachments) ? (data.attachments as Array<{ name?: string }>) : [];
    return (
      <>
        <div className="approval-icon"><Mail size={25} /></div>
        {field(t("받는 사람"), list(data.to).join(", ") || t("(없음)"))}
        {list(data.cc).length > 0 && field(t("참조"), list(data.cc).join(", "))}
        {list(data.bcc).length > 0 && field(t("숨은참조"), list(data.bcc).join(", "))}
        {field(t("제목"), text(data.subject))}
        <p className="approval-body-preview">{text(data.body_preview, t("(본문 없음)"))}</p>
        {attachments.length > 0 && (
          <div className="approval-attachments">
            {attachments.map((item, index) => (
              <span key={`${item.name}-${index}`}><FileText size={12} /> {item.name}</span>
            ))}
          </div>
        )}
      </>
    );
  }

  if (toolName === "google_drive_write") {
    return (
      <>
        <div className="approval-icon"><UploadCloud size={25} /></div>
        {field(t("무엇을"), text(data["무엇을"]))}
        {field(t("어디에"), text(data["어디에"]))}
        {field(t("어떻게"), text(data["어떻게"]))}
        {field(t("크기"), text(data["크기"]))}
        {/* 덮어쓰기가 아니라는 것을 승인 화면이 직접 말한다 — 권한(drive.file)이
            구조로 막고 있지만, 사람은 화면에서 보고 판단한다. */}
        {field(t("원본"), text(data["원본"]))}
        <pre className="approval-body">{text(data["내용 앞부분"], t("(미리보기 없음)"))}</pre>
      </>
    );
  }

  if (toolName === "google_calendar_create") {
    const start = (data.start as Record<string, unknown> | undefined) ?? {};
    const end = (data.end as Record<string, unknown> | undefined) ?? {};
    const conflicts = Array.isArray(data.conflicts) ? data.conflicts.length : 0;
    return (
      <>
        <div className="approval-icon"><CalendarClock size={25} /></div>
        {field(t("제목"), text(data.summary))}
        {field(t("시작"), text(start.dateTime ?? start.date))}
        {field(t("종료"), text(end.dateTime ?? end.date))}
        {data.location ? field(t("장소"), text(data.location)) : null}
        {list(data.attendees).length > 0 && field(t("참석자"), list(data.attendees).join(", "))}
        {field(t("참석자 알림"), data.send_updates === "all" ? t("발송함") : t("발송 안함"))}
        {conflicts > 0 && <p className="approval-warning">{t("⚠ 같은 시간대에")} {conflicts}{t("개의 일정과 겹칩니다")}</p>}
      </>
    );
  }

  if (toolName === "google_calendar_update") {
    const diff = Array.isArray(data.diff) ? (data.diff as Array<{ field?: string; before?: unknown; after?: unknown }>) : [];
    const conflicts = Array.isArray(data.conflicts) ? data.conflicts.length : 0;
    return (
      <>
        <div className="approval-icon"><CalendarClock size={25} /></div>
        {field(t("일정"), text(data.summary))}
        <div className="approval-diff">
          {diff.map((item, index) => (
            <div key={`${item.field}-${index}`}>
              <span>{item.field}</span>
              <small>{text(item.before, t("(없음)"))} → {text(item.after, t("(없음)"))}</small>
            </div>
          ))}
        </div>
        {field(t("참석자 알림"), data.send_updates === "all" ? t("발송함") : t("발송 안함"))}
        {conflicts > 0 && <p className="approval-warning">{t("⚠ 변경된 시간이")} {conflicts}{t("개의 일정과 겹칩니다")}</p>}
      </>
    );
  }

  if (toolName === "google_calendar_delete") {
    const start = (data.start as Record<string, unknown> | undefined) ?? {};
    return (
      <>
        <div className="approval-icon"><CalendarClock size={25} /></div>
        <p className="approval-warning">{t("⚠ 이 일정을 삭제합니다. 되돌릴 수 없습니다.")}</p>
        {field(t("제목"), text(data.summary))}
        {field(t("시각"), text(start.dateTime ?? start.date))}
        {field(t("참석자 알림"), data.send_updates === "all" ? t("발송함") : t("발송 안함"))}
      </>
    );
  }

  if (toolName === "naver_blog_save_draft") {
    return (
      <>
        <div className="approval-icon"><FileText size={25} /></div>
        {field(t("계정"), text(data.account))}
        {field(t("제목"), text(data.title))}
        {field(t("태그 수"), String(data.tag_count ?? 0))}
      </>
    );
  }

  if (toolName === "naver_blog_publish") {
    return (
      <>
        <div className="approval-icon"><ImageIcon size={25} /></div>
        <p className="approval-warning">{t("⚠ 실제로 공개 발행됩니다.")}</p>
        {field(t("계정"), text(data.account))}
        {field(t("제목"), text(data.title))}
        {field(t("공개범위"), text(data.visibility))}
        {data.category ? field(t("카테고리"), text(data.category)) : null}
        {list(data.tags).length > 0 && field(t("태그"), list(data.tags).join(", "))}
        {field(t("발행 시각"), text(data.publish_at))}
        {field(t("첨부 이미지"), t("{0}개", Number(data.image_count ?? 0)))}
      </>
    );
  }

  return <pre>{JSON.stringify(data, null, 2)}</pre>;
}
