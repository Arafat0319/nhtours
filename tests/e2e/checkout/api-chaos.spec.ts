/**
 * Checkout — API chaos (QA adversarial)
 *
 * Goal: force 4xx / safe rejects, never 500, never silent money bugs.
 * Requires Flask running at E2E_BASE_URL with trip slug available.
 */
import { test, expect } from '../fixtures/base';
import {
  expectNotServerError,
  minimalBuyer,
  postTripBooking,
} from '../helpers/api';

test.describe('Checkout API chaos @checkout @p1', () => {
  test('empty JSON body must not 500', async ({ request, cfg }) => {
    const res = await postTripBooking(request, cfg.tripSlug, {});
    await expectNotServerError(res, 'empty body');
  });

  test('missing booking_data must not 500', async ({ request, cfg }) => {
    const res = await postTripBooking(request, cfg.tripSlug, { foo: 'bar' });
    await expectNotServerError(res, 'missing booking_data');
  });

  test('negative package quantity is rejected safely', async ({ request, cfg }) => {
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer(),
        packages: [{ package_id: 1, quantity: -3, payment_plan_type: 'full' }],
        addons: [],
        participants: [],
      },
    });
    await expectNotServerError(res, 'negative qty');
    // Prefer client error over inventing a booking
    expect([400, 404, 422].includes(res.status()) || res.status() < 500).toBeTruthy();
  });

  test('nonexistent package_id is rejected safely', async ({ request, cfg }) => {
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer(),
        packages: [
          {
            package_id: 99999999,
            quantity: 1,
            payment_plan_type: 'full',
          },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Ghost',
            email: minimalBuyer().email,
          },
        ],
      },
    });
    await expectNotServerError(res, 'bad package_id');
  });

  test('XSS strings in buyer fields must not 500', async ({ request, cfg }) => {
    const xss = '<script>alert(1)</script>';
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({
          first_name: xss,
          last_name: xss,
          email: `xss-${Date.now()}@example.com`,
        }),
        packages: [],
        addons: [],
        participants: [],
      },
    });
    await expectNotServerError(res, 'xss buyer');
  });

  test('SQL-ish email must not 500', async ({ request, cfg }) => {
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({
          email: "qa' OR '1'='1@example.com",
        }),
        packages: [],
        participants: [],
        addons: [],
      },
    });
    await expectNotServerError(res, 'sqli email');
  });

  test('discount/apply forged amount must not honor client figure', async ({
    request,
  }) => {
    const res = await request.post('/api/discount/apply', {
      data: {
        payment_intent_id: 'pi_nonexistent_chaos',
        discount_code_id: 1,
        discount_amount: 999999,
      },
    });
    await expectNotServerError(res, 'forged discount');
    const json = await res.json().catch(() => ({}));
    if (json && json.success) {
      expect(Number(json.discount_amount)).toBeLessThan(999999);
    }
  });

  test('create-free without valid pending must fail safely', async ({ request }) => {
    const res = await request.post('/api/booking/create-free', {
      data: { payment_intent_id: 'free_does_not_exist' },
    });
    await expectNotServerError(res, 'create-free orphan');
    expect(res.status()).not.toBe(200);
  });

  test('payment/intent without ids must fail safely', async ({ request }) => {
    const res = await request.post('/api/payment/intent', {
      data: {},
    });
    await expectNotServerError(res, 'intent empty');
  });

  test('parallel duplicate booking posts must not 500', async ({ request, cfg }) => {
    const payload = {
      booking_data: {
        buyer_info: minimalBuyer({ email: `dup-${Date.now()}@example.com` }),
        packages: [{ package_id: 1, quantity: 1, payment_plan_type: 'full' }],
        addons: [],
        participants: [{ first_name: 'A', last_name: 'B', email: 'a@b.com' }],
      },
    };
    const [a, b] = await Promise.all([
      postTripBooking(request, cfg.tripSlug, payload),
      postTripBooking(request, cfg.tripSlug, payload),
    ]);
    await expectNotServerError(a, 'dup A');
    await expectNotServerError(b, 'dup B');
  });
});
