/**
 * 모델 태그 → 사람이 읽는 이름 하나 (2026-11-04 대표: 「Qwen3.5 / Qwen 3.5 표기 통일」).
 *
 * 머리 칩은 「Qwen3.5 · 9B」, 목록은 카탈로그의 「Qwen 3.5 9B」라 같은 모델이 두 이름이었다. 카탈로그 쪽 꼴로 맞춘다:
 *   qwen3.5:9b → Qwen 3.5 9B · hf.co/…/Swift-1.5-Qwen3.8-27B-…:… → Swift 27B · hf.co/ornith-ai/Ornith-1.5-9B-GGUF:Q4_K_M → Ornith 9B
 * 창 크기(128K)는 이름에 붙이지 않는다 — 고르기 창 안에 따로 적는다.
 */
export function friendlyModelName(tag: string): string {
  const raw = String(tag || "").trim();
  if (!raw) return "";
  if (raw.toLowerCase().startsWith("hf.co/")) {
    const repo = raw.split(":")[0].split("/").pop() ?? raw;
    const word = repo.split(/[-_]/)[0] ?? repo;
    const size = /(\d+(?:\.\d+)?)B(?![a-z])/i.exec(repo);
    return [cap(word), size ? `${size[1]}B` : ""].filter(Boolean).join(" ");
  }
  // qwen3.5 → Qwen 3.5 · mistral-small3.2 → Mistral Small 3.2 · gemma4 → Gemma 4 (낱말과 판 번호를 띄운다)
  // 우리가 만든 「글만 읽기」 별칭(sonjari-text-…)은 앞말을 떼고 「· 글만」 · 이름 속 크기(27b) · 양자화 꼬리(iq3xxs)는 이름에서 뺀다.
  const [rawName, variant = ""] = raw.split(":");
  const textOnly = /^sonjari-text-/i.test(rawName);
  const words = rawName.replace(/^sonjari-text-/i, "").split(/[-_]/).filter(Boolean);
  const sizeWord = words.find((word) => /^\d+(?:\.\d+)?b$/i.test(word));
  const head = words
    .filter((word) => word !== sizeWord && !/^(i?q\d\w*|bf16|f16|fp16|mtp|gsq|rco|latest)$/i.test(word))
    .map((word) => word.replace(/^([a-z]+)(\d[\d.]*)?$/i, (_m, letters: string, digits?: string) => cap(letters) + (digits ? ` ${digits}` : "")))
    .join(" ");
  const size = /^(\d+(?:\.\d+)?)b/i.exec(variant) ?? (sizeWord ? /^(\d+(?:\.\d+)?)/.exec(sizeWord) : null);
  const named = size ? `${head} ${size[1]}B` : head;
  return textOnly ? `${named} · 글만` : named;
}

function cap(word: string): string {
  return word ? word.charAt(0).toUpperCase() + word.slice(1) : word;
}

/**
 * 같은 이름이 여러 줄일 때 가르는 짧은 꼬리 — hf.co 면 「올린 사람 · 파일 꼬리」, Ollama 태그면 태그 그대로(11-04 대표:
 * 「Qwen3.8 27B」 세 줄이 이름으로 안 갈렸다).
 */
export function modelSource(tag: string): string {
  const raw = String(tag || "").trim();
  if (raw.toLowerCase().startsWith("hf.co/")) {
    const [repoPath, file = ""] = raw.slice(6).split(":");
    const owner = repoPath.split("/")[0] ?? "";
    const tail = file.replace(/\.gguf$/i, "").split("-").filter((w) => /^(i?q\d|bf16|f16|ud|mtp|q\d)/i.test(w)).join("-");
    return [owner, tail || file.replace(/\.gguf$/i, "")].filter(Boolean).join(" · ");
  }
  return raw.replace(/:latest$/, "");
}

/** 창 크기 → 「128K」. */
export function ctxShort(ctx: number): string {
  if (!ctx) return "";
  return ctx >= 1_000_000 ? "1M" : `${Math.round(ctx / 1024)}K`;
}
