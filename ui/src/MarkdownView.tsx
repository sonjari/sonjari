import { memo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
// ★ 스타일을 **여기서** 가져온다. 진입점(main.tsx)에 두면 이 컴포넌트를 다른 곳에
//   붙일 때 CSS 를 같이 챙기는 것을 잊는다 — 그러면 수식이 그려지긴 하는데
//   글자가 겹쳐 나오고, 아무 에러도 안 난다. 조용히 틀리는 자리를 안 만든다.
import "katex/dist/katex.min.css";
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./backend";

/**
 * 백엔드·모델이 인라인 수식을 `\(...\)`, 블록 수식을 `\[...\]` 로 내보내는 경우가
 * 있는데 remark-math 는 `$...$` / `$$...$$` 만 안다. 그대로 두면 마크다운이
 * 백슬래시를 삼켜 `\frac{1}{4}` 같은 원문이 화면에 그대로 찍힌다.
 *
 * ★ 튜터랩(web/alture-console)의 `normalizeLatexDelimiters.ts` 와 **같은 처리**다.
 *   두 벌을 두면 갈리고, 갈린 쪽은 조용히 틀린다 — 고칠 때 둘 다 고칠 것.
 */
export function normalizeLatexDelimiters(text: string): string {
  if (!text) return "";
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => `$$${expr}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => `$${expr}$`);
}

/** Repair the most common streamed-table boundary emitted by local models. */
export function normalizeJarvisMarkdown(value: string): string {
  return normalizeLatexDelimiters(
    value
      .replace(/\r\n?/g, "\n")
      // 모델이 표 칸 안에서 줄을 바꿀 때 `<br>` 을 쓴다. remark-gfm 은 원시 HTML 을
      // 글자로 흘려보내므로 "300,000원<br>Deluxe:" 가 그대로 찍혔다(2026-08-28 실측).
      //
      // rehypeRaw 로 HTML 을 켜지 않는다 — 표 한 칸 고치려고 모델 출력에 원시 HTML
      // 통로를 여는 것은 값이 안 맞는 거래다. 실제로 쓰이는 태그 하나만 바꾼다.
      // 표 줄 안에서는 개행이 표를 깨뜨리므로 가운뎃점으로 끊는다.
      .replace(/<br\s*\/?>/gi, (_match: string, offset: number, whole: string) => {
        const lineStart = whole.lastIndexOf("\n", offset) + 1;
        return whole.slice(lineStart, offset).trimStart().startsWith("|") ? " · " : "\n";
      })
      .replace(/\|\s*\|\s*(?=:?-{3})/g, "|\n|")
      .replace(/(\|(?:\s*:?-{3}:?\s*\|){2,})\s*(?=[^\n])/g, "$1\n"),
  );
}

type MdNode = { type: string; value?: string; children?: MdNode[] };

/**
 * 한국어에서 `**굵게**` 가 **별표 그대로** 찍히는 것을 고친다 (2026-09-16 밤 화면 확인).
 *
 * CommonMark 강조 규칙(left/right-flanking)은 영어 띄어쓰기를 전제한다. 닫는 `**` 앞이 문장부호
 * (따옴표·괄호)이고 뒤가 글자(조사)면 닫는 표시로 치지 않는다. 한국어는 조사를 붙여 쓰니 자주 걸린다:
 *
 *     **"내 PC에서 대신 움직여주는 AI"**로      ← 별표가 그대로 보였다
 *     **'사용자의 통제권'**입니다
 *     ** Automation(자동화) **과               ← 모델이 안쪽에 띄어쓰기를 넣은 경우
 *
 * 원문을 고치는 방식(폭 없는 공백 끼우기)은 **안 된다** — U+200B 는 CommonMark 의 공백이 아니다.
 * 그래서 파싱이 끝난 뒤, 짝을 못 찾아 **글자로 남은** `**…**` 만 굵게로 바꾼다. 코드·수식 노드는
 * 글자(text) 노드가 아니라서 건드리지 않는다.
 */
export function remarkLooseStrong() {
  const pattern = /\*\*\s*([^*\n]+?)\s*\*\*/g;
  const split = (value: string): MdNode[] => {
    const out: MdNode[] = [];
    let last = 0;
    for (const match of value.matchAll(pattern)) {
      const at = match.index ?? 0;
      if (at > last) out.push({ type: "text", value: value.slice(last, at) });
      out.push({ type: "strong", children: [{ type: "text", value: match[1] }] });
      last = at + match[0].length;
    }
    if (last < value.length) out.push({ type: "text", value: value.slice(last) });
    return out.length ? out : [{ type: "text", value }];
  };
  const walk = (node: MdNode): void => {
    if (!node.children) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type === "text" && child.value?.includes("**")) next.push(...split(child.value));
      else {
        walk(child);
        next.push(child);
      }
    }
    node.children = next;
  };
  return (tree: MdNode) => walk(tree);
}

const components: Components = {
  table: ({ children }) => (
    <div className="markdown-table-wrap" data-no-drag>
      <table>{children}</table>
    </div>
  ),
  // ★ 데스크톱 앱 안에서는 target=_blank 링크가 아무 데로도 안 간다(2026-09-29 「AWS EC2 대시보드 열기」 무반응).
  //   09-29 에는 손자리 크롬 새 탭으로 열었는데, 2026-10-01 밤 베타 테스터 노트북에서 「링크 눌러도 안 된다」 — 무대 모드(크롬이
  //   화면 밖)·크롬이 아직 안 뜬 때는 아무것도 안 보였고, 대신 부르던 window.open 은 앱 안에서 아무 일도 안 한다.
  //   사람이 보려고 누른 링크라 **기본 브라우저**로 연다(늘 보이는 곳). `https://` 없이 적힌 주소도 연다.
  a: ({ href, children }) => {
    const url = externalUrl(href);
    return (
      <a
        href={url || href}
        target="_blank"
        rel="noreferrer"
        onClick={(event) => {
          // 튜토리얼이 「사람이 읽은 곳을 직접 열어 확인했다」를 알 수 있게 알린다(2026-10-16 · 퀘스트 ①). 여는 길은 그대로다.
          if (url) window.dispatchEvent(new CustomEvent("sonjari:link-opened", { detail: { url } }));
          if (!url || !isTauri()) return;
          event.preventDefault();
          void invoke("open_external_url", { url }).catch(() => window.open(url, "_blank", "noreferrer"));
        }}
      >
        {children}
      </a>
    );
  },
};

/** 답 속 링크를 열 주소로 — `https://` 가 빠진 도메인 주소(`saramin.co.kr/...`)는 붙여 준다. 열 수 없는 것은 빈 문자열. */
export function externalUrl(href: string | undefined): string {
  const raw = String(href || "").trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:[/?#].*)?$/i.test(raw)) return `https://${raw}`;
  return "";
}

/**
 * ★ 같은 글이면 다시 풀지 않는다 (2026-10-07 대표: 「대화창이 길어질수록 화면이 느리다」). 마크다운 풀기(표·수식 변환 포함)는 비싸고,
 *   작업 화면은 입력 한 글자·답 한 토큰·1초 시계마다 통째로 다시 그린다 — 지난 답 전부를 그때마다 다시 풀고 있었다.
 */
export const MarkdownView = memo(function MarkdownView({ children, className = "" }: { children: string; className?: string }) {
  return (
    <div className={`markdown ${className}`.trim()}>
      <ReactMarkdown
        // ★ singleTilde: false (2026-10-01 테스터 시험 답). 한국어는 범위를 물결표 하나로 쓴다 — 「1/4~1/8 … (BC1~5)」의
        //   두 물결표 사이가 취소선이 되어 「1/41/8」로 보였다. 취소선은 `~~두 개~~` 일 때만.
        remarkPlugins={[[remarkGfm, { singleTilde: false }], remarkMath, remarkLooseStrong]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {normalizeJarvisMarkdown(children)}
      </ReactMarkdown>
    </div>
  );
});
