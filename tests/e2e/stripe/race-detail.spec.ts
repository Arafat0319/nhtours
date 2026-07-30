/**
 * Stripe status storm + webhook race after pay (detail)
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import {
  seedPaidBooking,
  tokenFromReceiptUrl,
} from '../helpers/paid-booking';
import {
  hasWebhookSecret,
  postSignedPaymentIntentSucceeded,
  retrievePaymentIntentRaw,
} from '../helpers/stripe-webhook';

test.describe('Stripe race detail @stripe @detail @p1', () => {
  test('status storm + webhook after full pay keeps amount_paid stable', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!paid, 'Need Stripe');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const stJson = await st.json();
    const token = tokenFromReceiptUrl(stJson.receipt_url);
    test.skip(!token, 'No token');

    const before = await (
      await request.get(`/api/booking/${paid!.bookingId}/summary`, {
        params: { token: token! },
      })
    ).json();
    const paidAmt = Number(before.amount_paid);

    await Promise.all(
      Array.from({ length: 12 }, () =>
        request.get('/api/payment/status', {
          params: { payment_intent_id: paid!.paymentIntentId },
        }),
      ),
    );

    if (hasWebhookSecret()) {
      const pi = await retrievePaymentIntentRaw(paid!.paymentIntentId);
      if (pi) {
        const posted = await postSignedPaymentIntentSucceeded(pi, {
          times: 3,
          baseURL: cfg.baseURL,
        });
        expect(posted?.statuses.every((s) => s === 200)).toBe(true);
      }
    }

    const after = await (
      await request.get(`/api/booking/${paid!.bookingId}/summary`, {
        params: { token: token! },
      })
    ).json();
    expect(Number(after.amount_paid)).toBe(paidAmt);
    expect(Number(after.trip_total)).toBe(Number(before.trip_total));
  });

  test('pending payment page garbage stays <500', async ({ request }) => {
    const res = await request.get('/booking/payment/pending', {
      params: {
        payment_intent_id: 'pi_not_real',
        payment_intent_client_secret: 'sec',
      },
    });
    await expectNotServerError(res, 'pending page');
    expect(res.status()).toBeLessThan(500);
  });
});
