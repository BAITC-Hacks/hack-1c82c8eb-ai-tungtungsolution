import { useState, type FormEvent } from "react";
import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  FileJson,
  FileUp,
  ListChecks,
  Target,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { useAudit, useOverview, useUpload } from "./queries";
import { ErrorNotice, LoadingCards, SectionTitle, SourceBadge } from "./shared";
import { dateLabel } from "./format";
import type { CareerData, UploadFiles } from "./types";

function Overview({ data }: { data: CareerData }) {
  const query = useOverview(data);
  if (query.isPending) return <LoadingCards />;
  if (query.isError)
    return (
      <div className="space-y-3">
        <ErrorNotice error={query.error} />
        <Button onClick={() => void query.refetch()}>Повторить</Button>
      </div>
    );
  const overview = query.data;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          {
            label: "Сотрудников",
            value: overview.employeeCount,
            icon: Users,
          },
          {
            label: "Средняя готовность",
            value:
              overview.averageReadiness === null
                ? "—"
                : `${Math.round(overview.averageReadiness)}%`,
            icon: BarChart3,
          },
          {
            label: "Готовы по навыкам",
            value: overview.promotionReadyCount,
            icon: Target,
          },
        ].map(({ label, value, icon: Icon }) => (
          <Card key={label} className="border-border/80 shadow-none">
            <CardContent className="flex items-center justify-between px-6">
              <div>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-3 text-3xl font-semibold tracking-tight">
                  {value}
                </p>
              </div>
              <span className="rounded-2xl bg-secondary p-3">
                <Icon className="size-5 text-primary" />
              </span>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card className="border-border/80 shadow-none">
          <CardContent className="px-6">
            <SectionTitle
              title="Где нужна поддержка"
              eyebrow="Разрывы в навыках"
            />
            <p className="mb-6 text-sm text-muted-foreground">
              Количество сотрудников, у которых навык ниже требований следующего
              грейда.
            </p>
            <div className="space-y-5">
              {overview.weakSkills.map((skill) => (
                <div key={skill.name}>
                  <div className="mb-2 flex justify-between gap-3 text-sm">
                    <span>{skill.name}</span>
                    <span className="font-medium">{skill.count} чел.</span>
                  </div>
                  <Progress
                    value={
                      (100 * skill.count) / Math.max(1, overview.employeeCount)
                    }
                    aria-label={`${skill.name}: ${skill.count} сотрудников`}
                    className="h-2"
                  />
                </div>
              ))}
              {!overview.weakSkills.length && (
                <p className="text-sm text-muted-foreground">
                  Разрывов по навыкам нет.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
        <Card className="border-border/80 shadow-none">
          <CardContent className="px-6">
            <SectionTitle
              title="Готовность по отделам"
              eyebrow="Общая картина"
            />
            <p className="mb-6 text-sm text-muted-foreground">
              Агрегированные показатели без рейтинга сотрудников. Данные на{" "}
              {dateLabel(overview.asOfDate)}.
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Отдел</TableHead>
                  <TableHead className="text-right">Сотрудников</TableHead>
                  <TableHead className="text-right">С траекторией</TableHead>
                  <TableHead className="text-right">Готовность</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {overview.departments.map((department) => (
                  <TableRow key={department.name}>
                    <TableCell className="py-4 font-medium">
                      {department.name}
                    </TableCell>
                    <TableCell className="text-right">
                      {department.employees}
                    </TableCell>
                    <TableCell className="text-right">
                      {department.withTrajectory}
                    </TableCell>
                    <TableCell className="text-right font-medium text-primary">
                      {department.averageReadiness === null
                        ? "—"
                        : `${Math.round(department.averageReadiness)}%`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-4 text-xs text-muted-foreground">
              Траектория рассчитана для {overview.employeesWithTrajectory} из{" "}
              {overview.employeeCount} сотрудников.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

const fileFields = [
  {
    key: "employees",
    title: "Профили сотрудников",
    name: "employees.json",
    accept: ".json,application/json",
    required: true,
  },
  {
    key: "history",
    title: "История активностей",
    name: "activity_history.csv",
    accept: ".csv,text/csv",
    required: true,
  },
  {
    key: "events",
    title: "Каталог активностей",
    name: "events.json",
    accept: ".json,application/json",
    required: true,
  },
  {
    key: "skills",
    title: "Навыки и требования",
    name: "skills.json",
    accept: ".json,application/json",
    required: true,
  },
] as const;

const countLabels: Record<string, string> = {
  metadata: "Метаданные",
  employees: "Сотрудники",
  employee_skills: "Навыки сотрудников",
  skills: "Навыки",
  role_profiles: "Профили ролей",
  grade_requirements: "Требования грейдов",
  events: "Активности",
  event_skills: "Эффекты активностей",
  activity_history: "История активностей",
};

function Upload({ data }: { data: CareerData }) {
  const [files, setFiles] = useState<Partial<UploadFiles>>({});
  const [validation, setValidation] = useState<Error | null>(null);
  const upload = useUpload(data);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidation(null);
    upload.reset();
    if (!files.employees || !files.history || !files.events || !files.skills) {
      setValidation(new Error("Выберите все четыре файла датасета."));
      return;
    }
    for (const field of fileFields) {
      const file = files[field.key];
      if (
        file &&
        (!file.size ||
          !file.name
            .toLowerCase()
            .endsWith(field.key === "history" ? ".csv" : ".json"))
      ) {
        setValidation(
          new Error(
            `${field.title}: нужен непустой ${field.key === "history" ? "CSV" : "JSON"} файл.`,
          ),
        );
        return;
      }
    }
    upload.mutate({
      employees: files.employees,
      history: files.history,
      events: files.events,
      skills: files.skills,
    });
  }
  return (
    <div className="max-w-3xl space-y-5">
      <Alert className="border-emerald-200 bg-emerald-50">
        <FileUp />
        <AlertTitle>Загрузка в Career Quest</AlertTitle>
        <AlertDescription>
          Backend проверит связи между записями и обновит датасет только после
          полной валидации всех файлов.
        </AlertDescription>
      </Alert>
      <Card className="border-border/80 shadow-none">
        <CardContent className="px-6">
          <SectionTitle
            title="Загрузка данных"
            eyebrow="Датасет Career Quest"
          />
          <p className="mb-6 text-sm leading-relaxed text-muted-foreground">
            Выберите полный комплект файлов в формате организаторов. Все четыре
            файла обязательны и должны относиться к одной версии датасета.
          </p>
          <form className="space-y-6" onSubmit={submit}>
            <div className="grid gap-5 sm:grid-cols-2">
              {fileFields.map((field) => (
                <div className="rounded-xl border p-4" key={field.key}>
                  <Label
                    htmlFor={`upload-${field.key}`}
                    className="mb-2 flex flex-wrap gap-2"
                  >
                    {field.title}
                    <Badge
                      variant="secondary"
                      className="text-[10px] font-normal"
                    >
                      Обязательно
                    </Badge>
                  </Label>
                  <p className="mb-3 text-xs text-muted-foreground">
                    {field.name}
                  </p>
                  <Input
                    id={`upload-${field.key}`}
                    type="file"
                    accept={field.accept}
                    disabled={upload.isPending}
                    className="h-auto min-h-10 cursor-pointer py-2 text-xs"
                    onChange={(event) => {
                      setFiles((current) => ({
                        ...current,
                        [field.key]: event.target.files?.[0],
                      }));
                      setValidation(null);
                      upload.reset();
                    }}
                  />
                </div>
              ))}
            </div>
            <ErrorNotice error={validation ?? upload.error} />
            <Button
              type="submit"
              className="h-11 px-5"
              disabled={upload.isPending}
            >
              <FileUp className="size-4" />
              {upload.isPending ? "Загрузка…" : "Загрузить датасет"}
            </Button>
          </form>
          {upload.data && (
            <div className="mt-6 space-y-3" aria-live="polite">
              <Alert>
                <CheckCircle2 />
                <AlertTitle>Результат импорта</AlertTitle>
                <AlertDescription>
                  {upload.data.dataset}, версия {upload.data.version}. Данные на{" "}
                  {dateLabel(upload.data.asOfDate)}.
                </AlertDescription>
              </Alert>
              <div className="grid gap-3 sm:grid-cols-3">
                {Object.entries(upload.data.counts).map(([name, count]) => (
                  <div key={name} className="rounded-xl border bg-muted/30 p-4">
                    <p className="text-xs text-muted-foreground">
                      {countLabels[name] ?? name}
                    </p>
                    <p className="mt-2 text-xl font-semibold">{count}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Audit({ data }: { data: CareerData }) {
  const query = useAudit(data);
  return (
    <Card className="border-border/80 shadow-none">
      <CardContent className="px-6">
        <SectionTitle
          title="Журнал AI"
          aside={
            <Button
              variant="outline"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              Обновить
            </Button>
          }
        />
        <p className="mb-6 text-sm text-muted-foreground">
          Реальные запуски агента: шаги инструментов, время ответа и
          использование резервных правил.
        </p>
        <ErrorNotice error={query.error} />
        {query.isPending ? (
          <LoadingCards />
        ) : (
          query.data && (
            <div className="space-y-3">
              {!query.data.length && (
                <div className="rounded-xl border border-dashed p-8 text-center">
                  <ListChecks className="mx-auto mb-3 size-8 text-primary" />
                  <h3 className="font-medium">Запросов пока нет</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Получите рекомендации в роли сотрудника, затем вернитесь
                    сюда.
                  </p>
                </div>
              )}
              {query.data.map((run) => (
                <Collapsible key={run.id} className="rounded-xl border">
                  <CollapsibleTrigger asChild>
                    <button className="flex w-full flex-wrap items-center gap-3 rounded-xl p-4 text-left hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-primary">
                      <div className="mr-auto">
                        <p className="text-sm font-semibold">{run.employee}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {dateLabel(run.createdAt)} ·{" "}
                          {new Date(run.createdAt).toLocaleTimeString("ru")}
                        </p>
                      </div>
                      <SourceBadge fallback={run.fallbackUsed} />
                      <span className="text-xs text-muted-foreground">
                        {run.latencyMs === null
                          ? "время не записано"
                          : `${run.latencyMs} мс`}
                      </span>
                      <ChevronDown className="size-4" />
                      <span className="sr-only">Открыть шаги запроса</span>
                    </button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="border-t p-4">
                    <p className="mb-4 text-sm">{run.answer}</p>
                    <ol className="space-y-3">
                      {run.steps.map((step, index) => (
                        <li
                          key={index}
                          className="min-w-0 rounded-lg bg-muted p-4"
                        >
                          <p className="mb-2 font-mono text-xs font-semibold">
                            {index + 1}. {step.tool}
                          </p>
                          <pre className="max-h-64 overflow-auto text-xs leading-relaxed whitespace-pre-wrap break-all">
                            {JSON.stringify(
                              {
                                arguments: step.arguments,
                                result: step.result,
                              },
                              null,
                              2,
                            )}
                          </pre>
                        </li>
                      ))}
                    </ol>
                  </CollapsibleContent>
                </Collapsible>
              ))}
            </div>
          )
        )}
      </CardContent>
    </Card>
  );
}

export function HrView({ data }: { data: CareerData }) {
  return (
    <div className="page-enter space-y-7">
      <div>
        <p className="eyebrow mb-2">HR · Пространство развития</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Помогайте команде расти<span className="text-primary">.</span>
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Общая картина навыков и возможности для поддержки сотрудников.
        </p>
      </div>
      <Tabs defaultValue="overview" className="gap-6">
        <TabsList className="h-11! max-w-full border bg-white p-1">
          <TabsTrigger value="overview" className="px-3 sm:px-5">
            <BarChart3 />
            Обзор
          </TabsTrigger>
          <TabsTrigger value="upload" className="px-3 sm:px-5">
            <FileUp />
            Загрузка данных
          </TabsTrigger>
          <TabsTrigger value="audit" className="px-3 sm:px-5">
            <FileJson />
            Журнал AI
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Overview data={data} />
        </TabsContent>
        <TabsContent value="upload">
          <Upload data={data} />
        </TabsContent>
        <TabsContent value="audit">
          <Audit data={data} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
