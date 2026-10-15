/**
 * 클립보드·드롭에서 **파일을 꺼낸다.**
 *
 * ## 왜 따로 뺐나
 *
 * 처음엔 붙여넣기 처리를 화면 안에 인라인으로 넣었는데, 두 가지를 놓쳤다:
 *
 *     이미지만 받았다      `type.startsWith("image/")` 로 걸러서 pdf·xlsx 가 튕겼다
 *     `items` 만 봤다      엔진에 따라 `files` 에만 채워 주는 경우가 있다
 *
 * 그래서 스크린샷은 되는데 파일은 안 되고, 어떤 판에서는 둘 다 안 됐다.
 * 꺼내는 규칙을 한 곳에 모으고 **검사로 지킨다** — 화면 안에 있으면 아무도 못 잰다.
 *
 * ## 규칙
 *
 * - 종류를 가리지 않는다. 첨부 자체가 이미 종류를 가린다(`readAttachment` 의 32MB,
 *   서버의 형식 판정). 여기서 또 거르면 **두 곳이 갈린다.**
 * - 두 통로를 **둘 다** 본다. 같은 파일이 양쪽에 오면 이름+크기로 하나만 남긴다.
 * - 글자만 붙여넣은 경우 빈 배열이다 — 부르는 쪽이 그때는 가로채지 않는다.
 */

/** 클립보드/드롭 자료에서 실제 파일들만. 없으면 빈 배열. */
export function filesFromTransfer(data: DataTransfer | null | undefined): File[] {
  if (!data) return [];
  const found: File[] = [];

  // 통로 ①: items — 스크린샷 붙여넣기가 대개 여기로 온다.
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (file) found.push(file);
  }

  // 통로 ②: files — 탐색기에서 복사한 파일이 여기로 오는 판이 있다.
  // ★ 2026-09-17 캡처 한 장을 붙였는데 image.png 가 **두 개** 붙었다. 같은 스크린샷이 양쪽 통로로 오는데
  //   `getAsFile()` 이 부를 때마다 새 File 을 만들어 `lastModified`(만든 시각)가 ms 단위로 갈렸고, 그 값을 열쇠에
  //   넣어 둔 탓에 같은 것으로 못 봤다. 이제 통로 **사이**의 겹침만 이름·크기·종류로 지운다 — 한 통로 안에서 온
  //   것은 이름이 같아도 사람이 따로 고른 두 파일이라 둘 다 남긴다.
  const fromItems = [...found];
  for (const file of Array.from(data.files ?? [])) {
    const twin = fromItems.findIndex((other) => sameFile(other, file));
    if (twin >= 0) {
      fromItems.splice(twin, 1);
      continue;
    }
    found.push(file);
  }
  return found;
}

function sameFile(a: File, b: File): boolean {
  return a === b || (a.name === b.name && a.size === b.size && a.type === b.type);
}

/** 첨부 상한(6개)에 맞춰 받을 만큼만. 자리가 없으면 빈 배열. */
export function roomFor(files: File[], already: number, limit = 6): File[] {
  return files.slice(0, Math.max(0, limit - already));
}
