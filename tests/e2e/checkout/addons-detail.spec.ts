/**
 * Checkout with add-on — amount must include addon server-side
 */
import { test, expect } from '../fixtures/base';
import { minimalBuyer, postTripBooking, expectNotServerError } from '../helpers/api';
import { extractPackageIds } from '../helpers/booking-seed';

async function extractAddonIds(
  request: import('@playwright/test').APIRequestContext,
  slug: string,
): Promise<number[]> {
  const html = await (await request.get(`/trips/${slug}`)).text();
  const block = html.match(/addons:\s*\[([\s\S]*?)\]\s*,\s*\w+\s*:/);
  const src = block ? block[1] : html;
  return [
    ...new Set([...src.matchAll(/\bid:\s*(\d+)/g)].map((m) => Number(m[1]))),
  ].filter((n) => n > 0);
}

test.describe('Checkout addons detail @checkout @detail @p1', () => {
  test('booking with addon increases base vs package-only', async ({
    request,
    cfg,
  }) => {
    const pkgs = await extractPackageIds(request, cfg.tripSlug);
    const addons = await extractAddonIds(request, cfg.tripSlug);
    test.skip(!pkgs.length, 'No packages');
    test.skip(!addons.length, 'No addons on QA trip');

    const pkg = pkgs.length > 1 ? pkgs[1] : pkgs[0];
    const addonId = addons[0];

    const email1 = `qa-addon-a-${Date.now()}@example.com`;
    const onlyPkg = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email: email1 }),
        packages: [
          { package_id: pkg, quantity: 1, payment_plan_type: 'full' },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Only',
            email: email1,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: null,
        payment_method: 'full',
      },
    });
    await expectNotServerError(onlyPkg, 'pkg only');
    const a = await onlyPkg.json();

    const email2 = `qa-addon-b-${Date.now()}@example.com`;
    const withAddon = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email: email2 }),
        packages: [
          { package_id: pkg, quantity: 1, payment_plan_type: 'full' },
        ],
        addons: [{ addon_id: addonId, quantity: 1 }],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Addon',
            email: email2,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: null,
        payment_method: 'full',
      },
    });
    await expectNotServerError(withAddon, 'with addon');
    const b = await withAddon.json();

    expect(a.success && b.success).toBe(true);
    expect(Number(b.base_amount_cents)).toBeGreaterThan(
      Number(a.base_amount_cents),
    );
  });

  test('quantity 0 package rejected safely', async ({ request, cfg }) => {
    const pkgs = await extractPackageIds(request, cfg.tripSlug);
    test.skip(!pkgs.length, 'No pkgs');
    const email = `qa-qty0-${Date.now()}@example.com`;
    const res = await postTripBooking(request, cfg.tripSlug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          {
            package_id: pkgs[0],
            quantity: 0,
            payment_plan_type: 'full',
          },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Zero',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: null,
        payment_method: 'full',
      },
    });
    await expectNotServerError(res, 'qty0');
    expect(res.status()).not.toBe(500);
  });
});
