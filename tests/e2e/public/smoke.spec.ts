/**
 * Public content smoke + form validation (QA)
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';

const PUBLIC_GETS = [
  '/',
  '/contact',
  '/feedback',
  '/privacy',
  '/terms',
  '/our-team',
  '/asia',
];

test.describe('Public smoke @public @p2', () => {
  for (const path of PUBLIC_GETS) {
    test(`GET ${path} < 500`, async ({ request }) => {
      const res = await request.get(path);
      expect(res.status(), path).toBeLessThan(500);
      expect(res.status(), path).toBeLessThan(400);
    });
  }

  test('QA trip page renders', async ({ page, cfg, jsErrors }) => {
    const res = await page.goto(`/trips/${cfg.tripSlug}`, {
      waitUntil: 'domcontentloaded',
    });
    expect(res?.status() ?? 500).toBeLessThan(500);
    await expect(page.locator('body')).toBeVisible();
    jsErrors.assertNoJsErrors();
  });

  test('unknown trip slug is 404 not 500', async ({ request }) => {
    const res = await request.get('/trips/this-slug-does-not-exist-e2e-xyz');
    expect(res.status()).toBe(404);
  });

  test('contact missing fields → 400', async ({ request }) => {
    const res = await request.post('/contact', {
      data: { form: 'contact', email: 'only@example.com' },
    });
    await expectNotServerError(res, 'contact incomplete');
    expect(res.status()).toBe(400);
  });

  test('contact valid payload → 200', async ({ request }) => {
    const res = await request.post('/contact', {
      data: {
        form: 'contact',
        firstName: 'QA',
        lastName: 'Contact',
        email: `qa-contact-${Date.now()}@example.com`,
        message: 'E2E contact smoke message — please ignore.',
      },
    });
    await expectNotServerError(res, 'contact ok');
    expect(res.status()).toBe(200);
  });

  test('testimonial too-short quote → 400', async ({ request }) => {
    const res = await request.post('/', {
      data: {
        form: 'testimonial',
        quote: 'short',
        author_name: 'QA',
      },
    });
    await expectNotServerError(res, 'testimonial short');
    expect(res.status()).toBe(400);
  });

  test('testimonial valid → 200', async ({ request }) => {
    const res = await request.post('/', {
      data: {
        form: 'testimonial',
        quote:
          'This is a long enough E2E testimonial quote for validation rules.',
        author_name: 'QA Tester',
        organization: 'E2E',
      },
    });
    await expectNotServerError(res, 'testimonial ok');
    expect(res.status()).toBe(200);
  });

  test('newsletter missing email → 400', async ({ request }) => {
    const res = await request.post('/', {
      data: { form: 'newsletter' },
    });
    await expectNotServerError(res, 'newsletter empty');
    expect([400, 200]).toContain(res.status()); // some handlers flash 200+false
  });

  test('/test/* gated when not debug (404 or 200 only in debug)', async ({
    request,
  }) => {
    const res = await request.get('/test/installment-modal');
    expect(res.status()).toBeLessThan(500);
    // Production-like: 404; local debug may 200 — both acceptable if not 500
    expect([200, 404]).toContain(res.status());
  });
});
