/**
 * 코드에 색을 입힌다 — **의존성 없이, 원문을 한 글자도 바꾸지 않고** (P11).
 *
 * ## 왜 직접 쓰나
 *
 * 이 저장소는 의존성을 일부러 적게 쓴다(Tailwind 도 일부러 안 넣었다). 색칠 하나
 * 하자고 하이라이터를 통째로 들이면 번들이 커지고, 우리가 읽는 파일은 사실 몇
 * 종류뿐이다 — 자비스가 여는 것은 대개 우리 `.ts/.tsx/.py`, 그리고 `.json`·`.css`·`.sql` 이다.
 *
 * ## 규칙 하나
 *
 * **원문을 절대 바꾸지 않는다.** 토큰을 이어 붙이면 입력과 글자 하나까지 같아야
 * 한다(`토막을 이어 붙이면 원문이다` 검사). 색칠이 내용을 바꾸면 그건 색칠이 아니라
 * 위조다 — 사람이 "봤다고 말한 것"을 대조하러 여기 오는데 대조 대상이 달라진다.
 *
 * 완벽한 파서가 아니다. 중첩 템플릿 문자열이나 정규식 리터럴은 놓친다. 놓치면
 * 그냥 **색이 안 칠해질 뿐** 글자는 그대로다 — 그게 이 설계에서 허용하는 유일한 실패다.
 */

export type TokenKind = "plain" | "comment" | "string" | "number" | "keyword" | "def";

export interface Token {
  kind: TokenKind;
  text: string;
}

const KEYWORDS: Record<string, string[]> = {
  common: [
    "if", "else", "for", "while", "return", "break", "continue", "true", "false",
    "null", "new", "class", "import", "from", "export", "default", "try", "catch",
    "finally", "throw", "await", "async", "in", "of", "not", "and", "or",
  ],
  typescript: ["const", "let", "var", "function", "interface", "type", "as", "extends", "implements", "this", "void", "undefined"],
  tsx: ["const", "let", "var", "function", "interface", "type", "as", "extends", "this", "void", "undefined"],
  javascript: ["const", "let", "var", "function", "this", "undefined"],
  jsx: ["const", "let", "var", "function", "this", "undefined"],
  python: ["def", "elif", "None", "True", "False", "with", "as", "lambda", "yield", "pass", "raise", "global", "assert", "is", "self"],
  sql: ["select", "from", "where", "join", "group", "order", "by", "limit", "insert", "update", "delete", "values", "on", "as"],
  css: [],
  json: ["true", "false", "null"],
};

/** 줄 주석이 무엇으로 시작하는가. 없으면 줄 주석이 없는 언어다. */
const LINE_COMMENT: Record<string, string> = {
  python: "#", sql: "--", bash: "#", powershell: "#", yaml: "#", ini: ";", toml: "#",
};

const BLOCK_LANGUAGES = new Set([
  "typescript", "tsx", "javascript", "jsx", "css", "c", "cpp", "csharp", "java", "go", "rust", "php",
]);

function keywordsFor(language: string): Set<string> {
  return new Set([...KEYWORDS.common, ...(KEYWORDS[language] ?? [])]);
}

/**
 * 한 줄을 토막으로 쪼갠다. 줄 단위로 도는 이유는 화면이 줄번호를 붙이기 때문이다 —
 * 여러 줄에 걸친 문자열은 그래서 놓친다. 놓치면 색이 안 칠해질 뿐이다.
 */
export function tokenizeLine(line: string, language: string): Token[] {
  const keywords = keywordsFor(language);
  const lineComment = LINE_COMMENT[language] ?? (BLOCK_LANGUAGES.has(language) ? "//" : "");
  const tokens: Token[] = [];
  let plain = "";

  const flush = () => {
    if (plain) {
      tokens.push({ kind: "plain", text: plain });
      plain = "";
    }
  };

  let index = 0;
  while (index < line.length) {
    const rest = line.slice(index);

    if (lineComment && rest.startsWith(lineComment)) {
      flush();
      tokens.push({ kind: "comment", text: rest });
      return tokens;
    }

    const char = line[index];

    if (char === '"' || char === "'" || char === "`") {
      const end = findStringEnd(line, index, char);
      flush();
      tokens.push({ kind: "string", text: line.slice(index, end) });
      index = end;
      continue;
    }

    if (/[0-9]/.test(char) && !/[A-Za-z_$]/.test(line[index - 1] ?? "")) {
      const match = /^[0-9][0-9_.]*/.exec(rest);
      if (match) {
        flush();
        tokens.push({ kind: "number", text: match[0] });
        index += match[0].length;
        continue;
      }
    }

    if (/[A-Za-z_$]/.test(char)) {
      const match = /^[A-Za-z_$][A-Za-z0-9_$]*/.exec(rest);
      if (match) {
        const word = match[0];
        if (keywords.has(word)) {
          flush();
          tokens.push({ kind: "keyword", text: word });
        } else if (line[index + word.length] === "(") {
          flush();
          tokens.push({ kind: "def", text: word });
        } else {
          plain += word;
        }
        index += word.length;
        continue;
      }
    }

    plain += char;
    index += 1;
  }
  flush();
  return tokens;
}

/** 닫는 따옴표 자리(그 다음 인덱스). 못 찾으면 줄 끝 — 잘린 줄에서도 안 죽는다. */
function findStringEnd(line: string, start: number, quote: string): number {
  let index = start + 1;
  while (index < line.length) {
    if (line[index] === "\\") {
      index += 2;
      continue;
    }
    if (line[index] === quote) return index + 1;
    index += 1;
  }
  return line.length;
}

/** 여러 줄. 화면은 줄마다 번호를 붙이므로 줄 배열로 돌려준다. */
export function tokenize(text: string, language: string): Token[][] {
  return text.split("\n").map((line) => tokenizeLine(line, language));
}
