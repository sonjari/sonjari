/**
 * 리허설용 **걸음 관측** — 뷰어를 화면으로 확인하려면 볼 것이 있어야 한다 (P14).
 *
 * 일곱 종류를 다 덮는다: 목록 · 표 · 코드 · 웹 화면 · 잘린 본문 · 초안 · 실패.
 * 특히 뒤의 셋이 중요하다 —
 *
 *   - **잘린 본문**: 잘렸다는 말이 본문 위에 뜨는지. 사고 Q 가 여기서 났다.
 *   - **초안**: 보낼 것을 보면서 승인하는 자리(P12).
 *   - **실패**: 눈금이 짧고 붉어지는지. 성공만 그리면 고장이 안 보인다.
 *
 * 값은 실제 도구가 돌려주는 모양 그대로다(`observations.py::shape` 가 만든 결과).
 */
import type { Observation } from "../workspace/observation";

const AT = Math.floor(Date.now() / 1000);

function step(row: Partial<Observation> & Pick<Observation, "step" | "tool" | "kind" | "title" | "payload">): Observation {
  return {
    job_id: "fixture-job",
    ok: true,
    status: "completed",
    error: "",
    arguments: {},
    truncation: {},
    at: AT + row.step * 4,
    took_ms: 0,
    truncated: false,
    ...row,
  } as Observation;
}

const CODE = `export function ComputerPane(props: {
  client: JarvisClient | null;
  /** 열려 있는가. 일이 도는 동안만 참이다. */
  open: boolean;
  live: boolean;
  jobId: string;
}) {
  const [rows, setRows] = useState<StepRow[]>([]);
  const [pinned, setPinned] = useState<number | null>(null);
  // 사람이 고른 걸음이 있으면 따라가지 않는다.
  useEffect(() => {
    if (pinned !== null) return setSelected(pinned);
    setSelected(live ? null : followingStep(rows, null));
  }, [rows, pinned, live]);
  return <aside className="computer-pane">{"Sonjari의 컴퓨터"}</aside>;
}`;

const LONG_PAGE = [
  "기업 내부에서 쓰는 메일과 일정을 하나로 묶어 드립니다. 수신함에서 조건에 맞는 메일을",
  "골라내고, 일정으로 옮기고, 담당자에게 자동으로 알립니다. 구축 기간은 영업일 기준 7일이며",
  "유지보수는 월 35만원부터입니다.",
  "",
  "포함 범위: 계정 연결, 규칙 5개까지, 실패 알림, 2주 무상 수정. 추가 규칙은 건당 8만원이고,",
  "사내 결재 연동은 별도 견적입니다.",
  "",
  "작업 방식은 먼저 지금 쓰시는 흐름을 그대로 옮긴 다음, 자동으로 돌릴 부분과 사람이 확인할",
  "부분을 나눕니다. 되돌릴 수 없는 동작은 반드시 사람이 한 번 눌러야 넘어가도록 만듭니다.",
].join("\n");

export const FIXTURE_STEPS: Observation[] = [
  step({
    step: 1,
    tool: "local_search_files",
    kind: "files",
    title: "docs · 4개",
    arguments: { path: "D:\\work\\project\\docs" },
    payload: {
      root: "D:\\work\\project\\docs",
      columns: ["name", "size", "modified"],
      rows: [
        ["단가표_2026.xlsx", "42 KB", "2026-08-14"],
        ["크몽_공고_초안.ko.md", "8 KB", "2026-08-11"],
        ["위시켓_포트폴리오_2026-08-10.ko.md", "14 KB", "2026-08-10"],
        ["2026 상반기 정산.pdf", "220 KB", "2026-07-02"],
      ],
      row_count: 4,
    },
  }),
  step({
    step: 2,
    tool: "local_read_document",
    kind: "table",
    title: "단가표_2026.xlsx · 시트 1개",
    arguments: { path: "D:\\work\\project\\docs\\단가표_2026.xlsx" },
    payload: {
      path: "D:\\work\\project\\docs\\단가표_2026.xlsx",
      source: "xlsx",
      sheets: [
        {
          name: "2026-08",
          columns: ["항목", "우리 단가", "비고"],
          rows: [
            ["기본 자동화 구축", "1200000", ""],
            ["크롤링 · 수집", "800000", "난이도 따라 가산"],
            ["문서 자동 생성", "950000", ""],
            ["메일 · 일정 연동", "600000", "2024년 이후 안 올림"],
            ["유지보수 (월)", "300000", ""],
            ["긴급 대응 (건)", "150000", ""],
          ],
          row_count: 6,
        },
      ],
    },
  }),
  step({
    step: 3,
    tool: "local_read_text_file",
    kind: "code",
    title: "ComputerPane.tsx",
    arguments: { path: "ui\\src\\workspace\\ComputerPane.tsx" },
    payload: {
      path: "D:\\work\\project\\ui\\src\\workspace\\ComputerPane.tsx",
      language: "tsx",
      text: CODE,
      line_count: CODE.split("\n").length,
    },
  }),
  step({
    step: 4,
    tool: "browser_site_search",
    kind: "page",
    title: "업무 자동화 검색 결과 — 크몽",
    arguments: { site: "kmong.com", query: "업무 자동화" },
    payload: {
      url: "https://kmong.com/search?type=gigs&keyword=업무+자동화&sort=review",
      title: "업무 자동화 검색 결과 — 크몽",
      text: "",
      action: "site_search",
      elements: {
        columns: ["순위", "제목", "가격", "리뷰"],
        rows: [
          ["1", "업무 자동화 프로그램 개발해 드립니다", "1,200,000원", "84"],
          ["2", "파이썬 크롤링 · 데이터 수집 자동화", "760,000원", "212"],
          ["3", "엑셀 · 문서 자동 생성 봇", "1,100,000원", "41"],
          ["4", "메일 · 일정 자동 연동 구축", "880,000원", "156"],
          ["5", "RPA 도입 컨설팅 + 유지보수", "2,400,000원", "19"],
        ],
        row_count: 5,
      },
    },
  }),
  step({
    step: 5,
    tool: "browser_extract",
    kind: "page",
    title: "메일 · 일정 자동 연동 구축",
    arguments: { url: "https://kmong.com/gig/641203" },
    truncated: true,
    // ★ 두 군데서 잘렸다. 둘 다 말해야 한다 — 하나만 말하면 나머지가 침묵이 된다.
    truncation: { store: true, char_count: 208_412, to_model: 30_000, model_cut: true },
    payload: {
      url: "https://kmong.com/gig/641203",
      title: "메일 · 일정 자동 연동 구축",
      text: LONG_PAGE,
      action: "extract",
    },
  }),
  step({
    step: 6,
    tool: "browser_click",
    kind: "page",
    title: "가격표 더 보기",
    ok: false,
    status: "failed",
    error: "element_not_found: 가격표 더 보기",
    arguments: { target: "가격표 더 보기" },
    payload: { url: "https://kmong.com/gig/641203", title: "", text: "", action: "click" },
  }),
  step({
    step: 7,
    tool: "google_gmail_prepare_send",
    kind: "draft",
    title: "보낼 것을 준비했습니다",
    payload: {
      action_id: "fixture-action-1",
      kind: "gmail_send",
      fields: {
        to: "파트너 담당자 <partner@example.com>",
        subject: "크몽 공고 단가 조정안 — 4개 항목 올림",
        body:
          "담당자님,\n\n크몽에서 리뷰 많은 순으로 다섯 개를 직접 열어 봤습니다. " +
          "우리 단가가 시세보다 낮은 항목이 네 개입니다.\n\n" +
          "· 메일 · 일정 연동  60만 → 88만\n· 기본 자동화 구축  120만 → 145만\n" +
          "· 문서 자동 생성  95만 → 110만\n· 긴급 대응(건)  15만 → 18만\n\n" +
          "크롤링만 우리가 5% 높습니다. 근거로 쓴 공고 5개 주소는 아래 붙였습니다.",
      },
    },
  }),
];
