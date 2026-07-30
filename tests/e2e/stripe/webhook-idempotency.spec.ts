/**
 * Stripe webhook detail — signed delivery + duplicate idempotency
 */
import { test, expect } from '../fixtures/base';
import {
  seedPaidBooking,
  tokenFromReceiptUrl,
} from '../helpers/paid-booking';
import {
  hasWebhookSecret,
  postSignedPaymentIntentSucceeded,
  retrievePaymentIntentRaw,
} from '../helpers/stripe-webhook';

test.describe('Webhook idempotency detail @stripe @detail @p1', () => {
  test('unsigned still rejected', async ({ request }) => {
    const res = await request.post('/webhooks/stripe', {
      data: JSON.stringify({
        type: 'payment_intent.succeeded',
        data: { object: { id: 'pi_x' } },
      }),
      headers: { 'Content-Type': 'application/json' },
    });
    expect(res.status()).not.toBe(200);
  });

  test('signed succeeded double-delivery does not double amount_paid', async ({
    request,
    cfg,
  }) => {
    test.skip(
      !hasWebhookSecret(),
      'Set STRIPE_WEBHOOK_SECRET / E2E_STRIPE_WEBHOOK_SECRET',
    );

    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!paid, 'Need Stripe Test secret for paid booking');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const stJson = await st.json();
    const token = tokenFromReceiptUrl(stJson.receipt_url);
    test.skip(!token, 'No receipt token');

    const before = await request.get(
      `/api/booking/${paid!.bookingId}/summary`,
      { params: { token: token! } },
    );
    expect(before.status()).toBe(200);
    const b = await before.json();
    const paidBefore = Number(b.amount_paid);

    const pi = await retrievePaymentIntentRaw(paid!.paymentIntentId);
    test.skip(!pi, 'Could not retrieve PI from Stripe');

    const posted = await postSignedPaymentIntentSucceeded(pi!, {
      times: 2,
      baseURL: cfg.baseURL,
    });
    expect(posted).toBeTruthy();
    for (let i = 0; i < posted!.statuses.length; i++) {
      expect(
        posted!.statuses[i],
        `webhook body=${posted!.bodies[i].slice(0, 300)}`,
      ).toBe(200);
    }

    const after = await request.get(
      `/api/booking/${paid!.bookingId}/summary`,
      { params: { token: token! } },
    );
    const a = await after.json();
    expect(Number(a.amount_paid)).toBe(paidBefore);
    expect(Number(a.trip_total)).toBe(Number(b.trip_total));
  });
});
