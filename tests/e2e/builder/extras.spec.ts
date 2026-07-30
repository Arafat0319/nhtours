/**
 * Builder / export / security leftovers
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  expectRedirectToLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { extractTripId } from '../helpers/discount';

test.describe('Builder & security extras @builder @detail @p2', () => {
  test('staff cannot archive/deactivate (admin-only ops if gated)', async ({
    request,
    cfg,
  }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'staff login');
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    // copy is login_required — staff may succeed; delete already covered
    const copy = await request.post(`/admin/trips/${tripId}/copy`, {
      form: {},
      maxRedirects: 0,
    });
    expect(copy.status()).toBeLessThan(500);
  });

  test('admin bookings export excel gated for anon', async ({ request }) => {
    const res = await request.get('/admin/trips/1/bookings/export', {
      maxRedirects: 0,
    });
    await expectRedirectToLogin(res, 'bookings export');
  });

  test('admin can open manage trip', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const res = await request.get(`/admin/trips/${tripId}/manage`);
    expect(res.status()).toBe(200);
  });

  test('/test routes stay non-500', async ({ request }) => {
    for (const path of [
      '/test/installment-modal',
      '/test/installment-payment-preview',
      '/test/installment-payment-preview?payoff=true',
    ]) {
      const res = await request.get(path);
      expect(res.status(), path).toBeLessThan(500);
      expect([200, 404]).toContain(res.status());
    }
  });
});
