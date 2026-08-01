/**
 * Admin ops detail — reconcile, mark-paid, cancel-$0, financials, clients gates
 */
import { test, expect } from '../fixtures/base';
import {
  adminCreds,
  adminLogin,
  expectRedirectToLogin,
  staffCreds,
} from '../helpers/admin-auth';
import { expectNotServerError, minimalBuyer, postTripBooking } from '../helpers/api';
import { extractPackageIds } from '../helpers/booking-seed';
import { extractTripId, resolveQaDiscount } from '../helpers/discount';
import { loadInstallmentFixture } from '../helpers/installment-fixture';
import { seedPaidBooking } from '../helpers/paid-booking';

async function resolveTripBooking(
  request: import('@playwright/test').APIRequestContext,
  bookingId: number,
): Promise<{ tripId: number } | null> {
  const tripsHtml = await (await request.get('/admin/trips')).text();
  const tripIds = [
    ...new Set(
      [...tripsHtml.matchAll(/\/admin\/trips\/(\d+)/g)].map((m) => Number(m[1])),
    ),
  ].slice(0, 40);
  for (const tid of tripIds) {
    const r = await request.get(
      `/admin/trips/${tid}/bookings/${bookingId}?format=json`,
    );
    if (r.status() === 200) return { tripId: tid };
  }
  return null;
}

test.describe('Admin ops detail @admin @detail @p1', () => {
  test('anonymous clients/cities/reports redirect', async ({ request }) => {
    for (const path of [
      '/admin/clients',
      '/admin/cities',
      '/admin/reports',
      '/admin/payments',
      '/admin/customers',
    ]) {
      const res = await request.get(path, { maxRedirects: 0 });
      await expectRedirectToLogin(res, path);
    }
  });

  test('admin reconcile-ledger JSON for paid booking', async ({
    request,
    playwright,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');

    const pub = await playwright.request.newContext({ baseURL: cfg.baseURL });
    const paid = await seedPaidBooking(pub, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    await pub.dispose();
    test.skip(!paid, 'Need Stripe');

    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'QA trip missing');

    const res = await request.get(
      `/admin/trips/${tripId}/bookings/${paid!.bookingId}/reconcile-ledger`,
    );
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.reconcile).toBeTruthy();
  });

  test('admin financials for QA trip', async ({ request, cfg }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const res = await request.get(`/admin/trips/${tripId}/financials`);
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.financials).toBeTruthy();
    expect(json.financials).toHaveProperty('total_refunded');
    expect(typeof json.financials.total_refunded).toBe('number');
  });

  test('admin mark-paid then reject double mark-paid', async ({
    request,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need unpaid installment fixture');

    expect(await adminLogin(request, admin!)).toBe(true);

    const first = await request.post(
      `/admin/payments/installments/${fx!.installment_id}/mark-paid`,
      { data: {} },
    );
    await expectNotServerError(first, 'mark-paid');
    // 200 success or 400 if already paid by prior detail test
    expect([200, 400]).toContain(first.status());

    const second = await request.post(
      `/admin/payments/installments/${fx!.installment_id}/mark-paid`,
      { data: {} },
    );
    expect(second.status()).toBe(400);
  });

  test('$0 cancel via refund validators + cancel_booking', async ({
    request,
    playwright,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');

    const pub = await playwright.request.newContext({ baseURL: cfg.baseURL });
    const tripIdPub = await extractTripId(pub, cfg.tripSlug);
    const disc = tripIdPub ? await resolveQaDiscount(pub, tripIdPub) : null;
    const pkgs = await extractPackageIds(pub, cfg.tripSlug);
    test.skip(!disc || !pkgs.length, 'Need QAZERO + packages');

    const email = `qa-cancel0-${Date.now()}@example.com`;
    const pkg = pkgs.length > 1 ? pkgs[1] : pkgs[0];
    const created = await postTripBooking(pub, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          { package_id: pkg, quantity: 1, payment_plan_type: 'full' },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Cancel',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: disc!.code,
        payment_method: 'full',
      },
    });
    const cjson = await created.json();
    test.skip(!cjson.payment_intent_id?.startsWith?.('free_'), 'Not free path');
    const free = await pub.post('/api/booking/create-free', {
      data: { payment_intent_id: cjson.payment_intent_id },
    });
    const fjson = await free.json();
    await pub.dispose();
    test.skip(!fjson.booking_id, 'create-free failed');

    expect(await adminLogin(request, admin!)).toBe(true);
    const loc = await resolveTripBooking(request, Number(fjson.booking_id));
    test.skip(!loc, 'locate booking');

    const cancel = await request.post(
      `/admin/trips/${loc!.tripId}/bookings/${fjson.booking_id}/refund`,
      {
        data: {
          amount: 0,
          reason: 'e2e $0 cancel',
          cancel_booking: true,
        },
      },
    );
    await expectNotServerError(cancel, '$0 cancel');
    expect(cancel.status()).toBe(200);
    const body = await cancel.json();
    expect(body.success).toBe(true);
  });

  test('staff can open payments api; cannot export', async ({ request }) => {
    const staff = staffCreds();
    test.skip(!staff, 'Need staff');
    test.skip(!(await adminLogin(request, staff!)), 'staff login');
    expect((await request.get('/admin/payments/api')).status()).toBe(200);
    expect((await request.get('/admin/payments/export')).status()).toBe(403);
  });

  test('admin payments list + reports pages', async ({ request }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);
    expect((await request.get('/admin/payments')).status()).toBe(200);
    expect((await request.get('/admin/reports')).status()).toBe(200);
    expect((await request.get('/admin/clients')).status()).toBe(200);
    expect((await request.get('/admin/cities')).status()).toBe(200);
  });
});
