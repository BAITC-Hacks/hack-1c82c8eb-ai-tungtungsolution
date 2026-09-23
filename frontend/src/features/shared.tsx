import type { ReactNode } from "react";
import { AlertCircle, ArrowUpRight, Sparkles } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>Не удалось выполнить действие</AlertTitle>
      <AlertDescription>
        {error instanceof Error
          ? error.message
          : "Произошла неизвестная ошибка. Повторите попытку."}
      </AlertDescription>
    </Alert>
  );
}
export function LoadingCards() {
  return (
    <div
      role="status"
      aria-label="Загрузка"
      className="grid gap-4 sm:grid-cols-2"
    >
      <Skeleton className="h-48 rounded-2xl" />
      <Skeleton className="h-48 rounded-2xl" />
      <span className="sr-only">Загрузка данных…</span>
    </div>
  );
}
export function SectionTitle({
  eyebrow,
  title,
  aside,
}: {
  eyebrow?: string;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      </div>
      {aside}
    </div>
  );
}
export function SourceBadge({ fallback }: { fallback: boolean }) {
  return (
    <Badge
      variant="outline"
      className={
        fallback
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-emerald-200 bg-emerald-50 text-emerald-800"
      }
    >
      {fallback ? <ArrowUpRight /> : <Sparkles />}
      {fallback ? "Правила (AI недоступен)" : "AI"}
    </Badge>
  );
}
