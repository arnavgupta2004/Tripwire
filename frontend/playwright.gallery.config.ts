import { defineConfig, devices } from "@playwright/test";

// Devpost gallery images (docs/gallery). Not part of CI: `npx playwright test -c playwright.gallery.config.ts`.
// The app runs against the in-browser mock API (no backend, no keys, no model calls); the
// mocked decisions use texts recorded from real runs (see docs/gallery/README.md).
export default defineConfig({
  testDir: "gallery",
  timeout: 60_000,
  workers: 1,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://localhost:5173",
    viewport: { width: 1500, height: 1000 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  },
  webServer: { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: true, timeout: 60_000 },
});
