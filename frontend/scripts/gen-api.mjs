import { spawnSync } from "node:child_process";

const result = spawnSync(
  "openapi-typescript",
  [
    process.env.OPENAPI_URL ?? "http://127.0.0.1:8000/openapi.json",
    "-o",
    "src/api/schema.d.ts",
  ],
  { stdio: "inherit", shell: false },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
