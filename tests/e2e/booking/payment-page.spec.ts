/**
 * Booking payment page + summary cross-checks (detail)
 */
import { test, expect } from '../fixtures/base';
import {
  seedPaidBooking,
  tokenFromReceiptUrl,
} from '../helpers/paid-booking';

test.describe('Booking payment page detail @booking @detail @p1', () => {
  test('payment page without token → 403', async ({ request }) => {
    const res = await request.get('/booking/payment/1');
    expect([403, 404]).toContain(res.status());
  });

  test('payment page garbage token → 403', async ({ request }) => {
    const res = await request.get('/booking/payment/1', {
      params: { token: 'garbage' },
    });
    expect([403, 404]).toContain(res.status());
  });

  test('fully paid booking payment page redirects success', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!paid, 'Need Stripe secret');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const token = tokenFromReceiptUrl((await st.json()).receipt_url);
    test.skip(!token, 'No token');

    const res = await request.get(`/booking/payment/${paid!.bookingId}`, {
      params: { token: token! },
      maxRedirects: 0,
    });
    expect([200, 302, 303]).toContain(res.status());
    if (res.status() === 302 || res.status() === 303) {
      expect(res.headers()['location'] || '').toMatch(/booking\/success/);
    }

    // summary via token vs via pi must agree on trip_total
    const s1 = await (
      await request.get(`/api/booking/${paid!.bookingId}/summary`, {
        params: { token: token! },
      })
    ).json();
    const s2 = await (
      await request.get(`/api/booking/${paid!.bookingId}/summary`, {
        params: { payment_intent_id: paid!.paymentIntentId },
      })
    ).json();
    expect(Number(s1.trip_total)).toBe(Number(s2.trip_total));
    expect(Number(s1.amount_paid)).toBe(Number(s2.amount_paid));
  });

  test('deposit booking payment page opens with token', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'deposit_installment',
    });
    test.skip(!paid, 'Need Stripe');
    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const token = tokenFromReceiptUrl((await st.json()).receipt_url);
    test.skip(!token, 'No token');

    const res = await request.get(`/booking/payment/${paid!.bookingId}`, {
      params: { token: token! },
      maxRedirects: 0,
    });
    // deposit_paid → may show payment UI or redirect depending on remaining
    expect(res.status()).toBeLessThan(500);
    expect([200, 302, 303]).toContain(res.status());
  });
});
