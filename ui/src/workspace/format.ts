import { locale } from "../i18n";
/** 화면에 시각을 적는 방식. 오늘 것은 시:분, 지난 것은 월/일. */
export function timeLabel(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString(locale(), { month: "short", day: "numeric" });
}
