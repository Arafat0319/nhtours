import { APIRequestContext, expect } from '@playwright/test';
import { expectNotServerError } from './api';

/** Trip numeric id from trip page HTML (`id: N,` in booking config). */
export async function extractTripId(
  request: APIRequestContext,
  slug: string,
): Promise<number | null> {
  const res = await request.get(`/trips/${slug}`);
  expect(res.status()).toBeLessThan(500);
  const html = await res.text();
  const m =
    html.match(/window\.tripData\s*=\s*\{[\s\S]*?\bid:\s*(\d+)\s*,/) ||
    html.match(/\bid:\s*(\d+)\s*,/);
  return m ? Number(m[1]) : null;
}

export async function validateDiscount(
  request: APIRequestContext,
  body: Record<string, unknown>,
) {
  const res = await request.post('/api/discount/validate', {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  await expectNotServerError(res, 'discount/validate');
  return { res, json: (await res.json().catch(() => ({}))) as Record<string, unknown> };
}

export async function applyDiscount(
  request: APIRequestContext,
  body: Record<string, unknown>,
) {
  const res = await request.post('/api/discount/apply', {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  await expectNotServerError(res, 'discount/apply');
  return { res, json: (await res.json().catch(() => ({}))) as Record<string, unknown> };
}

/** Resolve QAZERO (or E2E_DISCOUNT_CODE) via validate; null if missing. */
export async function resolveQaDiscount(
  request: APIRequestContext,
  tripId: number | null,
  orderAmount = 1000,
): Promise<{ id: number; code: string } | null> {
  const code = (process.env.E2E_DISCOUNT_CODE || 'QAZERO').toUpperCase();
  const { json } = await validateDiscount(request, {
    code,
    trip_id: tripId,
    order_amount: orderAmount,
  });
  if (!json.valid || !json.discount) return null;
  const d = json.discount as Record<string, unknown>;
  return { id: Number(d.id), code: String(d.code || code) };
}
