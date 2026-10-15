/**
 * 앞 물음이 안 끝났으면 **다시 묻지 않는** 되풀이. 멈추는 함수를 돌려준다.
 *
 * ★ 2026-10-07 「Sonjari 시작하기」가 안 눌린다(6GB 노트북 · 사무실 PC — 스토어 공개판 첫 설치 두 대).
 *   `setInterval(async () => { await 묻기 })` 는 앞 물음이 끝났는지 보지 않는다. 모델을 적용하면 마법사가 컨텍스트 상한을
 *   재기 시작하고(몇 분), 그동안 1초마다 상태를 물었다. 그래픽카드가 모델을 올렸다 내렸다 하는 PC 에서는 물음 하나가 1초를
 *   넘기 쉽다 — 그러면 물음이 쌓이고, 화면은 한 주소에 동시에 몇 개까지만 보낼 수 있어서 **끝냄 기록 같은 다른 요청이 그 뒤에 줄을 선다.**
 *   단추가 죽은 것처럼 보인다. (원인으로 확인된 것은 아니다 — 그 PC 의 기록이 없다. 다만 쌓이는 길은 코드에 분명히 있었다.)
 *   물음이 느려지면 그만큼 덜 묻는다 — 쌓이지 않는다.
 */
export function pollUnlessBusy(ask: () => Promise<unknown> | unknown, everyMs: number): () => void {
  let busy = false;
  const timer = window.setInterval(() => {
    if (busy) return;
    busy = true;
    Promise.resolve()
      .then(ask)
      .catch(() => undefined)
      .finally(() => {
        busy = false;
      });
  }, everyMs);
  return () => window.clearInterval(timer);
}
