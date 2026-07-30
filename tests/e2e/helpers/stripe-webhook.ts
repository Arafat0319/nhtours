import crypto from 'crypto';

function webhookSecret(): string | undefined {
  const raw =
    process.env.E2E_STRIPE_WEBHOOK_SECRET ||
    process.env.STRIPE_WEBHOOK_SECRET;
  return raw ? raw.trim().replace(/^["']|["']$/g, '') : undefined;
}

function stripeSecret(): string | undefined {
  const raw =
    process.env.E2E_STRIPE_SECRET_KEY || process.env.STRIPE_SECRET_KEY;
  return raw ? raw.trim().replace(/^["']|["']$/g, '') : undefined;
}

/**
 * Stripe webhook signing — use whsec_ secret as UTF-8 (stripe-python 11+).
 */
export function signStripeWebhookPayload(
  payload: string,
  secret: string,
): string {
  const t = Math.floor(Date.now() / 1000);
  const msg = `${t}.${payload}`;
  const sig = crypto
    .createHmac('sha256', secret)
    .update(msg, 'utf8')
    .digest('hex');
  return `t=${t},v1=${sig}`;
}

export function hasWebhookSecret(): boolean {
  return Boolean(webhookSecret());
}

/** Fetch PI JSON from Stripe API for webhook body. */
export async function retrievePaymentIntentRaw(
  piId: string,
): Promise<Record<string, unknown> | null> {
  const key = stripeSecret();
  if (!key) return null;
  const res = await fetch(`https://api.stripe.com/v1/payment_intents/${piId}`, {
    headers: { Authorization: `Bearer ${key}` },
  });
  if (!res.ok) return null;
  return (await res.json()) as Record<string, unknown>;
}

/**
 * POST signed payment_intent.succeeded (fetch keeps body bytes intact).
 */
export async function postSignedPaymentIntentSucceeded(
  paymentIntent: Record<string, unknown>,
  opts: { eventId?: string; times?: number; baseURL?: string } = {},
): Promise<{ statuses: number[]; bodies: string[] } | null> {
  const secret = webhookSecret();
  if (!secret) return null;

  const times = opts.times ?? 1;
  const base = (
    opts.baseURL ||
    process.env.E2E_BASE_URL ||
    'http://127.0.0.1:8080'
  ).replace(/\/$/, '');
  const eventId =
    opts.eventId ||
    `evt_e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const statuses: number[] = [];
  const bodies: string[] = [];

  // Slim PI object — Stripe webhooks don't need every expanded field
  const piSlim = {
    id: paymentIntent.id,
    object: 'payment_intent',
    status: paymentIntent.status || 'succeeded',
    amount: paymentIntent.amount,
    currency: paymentIntent.currency || 'usd',
    metadata: paymentIntent.metadata || {},
    client_secret: paymentIntent.client_secret,
  };

  for (let i = 0; i < times; i++) {
    const event = {
      id: eventId,
      object: 'event',
      type: 'payment_intent.succeeded',
      data: { object: piSlim },
    };
    const payload = JSON.stringify(event);
    const sig = signStripeWebhookPayload(payload, secret);
    const res = await fetch(`${base}/webhooks/stripe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Stripe-Signature': sig,
      },
      body: payload,
    });
    statuses.push(res.status);
    bodies.push(await res.text());
  }
  return { statuses, bodies };
}
