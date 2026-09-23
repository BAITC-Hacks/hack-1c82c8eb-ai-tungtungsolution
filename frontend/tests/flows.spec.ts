import { expect, test, type Page } from "@playwright/test";

type MockState = {
  session: { role: "employee" | "hr"; employee_id: string | null } | null;
  readiness: number;
  recommendationIds: string[];
  fallback: boolean;
  failProfileOnce: boolean;
  uploadReceived: boolean;
};

const employees = [
  {
    employee_id: "E0043",
    full_name: "Aidos Akhmetov",
    role: "Frontend Engineer",
    grade: "Senior",
  },
  {
    employee_id: "E0101",
    full_name: "Dana Testova",
    role: "Backend Engineer",
    grade: "Middle",
  },
];

function profile(state: MockState) {
  return {
    employee_id: "E0043",
    full_name: "Aidos Akhmetov",
    department: "Digital Products",
    role: "Frontend Engineer",
    grade: "Senior",
    tenure_months: 28,
    work_format: "hybrid",
    preferred_language: "ru",
    career_goal: { target_grade: "Lead" },
    as_of_date: "2026-10-01",
    skills: [
      {
        skill_id: "SK001",
        name: "System Design",
        level: state.readiness > 70 ? 3 : 2,
      },
      { skill_id: "SK002", name: "SQL", level: 3 },
    ],
    trajectory: {
      employee_id: "E0043",
      role: "Frontend Engineer",
      current_grade: "Senior",
      target_grade: "Lead",
      readiness: state.readiness,
      critical_skills_met: false,
      skills: [
        {
          skill_id: "SK001",
          current: state.readiness > 70 ? 3 : 2,
          required: 4,
          gap: state.readiness > 70 ? 1 : 2,
          is_critical: true,
        },
        {
          skill_id: "SK002",
          current: 3,
          required: 4,
          gap: 1,
          is_critical: false,
        },
      ],
      gaps: [],
      promotion_ready: false,
    },
    history: [
      {
        record_id: "H1",
        event_id: "EV0",
        title: "Python: практики разработки",
        date: "2026-09-22",
        status: "completed",
        completion_pct: 100,
      },
    ],
  };
}

function recommendation(id: string) {
  const design = id === "EV1";
  return {
    event_id: id,
    title: design
      ? "System Design: от сервиса к системе"
      : "SQL: оптимизация запросов",
    explanation: design
      ? "Навык System Design критичен для Lead, а онлайн-формат соответствует рабочему режиму. История похожих активностей учтена."
      : "SQL нужен для следующего грейда, формат можно проходить в своём темпе. История обучения учтена.",
    factors: [
      {
        factor: "gap_closure",
        value: design ? 0.5 : 0.33,
        explanation: "Закрывает часть разрыва.",
      },
      {
        factor: "grade_relevance",
        value: 1,
        explanation: "Навык нужен для Lead.",
      },
      {
        factor: "history_affinity",
        value: 0.6,
        explanation: "Учтена история похожих шагов.",
      },
      {
        factor: "format_fit",
        value: 1,
        explanation: "Формат подходит рабочему режиму.",
      },
    ],
    facts: {
      event_id: id,
      title: design
        ? "System Design: от сервиса к системе"
        : "SQL: оптимизация запросов",
      format: design ? "online" : "self_paced",
      duration_hours: design ? 3 : 4,
      next_session: design ? "2026-10-15" : null,
      factors: {
        gap_closure: 0.5,
        grade_relevance: 1,
        history_affinity: 0.6,
        format_fit: 1,
        score: 0.82,
      },
      history: {
        completed: 1,
        unsuccessful: 0,
        record_ids: ["H1"],
        affinity: 0.67,
      },
      changes: [
        {
          skill_id: design ? "SK001" : "SK002",
          before: design ? 2 : 3,
          after: design ? 3 : 4,
          gain: 1,
        },
      ],
      readiness_before: 68,
      readiness_after: design ? 74 : 72,
      critical_skills_closed: [],
      score: 0.82,
    },
  };
}

async function mockApi(page: Page, overrides: Partial<MockState> = {}) {
  const state: MockState = {
    session: null,
    readiness: 68,
    recommendationIds: ["EV1", "EV2"],
    fallback: false,
    failProfileOnce: false,
    uploadReceived: false,
    ...overrides,
  };
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;
    const method = request.method();
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, json: value });

    if (pathname === "/api/session" && method === "GET") {
      return state.session
        ? json(state.session)
        : json({ detail: "Требуется войти в систему" }, 401);
    }
    if (pathname === "/api/session" && method === "POST") {
      const body = request.postDataJSON() as {
        role: "employee" | "hr";
        employee_id?: string | null;
      };
      state.session = {
        role: body.role,
        employee_id:
          body.role === "employee" ? (body.employee_id ?? null) : null,
      };
      return json(state.session);
    }
    if (pathname === "/api/session" && method === "DELETE") {
      const previous = state.session;
      state.session = null;
      return json(previous);
    }
    if (pathname === "/api/employees") return json(employees);
    if (pathname === "/api/employee/profile") {
      if (state.failProfileOnce) {
        state.failProfileOnce = false;
        return json({ detail: "Профиль временно недоступен" }, 500);
      }
      return json(profile(state));
    }
    if (pathname === "/api/employee/recommendations") {
      const items = state.recommendationIds.map(recommendation);
      return json({
        answer: items.length
          ? "Подобраны следующие шаги."
          : "Подходящих шагов сейчас нет.",
        recommendations: items,
        status: items.length ? "ready" : "no_candidates",
        fallback_used: state.fallback,
        fallback_reason: state.fallback ? "openai_error" : null,
        steps: [],
        latency_ms: 24,
        cache_hit: false,
        id: 11,
        created_at: "2026-10-01T10:00:00Z",
      });
    }
    if (pathname === "/api/employee/events/EV1/complete") {
      state.readiness = 74;
      state.recommendationIds = state.recommendationIds.filter(
        (id) => id !== "EV1",
      );
      return json({
        record_id: "UI_1",
        event_id: "EV1",
        progress: {
          readiness_before: 68,
          readiness_after: 74,
          changes: [{ skill_id: "SK001", before: 2, after: 3, gain: 1 }],
        },
      });
    }
    if (pathname === "/api/employee/events/EV2/dismiss") {
      state.recommendationIds = state.recommendationIds.filter(
        (id) => id !== "EV2",
      );
      return json({ event_id: "EV2", status: "dismissed" });
    }
    if (pathname === "/api/hr/overview") {
      return json({
        as_of_date: "2026-10-01",
        employee_count: 200,
        department_count: 2,
        employees_with_trajectory: 190,
        promotion_ready_count: 12,
        average_readiness: 62.9,
        departments: [
          {
            department: "Digital Products",
            employee_count: 120,
            employees_with_trajectory: 115,
            average_readiness: 65.2,
          },
          {
            department: "Risk",
            employee_count: 80,
            employees_with_trajectory: 75,
            average_readiness: 59.4,
          },
        ],
        skill_gaps: [
          {
            skill_id: "SK001",
            name: "System Design",
            employees_with_gap: 42,
            average_gap: 1.8,
          },
          {
            skill_id: "SK002",
            name: "SQL",
            employees_with_gap: 31,
            average_gap: 1.4,
          },
        ],
      });
    }
    if (pathname === "/api/hr/agent-runs") {
      return json({
        total: 1,
        items: [
          {
            id: 11,
            employee_id: "E0043",
            kind: "recommendation",
            user_input: "Подбери следующие шаги развития",
            answer: "Подобраны следующие шаги.",
            steps: [
              {
                tool: "get_profile",
                arguments: { employee_id: "E0043" },
                result: { grade: "Senior" },
              },
            ],
            created_at: "2026-10-01T10:00:00Z",
            latency_ms: 24,
            fallback_used: state.fallback,
          },
        ],
      });
    }
    if (pathname === "/api/hr/dataset" && method === "POST") {
      const body = request.postDataBuffer()?.toString() ?? "";
      state.uploadReceived = [
        "employees.json",
        "events.json",
        "skills.json",
        "activity_history.csv",
      ].every((name) => body.includes(name));
      return json({
        status: "loaded",
        dataset: "Career Quest",
        version: "1.0",
        as_of_date: "2026-10-01",
        counts: {
          metadata: 3,
          employees: 200,
          employee_skills: 4451,
          skills: 60,
          role_profiles: 32,
          grade_requirements: 412,
          events: 40,
          event_skills: 72,
          activity_history: 2743,
        },
      });
    }
    return json({ detail: `${method} ${pathname} is not mocked` }, 500);
  });
  return state;
}

async function loginEmployee(page: Page) {
  await page
    .getByRole("combobox", { name: "Выбрать сотрудника" })
    .first()
    .click();
  await page.getByRole("combobox", { name: "Поиск сотрудников" }).fill("Aidos");
  await page.getByRole("option", { name: /Aidos Akhmetov/ }).click();
  await expect(
    page.getByRole("heading", { name: "Растите в своём темпе." }),
  ).toBeVisible();
}

test("employee signs in, loads recommendations, completes and dismisses steps", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/");
  await loginEmployee(page);
  await expect(page.getByTestId("readiness")).toHaveText("68%");
  await page
    .getByRole("button", { name: "Получить рекомендации", exact: true })
    .click();
  await expect(page.getByTestId("recommendation-EV1")).toBeVisible();
  await page
    .getByTestId("recommendation-EV1")
    .getByRole("button", { name: "Выполнено", exact: true })
    .click();
  await expect(page.getByText("Готовность: 68% → 74%")).toBeVisible();
  await expect(page.getByTestId("readiness")).toHaveText("74%");
  await expect(page.getByTestId("recommendation-EV1")).toHaveCount(0);
  await page
    .getByTestId("recommendation-EV2")
    .getByRole("button", { name: "Не сейчас" })
    .click();
  await expect(
    page.getByText("Шаг отложен. Он учтён при обновлении рекомендаций."),
  ).toBeVisible();
  await expect(page.getByTestId("recommendation-EV2")).toHaveCount(0);
  expect(state.recommendationIds).toEqual([]);
});

test("fallback is visible and logout clears private data", async ({ page }) => {
  await mockApi(page, { fallback: true });
  await page.goto("/");
  await loginEmployee(page);
  await page
    .getByRole("button", { name: "Получить рекомендации", exact: true })
    .click();
  await expect(page.getByText("Правила (AI недоступен)").first()).toBeVisible();
  await expect(
    page.getByText("AI временно недоступен — применены проверенные правила."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Начните свой путь" }),
  ).toBeVisible();
  await expect(page.getByTestId("readiness")).toHaveCount(0);
});

test("profile API errors are visible and retry recovers", async ({ page }) => {
  await mockApi(page, { failProfileOnce: true });
  await page.goto("/");
  await page
    .getByRole("combobox", { name: "Выбрать сотрудника" })
    .first()
    .click();
  await page.getByRole("option", { name: /Aidos Akhmetov/ }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Профиль временно недоступен",
  );
  await page.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(page.getByTestId("readiness")).toHaveText("68%");
});

test("HR overview, audit log and multipart upload use backend contracts", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Войти как HR" }).click();
  await expect(page.getByText("200", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Готовность по отделам" }),
  ).toBeVisible();
  await expect(page.getByText("Digital Products")).toBeVisible();
  await page.getByRole("tab", { name: "Журнал AI" }).click();
  await page.getByRole("button", { name: /Открыть шаги запроса/ }).click();
  await expect(page.getByText("1. get_profile")).toBeVisible();
  await page.getByRole("tab", { name: "Загрузка данных" }).click();
  await page.getByRole("button", { name: "Загрузить датасет" }).click();
  await expect(
    page.getByText("Выберите все четыре файла датасета."),
  ).toBeVisible();
  await page
    .locator("#upload-employees")
    .setInputFiles({
      name: "employees.json",
      mimeType: "application/json",
      buffer: Buffer.from("{}"),
    });
  await page
    .locator("#upload-events")
    .setInputFiles({
      name: "events.json",
      mimeType: "application/json",
      buffer: Buffer.from("{}"),
    });
  await page
    .locator("#upload-skills")
    .setInputFiles({
      name: "skills.json",
      mimeType: "application/json",
      buffer: Buffer.from("{}"),
    });
  await page
    .locator("#upload-history")
    .setInputFiles({
      name: "activity_history.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("record_id"),
    });
  await page.getByRole("button", { name: "Загрузить датасет" }).click();
  await expect(page.getByText("Career Quest, версия 1.0.")).toBeVisible();
  expect(state.uploadReceived).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
