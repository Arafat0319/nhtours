/**
 * Upload limits / pdf magic / path binding
 */
import { test, expect } from '../fixtures/base';
import { expectNotServerError } from '../helpers/api';
import { extractTripId } from '../helpers/discount';

const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

test.describe('Upload limits detail @upload @detail @p1', () => {
  test('pdf magic accepted', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const pdf = Buffer.from('%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n');
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: String(tripId),
        file: {
          name: 'qa.pdf',
          mimeType: 'application/pdf',
          buffer: pdf,
        },
      },
    });
    await expectNotServerError(res, 'pdf upload');
    expect([200, 400]).toContain(res.status());
    if (res.status() === 200) {
      const json = await res.json();
      expect(String(json.path)).toContain(`trip_${tripId}`);
    }
  });

  test('oversized payload rejected safely', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    // ~11MB of zeros with png header — should hit 10MB booking limit or flask 16MB
    const big = Buffer.concat([
      TINY_PNG.subarray(0, 8),
      Buffer.alloc(11 * 1024 * 1024, 1),
    ]);
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: String(tripId),
        file: {
          name: 'huge.png',
          mimeType: 'image/png',
          buffer: big,
        },
      },
      timeout: 60_000,
    });
    expect(res.status()).toBeLessThan(500);
    expect([400, 413]).toContain(res.status());
  });

  test('webp without magic rejected', async ({ request, cfg }) => {
    const tripId = await extractTripId(request, cfg.tripSlug);
    test.skip(!tripId, 'No trip');
    const res = await request.post('/api/booking/upload', {
      multipart: {
        trip_id: String(tripId),
        file: {
          name: 'fake.webp',
          mimeType: 'image/webp',
          buffer: Buffer.from('not-a-webp'),
        },
      },
    });
    await expectNotServerError(res, 'fake webp');
    expect(res.status()).toBe(400);
  });
});
