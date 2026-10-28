import { execSync } from 'node:child_process';
import { test as base, expect, type APIRequestContext, type BrowserContext } from '@playwright/test';
import { API_URL, PASSWORD, RETAILER_URL, CUSTOMER_URL, SEED_CMD } from './env';

/** Live OrderEasy hosts. Any request to one fails the test (G1). */
export const LIVE_HOST = /(^|\.)ordereasy\.win$/i;

/** Third-party services the apps call on load (Firebase, Google). Aborted silently, never reached. */
const THIRD_PARTY_HOST = /(googleapis\.com|gstatic\.com|firebaseio\.com|firebaseapp\.com|firebase\.com|google\.com|google-analytics\.com|googletagmanager\.com)$/i;

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost']);

export type SeedIds = {
  retailers: { R1: number; R2: number };
  customers: { C1: number; C2: number };
  products: { P1: number; P2: number; P3: number; P4: number; P5: number };
  c2_address: number;
};

export function runSeed(): SeedIds {
  const out = execSync(SEED_CMD, { encoding: 'utf8', shell: '/bin/bash' });
  const jsonLine = out.trim().split('\n').filter((line) => line.startsWith('{')).pop();
  if (!jsonLine) throw new Error(`seed_e2e printed no ids:\n${out}`);
  return JSON.parse(jsonLine);
}

/** Decide what happens to one outgoing URL. Records live-host hits in `liveHits`. */
export function guardDecision(url: string, liveHits: string[]): 'continue' | 'abort' {
  const parsed = new URL(url);
  if (['data:', 'blob:'].includes(parsed.protocol)) return 'continue';
  if (LIVE_HOST.test(parsed.hostname)) {
    liveHits.push(url);
    return 'abort';
  }
  if (LOCAL_HOSTS.has(parsed.hostname)) return 'continue';
  // Anything else (Firebase, Google, CDNs) is aborted so no test reaches the internet.
  return 'abort';
}

async function guardContext(context: BrowserContext, liveHits: string[]) {
  await context.route('**/*', (route) =>
    guardDecision(route.request().url(), liveHits) === 'continue' ? route.continue() : route.abort('blockedbyclient'),
  );
}

/** A request context that refuses live hosts before sending anything (G1 for API calls). */
function guardRequest(request: APIRequestContext, liveHits: string[]): APIRequestContext {
  return new Proxy(request, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      if (!['get', 'post', 'put', 'patch', 'delete', 'head', 'fetch'].includes(String(prop))) return value;
      return (url: string, options?: object) => {
        const absolute = new URL(String(url), API_URL).href;
        if (guardDecision(absolute, liveHits) === 'abort') {
          throw new Error(`Network guard blocked API request to ${absolute}`);
        }
        return value.call(target, absolute, options);
      };
    },
  });
}

type Fixtures = {
  liveHits: string[];
  seed: SeedIds;
  api: APIRequestContext;
  retailerToken: (username?: string) => Promise<string>;
};

export const test = base.extend<Fixtures>({
  liveHits: async ({}, use) => {
    const hits: string[] = [];
    await use(hits);
    expect(hits, `Request(s) to live ordereasy.win were attempted: ${hits.join(', ')}`).toEqual([]);
  },

  context: async ({ context, liveHits }, use) => {
    await guardContext(context, liveHits);
    // Skip the POS onboarding tour so it never covers the controls.
    await context.addInitScript(() => window.localStorage.setItem('pos_onboarding_done', 'true'));
    await use(context);
  },

  // Fresh dataset before every test; specs never depend on each other's leftovers.
  seed: [
    async ({}, use) => {
      await use(runSeed());
    },
    { auto: true },
  ],

  api: async ({ request, liveHits }, use) => {
    await use(guardRequest(request, liveHits));
  },

  retailerToken: async ({ api }, use) => {
    await use(async (username = 'e2e_retailer') => {
      const response = await api.post('auth/retailer/login/', { data: { username, password: PASSWORD } });
      expect(response.status(), await response.text()).toBe(200);
      const body = await response.json();
      return body.tokens?.access ?? body.access;
    });
  },
});

export { expect };

export const urls = { retailer: RETAILER_URL, customer: CUSTOMER_URL };
