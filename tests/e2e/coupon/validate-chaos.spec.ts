/**
 * Coupon — validate API chaos (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { extractTripId, validateDiscount } from '../helpers/discount';

test.describe('Discount validate chaos @coupon @p1', () => {
  test('empty code returns valid:false (not 5xx)', async ({ request }) => {
    const { res, json } = await validateDiscount(request, {
      code: '',
      order_amount: 100,
    });
    expect(res.status()).toBe(200);
    expect(json.valid).toBe(false);
  });

  test('missing body is safe', async ({ request }) => {
    const { res, json } = await validateDiscount(request, {});
    expect(res.status()).toBe(200);
    expect(json.valid).toBe(false);
  });

  test('XSS / injection strings never 500', async ({ request }) => {
    for (const code of [
      '<script>alert(1)</script>',
      "'; DROP TABLE discount_codes;--",
      '${7*7}',
      'A'.repeat(10_000),
    ]) {
      const { res, json } = await validateDiscount(request, {
        code,
        order_amount: 100,
      });
      expect(res.status()).toBe(200);
      expect(json.valid).toBe(false);
    }
  });

  test('negative / garbage order_amount must not 500', async ({ request }) => {
    for (const order_amount of [-100, 'abc', null]) {
      const { res } = await validateDiscount(request, {
        code: 'NOPE',
        order_amount,
      });
      expect(res.status()).toBeLessThan(500);
    }
  });

  test('QAZERO case-insensitive match', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const { json } = await validateDiscount(request, {
      code: 'qAzErO',
      trip_id: tripId,
      order_amount: 1000,
    });
    test.skip(!json.valid, 'Seed QAZERO on QA trip (see e2e_full_suite / coupon README)');
    expect(json.valid).toBe(true);
    const d = json.discount as Record<string, unknown>;
    expect(Number(d.discount_amount)).toBeGreaterThan(0);
  });

  test('trip-specific code rejected for wrong trip_id', async ({
    request,
    cfg,
  }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    const { json: ok } = await validateDiscount(request, {
      code: 'QAZERO',
      trip_id: tripId,
      order_amount: 1000,
    });
    test.skip(!ok.valid, 'Need QAZERO');

    const { json } = await validateDiscount(request, {
      code: 'QAZERO',
      trip_id: 99999999,
      order_amount: 1000,
    });
    expect(json.valid).toBe(false);
    expect(String(json.message || '')).toMatch(/not valid for this trip/i);
  });
});
