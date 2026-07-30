/**
 * CRM lead flow — public contact → admin leads list
 */
import { test, expect } from '../fixtures/base';
import { adminCreds, adminLogin } from '../helpers/admin-auth';

test.describe('CRM lead flow detail @crm @detail @p1', () => {
  test('contact create then admin leads page contains email', async ({
    request,
  }) => {
    const email = `qa-lead-flow-${Date.now()}@example.com`;
    const post = await request.post('/contact', {
      data: {
        form: 'contact',
        firstName: 'QA',
        lastName: 'LeadFlow',
        email,
        message: 'E2E lead flow message — please ignore this automated contact.',
        phone: '1234567890',
      },
    });
    expect(post.status()).toBe(200);

    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);

    const page = await request.get('/admin/customers/leads');
    expect(page.status()).toBe(200);
    const html = await page.text();
    expect(html).toContain(email);
  });

  test('admin update-status invalid id stays safe', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const res = await request.post(
      '/admin/customers/leads/99999999/update-status',
      { data: { status: 'archived' } },
    );
    expect(res.status()).toBeLessThan(500);
    expect([400, 404]).toContain(res.status());
  });

  test('testimonial approve/reject gates for missing id', async ({
    request,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    for (const action of ['approve', 'reject', 'delete']) {
      const res = await request.post(
        `/admin/customers/testimonials/99999999/${action}`,
        { data: {} },
      );
      expect(res.status(), action).toBeLessThan(500);
      expect([400, 404]).toContain(res.status());
    }
  });
});
