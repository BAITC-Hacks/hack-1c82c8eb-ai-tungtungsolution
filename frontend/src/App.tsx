import { useState } from "react";
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  ChevronRight,
  Compass,
  Leaf,
  LoaderCircle,
  LogOut,
  Sprout,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmployeeView } from "@/features/employee-view";
import { HrView } from "@/features/hr-view";
import { SessionSwitcher } from "@/features/session-switcher";
import { ErrorNotice } from "@/features/shared";
import {
  createApiService,
  createAppSession,
  deleteAppSession,
  getCurrentSession,
} from "@/api/client";
import type { Session } from "@/features/types";

function Login({
  data,
  busy,
  error,
  onLogin,
}: {
  data: ReturnType<typeof createApiService>;
  busy: boolean;
  error: unknown;
  onLogin: (session: Exclude<Session, null>) => void;
}) {
  return (
    <Card className="mx-auto my-10 max-w-xl border-border/80 shadow-none">
      <CardContent className="space-y-6 p-8">
        <Badge variant="secondary">Вход в Career Quest</Badge>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Начните свой путь
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Выберите сотрудника, чтобы увидеть личную траекторию, или откройте
            HR-пространство.
          </p>
        </div>
        <ErrorNotice error={error} />
        <div className="flex flex-wrap gap-3">
          <SessionSwitcher
            data={data}
            session={null}
            onChange={(next) => next && onLogin(next)}
            disabled={busy}
          />
          <Button disabled={busy} onClick={() => onLogin({ role: "hr" })}>
            Войти как HR
            <ArrowUpRight />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function App() {
  const [data] = useState(createApiService);
  const client = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: getCurrentSession,
    retry: false,
    staleTime: Infinity,
  });

  async function replaceSession(next: Session) {
    await client.cancelQueries();
    client.removeQueries({
      predicate: (query) =>
        !["employees", "session"].includes(String(query.queryKey[0])),
    });
    client.setQueryData(["session"], next);
  }

  const login = useMutation({
    mutationFn: createAppSession,
    onSuccess: replaceSession,
  });
  const logout = useMutation({
    mutationFn: deleteAppSession,
    onSuccess: () => replaceSession(null),
  });
  const mutating = useIsMutating() > 0;
  const busy = mutating || sessionQuery.isPending;
  const session = sessionQuery.data ?? null;
  const sessionError = sessionQuery.error ?? login.error ?? logout.error;

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[230px_minmax(0,1fr)]">
      <a href="#main" className="skip-link">
        Перейти к содержимому
      </a>
      <aside className="flex flex-col border-b bg-white lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex items-center gap-3 px-6 py-6 lg:px-7 lg:py-8">
          <span className="flex size-10 items-center justify-center rounded-xl bg-primary text-white">
            <Sprout className="size-6" />
          </span>
          <div>
            <p className="text-lg font-bold tracking-tight">Career Quest</p>
            <p className="text-[10px] tracking-[0.19em] text-muted-foreground uppercase">
              Halyk · HackAlem AI
            </p>
          </div>
        </div>
        <nav
          aria-label="Режим просмотра"
          className="flex gap-2 px-4 pb-4 lg:flex-col lg:pt-6"
        >
          <p className="eyebrow mb-3 hidden px-3 lg:block">
            Рабочее пространство
          </p>
          <div
            aria-current={session?.role === "employee" ? "page" : undefined}
            className={`flex h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium ${
              session?.role === "employee"
                ? "bg-secondary text-primary"
                : "text-muted-foreground"
            }`}
          >
            <Compass className="size-4" />
            Моё развитие
            <ChevronRight className="ml-auto size-3" />
          </div>
          <Button
            variant="ghost"
            disabled={busy}
            aria-pressed={session?.role === "hr"}
            className={`h-11 justify-start gap-3 px-3 ${
              session?.role === "hr"
                ? "bg-secondary text-primary"
                : "text-muted-foreground"
            }`}
            onClick={() => login.mutate({ role: "hr" })}
          >
            <BriefcaseBusiness className="size-4" />
            HR-пространство
            <ChevronRight className="ml-auto size-3" />
          </Button>
        </nav>
        <div className="mt-auto hidden p-5 lg:block">
          <div className="rounded-2xl border border-[#e8e5d9] bg-[#faf9f3] p-4">
            <Leaf className="mb-3 size-6 text-primary" />
            <p className="text-sm font-medium">Ваш рост — ваш выбор</p>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Рекомендации помогают выбрать направление. Решение всегда за вами.
            </p>
          </div>
          <p className="mt-6 px-2 text-[10px] text-muted-foreground">
            Career Quest · HackAlem AI 2026
          </p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex min-h-20 flex-wrap items-center justify-between gap-3 border-b bg-white/90 px-5 py-3 sm:px-8 lg:px-10">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            Пространство развития
            <ChevronRight className="size-3" />
            <span className="text-foreground">
              {session?.role === "hr"
                ? "HR"
                : session?.role === "employee"
                  ? "Сотрудник"
                  : "Вход"}
            </span>
          </p>
          <div className="flex max-w-full flex-wrap items-center gap-2">
            {!sessionQuery.isPending && (
              <SessionSwitcher
                data={data}
                session={session}
                onChange={(next) => next && login.mutate(next)}
                disabled={busy}
              />
            )}
            {session && (
              <Button
                variant="ghost"
                size="icon"
                className="size-10"
                aria-label="Выйти"
                title="Выйти"
                disabled={busy}
                onClick={() => logout.mutate()}
              >
                <LogOut className="size-4" />
              </Button>
            )}
          </div>
        </header>

        <main
          id="main"
          tabIndex={-1}
          className="mx-auto max-w-[1440px] px-5 py-7 outline-none sm:px-8 sm:py-9 lg:px-10"
        >
          {sessionQuery.isPending ? (
            <div className="flex min-h-80 items-center justify-center gap-3 text-sm text-muted-foreground">
              <LoaderCircle className="size-5 animate-spin text-primary" />
              Проверяем сессию…
            </div>
          ) : session?.role === "employee" ? (
            <div className="space-y-4">
              <ErrorNotice error={sessionError} />
              <EmployeeView
                key={session.employeeId}
                data={data}
                employeeId={session.employeeId}
              />
            </div>
          ) : session?.role === "hr" ? (
            <div className="space-y-4">
              <ErrorNotice error={sessionError} />
              <HrView data={data} />
            </div>
          ) : (
            <Login
              data={data}
              busy={busy}
              error={sessionError}
              onLogin={(next) => login.mutate(next)}
            />
          )}
        </main>
      </div>
    </div>
  );
}
