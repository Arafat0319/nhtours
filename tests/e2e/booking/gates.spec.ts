/**
 * Booking — access gates (QA adversarial)
 * No paid happy path required.
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';

test.describe('Booking access gates @booking @p1', () => {
  test('receipt without token must 404 (anti-enumeration)', async ({ request }) => {
    const res = await request.get('/booking/1/receipt');
    expect(res.status()).toBe(404);
  });

  test('receipt with garbage token must 404', async ({ request }) => {
    const res = await request.get('/booking/1/receipt', {
      params: { token: 'not.a.real.token' },
    });
    expect(res.status()).toBe(404);
  });

  test('summary without token/pi must 403', async ({ request }) => {
    const res = await request.get('/api/booking/1/summary');
    await expectNotServerError(res, 'summary no auth');
    expect([403, 404]).toContain(res.status());
  });

  test('summary with forged payment_intent_id must 403', async ({ request }) => {
    const res = await request.get('/api/booking/1/summary', {
      params: { payment_intent_id: 'pi_forged_not_linked' },
    });
    await expectNotServerError(res, 'summary forged pi');
    expect([403, 404]).toContain(res.status());
  });

  test('pay-installment without token must deny', async ({ request }) => {
    const res = await request.get('/pay-installment/1');
    expect([403, 404]).toContain(res.status());
  });

  test('pay-installment with garbage token must deny', async ({ request }) => {
    const res = await request.get('/pay-installment/1', {
      params: { token: 'garbage' },
    });
    expect([403, 404]).toContain(res.status());
  });
});
