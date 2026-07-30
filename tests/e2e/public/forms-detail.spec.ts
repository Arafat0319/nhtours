/**
 * Public forms — feedback / newsletter / contact edge cases
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';

test.describe('Public forms detail @public @detail @p1', () => {
  test('feedback missing rating → 400', async ({ request }) => {
    const res = await request.post('/feedback', {
      data: {
        form: 'feedback',
        firstName: 'QA',
        lastName: 'FB',
        email: `qa-fb-${Date.now()}@example.com`,
        comments: 'This feedback comment is long enough for validation rules.',
      },
    });
    await expectNotServerError(res, 'feedback no rating');
    expect(res.status()).toBe(400);
  });

  test('feedback short comments → 400', async ({ request }) => {
    const res = await request.post('/feedback', {
      data: {
        form: 'feedback',
        firstName: 'QA',
        lastName: 'FB',
        email: `qa-fb-${Date.now()}@example.com`,
        comments: 'too short',
        rating: 'excellent',
      },
    });
    await expectNotServerError(res, 'feedback short');
    expect(res.status()).toBe(400);
  });

  test('feedback valid → 200', async ({ request }) => {
    const res = await request.post('/feedback', {
      data: {
        form: 'feedback',
        firstName: 'QA',
        lastName: 'Feedback',
        email: `qa-fb-ok-${Date.now()}@example.com`,
        comments:
          'This is a sufficiently long post-trip feedback comment for E2E.',
        rating: 'good',
      },
    });
    await expectNotServerError(res, 'feedback ok');
    expect(res.status()).toBe(200);
  });

  test('newsletter valid email → success-ish', async ({ request }) => {
    const res = await request.post('/', {
      data: {
        form: 'newsletter',
        email: `qa-news-${Date.now()}@example.com`,
      },
    });
    await expectNotServerError(res, 'newsletter');
    expect(res.status()).toBeLessThan(500);
  });

  test('contact XSS fields must not 500', async ({ request }) => {
    const res = await request.post('/contact', {
      data: {
        form: 'contact',
        firstName: '<script>alert(1)</script>',
        lastName: '"><img src=x onerror=alert(1)>',
        email: `qa-xss-${Date.now()}@example.com`,
        message: '<script>alert(2)</script> hello there long enough',
      },
    });
    await expectNotServerError(res, 'contact xss');
    expect(res.status()).toBeLessThan(500);
  });

  test('unknown form type on index → error not 500', async ({ request }) => {
    const res = await request.post('/', {
      data: { form: 'not_a_real_form' },
    });
    await expectNotServerError(res, 'unknown form');
    expect(res.status()).toBeLessThan(500);
  });
});
