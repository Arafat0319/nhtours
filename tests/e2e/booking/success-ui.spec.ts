/**
 * Booking — success page resilience (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { seedPaidBooking, tokenFromReceiptUrl } from '../helpers/paid-booking';
import { attachJsErrorCollector } from '../helpers/chaos';

test.describe('Booking success UI @booking @p1', () => {
  test('success with unknown booking_id must not 500', async ({ page }) => {
    const js = attachJsErrorCollector(page);
    const res = await page.goto('/booking/success?booking_id=99999999&already_paid=1', {
      waitUntil: 'domcontentloaded',
    });
    expect(res?.status() ?? 200).toBeLessThan(500);
    await expect(page.locator('body')).toBeVisible();
    js.assertNoJsErrors();
  });

  test('success page refresh spam after paid booking', async ({
    page,
    request,
    cfg,
  }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug);
    test.skip(!paid, 'Need Stripe Test secret');

    const st = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const json = await st.json();
    const token = tokenFromReceiptUrl(json.receipt_url);
    const url =
      `/booking/success?booking_id=${paid!.bookingId}` +
      (token ? `&token=${encodeURIComponent(token)}` : '') +
      '&already_paid=1';

    const js = attachJsErrorCollector(page);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    for (let i = 0; i < 4; i++) {
      await page.reload({ waitUntil: 'domcontentloaded' });
    }
    await expect(page.locator('body')).toBeVisible();
    js.assertNoJsErrors();

    // Still a single booking under the PI
    const again = await request.get('/api/payment/status', {
      params: { payment_intent_id: paid!.paymentIntentId },
    });
    const againJson = await again.json();
    expect(Number(againJson.booking_id)).toBe(paid!.bookingId);
  });

  test('browser back from success must not 500', async ({ page, request, cfg }) => {
    const paid = await seedPaidBooking(request, cfg.tripSlug);
    test.skip(!paid, 'Need Stripe Test secret');

    await page.goto(`/trips/${cfg.tripSlug}`);
    await page.goto(`/booking/success?booking_id=${paid!.bookingId}&already_paid=1`);
    await page.goBack();
    await expect(page.locator('body')).toBeVisible();
    const res = await page.goto(page.url());
    expect(res?.status() ?? 200).toBeLessThan(500);
  });
});
