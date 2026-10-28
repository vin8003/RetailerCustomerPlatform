import * as fs from 'node:fs';
import * as path from 'node:path';
import { test, expect } from '../fixtures';
import { ALL_URLS } from '../env';
import { guardDecision, LIVE_HOST } from '../fixtures';
import config from '../playwright.config';

test('G1 guard aborts any *.ordereasy.win request and names the URL @G1', async () => {
  const hits: string[] = [];
  for (const url of [
    'https://retailer.ordereasy.win/login',
    'http://api.ordereasy.win/api/x',
    'https://images.ordereasy.win/a.png',
    'https://ordereasy.win/',
  ]) {
    expect(guardDecision(url, hits), url).toBe('abort');
  }
  expect(hits).toHaveLength(4);
  expect(guardDecision('http://127.0.0.1:8100/api/', [])).toBe('continue');
  expect(guardDecision('http://localhost:4273/', [])).toBe('continue');
  // Anything else off-box (e.g. Google/Firebase) is also aborted but is not a live-env hit.
  const other: string[] = [];
  expect(guardDecision('https://apis.google.com/js/platform.js', other)).toBe('abort');
  expect(other).toHaveLength(0);
});

test('G1 page and API contexts record and block .win requests @G1', async ({ page, api, liveHits }) => {
  const pageUrl = 'https://customer.ordereasy.win/';
  const pageError = await page.goto(pageUrl).then(() => null, (e: Error) => e);
  expect(pageError?.message).toContain('ERR_BLOCKED_BY_CLIENT');

  const apiUrl = 'https://api.ordereasy.win/api/health/';
  expect(() => api.get(apiUrl)).toThrow(`Network guard blocked API request to ${apiUrl}`);

  expect(liveHits).toEqual([pageUrl, apiUrl]);
  // Both were recorded, so teardown would fail this test naming them (G2 proves that path).
  // Clear them here so G1 itself reports the guard working.
  liveHits.length = 0;
});

test('G2 guard self-test: a .win request fails the test (expected to fail) @G2', async ({ page }) => {
  test.fail(true, 'Proves the guard fails a run; the request is aborted inside the route handler, never sent.');
  await page.goto('https://retailer.ordereasy.win/').catch(() => undefined);
});

test('G3 config and env point only at local hosts; CI workflow has no .win @G3', async () => {
  const configured = [config.use?.baseURL, ...Object.values(ALL_URLS)].filter(Boolean) as string[];
  for (const url of configured) {
    expect(new URL(url).hostname, url).not.toMatch(LIVE_HOST);
    expect(['127.0.0.1', 'localhost'], url).toContain(new URL(url).hostname);
  }
  for (const name of Object.keys(process.env).filter((k) => /API|URL|ORIGIN/.test(k))) {
    expect(process.env[name] ?? '', name).not.toMatch(/ordereasy\.win/i);
  }
  const workflow = fs.readFileSync(path.join(__dirname, '../../.github/workflows/e2e.yml'), 'utf8');
  expect(workflow).not.toMatch(/\.win/i);
});
