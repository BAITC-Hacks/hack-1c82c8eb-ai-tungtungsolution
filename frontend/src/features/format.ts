import type { FactorName } from "./types";

export const factorLabels: Record<FactorName, string> = {
  gap_closure: "Разрыв в навыках",
  grade_relevance: "Следующий грейд",
  history_affinity: "История обучения",
  format_fit: "Удобный формат",
};
export const percent = (value: number | null) =>
  value === null ? "—" : `${Math.round(value)}%`;
export function dateLabel(value: string) {
  return new Intl.DateTimeFormat("ru", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}
