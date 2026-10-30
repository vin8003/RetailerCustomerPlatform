/**
 * Every URL the suite talks to. Defaults are the local e2e stack; CI sets the same values.
 * G3 asserts none of these point at ordereasy.win.
 */
import { SEED } from './seed';
export const API_URL = process.env.E2E_API_URL ?? 'http://127.0.0.1:8100/api/';
export const RETAILER_URL = process.env.E2E_RETAILER_URL ?? 'http://127.0.0.1:4273';
export const CUSTOMER_URL = process.env.E2E_CUSTOMER_URL ?? 'http://127.0.0.1:4276';

/** Shell command that resets the dataset and prints its ids as JSON (see seed_e2e). */
/** Runs `python manage.py` from the RCP root against the e2e database. */
export const MANAGE_CMD = process.env.E2E_MANAGE_CMD ?? 'cd .. && python manage.py';
export const SEED_CMD = `${MANAGE_CMD} seed_e2e`;

export const PASSWORD = process.env.E2E_PASSWORD ?? SEED.password;

export const ALL_URLS = { API_URL, RETAILER_URL, CUSTOMER_URL };
