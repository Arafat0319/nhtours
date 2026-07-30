/**
 * Leads / Testimonials — public + admin auth (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  expectRedirectToLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { expectNotServerError } from '../helpers/api';

test.describe('Leads & testimonials @crm @p1', () => {
  test('anonymous leads bulk-delete → login', async ({ request }) => {
    const res = await request.post('/admin/customers/leads/bulk-delete', {
      data: { ids: [1] },
      maxRedirects: 0,
    });
    await expectRedirectToLogin(res, 'leads bulk anon');
  });

  test('staff leads bulk-delete → 403', async ({ request }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'Staff login failed');
    const res = await request.post('/admin/customers/leads/bulk-delete', {
      data: { ids: [1] },
    });
    expect(res.status()).toBe(403);
  });

  test('admin leads bulk-delete empty ids → 400', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const res = await request.post('/admin/customers/leads/bulk-delete', {
      data: { ids: [] },
    });
    await expectNotServerError(res, 'leads bulk empty');
    expect(res.status()).toBe(400);
  });

  test('admin leads page loads', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const res = await request.get('/admin/customers/leads');
    expect(res.status()).toBe(200);
  });

  test('admin testimonials page loads', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const res = await request.get('/admin/customers/testimonials');
    expect(res.status()).toBe(200);
  });

  test('testimonials bulk-delete empty → safe', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const res = await request.post('/admin/customers/testimonials/bulk-delete', {
      data: { ids: [] },
    });
    await expectNotServerError(res, 'testimonials bulk empty');
    expect([400, 200]).toContain(res.status());
  });

  test('staff can open customers pages', async ({ request }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'Staff login failed');
    expect((await request.get('/admin/customers/leads')).status()).toBe(200);
    expect(
      (await request.get('/admin/customers/testimonials')).status(),
    ).toBe(200);
  });
});
