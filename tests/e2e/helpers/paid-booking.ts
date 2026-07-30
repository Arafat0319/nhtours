import { APIRequestContext, expect } from '@playwright/test';
import { expectNotServerError } from './api';
import { seedCheckoutIntent, SeededIntent } from './booking-seed';

export type ConfirmedBooking = {
  paymentIntentId: string;
  bookingId: number;
  receiptUrl: string | null;
  statusPayload: Record<string, unknown>;
};

function stripeSecret(): string | undefined {
  return process.env.E2E_STRIPE_SECRET_KEY || process.env.STRIPE_SECRET_KEY;
}

/** Confirm a Test-mode PI via Stripe API (pm_card_visa). */
export async function confirmPaymentIntent(piId: string): Promise<boolean> {
  const key = stripeSecret();
  if (!key || !piId.startsWith('pi_')) return false;

  const body = new URLSearchParams({
    payment_method: 'pm_card_visa',
    return_url: process.env.E2E_BASE_URL || 'http://127.0.0.1:8080/',
  });
  const res = await fetch(`https://api.stripe.com/v1/payment_intents/${piId}/confirm`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    console.warn(`Stripe confirm failed ${res.status}: ${text.slice(0, 300)}`);
    return false;
  }
  const json = (await res.json()) as { status?: string };
  return json.status === 'succeeded' || json.status === 'requires_capture';
}

/** Poll /api/payment/status until booking_id or timeout. */
export async function waitForBookingFromStatus(
  request: APIRequestContext,
  paymentIntentId: string,
  opts: { timeoutMs?: number; intervalMs?: number } = {},
): Promise<ConfirmedBooking | null> {
  const timeoutMs = opts.timeoutMs ?? 45_000;
  const intervalMs = opts.intervalMs ?? 1_000;
  const start = Date.now();
  let last: Record<string, unknown> = {};

  while (Date.now() - start < timeoutMs) {
    const res = await request.get('/api/payment/status', {
      params: { payment_intent_id: paymentIntentId },
    });
    await expectNotServerError(res, 'waitForBooking status');
    last = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const bookingId = Number(last.booking_id);
    if (last.status === 'succeeded' && bookingId > 0) {
      return {
        paymentIntentId,
        bookingId,
        receiptUrl: last.receipt_url ? String(last.receipt_url) : null,
        statusPayload: last,
      };
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  console.warn('waitForBooking timeout last=', last);
  return null;
}

/**
 * Seed → Stripe confirm → status until Booking.
 * Returns null when Stripe secret missing or confirm fails (caller test.skip).
 */
export async function seedPaidBooking(
  request: APIRequestContext,
  slug: string,
  opts: { paymentPlanType?: 'full' | 'deposit_installment' } = {},
): Promise<ConfirmedBooking | null> {
  if (!stripeSecret()) return null;

  const seeded: SeededIntent | null = await seedCheckoutIntent(request, slug, {
    paymentPlanType: opts.paymentPlanType || 'full',
  });
  if (!seeded?.paymentRequired || !seeded.paymentIntentId.startsWith('pi_')) {
    return null;
  }

  const ok = await confirmPaymentIntent(seeded.paymentIntentId);
  if (!ok) return null;

  return waitForBookingFromStatus(request, seeded.paymentIntentId);
}

/** Poll status until succeeded (installment may already have booking_id). */
export async function waitForPaymentSucceeded(
  request: APIRequestContext,
  paymentIntentId: string,
  opts: { timeoutMs?: number; intervalMs?: number } = {},
): Promise<Record<string, unknown> | null> {
  const timeoutMs = opts.timeoutMs ?? 45_000;
  const intervalMs = opts.intervalMs ?? 1_000;
  const start = Date.now();
  let last: Record<string, unknown> = {};

  while (Date.now() - start < timeoutMs) {
    const res = await request.get('/api/payment/status', {
      params: { payment_intent_id: paymentIntentId },
    });
    await expectNotServerError(res, 'waitForPayment status');
    last = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (last.status === 'succeeded') return last;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  console.warn('waitForPaymentSucceeded timeout last=', last);
  return null;
}

export function tokenFromReceiptUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url, process.env.E2E_BASE_URL || 'http://127.0.0.1:8080');
    return u.searchParams.get('token');
  } catch {
    return null;
  }
}

export function extractPaymentIntentFromHtml(html: string): string | null {
  const m =
    html.match(/paymentIntentId:\s*["'](pi_[^"']+)["']/) ||
    html.match(/payment_intent_id["']?\s*[:=]\s*["'](pi_[^"']+)["']/);
  return m ? m[1] : null;
}
