// Presentation models. The API adapter maps generated OpenAPI types into them.
export type Session =
  | { role: "employee"; employeeId: string }
  | { role: "hr" }
  | null;
export type Skill = {
  id: string;
  name: string;
  current: number;
  required: number;
  critical: boolean;
};
export type Employee = {
  id: string;
  name: string;
  role: string;
  grade: string;
};
export type Activity = {
  id: string;
  title: string;
  date: string;
  status:
    | "completed"
    | "in_progress"
    | "dropped"
    | "no_show"
    | "declined"
    | "overdue";
};
export type Profile = Employee & {
  department: string;
  tenureMonths: number;
  workFormat: string;
  targetGrade: string | null;
  readiness: number | null;
  skills: Skill[];
  history: Activity[];
};
export type FactorName =
  | "gap_closure"
  | "grade_relevance"
  | "history_affinity"
  | "format_fit";
export type Factor = { name: FactorName; value: number; explanation: string };
export type Recommendation = {
  id: string;
  title: string;
  type: string;
  format: string;
  hours: number;
  description: string;
  rationale: string;
  gains: { skillId: string; name: string; gain: number; maxLevel: number }[];
  factors: Factor[];
};
export type Recommendations = {
  items: Recommendation[];
  fallbackUsed: boolean;
  uncertainty: string | null;
  emptyReason: string | null;
};
export type ProgressDiff = {
  title: string;
  before: number | null;
  after: number | null;
  skills: { name: string; before: number; after: number }[];
};
export type Overview = {
  asOfDate: string;
  employeeCount: number;
  employeesWithTrajectory: number;
  promotionReadyCount: number;
  averageReadiness: number | null;
  departments: {
    name: string;
    employees: number;
    withTrajectory: number;
    averageReadiness: number | null;
  }[];
  weakSkills: { name: string; count: number }[];
};
export type AuditRun = {
  id: string;
  employee: string;
  createdAt: string;
  latencyMs: number | null;
  fallbackUsed: boolean;
  answer: string;
  steps: { tool: string; arguments: unknown; result: unknown }[];
};
export type UploadFiles = {
  employees: File;
  history: File;
  events: File;
  skills: File;
};
export type UploadResult = {
  dataset: string;
  version: string;
  asOfDate: string;
  counts: Record<string, number>;
};
export interface CareerData {
  employees(): Promise<Employee[]>;
  profile(employeeId: string): Promise<Profile>;
  recommendations(employeeId: string): Promise<Recommendations>;
  complete(employeeId: string, eventId: string): Promise<ProgressDiff>;
  dismiss(employeeId: string, eventId: string): Promise<void>;
  overview(): Promise<Overview>;
  audit(): Promise<AuditRun[]>;
  upload(files: UploadFiles): Promise<UploadResult>;
}
