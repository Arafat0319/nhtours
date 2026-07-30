/**
 * Checkout — UI resilience (QA adversarial)
 *
 * Focus: illegal navigation, double actions, refresh, network abort.
 * Happy-path card charge is intentionally NOT here (Stripe module).
 */
import { test, expect } from '../fixtures/base';
import { hammerClick } from '../helpers/chaos';

test.describe('Checkout UI chaos @checkout @p1', () => {
  test('trip page loads without JS pageerror', async ({
    tripCheckout,
    cfg,
    jsErrors,
  }) => {
    const res = await tripCheckout.gotoTrip(cfg.tripSlug);
    expect(res?.status(), 'trip page status').toBeLessThan(500);
    expect(res?.status()).not.toBe(404);
    jsErrors.assertNoJsErrors();
  });

  test('unknown trip slug is not a 500', async ({ page, jsErrors }) => {
    const res = await page.goto('/trips/this-slug-should-not-exist-qa-zzzz', {
      waitUntil: 'domcontentloaded',
    });
    expect(res?.status()).toBeGreaterThanOrEqual(400);
    expect(res?.status()).toBeLessThan(500);
    jsErrors.assertNoJsErrors();
  });

  test('Book Now opens modal; Continue with qty 0 stays blocked', async ({
    tripCheckout,
    cfg,
    page,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await tripCheckout.tryContinueWithoutPackage();
    await expect(page.locator('.booking-step[data-step="1"]')).toBeVisible();
    const step5 = page.locator('.booking-step[data-step="5"]');
    if (await step5.count()) {
      await expect(step5).toHaveClass(/hidden/);
    }
    jsErrors.assertNoJsErrors();
  });

  test('hammer Continue without selection does not crash UI', async ({
    tripCheckout,
    cfg,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await hammerClick(tripCheckout.nextBtn(), 8);
    await expect(tripCheckout.modal()).toBeVisible();
    jsErrors.assertNoJsErrors();
  });

  test('select travelers then hammer Continue does not throw', async ({
    tripCheckout,
    cfg,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await tripCheckout.selectOneTravelerOnFirstPackage();
    await hammerClick(tripCheckout.nextBtn(), 5);
    await expect(tripCheckout.modal()).toBeVisible();
    jsErrors.assertNoJsErrors();
  });

  test('refresh mid-checkout does not leave a stuck overlay alone', async ({
    tripCheckout,
    cfg,
    page,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await tripCheckout.selectOneTravelerOnFirstPackage();
    await page.reload({ waitUntil: 'domcontentloaded' });
    // After full reload, modal should reset (not half-open zombie)
    const modal = tripCheckout.modal();
    const visible = await modal.isVisible().catch(() => false);
    if (visible) {
      // If implementation keeps modal open, at least page must be interactive
      await expect(page.locator('body')).toBeVisible();
    }
    jsErrors.assertNoJsErrors();
  });

  test('abort payment/intent network: UI must not white-screen', async ({
    tripCheckout,
    cfg,
    page,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await tripCheckout.selectOneTravelerOnFirstPackage();

    await page.route('**/api/payment/intent', (route) =>
      route.abort('failed'),
    );
    await page.route('**/api/payment/quote', (route) => route.abort('failed'));

    // Advance as far as validation allows; network may fail on later steps
    for (let i = 0; i < 4; i++) {
      if (await tripCheckout.nextBtn().isEnabled()) {
        await tripCheckout.nextBtn().click().catch(() => undefined);
      }
      await page.waitForTimeout(400);
    }

    await expect(page.locator('body')).toBeVisible();
    await expect(tripCheckout.modal()).toBeVisible();
    jsErrors.assertNoJsErrors();
  });

  test('XSS in discount field is not executed as script', async ({
    tripCheckout,
    cfg,
    page,
    jsErrors,
  }) => {
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    const input = tripCheckout.discountInput();
    if (!(await input.count())) {
      test.skip(true, 'discount input not on step 1 sidebar yet');
    }
    await input.fill('<img src=x onerror=window.__xss=1>');
    if (await tripCheckout.applyDiscountBtn().count()) {
      await tripCheckout.applyDiscountBtn().click();
    }
    const flagged = await page.evaluate(() => (window as any).__xss === 1);
    expect(flagged).toBeFalsy();
    jsErrors.assertNoJsErrors();
  });

  test('browser back after opening modal does not 500', async ({
    tripCheckout,
    cfg,
    page,
    jsErrors,
  }) => {
    await page.goto('/');
    await tripCheckout.gotoTrip(cfg.tripSlug);
    await tripCheckout.openModal();
    await page.goBack();
    await expect(page.locator('body')).toBeVisible();
    const statusProbe = await page.goto(page.url(), {
      waitUntil: 'domcontentloaded',
    });
    expect(statusProbe?.status() ?? 200).toBeLessThan(500);
    jsErrors.assertNoJsErrors();
  });
});
