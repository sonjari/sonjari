/**
 * 공유용 영수증 그림 — 1080×1080 PNG 한 장 (2026-10-21 대표 결정).
 *
 * 카드와 같은 숫자 · 같은 말만 그린다. 토큰과 페이지 수뿐 — 비유 · 달러 · 「약」 · 「배」 없음, 큰 숫자에는 늘 「최소」.
 * **사람 이름 · 메일 · 파일 경로는 그리지 않는다** — 받는 값(`ReceiptFacts`)에 그런 칸이 아예 없다.
 *
 * 색은 tokens.css 의 뜻 그대로 옮겨 적었다(캔버스는 CSS 변수를 못 읽는다). 바닥은 따뜻한 흑연, 종이는 카드 면,
 * 숫자는 고정폭(기계가 센 값), 보라 점 하나만 손자리 자신.
 */
import { t } from "../i18n";

export const RECEIPT_IMAGE_SIZE = 1080;

/** 그림에 들어가는 것 전부. 여기 없는 것은 그림에 못 들어간다. */
export interface ReceiptFacts {
  /** 「클로드」 · 「바깥 AI」 갈래. */
  claude: boolean;
  tokens: number;
  jobs: number;
  pages: number;
  flagged: number;
  /** 화면에 보일 기간 — 예: 「2026.10.14 – 10.21」. */
  period: string;
}

// tokens.css 에서 옮긴 값(rgb 채널). 바꾸면 거기도 같이.
const C = {
  ground: "#0a0908",
  paper: "#1b1815", // surface-3
  line: "#3a342d", // line-strong
  text1: "#f1ede6",
  text2: "#d6d1c8",
  text3: "#b2aca3",
  text4: "#918b82",
  text5: "#878178",
  brand: "#9384e0",
};
const UI = '"Noto Sans KR", "Malgun Gothic", "Segoe UI", sans-serif';
const MONO = 'Consolas, "Cascadia Mono", ui-monospace, monospace';

export function formatCount(n: number, localeTag: string): string {
  return Math.max(0, Math.floor(Number(n) || 0)).toLocaleString(localeTag);
}

/** 기간 표시 — 같은 해면 뒤쪽 해는 뺀다. 시각은 초(백엔드 time.time()). */
export function periodLabel(since: number | undefined, until: number | undefined): string {
  if (!since || !until) return "";
  const a = new Date(since * 1000);
  const b = new Date(until * 1000);
  const md = (d: Date) => `${d.getMonth() + 1}.${String(d.getDate()).padStart(2, "0")}`;
  const head = `${a.getFullYear()}.${md(a)}`;
  return a.getFullYear() === b.getFullYear() ? `${head} – ${md(b)}` : `${head} – ${b.getFullYear()}.${md(b)}`;
}

/** 그림의 문장들 — 카드와 같은 열쇠를 쓴다(번역이 갈리지 않게). */
export function receiptImageText(facts: ReceiptFacts, fmt: (n: number) => string) {
  return {
    brand: t("손자리"),
    title: t("이번 주 영수증"),
    heroLabel: facts.claude ? t("클로드에 안 실은 본문") : t("바깥 AI 에 안 실은 본문"),
    floor: t("최소"),
    number: fmt(facts.tokens),
    unit: t("토큰"),
    note: facts.claude
      ? t("손자리가 이 PC 에서 대신 읽고, 클로드에게는 답과 요약만 돌려줬어요.")
      : t("손자리가 이 PC 에서 대신 읽고, 바깥 AI 에는 답과 요약만 돌려줬어요."),
    stats: [
      { label: facts.claude ? t("클로드가 맡긴 일") : t("바깥 AI 가 맡긴 일"), value: t("{0}건", fmt(facts.jobs)) },
      { label: t("대신 읽은 페이지"), value: t("{0}개", fmt(facts.pages)) },
      { label: t("근거 없는 숫자 표시"), value: t("{0}건", fmt(facts.flagged)) },
    ],
    basis: t("센 글자 ÷ 4.5 로 낸 하한이라 실제는 더 커요 · 측정 판은 뺐어요"),
    site: "sonjari.com",
  };
}

/** 글이 폭을 넘으면 글자 크기를 줄인다(큰 숫자가 열 자리가 돼도 종이 밖으로 안 나가게). */
function fitFont(ctx: CanvasRenderingContext2D, text: string, family: string, weight: number, size: number, maxWidth: number, min = 24): number {
  let px = size;
  for (; px > min; px -= 2) {
    ctx.font = `${weight} ${px}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) break;
  }
  return px;
}

/** 띄어쓰기에서 줄을 나눈다(최대 줄 수 · 넘치면 마지막 줄에 몰아 넣는다). 영어 문장이 종이 밖으로 나가던 v1 을 고친 것. */
export function wrapLines(measure: (text: string) => number, text: string, maxWidth: number, maxLines = 2): string[] {
  const words = text.split(" ");
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure(next) > maxWidth && lines.length < maxLines - 1) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

/** 영수증 종이 — 아래 가장자리를 톱니로 자른다(찢어 낸 영수증). */
function paper(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  const tooth = 18;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + w, y);
  ctx.lineTo(x + w, y + h);
  const teeth = Math.round(w / tooth);
  const step = w / teeth;
  for (let i = teeth; i > 0; i -= 1) {
    ctx.lineTo(x + (i - 0.5) * step, y + h - step / 2);
    ctx.lineTo(x + (i - 1) * step, y + h);
  }
  ctx.closePath();
  ctx.fillStyle = C.paper;
  ctx.fill();
}

function dashed(ctx: CanvasRenderingContext2D, x1: number, x2: number, y: number) {
  ctx.save();
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 2;
  ctx.setLineDash([10, 10]);
  ctx.beginPath();
  ctx.moveTo(x1, y);
  ctx.lineTo(x2, y);
  ctx.stroke();
  ctx.restore();
}

/** 「136건」을 숫자와 단위로 — 단위는 작고 옅게 그린다. 번역마다 단위 자리가 달라도(영어는 없음) 같은 규칙. */
function numberAndUnit(value: string, number: string): { number: string; unit: string } {
  const at = value.indexOf(number);
  return at < 0 ? { number: value, unit: "" } : { number, unit: (value.slice(0, at) + value.slice(at + number.length)).trim() };
}

/**
 * 캔버스에 그린다 — 시험 · 미리보기가 같은 함수를 쓴다.
 *
 * 큰 숫자는 고정폭이 아니라 화면 글꼴로 그린다(v1 비평): 고정폭에서는 쉼표가 숫자 한 칸을 먹어 「912 , 788」처럼 벌어졌다.
 * 종이 길이는 내용에 맞춘다 — 영어처럼 두 줄이 되는 말에서도 빈 칸 없이, 종이는 가운데.
 */
export function drawReceipt(ctx: CanvasRenderingContext2D, facts: ReceiptFacts, fmt: (n: number) => string): void {
  const S = RECEIPT_IMAGE_SIZE;
  const text = receiptImageText(facts, fmt);
  const px = 84; // 종이 바깥 여백
  const pw = S - px * 2;
  const L = px + 64; // 종이 안 왼쪽
  const R = px + pw - 64;
  const width = R - L;
  const measureWith = (font: string) => (value: string) => { ctx.font = font; return ctx.measureText(value).width; };

  // ── 1) 자리 재기(종이 위쪽 기준) ──
  // 설명 줄은 조금 줄여서라도 한 줄이 낫다(한 낱말만 다음 줄로 넘어가면 v2 처럼 꼬리가 남는다). 그래도 길면 두 줄.
  const notePx = fitFont(ctx, text.note, UI, 400, 28, width, 25);
  const noteFont = `400 ${notePx}px ${UI}`;
  const noteLines = wrapLines(measureWith(noteFont), text.note, width);
  const basisFont = `400 24px ${UI}`;
  const basisLines = wrapLines(measureWith(basisFont), text.basis, width);
  ctx.font = `600 40px ${UI}`;
  const floorW = ctx.measureText(text.floor).width + 16;
  const unitW = ctx.measureText(text.unit).width + 16;
  const numPx = fitFont(ctx, text.number, UI, 700, 176, width - floorW - unitW, 60);

  const y = {
    head: 92,
    rule1: 140,
    heroLabel: 214,
    figure: 214 + 34 + Math.round(numPx * 0.86),
  } as Record<string, number>;
  y.note = y.figure + 66;
  y.rule2 = y.note + (noteLines.length - 1) * 40 + 54;
  y.statValue = y.rule2 + 90;
  y.statLabel = y.rule2 + 132;
  y.rule3 = y.rule2 + 182;
  y.basis = y.rule3 + 50;
  const ph = y.basis + (basisLines.length - 1) * 36 + 76;
  const top = Math.max(48, Math.round((S - ph - 56) / 2));

  // ── 2) 그리기 ──
  ctx.fillStyle = C.ground;
  ctx.fillRect(0, 0, S, S);
  paper(ctx, px, top, pw, ph);
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";

  // 머리 — 보라 점(손자리 자신) · 이름 · 무엇인지 · 기간
  ctx.fillStyle = C.brand;
  ctx.beginPath();
  ctx.arc(L + 9, top + y.head - 11, 9, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = C.text1;
  ctx.font = `700 34px ${UI}`;
  ctx.fillText(text.brand, L + 30, top + y.head);
  const brandW = ctx.measureText(text.brand).width;
  ctx.fillStyle = C.text3;
  ctx.font = `400 28px ${UI}`;
  ctx.fillText(text.title, L + 30 + brandW + 18, top + y.head);
  ctx.fillStyle = C.text4;
  ctx.font = `400 24px ${MONO}`;
  ctx.textAlign = "right";
  ctx.fillText(facts.period, R, top + y.head - 2);
  ctx.textAlign = "left";
  dashed(ctx, L, R, top + y.rule1);

  // 주인공 — 클로드에 안 실은 본문 · 최소 N 토큰
  ctx.fillStyle = C.text2;
  ctx.font = `600 36px ${UI}`;
  ctx.fillText(text.heroLabel, L, top + y.heroLabel);
  ctx.fillStyle = C.text3;
  ctx.font = `600 40px ${UI}`;
  ctx.fillText(text.floor, L, top + y.figure);
  ctx.fillStyle = C.text1;
  ctx.font = `700 ${numPx}px ${UI}`;
  const numW = ctx.measureText(text.number).width;
  ctx.fillText(text.number, L + floorW, top + y.figure);
  ctx.fillStyle = C.text3;
  ctx.font = `600 40px ${UI}`;
  ctx.fillText(text.unit, L + floorW + numW + 16, top + y.figure);

  ctx.fillStyle = C.text4;
  ctx.font = noteFont;
  noteLines.forEach((line, index) => ctx.fillText(line, L, top + y.note + index * 40));

  // 세 숫자 — 숫자는 크게, 단위는 작고 옅게
  dashed(ctx, L, R, top + y.rule2);
  const col = width / 3;
  const counts = [facts.jobs, facts.pages, facts.flagged];
  // 이름 셋은 같은 크기로 — 하나만 줄면 그것만 덜 중요해 보인다(v2 영어판).
  const labelPx = Math.min(...text.stats.map((stat) => fitFont(ctx, stat.label, UI, 400, 26, col - 20, 18)));
  text.stats.forEach((stat, index) => {
    const x = L + col * index;
    const parts = numberAndUnit(stat.value, fmt(counts[index]));
    ctx.fillStyle = C.text1;
    const valuePx = fitFont(ctx, parts.number, UI, 700, 60, col - 70, 30);
    ctx.font = `700 ${valuePx}px ${UI}`;
    ctx.fillText(parts.number, x, top + y.statValue);
    if (parts.unit) {
      const w = ctx.measureText(parts.number).width;
      ctx.fillStyle = C.text3;
      ctx.font = `400 30px ${UI}`;
      ctx.fillText(parts.unit, x + w + 6, top + y.statValue);
    }
    ctx.fillStyle = C.text4;
    ctx.font = `400 ${labelPx}px ${UI}`;
    ctx.fillText(stat.label, x, top + y.statLabel);
  });

  // 근거 — 셋 아래 점선 다음
  dashed(ctx, L, R, top + y.rule3);
  ctx.fillStyle = C.text5;
  ctx.font = basisFont;
  basisLines.forEach((line, index) => ctx.fillText(line, L, top + y.basis + index * 36));

  // 종이 밖 — 작은 주소
  ctx.fillStyle = C.text4;
  ctx.font = `400 26px ${MONO}`;
  ctx.textAlign = "right";
  ctx.fillText(text.site, px + pw, Math.min(S - 32, top + ph + 56));
  ctx.textAlign = "left";
}

/** PNG 를 base64(머리 `data:` 없이)로. 글꼴은 윈도우에 있는 것이라 기다릴 것이 거의 없지만, 첫 그림이 대체 글꼴로 나오지 않게 기다린다. */
export async function renderReceiptPng(facts: ReceiptFacts, fmt: (n: number) => string): Promise<string> {
  try {
    await (document as Document & { fonts?: { ready: Promise<unknown> } }).fonts?.ready;
  } catch {
    // 글꼴 상태를 못 읽어도 그린다.
  }
  const canvas = document.createElement("canvas");
  canvas.width = RECEIPT_IMAGE_SIZE;
  canvas.height = RECEIPT_IMAGE_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas_unavailable");
  drawReceipt(ctx, facts, fmt);
  return canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, "");
}
