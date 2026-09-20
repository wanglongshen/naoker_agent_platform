import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

describe("development scripts", () => {
  test("uses Webpack development mode and keeps production preview separate", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(process.cwd(), "package.json"), "utf8")
    ) as { scripts: Record<string, string> };

    expect(packageJson.scripts.dev).toBe("next dev --webpack");
    expect(packageJson.scripts.preview).toBe("npm run build && next start");
    expect(packageJson.scripts["dev:hot"]).toBeUndefined();
  });
});
