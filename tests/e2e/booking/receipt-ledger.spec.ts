/**
 * Booking receipt / summary ledger detail (money assertions)
 */
import { test, expect } from '../fixtures/base';
import {
  seedPaidBooking,
  tokenFromReceiptUrl,
} from '../helpers/paid-booking';

function near(actual: number, expected: number, tol = 0.02) {
  expect(Math.abs(actual - expected)).toBeLessThanOrEqual(tol);
}

test.describe('Receipt ledger detail @booking @detail @p1', () => {
  test('full pay: summary + HTML receipt amounts', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    test.skip(!paid, 'Need E2E_STRIPE_SECRET_KEY');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const stJson = await st.json();
    const token =
      tokenFromReceiptUrl(stJson.receipt_url) ||
      tokenFromReceiptUrl(paid!.receiptUrl);
    test.skip(!token, 'No receipt token');

    const summary = await request.get(
      `/api/booking/${paid!.bookingId}/summary`,
      { params: { token: token! } },
    );
    expect(summary.status()).toBe(200);
    const s = await summary.json();

    // QA full package = $1500 (setup_test_trip)
    near(Number(s.trip_total), 1500);
    near(Number(s.amount_paid), 1500);
    expect(Number(s.due_at_booking)).toBeGreaterThanOrEqual(1500);
    expect(Number(s.fee)).toBeGreaterThanOrEqual(0);
    expect(String(s.order_number || '')).toBeTruthy();
    expect(Array.isArray(s.order_summary_lines)).toBe(true);

    const htmlRes = await request.get(
      `/booking/${paid!.bookingId}/receipt`,
      { params: { token: token!, format: 'html' } },
    );
    expect(htmlRes.status()).toBe(200);
    const html = await htmlRes.text();
    expect(html).toMatch(/1500|1,500/);
    expect(html).toMatch(/Amount Paid|Paid/i);
    // Full pay: no history page required
    expect(html.toLowerCase()).not.toMatch(/installment schedule/);
  });

  test('deposit: paid 300 remaining 900 + history cues', async ({
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug, {
      paymentPlanType: 'deposit_installment',
    });
    test.skip(!paid, 'Need Stripe Test secret');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const stJson = await st.json();
    const token = tokenFromReceiptUrl(stJson.receipt_url);
    test.skip(!token, 'No receipt token');

    const summary = await request.get(
      `/api/booking/${paid!.bookingId}/summary`,
      {
        params: { payment_intent_id: paid!.paymentIntentId },
      },
    );
    expect(summary.status()).toBe(200);
    const s = await summary.json();

    near(Number(s.trip_total), 1200);
    near(Number(s.amount_paid), 300);

    const htmlRes = await request.get(
      `/booking/${paid!.bookingId}/receipt`,
      { params: { token: token!, format: 'html' } },
    );
    expect(htmlRes.status()).toBe(200);
    const html = await htmlRes.text();
    expect(html).toMatch(/1200|1,200/);
    expect(html).toMatch(/300/);
    // Deposit/installment should show remaining / schedule language
    expect(
      /Remaining|Installment|History|900/i.test(html),
    ).toBe(true);
  });
});
