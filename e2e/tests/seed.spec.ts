import { execSync } from 'node:child_process';
import { type APIRequestContext } from '@playwright/test';
import { test, expect, runSeed, type SeedIds } from '../fixtures';
import { SEED_CMD } from '../env';
import { getJson, khataBalance } from '../helpers';
import { R1, R2 } from '../seed';

/** What a spec can observe about the dataset, with database ids replaced by seed keys. */
async function snapshot(api: APIRequestContext, ids: SeedIds, token: (u?: string) => Promise<string>) {
  const r1 = await token(R1.username);
  const r2 = await token(R2.username);
  const products: Record<string, unknown> = {};
  for (const [key, id] of Object.entries(ids.products)) {
    const p = await getJson(api, `products/${id}/`, r1);
    products[key] = { name: p.name, price: p.price, quantity: p.quantity, barcode: p.barcode };
  }
  return {
    keys: { retailers: Object.keys(ids.retailers), customers: Object.keys(ids.customers) },
    products,
    khata: {
      C1_R1: await khataBalance(api, r1, ids.customers.C1),
      C1_R2: await khataBalance(api, r2, ids.customers.C1),
    },
  };
}

test('S1 seed twice gives the same data; it refuses a non-local database @S1 @core', async ({ api, seed, retailerToken }) => {
  const first = await snapshot(api, seed, retailerToken);
  const second = await snapshot(api, runSeed(), retailerToken);
  expect(second).toEqual(first);
  expect(first.khata).toEqual({ C1_R1: 500, C1_R2: 1000 });

  let refusal = '';
  try {
    execSync(SEED_CMD, { encoding: 'utf8', shell: '/bin/bash', stdio: 'pipe', env: { ...process.env, DB_HOST: 'db.example.com' } });
  } catch (error) {
    refusal = String((error as { stderr?: string }).stderr);
  }
  expect(refusal).toContain("seed_e2e refuses to run against database host 'db.example.com'");
});
