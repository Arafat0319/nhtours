/**
 * Export token chain (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { adminCreds, adminLogin } from '../helpers/admin-auth';
import { extractTripId } from '../helpers/discount';

test.describe('Export token chain @export @p1', () => {
  test('login → data-source-url → csv/html with token', async ({
    request,
    cfg,
  }) => {
    const admin = adminCreds();
    test.skip(!admin, 'Need admin');
    expect(await adminLogin(request, admin!)).toBe(true);

    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');

    const ds = await request.get(
      `/admin/trips/${tripId}/bookings/export/data-source-url`,
    );
    expect(ds.status()).toBe(200);
    const body = await ds.json();
    expect(body.success).toBe(true);
    const url = String(body.url || '');
    expect(url).toMatch(/token=/);

    // Follow as absolute or path
    const path = url.includes('://')
      ? new URL(url).pathname + new URL(url).search
      : url.startsWith('/')
        ? url
        : `/${url}`;

    const html = await request.get(path);
    expect(html.status()).toBe(200);
    const text = await html.text();
    expect(text.length).toBeGreaterThan(10);

    // Same token as csv (drop format=html if present)
    const u = new URL(url, cfg.baseURL);
    u.searchParams.delete('format');
    const csvPath = u.pathname + '?' + u.searchParams.toString();
    const csv = await request.get(csvPath);
    expect(csv.status()).toBe(200);
  });
});
