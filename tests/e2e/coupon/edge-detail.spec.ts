/**
 * Coupon edge details — remove, wrong id, apply then quote consistency
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError, minimalBuyer, postTripBooking } from '../helpers/api';
import { extractPackageIds } from '../helpers/booking-seed';
import {
  applyDiscount,
  extractTripId,
  resolveQaDiscount,
  validateDiscount,
} from '../helpers/discount';
import { seedCheckoutIntent } from '../helpers/booking-seed';

test.describe('Coupon edge detail @coupon @detail @p1', () => {
  test('validate with huge order_amount stays finite', async ({ request }) => {
    const { json } = await validateDiscount(request, {
      code: 'QAZERO',
      order_amount: 1e12,
    });
    expect(json.valid === true || json.valid === false).toBe(true);
    if (json.valid && json.discount) {
      const d = json.discount as Record<string, unknown>;
      expect(Number.isFinite(Number(d.discount_amount))).toBe(true);
    }
  });

  test('apply unknown discount_code_id → 400', async ({ request, cfg }) => {
    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentIntentId, 'Need PI');
    const { res } = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: 99999999,
    });
    expect(res.status()).toBe(400);
  });

  test('apply QAZERO then payment/quote uses discounted base', async ({
    request,
    cfg,
  }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const disc = await resolveQaDiscount(request, tripId);
    test.skip(!disc, 'Need QAZERO');

    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentIntentId, 'Need PI');

    const applied = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: disc!.id,
    });
    expect(applied.json.success).toBe(true);
    const base = Number(applied.json.base_amount_cents);

    if (base === 0) {
      expect(applied.json.payment_required).toBe(false);
      return;
    }

    const quote = await request.post('/api/payment/quote', {
      data: {
        payment_intent_id: seeded!.paymentIntentId,
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(quote, 'quote after discount');
    if (quote.status() === 200) {
      const q = await quote.json();
      expect(Number(q.base_amount)).toBe(base);
    }
  });

  test('invalid code on submit does not crash', async ({ request, cfg }) => {
    const pkgs = await extractPackageIds(request, cfg.tripSlug);
    test.skip(!pkgs.length, 'No pkgs');
    const email = `qa-badcode-${Date.now()}@example.com`;
    const pkg = pkgs.length > 1 ? pkgs[1] : pkgs[0];
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          { package_id: pkg, quantity: 1, payment_plan_type: 'full' },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'BadCode',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: 'THIS_CODE_DOES_NOT_EXIST_E2E',
        payment_method: 'full',
      },
    });
    await expectNotServerError(res, 'bad code submit');
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.payment_required).toBe(true);
    expect(Number(json.base_amount_cents)).toBeGreaterThan(50);
  });
});
