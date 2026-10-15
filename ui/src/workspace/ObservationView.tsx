/**
 * **뷰어** — 자비스가 만진 것을 실물로 편다 (P11·P12).
 *
 * 코드는 줄번호와 함께, 문서는 본문으로, 엑셀은 표로, 웹은 주소와 본문으로,
 * 초안은 보낼 모양 그대로 + 그 자리에서 승인.
 *
 * ## 종류로만 그린다
 *
 * 도구 이름을 보고 분기하지 않는다. 백엔드가 붙인 **종류**(`observations.py::shape`)
 * 하나만 본다 — 도구가 102개고 계속 늘기 때문이다. 새 도구가 생겨도 종류만 맞으면
 * 그날부터 여기 뜬다.
 *
 * ## 잘림은 본문 **위**에 적는다
 *
 * 아래에 적으면 긴 본문에서는 아무도 못 본다. 사고 Q 에서 본문 23%가 조용히
 * 사라졌던 것이 바로 그 모양이었다 — 잘렸다는 사실이 어디에도 없었다.
 */
import { t, locale } from "../i18n";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, Eye, FileText, Link2, Scissors, Send, Table2, Undo2 } from "lucide-react";
import { tokenize } from "./codeHighlight";
import type { Observation, ObservationKind } from "./observation";
import {
  KIND_LABEL, failureLine, markedLines, readingTerms, takeaway, truncationNotes,
} from "./observation";

/** 보관소가 한 걸음에 담는 글자 수. 백엔드 `observations._STORE_CHARS` 와 같아야 한다. */
const STORE_CHARS = 120_000;

const NUMBER = new Intl.NumberFormat(locale());

export function ObservationView(props: {
  item: Observation;
  /** 어느 쪽으로 되감았나. -1 이면 뒤로, 1 이면 앞으로. 0 이면 방향 없이 나타난다. */
  direction?: number;
  /**
   * 지금 승인을 기다리는 건의 `action_id`. 화면에 뜬 초안이 **바로 그것일 때만**
   * 승인 버튼을 보여 준다.
   *
   * ★ "승인 대기 중이면 아무 초안 아래에나 버튼을 단다"로 만들면 안 된다 —
   *   3걸음의 낡은 초안을 보면서 7걸음의 전송을 승인하게 된다. 무엇에 동의하는지가
   *   화면에 같이 있어야 한다는 P12 의 요점이 정확히 거기서 무너진다.
   */
  approvalActionId?: string;
  onApprove?: (approve: boolean) => void;
}) {
  const { item } = props;
  const still = useReducedMotion();
  const notes = truncationNotes(item, STORE_CHARS);
  const failed = failureLine(item);
  // 뒤로 갔으면 왼쪽에서, 앞으로 갔으면 오른쪽에서. 방향이 없으면 아래에서.
  const from = still ? {} : { opacity: 0, x: (props.direction ?? 0) * -10, y: props.direction ? 0 : 6 };

  return (
    <motion.div
      key={item.step}
      className="obs"
      initial={from}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: still ? 0 : 0.16, ease: [0.22, 1, 0.36, 1] }}
    >
      <Source item={item} />
      <Takeaway item={item} />
      {failed && (
        <p className="obs-fail" role="status">
          <AlertTriangle size={12} /> {failed}
        </p>
      )}
      {notes.map((line) => (
        <p className="obs-cut" key={line}>
          <Scissors size={12} /> {line}
        </p>
      ))}
      <Body {...props} />
    </motion.div>
  );
}

/** 어디서 온 것인가 — 경로·주소·도구. 이게 없으면 근거가 아니라 그냥 글이다. */
function Source({ item }: { item: Observation }) {
  const payload = item.payload as Record<string, unknown>;
  const where = String(payload.path || payload.url || item.arguments.path || item.arguments.url || "");
  return (
    <div className="obs-src">
      <span className="obs-kind">{KIND_LABEL[item.kind] ?? item.kind}</span>
      <b title={where || item.tool}>{where || item.tool}</b>
      {where ? <u>{item.tool}</u> : null}
    </div>
  );
}

function Body(props: { item: Observation; approvalActionId?: string; onApprove?: (approve: boolean) => void }) {
  const { item } = props;
  const payload = item.payload as Record<string, any>;
  // 찾던 말이 실제로 들어 있는 줄. 근거가 없으면 빈 집합이고, 그러면 한 줄도 안 칠한다.
  const marks = markedLines(String(payload.text ?? ""), readingTerms(item));

  switch (item.kind) {
    case "code":
      return <CodeBody text={String(payload.text ?? "")} language={String(payload.language ?? "")} marks={marks} />;
    case "document":
      return <DocumentBody text={String(payload.text ?? "")} format={String(payload.format ?? "")} marks={marks} />;
    case "table":
      return <TableBody payload={payload} />;
    case "files":
      return <GridBody columns={payload.columns ?? []} rows={payload.rows ?? []} />;
    case "page":
      return <PageBody payload={payload} />;
    case "draft":
      return (
        <DraftBody
          payload={payload}
          // 이 초안이 지금 기다리는 그 건인가. 아니면 버튼을 안 단다.
          approvable={Boolean(props.approvalActionId) && payload.action_id === props.approvalActionId}
          onApprove={props.onApprove}
        />
      );
    default:
      return <DocumentBody text={String(payload.text ?? "")} format="json" />;
  }
}

function CodeBody({ text, language, marks }: { text: string; language: string; marks?: Set<number> }) {
  const lines = tokenize(text, language);
  const lit = marks ?? new Set<number>();
  return (
    <div className="obs-code-wrap">
      <Scan />
      <pre className="obs-code">
        {lines.map((tokens, index) => (
          <div key={index} className={lit.has(index) ? "lit" : undefined}>
            <i>{index + 1}</i>
            <span>
              {tokens.map((token, at) => (
                <em key={at} className={`t-${token.kind}`}>{token.text}</em>
              ))}
            </span>
          </div>
        ))}
      </pre>
      <FoundLine marks={lit} />
    </div>
  );
}

function DocumentBody({ text, format, marks }: { text: string; format: string; marks?: Set<number> }) {
  if (!text.trim()) {
    return <Empty title={t("본문이 비어 있습니다")} detail={t("파일은 열렸지만 읽을 글자가 없었습니다.")} />;
  }
  const lit = marks ?? new Set<number>();
  // 칠할 줄이 없으면 통짜로 둔다. 줄마다 마디를 만드는 것은 표시할 것이 있을 때의
  // 값이다 — 12만 자짜리 문서에 이유 없이 수천 개 마디를 만들 필요가 없다.
  const body = lit.size
    ? text.split("\n").map((line, at) => (
        <div key={at} className={lit.has(at) ? "lit" : undefined}>{line || "\u00a0"}</div>
      ))
    : text;
  return (
    <div className="obs-doc">
      <Scan />
      <p className="obs-doc-meta">
        <FileText size={12} /> {format || "text"} · {NUMBER.format(text.length)}{t("자")}
      </p>
      <pre>{body}</pre>
      <FoundLine marks={lit} />
    </div>
  );
}

/**
 * 들어올 때 한 번 지나가는 빛. **아무 줄도 지목하지 않는다.**
 *
 * 이건 연출이지 주장이 아니다 — "지금 이걸 읽는다"는 입장 인사다. 어느 줄을
 * 봤다는 말은 `.lit` 만 한다. 움직임을 줄여 달라고 한 사람에게는 안 그린다.
 */
function Scan() {
  const still = useReducedMotion();
  if (still) return null;
  return <span className="obs-scan" aria-hidden />;
}

/** 무엇 때문에 칠했는지 말한다. 표시만 있고 이유가 없으면 사람이 못 읽는다. */
function FoundLine({ marks }: { marks: Set<number> }) {
  if (!marks.size) return null;
  return (
    <p className="obs-found">
      <Eye size={12} /> {t("찾던 말이 있는 줄")} {marks.size}{t("개를 표시했습니다")}
    </p>
  );
}

/**
 * 이 step 이 본 것을 한 줄로. 셀 것이 없으면 아예 안 그린다 (2026-08-23).
 *
 * 말머리는 종류마다 다르다 — "이 화면엔"과 "이 파일은"은 사람이 다음에 무엇을
 * 기대해야 하는지를 바꾼다. 뒤에 붙는 것은 전부 **센 값**이다.
 */
const LEAD: Partial<Record<ObservationKind, string>> = {
  page: t("이 화면엔"),
  code: t("이 파일은"),
  document: t("이 문서는"),
  table: t("여기엔"),
  files: t("여기엔"),
};

function Takeaway({ item }: { item: Observation }) {
  const line = takeaway(item);
  if (!line) return null;
  const lead = LEAD[item.kind];
  return (
    <p className="obs-take">
      <Eye size={12} /> {lead ? `${lead} ${line}` : line}
    </p>
  );
}

/** 엑셀은 시트가 여럿일 수 있다. 시트 이름을 빼면 어느 시트인지 알 수 없다. */
function TableBody({ payload }: { payload: Record<string, any> }) {
  const sheets = Array.isArray(payload.sheets) ? payload.sheets : null;
  if (sheets) {
    return (
      <>
        {sheets.map((sheet: any) => (
          <div className="obs-sheet" key={sheet.name}>
            <p className="obs-doc-meta">
              <Table2 size={12} /> {sheet.name} · {NUMBER.format(sheet.row_count ?? 0)}{t("행")}
            </p>
            <GridBody columns={sheet.columns ?? []} rows={sheet.rows ?? []} />
          </div>
        ))}
      </>
    );
  }
  return <GridBody columns={payload.columns ?? []} rows={payload.rows ?? []} />;
}

function GridBody({ columns, rows }: { columns: string[]; rows: string[][] }) {
  if (!rows.length) {
    return <Empty title={t("행이 없습니다")} detail={t("조회는 됐지만 조건에 맞는 것이 없었습니다.")} />;
  }
  return (
    <div className="obs-grid-wrap">
      <table className="obs-grid">
        <thead>
          <tr>
            {columns.map((name, at) => (
              <th key={name} className={isIdColumn(name, rows, at) ? "id" : ""}>{name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, index) => (
            <tr key={index}>
              {cells.map((cell, at) => (
                <td
                  key={at}
                  className={
                    isIdColumn(columns[at] ?? "", rows, at) ? "id"
                      : isNumeric(cell) ? "num" : ""
                  }
                  title={cell}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * 이 칸이 **사람이 읽을 것이 아닌 식별자**인가.
 *
 * ★ 2026-08-23. `schedule_list` 표에서 `id` 가 맨 앞에 서서 폭을 다 먹었다.
 * 32자리 해시가 세 칸을 차지하는 동안 정작 볼 것(제목·내용)은 잘려 있었다.
 * 식별자는 **있어야 하지만 앞자리를 차지할 이유가 없다** — 좁게 눌러 두고,
 * 필요하면 마우스를 올려 전체를 본다(`title` 속성).
 *
 * 이름으로만 판정하지 않는다. 값이 실제로 길고 사람 말이 아닌지도 본다 —
 * "id" 라는 이름의 짧은 순번(1·2·3)까지 눌러 버리면 오히려 읽기 나빠진다.
 */
function isIdColumn(name: string, rows: string[][], at: number): boolean {
  if (!/^(id|.*_id|uuid|hash|key|token|action_id|job_id)$/i.test(name.trim())) return false;
  const sample = rows.slice(0, 8).map((cells) => cells[at] ?? "");
  const long = sample.filter((value) => value.length >= 16).length;
  return long >= Math.max(1, Math.ceil(sample.length / 2));
}

function isNumeric(value: string): boolean {
  return value !== "" && !Number.isNaN(Number(value.replace(/,/g, "")));
}

function PageBody({ payload }: { payload: Record<string, any> }) {
  const text = String(payload.text ?? "");
  const elements = payload.elements;
  return (
    <>
      {payload.url && (
        <a className="obs-url" href={String(payload.url)} target="_blank" rel="noreferrer">
          <Link2 size={12} /> {String(payload.url)}
        </a>
      )}
      {text.trim()
        ? <div className="obs-doc"><pre>{text}</pre></div>
        : elements
          ? <GridBody columns={elements.columns ?? []} rows={elements.rows ?? []} />
          : <Empty title={t("이 걸음은 글을 안 가져왔습니다")} detail={t("누르거나 옮기기만 한 걸음입니다. 화면은 「지금」에서 봅니다.")} />}
    </>
  );
}

/**
 * 초안 — **보낼 것을 보면서** 승인한다 (P12).
 *
 * 예전에는 승인 카드가 대화 위에 뜨고 내용은 다른 칸에 있었다. 무엇에 동의하는지가
 * 화면에 같이 있어야 한다.
 */
function DraftBody(props: {
  payload: Record<string, any>;
  approvable?: boolean;
  onApprove?: (approve: boolean) => void;
}) {
  const fields = (props.payload.fields ?? {}) as Record<string, string | number | boolean>;
  const rows = Object.entries(fields).filter(([key]) => !["action_id", "kind", "ok", "status"].includes(key));
  return (
    <>
      <div className="obs-draft">
        {rows.length === 0 && <p className="obs-doc-meta">{t("준비된 내용이 아직 안 왔습니다.")}</p>}
        {rows.map(([key, value]) => (
          <div className="obs-draft-row" key={key}>
            <span>{draftLabel(key)}</span>
            <b>{String(value)}</b>
          </div>
        ))}
      </div>
      {props.approvable && props.onApprove && (
        <motion.div
          className="obs-gate"
          initial={{ opacity: 0, y: 12, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ type: "spring", stiffness: 420, damping: 30 }}
        >
          <b>{t("보내기 전에 확인해 주세요")}</b>
          <p>{t("승인하면 그 자리에서 나갑니다. 보낸 것은 Sonjari가 되돌리지 못합니다.")}</p>
          <div className="obs-gate-btns">
            <button type="button" className="go" onClick={() => props.onApprove?.(true)}>
              <Send size={13} /> {t("승인하고 보내기")}
            </button>
            <button type="button" onClick={() => props.onApprove?.(false)}>
              <Undo2 size={13} /> {t("보내지 않기")}
            </button>
          </div>
        </motion.div>
      )}
    </>
  );
}

const DRAFT_LABELS: Record<string, string> = {
  to: t("받는이"), subject: t("제목"), body: t("본문"), summary: t("요약"),
  title: t("제목"), start: t("시작"), end: t("끝"), when: t("때"), where: t("곳"),
};

function draftLabel(key: string): string {
  return DRAFT_LABELS[key] ?? key;
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="obs-empty">
      <b>{title}</b>
      <p>{detail}</p>
    </div>
  );
}

export default ObservationView;
