/**
 * Slice scan / delivery fee / bundles: data, ids and helpers.
 * Data comes from seed/scan_fee_bundles.json (seeded by seed_e2e via seed_e2e_sfb.py).
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { type APIRequestContext } from '@playwright/test';
import data from './seed/scan_fee_bundles.json';
import { expect } from './fixtures';
import { authed, getJson } from './helpers';
import { mobile } from './seed';

export const SFB = data;
export const SFB_RETAILER = data.retailer;
export const SFB_CUSTOMER_MOBILE = mobile(data.customer.phone);
export const SFB_PRODUCT = data.products;
export const SFB_ADDRESS = data.addresses;

export type SfbIds = {
  retailer: number;
  customer: number;
  addresses: Record<keyof typeof data.addresses, number>;
  products: Record<keyof typeof data.products, number>;
};

/** The SFB ids out of the seed_e2e JSON (the `seed` fixture keeps unknown keys). */
export function sfbIds(seed: unknown): SfbIds {
  const ids = (seed as { sfb?: SfbIds }).sfb;
  if (!ids) throw new Error('seed_e2e printed no "sfb" ids; is seed_e2e_sfb hooked into seed_e2e?');
  return ids;
}

export async function stock(api: APIRequestContext, token: string, productId: number): Promise<number> {
  return Number((await getJson(api, `products/${productId}/`, token)).quantity);
}

export async function sfbRetailerToken(api: APIRequestContext, password: string): Promise<string> {
  const response = await api.post('auth/retailer/login/', { data: { username: SFB_RETAILER.username, password } });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  return body.tokens?.access ?? body.access;
}

export async function setCart(api: APIRequestContext, token: string, items: [number, number][]) {
  for (const [product_id, quantity] of items) {
    const response = await api.post('cart/add/', { ...authed(token), data: { product_id, quantity } });
    expect(response.status(), await response.text()).toBe(201);
  }
}

// ---------------------------------------------------------------------------
// EAN-13 barcode as a Y4M clip for Chromium's fake camera
// (--use-file-for-fake-video-capture). Generated on the fly: no binary in git.
// ---------------------------------------------------------------------------

const L = ['0001101', '0011001', '0010011', '0111101', '0100011', '0110001', '0101111', '0111011', '0110111', '0001011'];
const G = ['0100111', '0110011', '0011011', '0100001', '0011101', '0111001', '0000101', '0010001', '0001001', '0010111'];
const R = ['1110010', '1100110', '1101100', '1000010', '1011100', '1001110', '1010000', '1000100', '1001000', '1110100'];
const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];

export function ean13Modules(code: string): string {
  if (!/^\d{13}$/.test(code)) throw new Error(`not an EAN-13: ${code}`);
  const d = [...code].map(Number);
  const sum = d.slice(0, 12).reduce((s, n, i) => s + n * (i % 2 ? 3 : 1), 0);
  if ((10 - (sum % 10)) % 10 !== d[12]) throw new Error(`bad EAN-13 check digit: ${code}`);
  let bits = '101';
  for (let i = 1; i <= 6; i++) bits += (PARITY[d[0]][i - 1] === 'L' ? L : G)[d[i]];
  bits += '01010';
  for (let i = 7; i <= 12; i++) bits += R[d[i]];
  return bits + '101';
}

/** Write a looping 640x480 Y4M of `code` (black bars on white) and return its path. */
export function writeBarcodeY4m(code: string, path: string, frames = 10): string {
  // Narrow modules: the viewfinder crops the 640px frame (object-fit cover), so the code must fit the scan box with a quiet zone.
  const width = 640, height = 480, module = 4;
  const bits = ean13Modules(code);
  const left = Math.floor((width - bits.length * module) / 2);
  // Bars run the full frame height: on a tall phone the scan box sits below the middle of the picture
  // (https://vin8003.atlassian.net/browse/OE-387).
  const top = 0, bottom = height;
  const y = Buffer.alloc(width * height, 235);
  for (let row = top; row < bottom; row++) {
    for (let i = 0; i < bits.length; i++) {
      if (bits[i] === '1') y.fill(16, row * width + left + i * module, row * width + left + (i + 1) * module);
    }
  }
  const chroma = Buffer.alloc((width / 2) * (height / 2) * 2, 128);
  const header = Buffer.from(`YUV4MPEG2 W${width} H${height} F10:1 Ip A1:1 C420jpeg\n`);
  const frame = Buffer.concat([Buffer.from('FRAME\n'), y, chroma]);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, Buffer.concat([header, ...Array(frames).fill(frame)]));
  return path;
}
