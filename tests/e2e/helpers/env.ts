/** Shared env for E2E. Fail loudly if trip slug missing when UI needs it. */
export function e2eConfig() {
  const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8080';
  const tripSlug = process.env.E2E_TRIP_SLUG || 'qa-payment-trip-2026';
  const unpublishedSlug = process.env.E2E_UNPUBLISHED_SLUG || '';
  const discountCode = (
    process.env.E2E_DISCOUNT_CODE || 'QAZERO'
  ).toUpperCase();
  return { baseURL, tripSlug, unpublishedSlug, discountCode };
}
