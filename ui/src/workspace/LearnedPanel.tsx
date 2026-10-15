import { t } from "../i18n";
import { AnimatePresence, motion } from "framer-motion";
import { Brain, Loader2, Quote, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { JarvisClient } from "../backend";
import type { LearnedFact, LearnedFacts } from "../types";

/**
 * **배운 것** — 자비스가 기억하는 사실을 사람이 보고 고치는 자리 (2026-08-24, P5).
 *
 * ## 왜 추출과 같은 날 만들었나
 *
 * 자동 추출이 도는 순간부터 **틀린 사실이 쌓인다.** 그리고 틀린 사실은 영구적으로
 * 틀리다 — 매 턴 시스템 프롬프트에 실려 가면서 모든 답을 조금씩 물들인다.
 *
 * **사람이 볼 수 없는 기억은 고칠 수도 없다.** 그래서 목록과 지우기가 추출과
 * 한 묶음이어야 한다. 나중에 만들자고 미루면, 그 사이에 들어온 틀린 사실은
 * 아무도 모르게 산다.
 *
 * ## 출처를 반드시 같이 보여 준다
 *
 * "사무실은 부산에 있다"만 보여 주면 지울지 말지 못 정한다. 어느 말에서
 * 나왔는지를 봐야 판단이 선다. `source_message_id` 를 저장할 때 필수로 만든
 * 규율이 여기서 값을 한다.
 *
 * 출처를 **못 찾는 경우도 숨기지 않는다.** 근거 없는 사실이 있다는 것 자체가
 * 사람이 알아야 할 정보다.
 *
 * ## 어디서 왔는지 구별해 보여 준다
 *
 *     심음    사람이 넣은 문장. 출처는 그 낱말이 나온 자리일 뿐이다(근거가 약하다)
 *     뽑음    대화에서 모델이 뽑고 **인용을 대조해** 통과한 것 (근거가 정확하다)
 *     직접    화면에서 사람이 넣은 것
 *
 * 셋을 같은 모양으로 그리면 근거의 세기가 다르다는 것을 사람이 못 본다.
 */

const ORIGIN_LABEL: Record<string, string> = {
  seed: t("심음"),
  extracted: t("뽑음"),
  manual: t("직접"),
};

const KIND_LABEL: Record<string, string> = {
  person: t("사람"),
  product: t("우리 것"),
  preference: t("일하는 방식"),
  ongoing: t("진행 중"),
  reference: t("참고"),
};

export function LearnedPanel({ client, open }: { client: JarvisClient | null; open: boolean }) {
  const [data, setData] = useState<LearnedFacts | null>(null);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!client) return;
    try {
      setData(await client.listFacts());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("기억을 못 읽었습니다"));
    }
  }, [client]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const forget = async (fact: LearnedFact) => {
    if (!client) return;
    setBusy(fact.id);
    try {
      await client.forgetFact(fact.id);
      // 지운 뒤 **다시 읽는다.** 「지웠다」는 응답은 증거가 아니다 — 이 저장소는
      // 되돌림이 조용히 실패해 엿새를 잃은 적이 있다.
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("못 지웠습니다"));
    } finally {
      setBusy(0);
    }
  };

  if (!open) return null;

  if (error) {
    return <p className="learned-empty"><TriangleAlert size={13} /> {error}</p>;
  }
  if (!data) {
    return <p className="learned-empty"><Loader2 size={13} className="spin" /> {t("읽는 중입니다")}</p>;
  }
  if (!data.count) {
    return (
      <p className="learned-empty">
        <Brain size={13} /> {t("아직 배운 것이 없습니다. 대화하면 오래 남을 사실만 골라 여기 쌓입니다.")}
      </p>
    );
  }

  return (
    <div className="learned">
      <p className="learned-head">
        <Brain size={13} />
        {t("배운 사실")} <b>{data.count}</b>{t("개 · 매 턴 실려 가는 것")} <b>{data.always_on_chars.toLocaleString()}</b>{t("자")}
        <span> / {data.always_on_cap.toLocaleString()}</span>
      </p>
      <AnimatePresence initial={false}>
        {data.items.map((fact) => (
          <motion.div
            key={fact.id}
            className="learned-row"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
          >
            <div className="learned-body">
              <p className="learned-fact">
                <i>{KIND_LABEL[fact.kind] ?? fact.kind}</i>
                <b>{fact.subject}</b> {fact.fact}
                <u className={`origin-${fact.origin}`}>{ORIGIN_LABEL[fact.origin] ?? fact.origin}</u>
              </p>
              {fact.source ? (
                <p className="learned-source" title={fact.source.excerpt}>
                  <Quote size={11} /> {fact.source.excerpt}
                </p>
              ) : (
                <p className="learned-source none">
                  <TriangleAlert size={11} /> {t("근거가 된 말을 못 찾았습니다 — 판단하기 어렵다면 지우세요")}
                </p>
              )}
            </div>
            <button
              onClick={() => void forget(fact)}
              disabled={busy === fact.id}
              title={t("이 사실을 잊는다")}
            >
              {busy === fact.id ? <Loader2 size={13} className="spin" /> : <Trash2 size={13} />}
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
