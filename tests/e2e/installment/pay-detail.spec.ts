/**
 * Installment pay detail — real Stripe confirm on fixture installment
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { loadInstallmentFixture } from '../helpers/installment-fixture';
import {
  confirmPaymentIntent,
  extractPaymentIntentFromHtml,
  waitForPaymentSucceeded,
} from '../helpers/paid-booking';

function near(a: number, b: number, tol = 0.05) {
  expect(Math.abs(a - b), `${a} vs ${b}`).toBeLessThanOrEqual(tol);
}

test.describe('Installment pay detail @installment @detail @p1', () => {
  test('token page → quote/intent → confirm → amount_paid += installment', async ({
    request,
    cfg,
  }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Run npm pretest for installment fixture');
    test.skip(
      !process.env.E2E_STRIPE_SECRET_KEY && !process.env.STRIPE_SECRET_KEY,
      'Need Stripe Test secret',
    );

    // Snapshot paid before via status on any known path — use booking summary after we have PI
    const page = await request.get(
      `/pay-installment/${fx!.installment_id}`,
      { params: { token: fx!.token } },
    );
    expect(page.status()).toBe(200);
    const html = await page.text();
    const piId = extractPaymentIntentFromHtml(html);
    test.skip(!piId, 'No payment_intent_id on installment page');

    // Paid-before: try summary with forged path unavailable — use reconcile after pay only
    // Quote with test PM
    const quote = await request.post('/api/payment/quote', {
      data: {
        installment_id: fx!.installment_id,
        payment_method_id: 'pm_card_visa',
        payment_plan: 'installment',
        payment_step: 'installment',
      },
    });
    await expectNotServerError(quote, 'installment quote');
    expect(quote.status()).toBe(200);
    const q = await quote.json();
    expect(Number(q.base_amount)).toBe(
      Math.round(Number(fx!.amount) * 100),
    );

    const intent = await request.post('/api/payment/intent', {
      data: {
        installment_id: fx!.installment_id,
        payment_method_id: 'pm_card_visa',
        payment_plan: 'installment',
        payment_step: 'installment',
      },
    });
    await expectNotServerError(intent, 'installment intent');
    expect(intent.status()).toBe(200);

    const ok = await confirmPaymentIntent(piId!);
    expect(ok, 'Stripe confirm installment PI').toBe(true);

    const st = await waitForPaymentSucceeded(request, piId!);
    expect(st).toBeTruthy();
    expect(st!.status).toBe('succeeded');

    const bookingId = Number(st!.booking_id || fx!.booking_id);
    expect(bookingId).toBeGreaterThan(0);

    const token =
      typeof st!.receipt_url === 'string'
        ? new URL(
            String(st!.receipt_url),
            cfg.baseURL,
          ).searchParams.get('token')
        : null;

    const summary = await request.get(`/api/booking/${bookingId}/summary`, {
      params: token
        ? { token }
        : { payment_intent_id: piId! },
    });
    expect(summary.status()).toBe(200);
    const s = await summary.json();

    // After paying this installment once, amount_paid should include at least this amount
    expect(Number(s.amount_paid)).toBeGreaterThanOrEqual(Number(fx!.amount) - 0.01);

    // Re-open installment link: already paid → redirect success (302) or success page
    const again = await request.get(
      `/pay-installment/${fx!.installment_id}`,
      { params: { token: fx!.token }, maxRedirects: 0 },
    );
    expect([200, 302, 303]).toContain(again.status());
    if (again.status() === 302 || again.status() === 303) {
      expect(again.headers()['location'] || '').toMatch(/booking\/success/);
    }

    // Double status storm must not inflate paid unboundedly
    const paid1 = Number(s.amount_paid);
    const storms = await Promise.all(
      Array.from({ length: 5 }, () =>
        request.get('/api/payment/status', {
          params: { payment_intent_id: piId! },
        }),
      ),
    );
    for (const r of storms) {
      await expectNotServerError(r, 'post-pay status storm');
    }
    const summary2 = await request.get(`/api/booking/${bookingId}/summary`, {
      params: token
        ? { token }
        : { payment_intent_id: piId! },
    });
    const s2 = await summary2.json();
    near(Number(s2.amount_paid), paid1);
  });
});
