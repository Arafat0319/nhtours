/**
 * Installment payoff detail
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { loadInstallmentFixture } from '../helpers/installment-fixture';
import {
  confirmPaymentIntent,
  extractPaymentIntentFromHtml,
  waitForPaymentSucceeded,
} from '../helpers/paid-booking';

test.describe('Installment payoff detail @installment @detail @p1', () => {
  test('payoff page with token loads or redirects safely', async ({
    request,
    cfg,
  }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need fixture (npm pretest)');

    const res = await request.get(
      `/pay-installment/${fx!.installment_id}/payoff`,
      { params: { token: fx!.token } },
    );
    expect(res.status()).toBeLessThan(500);
    expect([200, 302, 303]).toContain(res.status());
  });

  test('payoff garbage token denied', async ({ request }) => {
    const res = await request.get('/pay-installment/1/payoff', {
      params: { token: 'nope' },
    });
    expect([403, 404]).toContain(res.status());
  });

  test('payoff confirm path when page exposes PI', async ({ request, cfg }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need fixture');
    test.skip(
      !process.env.E2E_STRIPE_SECRET_KEY && !process.env.STRIPE_SECRET_KEY,
      'Need Stripe',
    );

    const page = await request.get(
      `/pay-installment/${fx!.installment_id}/payoff`,
      { params: { token: fx!.token } },
    );
    if (page.status() !== 200) {
      test.skip(true, 'Payoff redirected (already settled or no balance)');
    }
    const html = await page.text();
    const piId = extractPaymentIntentFromHtml(html);
    test.skip(!piId, 'No PI on payoff page');

    const quote = await request.post('/api/payment/quote', {
      data: {
        installment_id: fx!.installment_id,
        payment_method_id: 'pm_card_visa',
        payment_plan: 'installment',
        payment_step: 'payoff',
      },
    });
    await expectNotServerError(quote, 'payoff quote');
    expect(quote.status()).toBeLessThan(500);

    const intent = await request.post('/api/payment/intent', {
      data: {
        installment_id: fx!.installment_id,
        payment_method_id: 'pm_card_visa',
        payment_plan: 'installment',
        payment_step: 'payoff',
      },
    });
    await expectNotServerError(intent, 'payoff intent');

    if (intent.status() === 200 && piId) {
      const ok = await confirmPaymentIntent(piId);
      if (ok) {
        const st = await waitForPaymentSucceeded(request, piId);
        expect(st?.status).toBe('succeeded');
      }
    }
  });
});
