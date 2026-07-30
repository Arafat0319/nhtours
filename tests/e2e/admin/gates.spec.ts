/**
 * Admin — anonymous auth gates (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { expectRedirectToLogin } from '../helpers/admin-auth';
import { expectNotServerError } from '../helpers/api';

test.describe('Admin anonymous gates @admin @p1', () => {
  test('money / PII endpoints redirect to login', async ({ request }) => {
    const paths: { method: 'GET' | 'POST'; path: string; data?: object }[] = [
      { method: 'GET', path: '/admin/trips' },
      { method: 'GET', path: '/admin/payments/api' },
      { method: 'GET', path: '/admin/payments/export' },
      { method: 'GET', path: '/admin/trips/1/bookings/1?format=json' },
      { method: 'GET', path: '/admin/trips/1/bookings/1/receipt' },
      { method: 'GET', path: '/admin/trips/1/bookings/1/reconcile-ledger' },
      {
        method: 'POST',
        path: '/admin/trips/1/bookings/1/refund',
        data: { amount: 1, reason: 'e2e' },
      },
      { method: 'POST', path: '/admin/trips/1/bookings/1/delete' },
      { method: 'POST', path: '/admin/payments/installments/1/mark-paid' },
      { method: 'POST', path: '/admin/payments/installments/1/send-reminder' },
    ];

    for (const p of paths) {
      const res =
        p.method === 'GET'
          ? await request.get(p.path, { maxRedirects: 0 })
          : await request.post(p.path, {
              data: p.data || {},
              maxRedirects: 0,
              headers: { 'Content-Type': 'application/json' },
            });
      await expectRedirectToLogin(res, `${p.method} ${p.path}`);
    }
  });

  test('export csv without token is 403', async ({ request }) => {
    const res = await request.get('/admin/trips/bookings/export/csv');
    expect(res.status()).toBe(403);
  });

  test('export csv with garbage token is 403', async ({ request }) => {
    const res = await request.get('/admin/trips/bookings/export/csv', {
      params: { token: 'not.a.token' },
    });
    expect(res.status()).toBe(403);
  });

  test('login without csrf must not enter admin', async ({ request }) => {
    const res = await request.post('/admin/login', {
      form: {
        username: 'anyone',
        password: 'wrong',
        submit: 'Sign In',
      },
      maxRedirects: 0,
    });
    await expectNotServerError(res, 'login no csrf');
    if (res.status() === 302 || res.status() === 303) {
      const loc = res.headers()['location'] || '';
      expect(loc).not.toMatch(/\/admin\/trips$/);
    } else {
      expect(res.status()).toBe(200);
      const html = await res.text();
      expect(html).toMatch(/csrf|password|login/i);
    }
  });

  test('wrong password stays on login (no 500)', async ({ request }) => {
    const page = await request.get('/admin/login');
    const html = await page.text();
    const m =
      html.match(/name=["']csrf_token["'][^>]*value=["']([^"']+)["']/) ||
      html.match(/value=["']([^"']+)["'][^>]*name=["']csrf_token["']/);
    test.skip(!m, 'No csrf on login page');
    const res = await request.post('/admin/login', {
      form: {
        username: 'no_such_user_e2e',
        password: 'definitely-wrong',
        csrf_token: m![1],
        submit: 'Sign In',
      },
      maxRedirects: 0,
    });
    await expectNotServerError(res, 'bad login');
    if (res.status() === 302 || res.status() === 303) {
      expect(res.headers()['location'] || '').toMatch(/login/);
    } else {
      expect(res.status()).toBe(200);
    }
  });
});
