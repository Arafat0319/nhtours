import { APIRequestContext, expect } from '@playwright/test';
import { minimalBuyer, postTripBooking, expectNotServerError } from './api';

/** Pull package ids from trip HTML (stable data-package-id). */
export async function extractPackageIds(
  request: APIRequestContext,
  slug: string,
): Promise<number[]> {
  const res = await request.get(`/trips/${slug}`);
  expect(res.status()).toBeLessThan(500);
  const html = await res.text();
  const ids = [...html.matchAll(/data-package-id="(\d+)"/g)].map((m) =>
    Number(m[1]),
  );
  return [...new Set(ids.filter((n) => n > 0))];
}

export type SeededIntent = {
  paymentIntentId: string;
  clientSecret: string | null;
  paymentRequired: boolean;
  raw: Record<string, unknown>;
};

/**
 * Create PendingBooking + Stripe PI (or free_*) via public booking API.
 * Returns null when trip/packages/Stripe are not ready — callers should test.skip.
 */
export async function seedCheckoutIntent(
  request: APIRequestContext,
  slug: string,
  opts: { paymentPlanType?: 'full' | 'deposit_installment' } = {},
): Promise<SeededIntent | null> {
  const packageIds = await extractPackageIds(request, slug);
  if (!packageIds.length) return null;

  const plan = opts.paymentPlanType || 'full';
  // Prefer second package if full pay exists on QA trip (setup creates installment then full)
  let packageId =
    plan === 'full' && packageIds.length > 1 ? packageIds[1] : packageIds[0];

  const trySeed = async (pkgId: number) => {
    const email = `qa-stripe-${Date.now()}-${pkgId}@example.com`;
    const res = await postTripBooking(request, slug, {
      booking_data: {
        buyer_info: minimalBuyer({ email }),
        packages: [
          {
            package_id: pkgId,
            quantity: 1,
            payment_plan_type: plan,
          },
        ],
        addons: [],
        participants: [
          {
            first_name: 'QA',
            last_name: 'Stripe',
            email,
            phone: '1234567890',
            dob: '1990-01-15',
          },
        ],
        discount_code: null,
        payment_method: plan,
      },
    });
    await expectNotServerError(res, 'seedCheckoutIntent');
    return res;
  };

  let res = await trySeed(packageId);
  // Sold out → try other packages on the trip
  if (res.status() === 400) {
    const body = await res.text();
    if (/sold out/i.test(body)) {
      for (const alt of packageIds) {
        if (alt === packageId) continue;
        res = await trySeed(alt);
        if (res.status() === 200) {
          packageId = alt;
          break;
        }
      }
    }
  }

  if (res.status() !== 200) {
    console.warn('seedCheckoutIntent bad status', res.status(), await res.text());
    return null;
  }

  const raw = (await res.json()) as Record<string, unknown>;
  if (!raw.success) {
    console.warn('seedCheckoutIntent not success', raw);
    return null;
  }

  const paymentIntentId = String(raw.payment_intent_id || '');
  if (!paymentIntentId) {
    console.warn('seedCheckoutIntent missing pi', raw);
    return null;
  }

  return {
    paymentIntentId,
    clientSecret: raw.client_secret ? String(raw.client_secret) : null,
    paymentRequired: Boolean(raw.payment_required),
    raw,
  };
}
