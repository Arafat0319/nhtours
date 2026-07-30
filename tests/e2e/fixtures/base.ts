import { test as base } from '@playwright/test';
import { TripCheckoutPage } from '../pages/trip-checkout.page';
import { attachJsErrorCollector } from '../helpers/chaos';
import { e2eConfig } from '../helpers/env';

type Fixtures = {
  tripCheckout: TripCheckoutPage;
  jsErrors: ReturnType<typeof attachJsErrorCollector>;
  cfg: ReturnType<typeof e2eConfig>;
};

export const test = base.extend<Fixtures>({
  cfg: async ({}, use) => {
    await use(e2eConfig());
  },
  jsErrors: async ({ page }, use) => {
    const collector = attachJsErrorCollector(page);
    await use(collector);
  },
  tripCheckout: async ({ page }, use) => {
    await use(new TripCheckoutPage(page));
  },
});

export { expect } from '@playwright/test';
