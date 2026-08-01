import { APIRequestContext, expect } from '@playwright/test';
import { expectNotServerError } from './api';
import { e2eConfig } from './env';

export type AdminCreds = {
  username: string;
  password: string;
};

export function adminCreds(): AdminCreds | null {
  const username =
    process.env.E2E_ADMIN_USERNAME || process.env.ADMIN_USERNAME || '';
  const password =
    process.env.E2E_ADMIN_PASSWORD || process.env.TEST_ADMIN_PASSWORD || '';
  if (!username || !password) return null;
  return { username, password };
}

export function staffCreds(): AdminCreds | null {
  const username =
    process.env.E2E_STAFF_USERNAME || '_pytest_staff';
  const password =
    process.env.E2E_STAFF_PASSWORD || 'pytest-staff-temp';
  if (!username || !password) return null;
  return { username, password };
}

function csrfFromHtml(html: string): string | null {
  const m =
    html.match(/name=["']csrf_token["'][^>]*value=["']([^"']+)["']/) ||
    html.match(/value=["']([^"']+)["'][^>]*name=["']csrf_token["']/);
  return m ? m[1] : null;
}

/** Login via form + CSRF; cookies stick on the request context. */
export async function adminLogin(
  request: APIRequestContext,
  creds: AdminCreds,
): Promise<boolean> {
  const loginPage = await request.get('/admin/login');
  await expectNotServerError(loginPage, 'admin login page');
  const csrf = csrfFromHtml(await loginPage.text());
  if (!csrf) return false;

  const res = await request.post('/admin/login', {
    form: {
      username: creds.username,
      password: creds.password,
      csrf_token: csrf,
      submit: 'Sign In',
    },
    maxRedirects: 0,
  });
  // Playwright may follow; accept 200 on /admin/trips or 302
  const status = res.status();
  if (status === 302 || status === 303) {
    const loc = res.headers()['location'] || '';
    return loc.includes('/admin') && !loc.includes('/login');
  }
  if (status === 200) {
    const trips = await request.get('/admin/trips');
    return trips.status() === 200 && !(await trips.text()).includes('name="password"');
  }
  return false;
}

/** Copy cookies from API request context onto a browser page context. */
export async function applyAdminSessionToPage(
  request: APIRequestContext,
  page: import('@playwright/test').Page,
): Promise<void> {
  const state = await request.storageState();
  if (state.cookies?.length) {
    await page.context().addCookies(state.cookies);
  }
}

/** Browser form login (reliable for Manage UI tests). */
export async function adminLoginOnPage(
  page: import('@playwright/test').Page,
  creds: AdminCreds,
): Promise<void> {
  await page.goto('/admin/login');
  await page.locator('input[name="username"]').fill(creds.username);
  await page.locator('input[name="password"]').fill(creds.password);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForURL(/\/admin(?!\/login)/, { timeout: 15_000 });
}

export async function expectRedirectToLogin(
  res: { status: () => number; headers: () => Record<string, string> },
  label: string,
) {
  const status = res.status();
  expect(status, `${label}: expected redirect, got ${status}`).toBeGreaterThanOrEqual(300);
  expect(status, `${label}: expected redirect, got ${status}`).toBeLessThan(400);
  const loc = res.headers()['location'] || '';
  expect(loc, `${label}: Location should hit login`).toMatch(/\/admin\/login/);
}

export function adminBase(): string {
  return e2eConfig().baseURL;
}
