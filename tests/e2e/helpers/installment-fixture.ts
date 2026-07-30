import fs from 'fs';
import path from 'path';

export type InstallmentFixture = {
  installment_id: number;
  booking_id: number;
  status: string;
  token: string;
  amount: number;
};

const CACHE = path.resolve(__dirname, '../.cache/installment-fixture.json');

/**
 * Read pre-generated fixture (npm pretest → scripts/gen-installment-fixture.mjs).
 * Playwright workers cannot spawn Python on some Windows sandboxes.
 */
export function loadInstallmentFixture(
  _tripSlug?: string,
): InstallmentFixture | null {
  try {
    if (!fs.existsSync(CACHE)) return null;
    const json = JSON.parse(fs.readFileSync(CACHE, 'utf8')) as InstallmentFixture & {
      error?: string;
    };
    if (json.error || !json.token || !json.installment_id) return null;
    return json;
  } catch (err) {
    console.warn('loadInstallmentFixture failed', err);
    return null;
  }
}
