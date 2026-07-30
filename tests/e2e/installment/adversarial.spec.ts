/**
 * Installments — token gates, IDOR quote, payoff (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { loadInstallmentFixture } from '../helpers/installment-fixture';

test.describe('Installment adversarial @installment @p1', () => {
  test('pay-installment without token is denied', async ({ request }) => {
    const res = await request.get('/pay-installment/1');
    expect([403, 404]).toContain(res.status());
  });

  test('pay-installment garbage token is denied', async ({ request }) => {
    const res = await request.get('/pay-installment/1', {
      params: { token: 'not.real' },
    });
    expect([403, 404]).toContain(res.status());
  });

  test('valid token opens page; wrong id with that token fails', async ({
    request,
    cfg,
  }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need unpaid installment fixture (python helper)');

    const ok = await request.get(`/pay-installment/${fx!.installment_id}`, {
      params: { token: fx!.token },
    });
    expect(ok.status()).toBeLessThan(500);
    // pending → 200 HTML; already paid → redirect success
    expect([200, 302, 303]).toContain(ok.status());
    if (ok.status() === 200) {
      const html = await ok.text();
      expect(html.length).toBeGreaterThan(100);
    }

    const cross = await request.get(
      `/pay-installment/${fx!.installment_id + 99999}`,
      { params: { token: fx!.token } },
    );
    expect([403, 404]).toContain(cross.status());
  });

  test('payoff with valid token must not 500', async ({ request, cfg }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need fixture');
    const res = await request.get(
      `/pay-installment/${fx!.installment_id}/payoff`,
      { params: { token: fx!.token } },
    );
    expect(res.status()).toBeLessThan(500);
    expect([200, 302, 303]).toContain(res.status());
  });

  test('quote/intent with unknown installment stays safe (no auth)', async ({
    request,
  }) => {
    const quote = await request.post('/api/payment/quote', {
      data: {
        installment_id: 99999999,
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(quote, 'installment quote unknown');
    expect([400, 404]).toContain(quote.status());

    const intent = await request.post('/api/payment/intent', {
      data: {
        installment_id: 99999999,
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(intent, 'installment intent unknown');
    expect([400, 404, 409]).toContain(intent.status());
  });

  test('quote for real installment without token is reachable (document IDOR)', async ({
    request,
    cfg,
  }) => {
    const fx = loadInstallmentFixture(cfg.tripSlug);
    test.skip(!fx, 'Need fixture');
    // Known gap: quote does not require installment token — assert non-500 + shape
    const res = await request.post('/api/payment/quote', {
      data: {
        installment_id: fx!.installment_id,
        payment_method_id: 'pm_card_visa',
      },
    });
    await expectNotServerError(res, 'installment quote no token');
    // May 200 (fee quote) or 400 (bad PM) — must not crash
    expect(res.status()).toBeLessThan(500);
  });
});
