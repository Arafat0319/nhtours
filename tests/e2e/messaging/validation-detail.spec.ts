/**
 * Messaging schedule / get / delete validation
 */
import { test, expect } from '../fixtures/base';
import { adminCreds, adminLogin } from '../helpers/admin-auth';
import { expectNotServerError } from '../helpers/api';
import { extractTripId } from '../helpers/discount';

test.describe('Messaging validation detail @messaging @detail @p1', () => {
  test('schedule without time → 400', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const res = await request.post(`/admin/trips/${tripId}/messages/create`, {
      form: {
        subject: 'E2E schedule missing time',
        body_html: '<p>probe</p>',
        recipient_config: JSON.stringify({ type: 'all' }),
        send_option: 'schedule',
        scheduled_at: '',
      },
    });
    await expectNotServerError(res, 'schedule empty');
    expect(res.status()).toBe(400);
  });

  test('schedule in the past → 400', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const res = await request.post(`/admin/trips/${tripId}/messages/create`, {
      form: {
        subject: 'E2E schedule past',
        body_html: '<p>probe</p>',
        recipient_config: JSON.stringify({ type: 'all' }),
        send_option: 'schedule',
        scheduled_at: '2020-01-01T10:00',
      },
    });
    await expectNotServerError(res, 'schedule past');
    expect(res.status()).toBe(400);
  });

  test('package recipient without package_id → 400', async ({
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
        subject: 'E2E package missing',
        body_html: '<p>probe</p>',
        recipient_config: JSON.stringify({ type: 'package' }),
        send_option: 'now',
        status: 'draft',
      },
    });
    await expectNotServerError(res, 'package missing');
    expect(res.status()).toBe(400);
  });

  test('get missing message → 404', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const res = await request.get(`/admin/trips/${tripId}/messages/99999999`);
    expect(res.status()).toBe(404);
  });
});
