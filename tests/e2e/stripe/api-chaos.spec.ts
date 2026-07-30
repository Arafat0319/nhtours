/**
 * Stripe Payment — API / webhook chaos (QA adversarial)
 *
 * Not a happy-path “pay with 4242” suite. Goal: unsigned webhooks, status storms,
 * forged quote/intent, broken client secrets, no 500 on garbage.
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { seedCheckoutIntent } from '../helpers/booking-seed';

test.describe('Stripe webhook & status chaos @stripe @p1', () => {
  test('webhook without Stripe-Signature must not accept event', async ({
    request,
  }) => {
    const res = await request.post('/webhooks/stripe', {
      data: JSON.stringify({
        type: 'payment_intent.succeeded',
        data: { object: { id: 'pi_forged_qa' } },
      }),
      headers: { 'Content-Type': 'application/json' },
    });
    // 400 invalid signature/payload; 500 only if secret missing (misconfig)
    expect([400, 500]).toContain(res.status());
    if (res.status() === 200) {
      throw new Error('Unsigned webhook must never return 200');
    }
  });

  test('webhook alias path also rejects unsigned body', async ({ request }) => {
    const res = await request.post('/api/stripe/webhook', {
      data: '{"type":"charge.refunded","data":{"object":{}}}',
      headers: { 'Content-Type': 'application/json' },
    });
    expect([400, 500]).toContain(res.status());
    expect(res.status()).not.toBe(200);
  });

  test('webhook garbage payload is rejected', async ({ request }) => {
    const res = await request.post('/webhooks/stripe', {
      data: 'not-json-at-all<<<',
      headers: {
        'Content-Type': 'application/json',
        'Stripe-Signature': 't=1,v1=deadbeef',
      },
    });
    await expectNotServerError(res, 'garbage webhook');
    expect(res.status()).not.toBe(200);
  });

  test('payment/status with no ids must not 500', async ({ request }) => {
    const res = await request.get('/api/payment/status');
    await expectNotServerError(res, 'status empty');
  });

  test('payment/status with forged pi_ id stays safe', async ({ request }) => {
    const res = await request.get('/api/payment/status', {
      params: { payment_intent_id: 'pi_does_not_exist_qa_chaos' },
    });
    await expectNotServerError(res, 'status forged pi');
    const json = await res.json().catch(() => ({}));
    // Should not invent a succeeded booking
    expect(json.status === 'succeeded' && json.booking_id).toBeFalsy();
  });

  test('payment/status storm on forged id must not 500', async ({ request }) => {
    const calls = Array.from({ length: 8 }, () =>
      request.get('/api/payment/status', {
        params: { payment_intent_id: 'pi_storm_qa' },
      }),
    );
    const results = await Promise.all(calls);
    for (const res of results) {
      await expectNotServerError(res, 'status storm');
    }
  });
});

test.describe('Stripe quote/intent chaos @stripe @p1', () => {
  test('quote missing payment_method_id → 4xx not 500', async ({ request }) => {
    const res = await request.post('/api/payment/quote', {
      data: { payment_intent_id: 'pi_x' },
    });
    await expectNotServerError(res, 'quote no pm');
    expect(res.status()).toBeGreaterThanOrEqual(400);
  });

  test('quote with unknown PI → safe error', async ({ request }) => {
    const res = await request.post('/api/payment/quote', {
      data: {
        payment_intent_id: 'pi_unknown_qa',
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(res, 'quote unknown pi');
    expect(res.status()).not.toBe(200);
  });

  test('intent update with unknown PI → safe error', async ({ request }) => {
    const res = await request.post('/api/payment/intent', {
      data: {
        payment_intent_id: 'pi_unknown_qa',
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(res, 'intent unknown pi');
    expect(res.status()).not.toBe(200);
  });
});

test.describe('Stripe seeded PI chaos @stripe @p1', () => {
  test('seed PI then parallel status polls stay non-500', async ({
    request,
    cfg,
  }) => {
    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded, 'Could not seed PI (Stripe keys / trip packages)');

    expect(seeded!.paymentIntentId).toMatch(/^(pi_|free_)/);

    if (seeded!.paymentRequired) {
      expect(seeded!.paymentIntentId.startsWith('pi_')).toBeTruthy();
      expect(seeded!.clientSecret).toBeTruthy();
    }

    const polls = await Promise.all(
      Array.from({ length: 6 }, () =>
        request.get('/api/payment/status', {
          params: { payment_intent_id: seeded!.paymentIntentId },
        }),
      ),
    );
    for (const res of polls) {
      await expectNotServerError(res, 'seeded status poll');
      const json = await res.json();
      // Unpaid draft must not look like a completed booking
      if (json.status === 'succeeded' && json.booking_id) {
        throw new Error(
          'Unconfirmed PI reported succeeded+booking_id — possible false positive',
        );
      }
    }
  });

  test('seed PI then quote must use server amount path safely', async ({
    request,
    cfg,
  }) => {
    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentRequired, 'Need paid PI for quote path');

    const res = await request.post('/api/payment/quote', {
      data: {
        payment_intent_id: seeded!.paymentIntentId,
        payment_method_id: 'pm_card_visa',
        // Client trying to whisper a tiny amount — server should ignore / use pending
        amount: 1,
        final_amount_cents: 1,
      },
    });
    await expectNotServerError(res, 'quote seeded');
    if (res.status() === 200) {
      const json = await res.json();
      const finalAmt = Number(json.final_amount ?? json.amount ?? 0);
      // Fee quote for a real package should not collapse to $0.01
      expect(finalAmt === 0.01 || finalAmt === 1).toBeFalsy();
    }
  });

  test('create-free on a real pi_ id must fail (not free path)', async ({
    request,
    cfg,
  }) => {
    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentRequired, 'Need pi_ checkout');

    const res = await request.post('/api/booking/create-free', {
      data: { payment_intent_id: seeded!.paymentIntentId },
    });
    await expectNotServerError(res, 'create-free on pi_');
    // Must not convert a payable PI into a free booking
    if (res.status() === 200) {
      const json = await res.json();
      expect(json.success).not.toBeTruthy();
    }
  });
});
