/**
 * Booking — idempotency after pay (QA adversarial)
 *
 * Requires E2E_STRIPE_SECRET_KEY (Test mode) so we can confirm PI.
 * Focus: one PI → one booking_id under status storms / repeated polls.
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import {
  seedPaidBooking,
  tokenFromReceiptUrl,
} from '../helpers/paid-booking';

test.describe('Booking idempotency @booking @p1', () => {
  test('status storm after confirm yields a single booking_id', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug);
    test.skip(
      !paid,
      'Set E2E_STRIPE_SECRET_KEY (Stripe Test) to run paid booking idempotency',
    );

    const ids = new Set<number>();
    const polls = await Promise.all(
      Array.from({ length: 10 }, () =>
        request.get('/api/payment/status', {
          params: { payment_intent_id: paid!.paymentIntentId },
        }),
      ),
    );

    for (const res of polls) {
      await expectNotServerError(res, 'post-pay status');
      const json = await res.json();
      expect(json.status).toBe('succeeded');
      expect(Number(json.booking_id)).toBeGreaterThan(0);
      ids.add(Number(json.booking_id));
    }
    expect(ids.size, 'duplicate bookings for one PI').toBe(1);
    expect([...ids][0]).toBe(paid!.bookingId);
  });

  test('receipt token works; wrong booking id with that token fails', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug);
    test.skip(!paid, 'Need Stripe Test secret for paid booking');

    // Refresh status for receipt_url if seed payload lacked it
    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const json = await st.json();
    const token =
      tokenFromReceiptUrl(json.receipt_url) ||
      tokenFromReceiptUrl(paid!.receiptUrl);
    test.skip(!token, 'No receipt token in status payload');

    const ok = await request.get(`/booking/${paid!.bookingId}/receipt`, {
      params: { token: token! },
    });
    expect(ok.status()).toBe(200);
    const buf = Buffer.from(await ok.body());
    expect(buf.subarray(0, 4).toString()).toBe('%PDF');

    const otherId = paid!.bookingId + 99999;
    const cross = await request.get(`/booking/${otherId}/receipt`, {
      params: { token: token! },
    });
    expect(cross.status()).toBe(404);
  });

  test('summary requires matching token or pi', async ({ request, cfg }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug);
    test.skip(!paid, 'Need Stripe Test secret');

    const denied = await request.get(`/api/booking/${paid!.bookingId}/summary`);
    expect(denied.status()).toBe(403);

    const withPi = await request.get(`/api/booking/${paid!.bookingId}/summary`, {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    expect(withPi.status()).toBe(200);
    const body = await withPi.json();
    expect(body.order_number || body.trip_total != null).toBeTruthy();
  });
});
