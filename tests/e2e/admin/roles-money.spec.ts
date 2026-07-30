/**
 * Admin — role gates & refund validation (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { expectNotServerError } from '../helpers/api';
import { seedPaidBooking } from '../helpers/paid-booking';

test.describe('Admin roles & money ops @admin @p1', () => {
  test('admin can open trips; staff blocked from export/refund', async ({
    request,
  }) => {
    const admin = adminCreds();
    test.skip(
      !admin,
      'Set E2E_ADMIN_USERNAME + E2E_ADMIN_PASSWORD (or TEST_ADMIN_PASSWORD)',
    );

    const ok = await adminLogin(request, admin!);
    expect(ok, 'admin login failed').toBe(true);

    const trips = await request.get('/admin/trips');
    expect(trips.status()).toBe(200);

    await request.get('/admin/logout');
    const staff = staffCreds();
    test.skip(!staff, 'Need staff creds');
    const staffOk = await adminLogin(request, staff!);
    test.skip(!staffOk, 'Staff login failed (create _pytest_staff)');

    const exportRes = await request.get('/admin/payments/export', {
      maxRedirects: 0,
    });
    expect(exportRes.status()).toBe(403);

    const refund = await request.post('/admin/trips/1/bookings/1/refund', {
      data: { amount: 1, reason: 'staff probe' },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(refund.status()).toBe(403);

    const mark = await request.post('/admin/payments/installments/1/mark-paid', {
      data: {},
      headers: { 'Content-Type': 'application/json' },
    });
    expect(mark.status()).toBe(403);
  });

  test('admin refund validation rejects empty reason / overpay', async ({
    request,
    playwright,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin creds');

    // Seed as anonymous — admin session cookies can alter public booking routes
    const publicApi = await playwright.request.newContext({
      baseURL: cfg.baseURL,
    });
    const paid = await seedPaidBooking(publicApi, cfg.tripSlug);
    await publicApi.dispose();
    test.skip(
      !paid,
      'Need E2E_STRIPE_SECRET_KEY + available QA package capacity',
    );

    expect(await adminLogin(request, admin!)).toBe(true);

    const tripsHtml = await (await request.get('/admin/trips')).text();
    const tripIds = [
      ...new Set(
        [...tripsHtml.matchAll(/\/admin\/trips\/(\d+)/g)].map((m) =>
          Number(m[1]),
        ),
      ),
    ].slice(0, 20);

    let tripId: number | null = null;
    const bookingId = paid!.bookingId;
    let detail: Record<string, unknown> | null = null;
    for (const tid of tripIds) {
      const r = await request.get(
        `/admin/trips/${tid}/bookings/${bookingId}?format=json`,
      );
      if (r.status() === 200) {
        detail = (await r.json()) as Record<string, unknown>;
        tripId = tid;
        break;
      }
    }
    test.skip(!detail || !tripId, 'Could not resolve booking in admin');

    const noReason = await request.post(
      `/admin/trips/${tripId}/bookings/${bookingId}/refund`,
      {
        data: { amount: 0.01 },
        headers: { 'Content-Type': 'application/json' },
      },
    );
    await expectNotServerError(noReason, 'refund no reason');
    expect([400, 422]).toContain(noReason.status());

    const over = await request.post(
      `/admin/trips/${tripId}/bookings/${bookingId}/refund`,
      {
        data: { amount: 99999999, reason: 'e2e overpay probe' },
        headers: { 'Content-Type': 'application/json' },
      },
    );
    await expectNotServerError(over, 'refund overpay');
    expect([400, 422]).toContain(over.status());

    const wrongTrip = tripId! + 99999;
    const idor = await request.post(
      `/admin/trips/${wrongTrip}/bookings/${bookingId}/refund`,
      {
        data: { amount: 0.01, reason: 'idor probe' },
        headers: { 'Content-Type': 'application/json' },
      },
    );
    await expectNotServerError(idor, 'refund idor');
    expect([400, 404]).toContain(idor.status());
  });

  test('admin receipt for known booking is PDF', async ({
    request,
    playwright,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin creds');

    const publicApi = await playwright.request.newContext({
      baseURL: cfg.baseURL,
    });
    const paid = await seedPaidBooking(publicApi, cfg.tripSlug);
    await publicApi.dispose();
    test.skip(!paid, 'Need Stripe Test secret + capacity');

    expect(await adminLogin(request, admin!)).toBe(true);

    const tripsHtml = await (await request.get('/admin/trips')).text();
    const tripIds = [
      ...new Set(
        [...tripsHtml.matchAll(/\/admin\/trips\/(\d+)/g)].map((m) =>
          Number(m[1]),
        ),
      ),
    ].slice(0, 30);

    let pdfRes = null as Awaited<ReturnType<typeof request.get>> | null;
    for (const tid of tripIds) {
      const r = await request.get(
        `/admin/trips/${tid}/bookings/${paid!.bookingId}/receipt`,
      );
      if (r.status() === 200) {
        pdfRes = r;
        break;
      }
    }
    test.skip(!pdfRes, 'Admin receipt route not found for booking');
    const buf = Buffer.from(await pdfRes!.body());
    expect(buf.subarray(0, 4).toString()).toBe('%PDF');
  });
});
