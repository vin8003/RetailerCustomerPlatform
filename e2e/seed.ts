/** The e2e dataset, read from the same seed-data.json that seed_e2e.py loads. */
import data from './seed-data.json';

export const SEED = data;

/** 10-digit mobile as typed into the apps (+91 dropped). */
export const mobile = (phone: string) => phone.replace(/^\+91/, '');

export const R1 = data.retailers.R1;
export const R2 = data.retailers.R2;
export const C1_MOBILE = mobile(data.customers.C1.phone);
export const C2_MOBILE = mobile(data.customers.C2.phone);
export const PRODUCT = data.products;
