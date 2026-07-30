/**
 * Admin messaging HTTP gates (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  expectRedirectToLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { expectNotServerError } from '../helpers/api';
import { extractTripId } from '../helpers/discount';

test.describe('Admin messaging @messaging @p1', () => {
  test('anonymous create message → login redirect', async ({ request }) => {
    const res = await request.post('/admin/trips/1/messages/create', {
      form: {
        subject: 'x',
        body_html: '<p>y</p>',
        recipient_config: JSON.stringify({ type: 'all' }),
        send_option: 'now',
        status: 'draft',
      },
      maxRedirects: 0,
    });
    await expectRedirectToLogin(res, 'messages create anon');
  });

  test('staff cannot create message (403)', async ({ request }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'Staff login failed');

    const res = await request.post('/admin/trips/1/messages/create', {
      form: {
        subject: 'staff probe',
        body_html: '<p>no</p>',
        recipient_config: JSON.stringify({ type: 'all' }),
        send_option: 'now',
        status: 'draft',
      },
    });
    expect(res.status()).toBe(403);
  });

  test('admin draft with invalid recipient type → 400', async ({
    request,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);

    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const res = await request.post(`/admin/trips/${tripId}/messages/create`, {
      form: {
        subject: 'e2e invalid type',
        body_html: '<p>probe</p>',
        recipient_config: JSON.stringify({ type: 'not_a_real_type' }),
        send_option: 'now',
        status: 'draft',
      },
    });
    await expectNotServerError(res, 'msg invalid type');
    expect(res.status()).toBe(400);
  });

  test('admin can save draft with type=all', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const res = await request.post(`/admin/trips/${tripId}/messages/create`, {
      form: {
        subject: `E2E draft ${Date.now()}`,
        body_html: '<p>E2E draft — ignore</p>',
        recipient_config: JSON.stringify({ type: 'all' }),
        send_option: 'now',
        status: 'draft',
      },
    });
    await expectNotServerError(res, 'msg draft');
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
  });
});
