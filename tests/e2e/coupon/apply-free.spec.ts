/**
 * Coupon — apply / $0 free path (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { minimalBuyer, postTripBooking, expectNotServerError } from '../helpers/api';
import { extractPackageIds, seedCheckoutIntent } from '../helpers/booking-seed';
import {
  applyDiscount,
  extractTripId,
  resolveQaDiscount,
} from '../helpers/discount';

test.describe('Discount apply & free path @coupon @p1', () => {
  test('apply forged discount_amount is ignored', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const disc = await resolveQaDiscount(request, tripId);
    test.skip(!disc, 'Need QAZERO');

    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentIntentId, 'Could not seed PendingBooking+PI');

    const { res, json } = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: disc!.id,
      discount_amount: 999999,
    });
    expect(res.status()).toBe(200);
    expect(json.success).toBe(true);
    expect(Number(json.discount_amount)).toBeLessThan(999999);
    expect(Number(json.discount_amount)).toBeLessThanOrEqual(
      Number(json.gross_amount) + 0.01,
    );
  });

  test('apply → remove → re-apply restores then discounts', async ({
    request,
    cfg,
  }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const disc = await resolveQaDiscount(request, tripId);
    test.skip(!disc, 'Need QAZERO');

    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentIntentId, 'Need PI seed');

    const applied = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: disc!.id,
    });
    expect(applied.json.success).toBe(true);
    const discountedBase = Number(applied.json.base_amount_cents);

    const removed = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: null,
    });
    expect(removed.json.success).toBe(true);
    expect(Number(removed.json.base_amount_cents)).toBeGreaterThan(discountedBase);

    const again = await applyDiscount(request, {
      payment_intent_id: seeded!.paymentIntentId,
      discount_code_id: disc!.id,
    });
    expect(again.json.success).toBe(true);
    expect(Number(again.json.base_amount_cents)).toBe(discountedBase);
  });

  test('parallel apply same PI must not 500 / stay consistent', async ({
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

    const results = await Promise.all(
      Array.from({ length: 6 }, () =>
        applyDiscount(request, {
          payment_intent_id: seeded!.paymentIntentId,
          discount_code_id: disc!.id,
          discount_amount: 1,
        }),
      ),
    );
    for (const r of results) {
      expect(r.res.status()).toBeLessThan(500);
    }
    const ok = results.filter((r) => r.json.success);
    expect(ok.length).toBeGreaterThan(0);
    const bases = new Set(ok.map((r) => Number(r.json.base_amount_cents)));
    expect(bases.size).toBe(1);
  });

  test('submit forged discount_amount without code does not discount', async ({
    request,
    cfg,
  }) => {
    const packageIds = await extractPackageIds(request, cfg.tripSlug);
    test.skip(!packageIds.length, 'No packages');
    const packageId = packageIds.length > 1 ? packageIds[1] : packageIds[0];
    const email = `qa-forge-disc-${Date.now()}@example.com`;

    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          {
            package_id: packageId,
            quantity: 1,
            payment_plan_type: 'full',
          },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Forge',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: null,
        discount_amount: 999999,
        discount_code_id: 1,
        payment_method: 'full',
      },
    });
    await expectNotServerError(res, 'forge amount submit');
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.payment_required).toBe(true);
    expect(Number(json.base_amount_cents)).toBeGreaterThan(50);
  });

  test('QAZERO submit → free_* → create-free idempotent', async ({
    request,
    cfg,
  }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const disc = await resolveQaDiscount(request, tripId);
    test.skip(!disc, 'Need QAZERO');

    const packageIds = await extractPackageIds(request, cfg.tripSlug);
    const packageId = packageIds.length > 1 ? packageIds[1] : packageIds[0];
    const email = `qa-zero-${Date.now()}@example.com`;

    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          {
            package_id: packageId,
            quantity: 1,
            payment_plan_type: 'full',
          },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Zero',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: disc!.code,
        payment_method: 'full',
      },
    });
    await expectNotServerError(res, 'QAZERO submit');
    expect(res.status()).toBe(200);
    const created = await res.json();
    expect(created.success).toBe(true);
    expect(created.payment_required).toBe(false);
    expect(String(created.payment_intent_id)).toMatch(/^free_/);

    const free1 = await request.post('/api/booking/create-free', {
      data: { payment_intent_id: created.payment_intent_id },
    });
    expect(free1.status()).toBe(200);
    const b1 = await free1.json();
    expect(b1.success).toBe(true);
    const bookingId = Number(b1.booking_id);
    expect(bookingId).toBeGreaterThan(0);

    const storms = await Promise.all(
      Array.from({ length: 5 }, () =>
        request.post('/api/booking/create-free', {
          data: { payment_intent_id: created.payment_intent_id },
        }),
      ),
    );
    const ids = new Set<number>();
    for (const s of storms) {
      await expectNotServerError(s, 'create-free storm');
      const j = await s.json();
      expect(j.success).toBe(true);
      ids.add(Number(j.booking_id));
    }
    expect(ids.size).toBe(1);
    expect([...ids][0]).toBe(bookingId);
  });

  test('create-free on paid pi_ must fail', async ({ request, cfg }) => {
    const seeded = await seedCheckoutIntent(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!seeded?.paymentRequired, 'Need paid PI (check package capacity)');
    const res = await request.post('/api/booking/create-free', {
      data: { payment_intent_id: seeded!.paymentIntentId },
    });
    await expectNotServerError(res, 'create-free on pi_');
    expect(res.status()).not.toBe(200);
  });
});
