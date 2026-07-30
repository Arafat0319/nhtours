/**
 * Stripe Payment — UI / network interruption (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { hammerClick } from '../helpers/chaos';

test.describe('Stripe UI interruption @stripe @p1', () => {
  test('blocking Stripe.js must not white-screen trip page', async ({
    page,
    tripCheckout,
    cfg,
    jsErrors,
  }) => {
    await page.route('**/js.stripe.com/**', (route) => route.abort('failed'));
    await page.route('**/api.stripe.com/**', (route) => route.abort('failed'));

    const res = await tripCheckout.gotoTrip(cfg.tripSlug);
    expect(res?.status()).toBeLessThan(500);
    await tripCheckout.openModal();
    await tripCheckout.selectOneTravelerOnFirstPackage();
    await hammerClick(tripCheckout.nextBtn(), 3);

    await expect(page.locator('body')).toBeVisible();
    await expect(tripCheckout.modal()).toBeVisible();
    // pageerror from missing Stripe is possible — collect but require page alive
    expect(jsErrors.errors.length).toBeLessThan(20);
  });

  test('payment/pending with garbage query must not 500', async ({ page }) => {
    const res = await page.goto(
      '/payment/pending?payment_intent_id=pi_bogus&booking_id=99999999',
      { waitUntil: 'domcontentloaded' },
    );
    expect(res?.status() ?? 200).toBeLessThan(500);
  });

  test('booking/success without paid context must not 500', async ({ page }) => {
    const res = await page.goto('/booking/success?booking_id=99999999', {
      waitUntil: 'domcontentloaded',
    });
    expect(res?.status() ?? 200).toBeLessThan(500);
  });
});
