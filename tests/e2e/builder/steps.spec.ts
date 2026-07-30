/**
 * Trip Builder steps + delete auth (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  expectRedirectToLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { extractTripId } from '../helpers/discount';

const STEPS = [
  'basics',
  'description',
  'packages',
  'addons',
  'buyer_info',
  'participants',
  'coupons',
  'settings',
] as const;

test.describe('Trip builder @builder @p2', () => {
  test('anonymous builder redirects to login', async ({ request }) => {
    const res = await request.get('/admin/trips/1/builder/basics', {
      maxRedirects: 0,
    });
    await expectRedirectToLogin(res, 'builder anon');
  });

  test('invalid builder step → 404', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const res = await request.get(`/admin/trips/${tripId}/builder/not-a-step`);
    expect(res.status()).toBe(404);
  });

  test('admin can open each builder step', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    for (const step of STEPS) {
      const res = await request.get(`/admin/trips/${tripId}/builder/${step}`);
      expect(res.status(), step).toBe(200);
    }
  });

  test('staff can open builder; cannot delete trip', async ({
    request,
    cfg,
  }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'Staff login failed');
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const page = await request.get(`/admin/trips/${tripId}/builder/basics`);
    expect(page.status()).toBe(200);

    const del = await request.post(`/admin/trips/${tripId}/delete`, {
      form: {},
      maxRedirects: 0,
    });
    expect(del.status()).toBe(403);
  });
});
