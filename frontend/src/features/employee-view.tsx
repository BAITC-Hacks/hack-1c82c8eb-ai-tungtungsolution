import { useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Compass,
  Flag,
  Lightbulb,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActivity, useProfile, useRecommendations } from "./queries";
import { ErrorNotice, LoadingCards, SectionTitle, SourceBadge } from "./shared";
import { dateLabel, factorLabels, percent } from "./format";
import type { CareerData, Profile, Recommendation } from "./types";

const statusLabels = {
  completed: "Выполнено",
  in_progress: "В процессе",
  dropped: "Прервано",
  no_show: "Пропущено",
  declined: "Отказ",
  overdue: "Просрочено",
};

function ProfileSummary({ profile }: { profile: Profile }) {
  const remaining = profile.skills.filter(
    (skill) => skill.current < skill.required,
  );
  const critical = remaining.filter((skill) => skill.critical).length;
  return (
    <div className="grid gap-5 lg:grid-cols-[1.65fr_1fr]">
      <Card className="trajectory-card overflow-hidden border-0 text-white">
        <CardContent className="relative flex h-full flex-col justify-between gap-8 p-7 sm:p-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium tracking-widest text-emerald-100/80 uppercase">
                Ваша траектория
              </p>
              <h2 className="mt-3 text-2xl font-semibold">
                {profile.grade}{" "}
                <span className="mx-2 font-normal text-emerald-200/60">→</span>{" "}
                {profile.targetGrade ?? "Верхний грейд"}
              </h2>
              <p className="mt-2 text-sm text-emerald-100/85">{profile.role}</p>
            </div>
            <div className="rounded-2xl border border-white/20 p-3">
              <TrendingUp className="size-6" />
            </div>
          </div>
          {profile.readiness !== null ? (
            <div>
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <span className="text-sm text-emerald-100">
                  Готовность по навыкам
                </span>
                <strong
                  className="text-4xl font-medium tracking-tight"
                  data-testid="readiness"
                >
                  {percent(profile.readiness)}
                </strong>
              </div>
              <Progress
                value={profile.readiness}
                aria-label="Готовность к следующему грейду"
                className="h-2 bg-white/20 [&_[data-slot=progress-indicator]]:bg-[#b9ec91]"
              />
              <p className="mt-4 text-xs leading-relaxed text-emerald-100/80">
                {remaining.length
                  ? `Навыков для развития: ${remaining.length}. Из них критических: ${critical}.`
                  : "Все требования к навыкам следующего грейда выполнены."}{" "}
                Готовность по навыкам не означает автоматическое повышение.
              </p>
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-emerald-100">
              Следующий грейд в данных не задан. Обсудите дальнейшие направления
              развития с руководителем.
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="border-border/80 shadow-none">
        <CardContent className="p-6 sm:p-7">
          <div className="mb-5 flex items-center gap-3">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-[#f2eddf] text-lg font-semibold text-[#6f644a]">
              {profile.name
                .split(" ")
                .map((word) => word[0])
                .join("")}
            </span>
            <div>
              <p className="font-semibold">{profile.name}</p>
              <p className="text-sm text-muted-foreground">
                {profile.department}
              </p>
            </div>
          </div>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Стаж в компании</dt>
              <dd className="font-medium">{profile.tenureMonths} мес.</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Формат работы</dt>
              <dd className="text-right font-medium">{profile.workFormat}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Текущий грейд</dt>
              <dd>
                <Badge variant="secondary">{profile.grade}</Badge>
              </dd>
            </div>
          </dl>
          <div className="mt-5 flex gap-2 border-t pt-4 text-xs leading-relaxed text-muted-foreground">
            <Compass className="mt-0.5 size-4 shrink-0 text-primary" />
            Развитие в вашем темпе. Вы сами выбираете следующий шаг.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Skills({ profile }: { profile: Profile }) {
  return (
    <Card className="gap-0 border-border/80 py-0 shadow-none">
      <CardContent className="p-6">
        <SectionTitle
          title="Навыки для следующего шага"
          aside={
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-2 rounded-full bg-amber-500" />
              Критический навык
            </span>
          }
        />
        {profile.skills.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Навык</TableHead>
                <TableHead className="min-w-28">Уровень</TableHead>
                <TableHead className="text-right">Цель</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {profile.skills.map((skill) => (
                <TableRow key={skill.id}>
                  <TableCell className="py-4 font-medium">
                    <span className="flex items-center gap-2">
                      {skill.critical && skill.current < skill.required ? (
                        <span
                          className="size-2 shrink-0 rounded-full bg-amber-500"
                          aria-label="Критический навык"
                        />
                      ) : (
                        <span className="size-2 shrink-0" />
                      )}
                      {skill.name}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div
                        className="flex gap-1"
                        role="img"
                        aria-label={`Текущий уровень ${skill.current} из 5`}
                      >
                        {Array.from({ length: 5 }, (_, index) => (
                          <span
                            key={index}
                            className={`h-2 w-3 rounded-sm sm:w-4 ${index < skill.current ? "bg-primary" : index < skill.required ? "bg-emerald-100" : "bg-muted"}`}
                          />
                        ))}
                      </div>
                      <span className="text-xs tabular-nums">
                        {skill.current}/5
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="inline-flex items-center gap-1 text-sm">
                      {skill.current >= skill.required && (
                        <Check className="size-3 text-primary" />
                      )}
                      {skill.required}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="py-6 text-sm text-muted-foreground">
            Требования следующего грейда отсутствуют.
          </p>
        )}
        <p className="mt-4 text-xs text-muted-foreground">
          Тёмные деления — текущий уровень, светлые — разрыв до цели.
        </p>
      </CardContent>
    </Card>
  );
}

function History({ profile }: { profile: Profile }) {
  return (
    <Card className="border-border/80 py-0 shadow-none">
      <CardContent className="p-6">
        <SectionTitle
          title="История развития"
          aside={<Clock3 className="size-4 text-muted-foreground" />}
        />
        {!profile.history.length && (
          <p className="py-6 text-sm text-muted-foreground">
            Здесь появятся пройденные активности.
          </p>
        )}
        <ol className="max-h-80 space-y-5 overflow-y-auto pr-1">
          {profile.history.map((activity) => (
            <li key={activity.id} className="flex gap-3">
              <span
                className={`mt-1 flex size-7 shrink-0 items-center justify-center rounded-full ${activity.status === "completed" ? "bg-emerald-50 text-primary" : "bg-muted text-muted-foreground"}`}
              >
                {activity.status === "completed" ? (
                  <Check className="size-3.5" />
                ) : (
                  <Clock3 className="size-3.5" />
                )}
              </span>
              <div>
                <p className="text-sm leading-snug font-medium">
                  {activity.title}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {dateLabel(activity.date)}
                </p>
                <Badge
                  variant="outline"
                  className="mt-2 text-[10px] font-normal"
                >
                  {statusLabels[activity.status]}
                </Badge>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function RecommendationCard({
  item,
  fallback,
  pending,
  onComplete,
  onDismiss,
  number,
}: {
  item: Recommendation;
  fallback: boolean;
  pending: boolean;
  number: number;
  onComplete: () => void;
  onDismiss: () => void;
}) {
  return (
    <Card
      className="recommendation-card gap-0 overflow-hidden border-border/80 py-0 shadow-none"
      data-testid={`recommendation-${item.id}`}
    >
      <CardContent className="flex h-full flex-col p-6">
        <div className="mb-5 flex items-center justify-between gap-2">
          <span className="flex size-8 items-center justify-center rounded-xl bg-secondary font-mono text-sm text-primary">
            0{number}
          </span>
          <SourceBadge fallback={fallback} />
        </div>
        <div className="mb-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span>{item.type}</span>
          <span aria-hidden>·</span>
          <span>{item.format}</span>
          <span aria-hidden>·</span>
          <span>{item.hours} ч.</span>
        </div>
        <h3 className="text-lg leading-snug font-semibold tracking-tight">
          {item.title}
        </h3>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          {item.description}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {item.gains.map((gain) => (
            <Badge
              key={gain.skillId}
              variant="secondary"
              className="font-normal"
            >
              {gain.name}
              <span className="font-semibold">+{gain.gain}</span>
            </Badge>
          ))}
        </div>
        <p className="mt-5 text-sm leading-relaxed">{item.rationale}</p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {item.factors.map((factor) => (
            <span
              className="rounded-md bg-muted px-2 py-1 text-[10px] text-muted-foreground"
              key={factor.name}
            >
              {factorLabels[factor.name]}
            </span>
          ))}
        </div>
        <Collapsible className="mt-4">
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="h-8 px-0 text-xs text-primary">
              Почему этот шаг?
              <ChevronDown className="size-3" />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <dl className="mt-2 space-y-3 rounded-xl bg-muted/70 p-4">
              {item.factors.map((factor) => (
                <div key={factor.name}>
                  <dt className="flex justify-between gap-2 text-xs font-semibold">
                    <span>{factorLabels[factor.name]}</span>
                    <span>{percent(factor.value * 100)}</span>
                  </dt>
                  <dd className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {factor.explanation}
                  </dd>
                </div>
              ))}
            </dl>
          </CollapsibleContent>
        </Collapsible>
        <div className="mt-auto flex flex-wrap gap-2 pt-6">
          <Button
            className="h-10 flex-1"
            disabled={pending}
            onClick={onComplete}
          >
            <Check className="size-4" />
            Выполнено
          </Button>
          <Button
            variant="outline"
            className="h-10 flex-1"
            disabled={pending}
            onClick={onDismiss}
          >
            Не сейчас
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function EmployeeView({
  data,
  employeeId,
}: {
  data: CareerData;
  employeeId: string;
}) {
  const profile = useProfile(data, employeeId);
  const [requested, setRequested] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const recommendations = useRecommendations(data, employeeId, requested);
  const { complete, dismiss } = useActivity(data, employeeId);
  const busy = complete.isPending || dismiss.isPending;
  function act(kind: "complete" | "dismiss", id: string) {
    setNotice(null);
    complete.reset();
    dismiss.reset();
    if (kind === "complete") complete.mutate(id);
    else
      dismiss.mutate(id, {
        onSuccess: () =>
          setNotice("Шаг отложен. Он учтён при обновлении рекомендаций."),
      });
  }
  if (profile.isPending) return <LoadingCards />;
  if (profile.isError)
    return (
      <div className="space-y-4">
        <ErrorNotice error={profile.error} />
        <Button variant="outline" onClick={() => void profile.refetch()}>
          Повторить загрузку
        </Button>
      </div>
    );
  return (
    <div className="page-enter space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-2">Моё развитие</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Растите в своём темпе<span className="text-primary">.</span>
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            {profile.data.name.split(" ")[0]}, вот ваш путь к следующему
            профессиональному шагу.
          </p>
        </div>
        <Badge
          variant="outline"
          className="gap-1.5 bg-white px-3 py-1.5 font-normal"
        >
          <Target className="size-3.5 text-primary" />
          {profile.data.targetGrade
            ? `Цель: ${profile.data.targetGrade}`
            : "Верхний грейд"}
        </Badge>
      </div>
      <ProfileSummary profile={profile.data} />
      <section
        id="recommendations"
        aria-labelledby="recommendation-title"
        className="scroll-mt-6"
      >
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow mb-2">Небольшие шаги. Заметный рост.</p>
            <h2
              id="recommendation-title"
              className="text-xl font-semibold tracking-tight"
            >
              Рекомендовано для вас
            </h2>
          </div>
          <Button
            className="h-10 gap-2 px-4"
            disabled={recommendations.isFetching || busy}
            onClick={() =>
              requested ? void recommendations.refetch() : setRequested(true)
            }
          >
            <Sparkles className="size-4" />
            {recommendations.isFetching
              ? "Подбираем шаги…"
              : requested
                ? "Обновить рекомендации"
                : "Получить рекомендации"}
          </Button>
        </div>
        <div className="space-y-4" aria-live="polite">
          <ErrorNotice error={complete.error ?? dismiss.error} />
          {complete.data && (
            <Alert className="border-emerald-200 bg-emerald-50">
              <CheckCircle2 />
              <AlertTitle>Шаг выполнен — прогресс обновлён</AlertTitle>
              <AlertDescription>
                <p>{complete.data.title}</p>
                <p className="font-medium">
                  Готовность: {percent(complete.data.before)} →{" "}
                  {percent(complete.data.after)}
                </p>
                {complete.data.skills.map((skill) => (
                  <p key={skill.name}>
                    {skill.name}: {skill.before} → {skill.after}
                  </p>
                ))}
              </AlertDescription>
            </Alert>
          )}
          {notice && (
            <Alert>
              <Check />
              <AlertDescription>{notice}</AlertDescription>
            </Alert>
          )}
          <ErrorNotice error={recommendations.error} />
        </div>
        {!requested && (
          <div className="mt-4 flex flex-col items-start gap-5 rounded-2xl border border-dashed border-primary/25 bg-white/60 p-7 sm:flex-row sm:items-center">
            <span className="rounded-2xl bg-emerald-50 p-4">
              <Lightbulb className="size-7 text-primary" />
            </span>
            <div>
              <h3 className="font-medium">Что поможет двигаться дальше?</h3>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
                Получите до трёх шагов с объяснением: какие навыки они
                развивают, как связаны с грейдом и почему подходят вам.
              </p>
            </div>
            <ArrowRight className="ml-auto hidden size-5 text-primary sm:block" />
          </div>
        )}
        {recommendations.isFetching ? (
          <div className="mt-4">
            <LoadingCards />
          </div>
        ) : (
          recommendations.data &&
          !recommendations.isError && (
            <div className="mt-4">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {recommendations.data.items.map((item, index) => (
                  <RecommendationCard
                    key={item.id}
                    item={item}
                    fallback={recommendations.data.fallbackUsed}
                    pending={busy}
                    number={index + 1}
                    onComplete={() => act("complete", item.id)}
                    onDismiss={() => act("dismiss", item.id)}
                  />
                ))}
              </div>
              {!recommendations.data.items.length && (
                <Alert>
                  <Flag />
                  <AlertTitle>Пока нет подходящих шагов</AlertTitle>
                  <AlertDescription>
                    {recommendations.data.emptyReason}
                  </AlertDescription>
                </Alert>
              )}
              {recommendations.data.uncertainty && (
                <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                  {recommendations.data.uncertainty}
                </p>
              )}
            </div>
          )
        )}
      </section>
      <div className="grid items-start gap-5 xl:grid-cols-[1.65fr_1fr]">
        <Skills profile={profile.data} />
        <History profile={profile.data} />
      </div>
    </div>
  );
}
