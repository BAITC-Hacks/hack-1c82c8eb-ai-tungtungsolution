import createClient from "openapi-fetch";
import type { components, paths } from "./schema";
import type {
  AuditRun,
  CareerData,
  Employee,
  Overview,
  Profile,
  ProgressDiff,
  Recommendation,
  Recommendations,
  Session,
  UploadFiles,
  UploadResult,
} from "@/features/types";

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
});

type ApiResult<T> = { data?: T; error?: unknown; response: Response };

function errorDetail(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("detail" in error)) return null;
  const detail = error.detail;
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail.flatMap((item) => {
    if (!item || typeof item !== "object" || !("msg" in item)) return [];
    return typeof item.msg === "string" ? [item.msg] : [];
  });
  return messages.length ? messages.join("; ") : null;
}

async function execute<T>(
  action: string,
  request: () => Promise<ApiResult<T>>,
): Promise<T> {
  try {
    const result = await request();
    if (
      !result.response.ok ||
      result.error !== undefined ||
      result.data === undefined
    ) {
      throw new Error(
        errorDetail(result.error) ??
          `Сервер вернул HTTP ${result.response.status}.`,
      );
    }
    return result.data;
  } catch (error) {
    if (
      error instanceof Error &&
      !error.message.startsWith("Failed to fetch")
    ) {
      throw new Error(`${action}: ${error.message}`, { cause: error });
    }
    throw new Error(
      `${action}: сервер недоступен. Проверьте, что backend и PostgreSQL запущены.`,
      { cause: error },
    );
  }
}

function toSession(value: components["schemas"]["SessionOut"]): Session {
  if (value.role === "hr") return { role: "hr" };
  if (!value.employee_id)
    throw new Error("Сервер вернул сессию без сотрудника.");
  return { role: "employee", employeeId: value.employee_id };
}

export async function getCurrentSession(): Promise<Session> {
  try {
    const result = await api.GET("/api/session", {
      signal: AbortSignal.timeout(10_000),
    });
    if (result.response.status === 401) return null;
    if (!result.response.ok || result.error !== undefined || !result.data) {
      throw new Error(
        errorDetail(result.error) ?? `HTTP ${result.response.status}`,
      );
    }
    return toSession(result.data);
  } catch (error) {
    throw new Error(
      `Не удалось прочитать сессию. Проверьте backend. ${error instanceof Error ? error.message : ""}`,
      { cause: error },
    );
  }
}

export async function createAppSession(
  session: Exclude<Session, null>,
): Promise<Session> {
  const data = await execute("Не удалось войти", () =>
    api.POST("/api/session", {
      body:
        session.role === "employee"
          ? { role: "employee", employee_id: session.employeeId }
          : { role: "hr", employee_id: null },
    }),
  );
  return toSession(data);
}

export async function deleteAppSession(): Promise<void> {
  await execute("Не удалось завершить сессию", () =>
    api.DELETE("/api/session"),
  );
}

export async function checkHealth() {
  const data = await execute("Не удалось проверить сервер", () =>
    api.GET("/api/health", { signal: AbortSignal.timeout(10_000) }),
  );
  if (data.status !== "ok" || data.database !== "ok") {
    throw new Error("Сервер или база данных не готовы.");
  }
  return data;
}

const formatNames = {
  online: "Онлайн",
  offline: "Очно",
  self_paced: "В своём темпе",
} as const;
const workFormatNames: Record<string, string> = {
  office: "Офис",
  hybrid: "Гибридный формат",
  remote: "Удалённый формат",
};
const fallbackNames: Record<string, string> = {
  timeout: "AI не ответил вовремя — применены проверенные правила.",
  round_limit: "AI превысил лимит шагов — применены проверенные правила.",
  invalid_response:
    "AI вернул некорректный ответ — применены проверенные правила.",
  openai_error: "AI временно недоступен — применены проверенные правила.",
};

export function createApiService(): CareerData {
  const skillNames = new Map<string, string>();
  const recommendationTitles = new Map<string, string>();

  return {
    async employees(): Promise<Employee[]> {
      const rows = await execute("Не удалось загрузить сотрудников", () =>
        api.GET("/api/employees"),
      );
      return rows.map((row) => ({
        id: row.employee_id,
        name: row.full_name,
        role: row.role,
        grade: row.grade,
      }));
    },

    async profile(): Promise<Profile> {
      const value = await execute("Не удалось загрузить профиль", () =>
        api.GET("/api/employee/profile"),
      );
      value.skills.forEach((skill) =>
        skillNames.set(skill.skill_id, skill.name),
      );
      return {
        id: value.employee_id,
        name: value.full_name,
        department: value.department,
        role: value.role,
        grade: value.grade,
        tenureMonths: value.tenure_months,
        workFormat: workFormatNames[value.work_format] ?? value.work_format,
        targetGrade: value.trajectory.target_grade,
        readiness: value.trajectory.readiness,
        skills: value.trajectory.skills.map((skill) => ({
          id: skill.skill_id,
          name: skillNames.get(skill.skill_id) ?? skill.skill_id,
          current: skill.current,
          required: skill.required,
          critical: skill.is_critical,
        })),
        history: value.history.map((item) => ({
          id: item.record_id,
          title: item.title,
          date: item.date,
          status: item.status,
        })),
      };
    },

    async recommendations(): Promise<Recommendations> {
      const value = await execute("Не удалось получить рекомендации", () =>
        api.POST("/api/employee/recommendations", {
          body: { message: "Подбери следующие шаги развития" },
          signal: AbortSignal.timeout(12_000),
        }),
      );
      const items: Recommendation[] = value.recommendations.map((item) => {
        recommendationTitles.set(item.event_id, item.title);
        const facts = item.facts;
        return {
          id: item.event_id,
          title: item.title,
          type: "Шаг развития",
          format: formatNames[facts.format],
          hours: facts.duration_hours,
          description: facts.next_session
            ? `Ближайшая дата: ${new Intl.DateTimeFormat("ru").format(new Date(facts.next_session))}.`
            : "Можно начать в удобное время.",
          rationale: item.explanation,
          gains: facts.changes.map((change) => ({
            skillId: change.skill_id,
            name: skillNames.get(change.skill_id) ?? change.skill_id,
            gain: change.after - change.before,
            maxLevel: change.after,
          })),
          factors: item.factors.map((factor) => ({
            name: factor.factor,
            value: factor.value,
            explanation: factor.explanation,
          })),
        };
      });
      return {
        items,
        fallbackUsed: value.fallback_used,
        uncertainty: value.fallback_reason
          ? fallbackNames[value.fallback_reason]
          : value.cache_hit
            ? "Показан последний актуальный результат из кэша."
            : null,
        emptyReason: value.status === "no_candidates" ? value.answer : null,
      };
    },

    async complete(
      _employeeId: string,
      eventId: string,
    ): Promise<ProgressDiff> {
      const value = await execute("Не удалось отметить шаг выполненным", () =>
        api.POST("/api/employee/events/{event_id}/complete", {
          params: { path: { event_id: eventId } },
        }),
      );
      return {
        title: recommendationTitles.get(eventId) ?? "Шаг развития",
        before: value.progress.readiness_before,
        after: value.progress.readiness_after,
        skills: value.progress.changes.map((change) => ({
          name: skillNames.get(change.skill_id) ?? change.skill_id,
          before: change.before,
          after: change.after,
        })),
      };
    },

    async dismiss(_employeeId: string, eventId: string): Promise<void> {
      await execute("Не удалось отложить шаг", () =>
        api.POST("/api/employee/events/{event_id}/dismiss", {
          params: { path: { event_id: eventId } },
        }),
      );
    },

    async overview(): Promise<Overview> {
      const value = await execute("Не удалось загрузить HR-обзор", () =>
        api.GET("/api/hr/overview"),
      );
      return {
        asOfDate: value.as_of_date,
        employeeCount: value.employee_count,
        employeesWithTrajectory: value.employees_with_trajectory,
        promotionReadyCount: value.promotion_ready_count,
        averageReadiness: value.average_readiness ?? null,
        departments: value.departments.map((department) => ({
          name: department.department,
          employees: department.employee_count,
          withTrajectory: department.employees_with_trajectory,
          averageReadiness: department.average_readiness ?? null,
        })),
        weakSkills: value.skill_gaps.map((skill) => ({
          name: skill.name,
          count: skill.employees_with_gap,
        })),
      };
    },

    async audit(): Promise<AuditRun[]> {
      const value = await execute("Не удалось загрузить журнал AI", () =>
        api.GET("/api/hr/agent-runs", {
          params: { query: { limit: 100, offset: 0 } },
        }),
      );
      return value.items.map((run) => ({
        id: String(run.id),
        employee: run.employee_id ?? "Отладочный запуск",
        createdAt: run.created_at,
        latencyMs: run.latency_ms,
        fallbackUsed: run.fallback_used,
        answer: run.answer,
        steps: run.steps.map((step) => ({
          tool: typeof step.tool === "string" ? step.tool : "unknown",
          arguments: step.arguments ?? {},
          result: step.result ?? {},
        })),
      }));
    },

    async upload(files: UploadFiles): Promise<UploadResult> {
      const form = new FormData();
      form.append("employees", files.employees);
      form.append("events", files.events);
      form.append("skills", files.skills);
      form.append("activity_history", files.history);
      const value = await execute("Не удалось загрузить датасет", () =>
        api.POST("/api/hr/dataset", {
          body: {
            employees: files.employees.name,
            events: files.events.name,
            skills: files.skills.name,
            activity_history: files.history.name,
          },
          bodySerializer: () => form,
        }),
      );
      return {
        dataset: value.dataset,
        version: value.version,
        asOfDate: value.as_of_date,
        counts: value.counts,
      };
    },
  };
}
