import { Page, expect } from '@playwright/test';

/**
 * Trip detail + booking modal (checkout funnel entry).
 * Selectors prefer stable ids / data-testid used in production templates.
 */
export class TripCheckoutPage {
  constructor(readonly page: Page) {}

  async gotoTrip(slug: string) {
    const res = await this.page.goto(`/trips/${slug}`, { waitUntil: 'domcontentloaded' });
    return res;
  }

  bookNowTriggers() {
    return this.page.locator('.book-now-trigger, .package-book-now').first();
  }

  modal() {
    return this.page.locator('#booking-modal');
  }

  nextBtn() {
    return this.page.locator('#nextBtn');
  }

  stepError() {
    return this.page.locator('#step1-error-message, [role="alert"]').first();
  }

  packageStepperPlus(packageIndex = 0) {
    // experimental modal: first package card + button inside stepper
    return this.page
      .locator(`[data-testid="package-row-${packageIndex}"] button, .pkg-stepper-wrapper button`)
      .filter({ hasText: /\+|▲|›/ })
      .first()
      .or(
        this.page.locator(`[data-testid="package-row-${packageIndex}"] .pkg-stepper-wrapper button`).nth(1),
      );
  }

  async openModal() {
    await this.bookNowTriggers().click();
    await expect(this.modal()).toBeVisible();
  }

  async tryContinueWithoutPackage() {
    // Ensure qty stays 0 if possible, then Continue
    await this.nextBtn().click();
  }

  async selectOneTravelerOnFirstPackage() {
    const row = this.page.locator('[data-testid="package-row-0"], .package-card').first();
    await expect(row).toBeVisible();
    const plus = row.locator('.pkg-stepper-plus').first();
    if (await plus.count()) {
      await plus.click();
      return;
    }
    const radio1 = row.locator('input.quantity-radio[value="1"]').first();
    if (await radio1.count()) {
      await radio1.check({ force: true });
      return;
    }
    await row.click();
  }

  discountInput() {
    return this.page.locator('#discount-code-input');
  }

  applyDiscountBtn() {
    return this.page.locator('#apply-discount-btn');
  }
}
