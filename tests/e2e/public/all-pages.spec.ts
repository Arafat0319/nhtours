/**
 * All public content pages — smoke every marketing route
 */
import { test, expect } from '../fixtures/base';

const PAGES = [
  '/',
  '/home-classic',
  '/our-team',
  '/contact',
  '/feedback',
  '/privacy',
  '/terms',
  '/mindx',
  '/asia',
  '/asia/educational',
  '/asia/family',
  '/asia/business',
  '/asia/beijing',
  '/asia/hubei',
  '/asia/japan',
  '/asia/jiangnan',
  '/asia/landscapes',
  '/asia/panda',
  '/asia/southern-china',
  '/asia/yunnan',
  '/north-america',
  '/north-america/educational',
  '/north-america/newyork',
  '/north-america/vancouver',
  '/north-america/canada',
];

test.describe('Public content pages @public @detail @p2', () => {
  for (const path of PAGES) {
    test(`GET ${path}`, async ({ request }) => {
      const res = await request.get(path);
      expect(res.status(), path).toBeLessThan(500);
      expect(res.status(), path).toBeLessThan(400);
      const body = await res.text();
      expect(body.length, path).toBeGreaterThan(50);
    });
  }

  test('design-preview unpublished-ish slug stays safe', async ({ request }) => {
    const res = await request.get('/trips/no-such-trip-e2e/design-preview');
    expect(res.status()).toBeLessThan(500);
    expect([200, 302, 303, 404]).toContain(res.status());
  });
});
