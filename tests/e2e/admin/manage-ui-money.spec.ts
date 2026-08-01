/**
 * Manage UI money controls — catches Refund/Cancel button & modal regressions
 * that API-only suites (e2e_full_suite / roles-money) cannot see.
 */
import { test, expect } from '../fixtures/base';
import { adminCreds, adminLoginOnPage } from '../helpers/admin-auth';
import { extractTripId } from '../helpers/discount';
import { seedPaidBooking } from '../helpers/paid-booking';

async function openManageForBooking(
  page: import('@playwright/test').Page,
  tripId: number,
  bookingId: number,
) {
  await page.goto(`/admin/trips/${tripId}/manage`);
  await expect(page.locator('#bookingsTableBody')).toBeVisible({ timeout: 20_000 });
  const row = page.locator(`tr.booking-row[data-booking-id="${bookingId}"]`);
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.getByRole('button', { name: 'Manage' }).click();
  await expect(page.locator('#manageBookingModal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#refundBookingBtn')).toBeVisible();
}

test.describe('Manage UI money @admin @ui @p0', () => {
  test('Refund button opens modal above Manage; Full refund fills amount', async ({
    page,
    request,
    playwright,
    cfg,
    jsErrors,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need E2E_ADMIN_* (run prepare_e2e_env.py)');

    const pub = await playwright.request.newContext({ baseURL: cfg.baseURL });
    const paid = await seedPaidBooking(pub, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    await pub.dispose();
    test.skip(!paid, 'Need Stripe Test seed (E2E_STRIPE_SECRET_KEY)');

    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'QA trip missing');

    await adminLoginOnPage(page, admin!);
    await openManageForBooking(page, tripId!, paid!.bookingId);

    // Core regression: button must open refund dialog (z-index / listener / load race)
    await page.locator('#refundBookingBtn').click();
    const refundModal = page.locator('#refundModal');
    await expect(refundModal).not.toHaveClass(/hidden/);
    await expect(refundModal).toBeVisible();
    await expect(page.locator('#refundAmount')).toBeVisible();
    await expect(page.locator('#refundReason')).toBeVisible();
    await expect(page.locator('#refundFullAmount')).toBeVisible();
    await expect(page.locator('#confirmRefundBtn')).toBeEnabled();

    const maxText = await page.locator('#refundMaxAmount').innerText();
    expect(maxText).toMatch(/\$\d/);

    await page.locator('#refundFullAmount').check();
    const filled = await page.locator('#refundAmount').inputValue();
    expect(Number(filled)).toBeGreaterThan(0);

    // Partial UI refund ($1) through the same path a human uses
    await page.locator('#refundFullAmount').uncheck();
    await page.locator('#refundAmount').fill('1.00');
    await page.locator('#refundReason').fill('e2e manage UI refund');
    await page.locator('#confirmRefundBtn').click();

    await expect(refundModal).toHaveClass(/hidden/, { timeout: 30_000 });

    // Re-login API context for financials check
    const { adminLogin } = await import('../helpers/admin-auth');
    expect(await adminLogin(request, admin!)).toBe(true);
    const fin = await request.get(`/admin/trips/${tripId}/financials`);
    expect(fin.status()).toBe(200);
    const body = await fin.json();
    expect(body.success).toBe(true);
    expect(body.financials).toHaveProperty('total_refunded');
    expect(Number(body.financials.total_refunded)).toBeGreaterThanOrEqual(1);

    jsErrors.assertNoJsErrors();
  });

  test('Cancel order button prompts and cancels booking', async ({
    page,
    request,
    playwright,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need E2E_ADMIN_*');

    const pub = await playwright.request.newContext({ baseURL: cfg.baseURL });
    const paid = await seedPaidBooking(pub, cfg.tripSlug, {
      paymentPlanType: 'full',
    });
    await pub.dispose();
    test.skip(!paid, 'Need Stripe Test seed');

    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'QA trip missing');

    await adminLoginOnPage(page, admin!);
    await openManageForBooking(page, tripId!, paid!.bookingId);

    page.once('dialog', async (dialog) => {
      expect(dialog.message().toLowerCase()).toContain('cancel');
      await dialog.accept();
    });
    await page.locator('#cancelOrderBtn').click();

    const { adminLogin } = await import('../helpers/admin-auth');
    expect(await adminLogin(request, admin!)).toBe(true);
    await expect
      .poll(async () => {
        const r = await request.get(
          `/admin/trips/${tripId}/bookings/${paid!.bookingId}?format=json`,
        );
        if (r.status() !== 200) return '';
        const j = await r.json();
        return j?.booking?.status || j?.status || '';
      }, { timeout: 20_000 })
      .toBe('cancelled');
  });
});
