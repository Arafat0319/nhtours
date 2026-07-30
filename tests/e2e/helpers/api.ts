import { APIRequestContext, expect } from '@playwright/test';

/**
 * Minimal booking payload shapes for API chaos.
 * Intentionally incomplete / wrong in many tests — that is the point.
 */
export function minimalBuyer(overrides: Record<string, unknown> = {}) {
  return {
    first_name: 'QA',
    last_name: 'Chaos',
    email: `qa-chaos-${Date.now()}@example.com`,
    phone: '1234567890',
    ...overrides,
  };
}

export async function postTripBooking(
  request: APIRequestContext,
  slug: string,
  body: unknown,
) {
  return request.post(`/trips/${slug}`, {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Assert response is not a server crash. 4xx is acceptable for bad input. */
export async function expectNotServerError(
  response: { status: () => number; text: () => Promise<string> },
  label: string,
) {
  const status = response.status();
  const body = await response.text();
  expect(
    status,
    `${label}: unexpected 5xx. body=${body.slice(0, 500)}`,
  ).toBeLessThan(500);
}
