import { t } from "../i18n";
import { memo, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, X } from "lucide-react";
import type { ShowcaseShot } from "../types";

/**
 * 답이 기댄 페이지 — 답 아래 사진 카드 한두 장 (2026-10-18 대표 결정).
 *
 * 꾸밈이 아니라 **증거**다: 「이 답이 이 화면에서 나왔다」. 그래서 카드는 대화 쪽(따뜻한 흑연)이 아니라
 * 「손자리의 컴퓨터」 쪽 온도(`--machine-*`)로 앉는다 — 오른쪽 판에서 본 그 화면을 한 장 떼어 답 아래 붙인 것이다.
 * 주소 · 시각 · 개수는 기계가 센 값이라 고정폭(tokens.css 「글꼴은 화자다」).
 *
 * 데이터는 그 판 result.showcase(`showcase.pick_showcase_shots`), 사진 바이트는 좁은 문
 * `GET /v1/jobs/{job}/showcase/{index}` 로 받는다. 비어 있으면 **아무것도 안 그린다** — 빈 칸은 「증거가 없다」가 아니라
 * 그냥 소음이다. 판이 도는 동안에도 안 그린다(이 줄은 안착한 답에만 붙는다 · MessageView).
 */

/** 판 결과 · 사진을 가져오는 손. 화면(WorkspaceApp)이 한 번 만들어 넘긴다 — 같은 판을 두 번 묻지 않게 안에서 잡아 둔다. */
export interface ShowcaseSource {
  list(jobId: string): Promise<ShowcaseShot[]>;
  /** 화면에 걸 주소(blob:). 못 받으면 null — 그 카드는 안 그린다. */
  image(jobId: string, index: number): Promise<string | null>;
  open(url: string): void;
}

interface ShowcaseClient {
  getJob(jobId: string): Promise<{ status?: string; result?: { showcase?: ShowcaseShot[] } | null }>;
  fetchShowcaseShot(jobId: string, index: number): Promise<Blob | null>;
}

const FINAL = new Set(["completed", "failed", "cancelled", "canceled", "interrupted"]);
/** 답은 판이 「끝남」으로 적히기 **조금 전에** 대화 기록에 안착한다(runtime: add_exchange → 그 뒤 결과 저장).
 *  그 틈에 물으면 결과가 아직 비어 있다 — 끝났다고 적힐 때까지 몇 번만 다시 묻는다. */
const RETRY_MS = 1500;
const RETRIES = 4;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function createShowcaseSource(
  getClient: () => ShowcaseClient | null,
  openUrl: (url: string) => void,
): ShowcaseSource {
  const lists = new Map<string, Promise<ShowcaseShot[]>>();
  const images = new Map<string, Promise<string | null>>();
  const read = async (jobId: string): Promise<ShowcaseShot[]> => {
    for (let attempt = 0; attempt <= RETRIES; attempt += 1) {
      const client = getClient();
      if (!client) return [];
      const job = await client.getJob(jobId).catch(() => null);
      if (!job) return [];
      const shots = Array.isArray(job.result?.showcase) ? job.result!.showcase! : [];
      if (shots.length || FINAL.has(String(job.status ?? ""))) return shots.slice(0, 2);
      await wait(RETRY_MS);
    }
    return [];
  };
  return {
    list(jobId) {
      let held = lists.get(jobId);
      if (!held) {
        held = read(jobId);
        lists.set(jobId, held);
      }
      return held;
    },
    image(jobId, index) {
      const key = `${jobId}#${index}`;
      let held = images.get(key);
      if (!held) {
        const client = getClient();
        held = client
          ? client.fetchShowcaseShot(jobId, index).then((blob) => (blob ? URL.createObjectURL(blob) : null)).catch(() => null)
          : Promise.resolve(null);
        // 못 받은 것은 잡아 두지 않는다 — 백엔드가 잠깐 늦었던 것일 수 있다. 받은 주소는 이 창이 살아 있는 동안 쓴다(많아야 판당 둘).
        void held.then((url) => { if (!url) images.delete(key); });
        images.set(key, held);
      }
      return held;
    },
    open: openUrl,
  };
}

/** 사이트 이름 — `www.` 는 뗀다. 사람이 아는 이름은 `danawa.com` 이지 `www.danawa.com` 이 아니다. */
export function siteName(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}

/** 읽은 시각 — 시:분(24시). 「00:14 읽음」. */
export function readClock(epochSeconds: number): string {
  if (!Number.isFinite(epochSeconds) || epochSeconds <= 0) return "";
  const date = new Date(epochSeconds * 1000);
  const two = (value: number) => String(value).padStart(2, "0");
  return `${two(date.getHours())}:${two(date.getMinutes())}`;
}

interface ShownShot extends ShowcaseShot {
  index: number;
  src: string;
}

export const ShowcaseStrip = memo(function ShowcaseStrip({ jobId, source }: { jobId: string; source: ShowcaseSource }) {
  const [shots, setShots] = useState<ShownShot[]>([]);
  const [open, setOpen] = useState<ShownShot | null>(null);
  const [near, setNear] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);

  // 화면에 다가올 때만 묻는다 — 긴 대화를 열 때 모든 답의 판 기록을 한꺼번에 긁어 오지 않는다(목록 455KB 사고와 같은 자리).
  useEffect(() => {
    const node = anchorRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setNear(true);
        observer.disconnect();
      }
    }, { rootMargin: "320px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!near || !jobId) return;
    let alive = true;
    void source.list(jobId).then(async (rows) => {
      const loaded = await Promise.all(rows.map(async (row, index) => {
        const src = await source.image(jobId, index);
        return src ? { ...row, index, src } : null;
      }));
      if (alive) setShots(loaded.filter((row): row is ShownShot => row !== null));
    });
    return () => { alive = false; };
  }, [near, jobId, source]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // 아직 모르거나 비었으면 자리만(높이 0) — 빈 틀을 그리지 않는다.
  if (!shots.length) return <div ref={anchorRef} className="showcase-anchor" aria-hidden />;

  return (
    <section className="showcase" aria-label={t("답이 기댄 페이지")}>
      <p className="showcase-label">{t("답이 기댄 페이지")}</p>
      <div className={`showcase-cards count-${shots.length}`}>
        {shots.map((shot) => {
          const site = siteName(shot.url);
          const clock = readClock(shot.read_at);
          return (
            <button
              key={shot.index}
              type="button"
              className="showcase-card"
              onClick={() => setOpen(shot)}
              title={shot.url}
              aria-label={t("{0} 화면 크게 보기", shot.title || site)}
            >
              <span className="showcase-shot">
                <img src={shot.src} alt="" loading="lazy" draggable={false} />
              </span>
              <span className="showcase-meta">
                <span className="showcase-line">
                  <span className="showcase-site">{site}</span>
                  {clock && <span className="showcase-clock">{t("{0} 읽음", clock)}</span>}
                </span>
                {shot.title && <span className="showcase-title">{shot.title}</span>}
                {shot.matched > 0 && (
                  <span className="showcase-matched">{t("답과 맞은 것 {0}개", shot.matched)}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>
      {/* 몸(body)에 띄운다 — 말 칸의 등장 애니메이션(transform)이 fixed 를 자기 안에 가둔다(MessageAttachments 와 같은 까닭). */}
      {open && createPortal(
        <div className="image-lightbox showcase-lightbox" role="dialog" aria-modal="true" aria-label={open.title || siteName(open.url)} onClick={() => setOpen(null)}>
          <figure onClick={(event) => event.stopPropagation()}>
            <img src={open.src} alt={open.title || siteName(open.url)} />
            <figcaption>
              <span className="showcase-lightbox-text">
                <span className="showcase-lightbox-title">{open.title || siteName(open.url)}</span>
                <span className="showcase-lightbox-sub">
                  {siteName(open.url)}
                  {readClock(open.read_at) ? ` · ${t("{0} 읽음", readClock(open.read_at))}` : ""}
                  {open.matched > 0 ? ` · ${t("답과 맞은 것 {0}개", open.matched)}` : ""}
                </span>
              </span>
              {/^https?:\/\//i.test(open.url) && (
                <button type="button" className="showcase-open" onClick={() => source.open(open.url)}>
                  <ExternalLink size={13} aria-hidden /> {t("원래 페이지 열기")}
                </button>
              )}
            </figcaption>
          </figure>
          <button type="button" className="image-lightbox-close" onClick={() => setOpen(null)} aria-label={t("닫기")} autoFocus>
            <X size={16} />
          </button>
        </div>,
        document.body,
      )}
    </section>
  );
});
