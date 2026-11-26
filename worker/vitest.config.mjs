import { defineConfig } from "vitest/config";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";

export default defineConfig(async () => {
  const migrations = await readD1Migrations("./migrations");
  return {
    plugins: [cloudflareTest({
      wrangler: { configPath: "./wrangler.toml" },
      miniflare: {
        bindings: {
          TEST_MIGRATIONS: migrations,
          BOOTSTRAP_TOKEN: "test-bootstrap",
          SERVICE_TOKEN: "test-service",
          TURNSTILE_SECRET: "test-turnstile",
          STRAVA_CLIENT_ID: "123",
          STRAVA_CLIENT_SECRET: "test-strava",
          NTFY_TOPIC: "test-topic",
        },
      },
    })],
    test: { setupFiles: ["./test/apply-migrations.js"] },
  };
});
