import { t } from "../i18n";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { fileBadge, formatBytes, isImage } from "./attachmentPreview";

export interface ShownAttachment {
  name?: string;
  mime_type?: string;
  thumbnail?: string;
  width?: number;
  height?: number;
  size?: number;
}

/**
 * 보낸 말에 붙은 첨부. 그림은 그림으로, 문서는 종류가 보이는 카드로.
 *
 * 미리보기가 없는 옛 기록(09-17 이전)이나 웹뷰가 못 연 형식은 카드로 떨어진다 — 없는 그림을 빈 틀로 두지 않는다.
 */
export function MessageAttachments({ files }: { files: ShownAttachment[] }) {
  const [open, setOpen] = useState<ShownAttachment | null>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!files.length) return null;
  const images = files.filter((file) => isImage(file.mime_type) && file.thumbnail);
  const others = files.filter((file) => !(isImage(file.mime_type) && file.thumbnail));
  return (
    <div className="message-files">
      {images.length > 0 && (
        <div className={`message-images count-${Math.min(images.length, 3)}`}>
          {images.map((file, index) => (
            <button
              key={`${file.name}-${index}`}
              type="button"
              className="message-image"
              onClick={() => setOpen(file)}
              aria-label={t("{0} 크게 보기", file.name ?? t("이미지"))}
            >
              <img src={file.thumbnail} alt={file.name ?? t("첨부 이미지")} loading="lazy" draggable={false} />
              {file.width && file.height ? <span className="message-image-size">{file.width}×{file.height}</span> : null}
            </button>
          ))}
        </div>
      )}
      {others.length > 0 && (
        <div className="message-docs">
          {others.map((file, index) => (
            <span key={`${file.name}-${index}`} className="message-doc" title={file.name}>
              <b className="message-doc-badge">{isImage(file.mime_type) ? "IMG" : fileBadge(file.name ?? "", file.mime_type ?? "")}</b>
              <span className="message-doc-text">
                <span className="message-doc-name">{file.name}</span>
                {file.size ? <span className="message-doc-size">{formatBytes(file.size)}</span> : null}
              </span>
            </span>
          ))}
        </div>
      )}
      {/* 몸(body)에 띄운다 — 말 칸의 등장 애니메이션(transform)이 fixed 를 자기 안에 가둬 오른쪽 칸 밑에 깔렸다. */}
      {open && createPortal(
        <div className="image-lightbox" role="dialog" aria-modal="true" aria-label={open.name} onClick={() => setOpen(null)}>
          <figure onClick={(event) => event.stopPropagation()}>
            <img src={open.thumbnail} alt={open.name ?? t("첨부 이미지")} />
            <figcaption>
              <span>{open.name}</span>
              {open.width && open.height ? <span>{open.width}×{open.height} {t("· 기록에는 미리보기만 남습니다")}</span> : null}
            </figcaption>
          </figure>
          <button type="button" className="image-lightbox-close" onClick={() => setOpen(null)} aria-label={t("닫기")} autoFocus>
            <X size={16} />
          </button>
        </div>,
        document.body,
      )}
    </div>
  );
}
