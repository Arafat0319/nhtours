import { Page, expect } from '@playwright/test';

/** Fail the test if the page throws an uncaught exception (common production footgun). */
export function attachJsErrorCollector(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (err) => {
    errors.push(String(err.message || err));
  });
  return {
    assertNoJsErrors() {
      expect(errors, `Unexpected pageerror(s):\n${errors.join('\n')}`).toEqual([]);
    },
    errors,
  };
}

/** Rapid double activation — catches missing debounce / double submit. */
export async function hammerClick(locator: ReturnType<Page['locator']>, times = 5) {
  for (let i = 0; i < times; i++) {
    await locator.click({ force: true }).catch(() => undefined);
  }
}
