/**
 * Booking upload — magic bytes / trip binding (QA adversarial)
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { extractTripId } from '../helpers/discount';

/** 1x1 PNG */
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

test.describe('Upload gates @upload @p1', () => {
  test('missing trip_id → 400', async ({ request }) => {
    const res = await request.post('/api/booking/upload', {
      multipart: {
        file: {
          name: 'x.png',
          mimeType: 'image/png',
          buffer: TINY_PNG,
        },
      },
    });
    await expectNotServerError(res, 'upload no trip');
    expect(res.status()).toBe(400);
  });

  test('invalid trip_id → 400', async ({ request }) => {
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: '99999999',
        file: {
          name: 'x.png',
          mimeType: 'image/png',
          buffer: TINY_PNG,
        },
      },
    });
    await expectNotServerError(res, 'upload bad trip');
    expect(res.status()).toBe(400);
  });

  test('exe disguised as jpg rejected by magic', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip id');
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: String(tripId),
        file: {
          name: 'malware.jpg',
          mimeType: 'image/jpeg',
          buffer: Buffer.from('MZ-this-is-not-a-jpeg'),
        },
      },
    });
    await expectNotServerError(res, 'upload fake jpeg');
    expect(res.status()).toBe(400);
  });

  test('valid tiny png uploads', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip id');
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: String(tripId),
        file: {
          name: 'qa-dot.png',
          mimeType: 'image/png',
          buffer: TINY_PNG,
        },
      },
    });
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(String(json.path || '')).toContain(`trip_${tripId}`);
    expect(String(json.url || '')).toBeTruthy();
  });

  test('no file field → 400', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip id');
    const res = await request.post('/api/booking/upload', {
      multipart: { trip_id: String(tripId) },
    });
    await expectNotServerError(res, 'upload no file');
    expect(res.status()).toBe(400);
  });
});
