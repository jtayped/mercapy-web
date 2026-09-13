import { z } from 'zod';
import { detailScopes, trackedPriceBases } from './enums.ts';

// decimals travel as strings so neither side rounds them. the collector writes
// `str(Decimal)`, the web feeds them to Intl.NumberFormat or numeric columns.
export const decimalString = z.string().regex(/^-?\d+(\.\d+)?$/);

export const summaryPrice = z
  .object({
    unit: decimalString.nullable(),
    previous: decimalString.nullable(),
    bulk: decimalString.nullable(),
    reference: decimalString.nullable(),
    tax_percentage: decimalString.nullable(),
    unit_size: decimalString.nullable(),
    pack_size: decimalString.nullable(),
    total_units: decimalString.nullable(),
    drained_weight: decimalString.nullable(),
    minimum_amount: decimalString.nullable(),
    increment_amount: decimalString.nullable(),
    unit_name: z.string().nullable(),
    size_format: z.string().nullable(),
    reference_format: z.string().nullable(),
    is_discounted: z.boolean(),
    is_new: z.boolean(),
    is_pack: z.boolean(),
    approximate_size: z.boolean(),
  })
  .strict();

export const summaryCategory = z
  .object({
    id: z.string(),
    name: z.string(),
    level: z.number().int().nullable(),
    parent_id: z.string().nullable(),
    order: z.number().int().nullable(),
    layout: z.number().int().nullable(),
    published: z.boolean().nullable(),
    is_extended: z.boolean().nullable(),
    image_url: z.string().nullable(),
    subtitle: z.string().nullable(),
  })
  .strict();

// what a product_version stores: the whole catalog summary, so nothing has to
// be collected twice. the fingerprint that opens a version covers a subset:
// share urls, purchase amounts, the next unavailability, and category artwork
// and ordering change without meaning anything and are kept but not compared.
// the subset is defined in one place, apps/collector/src/collector/payloads.py.
export const summaryData = z
  .object({
    id: z.string(),
    name: z.string(),
    slug: z.string().nullable(),
    brand: z.string().nullable(),
    packaging: z.string().nullable(),
    main_feature: z.string().nullable(),
    share_url: z.string().nullable(),
    thumbnail: z.string().nullable(),
    price: summaryPrice,
    published: z.boolean().nullable(),
    status: z.string().nullable(),
    availability_limit: decimalString.nullable(),
    unavailable_from: z.string().nullable(),
    unavailable_weekdays: z.array(z.number().int()),
    categories: z.array(summaryCategory),
    requires_age_check: z.boolean(),
    is_water: z.boolean(),
    is_new_arrival: z.boolean(),
  })
  .strict();
export type SummaryData = z.infer<typeof summaryData>;

// what a product_detail_version stores. POLICY.md: facts only. the marketing
// description is deliberately absent; ingredients and allergens are kept.
export const detailData = z
  .object({
    id: z.string(),
    name: z.string(),
    ean: z.string().nullable(),
    slug: z.string().nullable(),
    brand: z.string().nullable(),
    packaging: z.string().nullable(),
    main_feature: z.string().nullable(),
    photos: z.array(z.string()),
    legal_name: z.string().nullable(),
    origin: z.string().nullable(),
    suppliers: z.array(z.string()),
    counter_info: z.string().nullable(),
    danger_mentions: z.string().nullable(),
    mandatory_mentions: z.string().nullable(),
    production_variant: z.string().nullable(),
    usage_instructions: z.string().nullable(),
    storage_instructions: z.string().nullable(),
    alcohol_by_volume: decimalString.nullable(),
    prepared_by_mercadona: z.boolean().nullable(),
    allergens: z.string().nullable(),
    ingredients: z.string().nullable(),
    is_bulk: z.boolean(),
    is_variable_weight: z.boolean(),
    requires_age_check: z.boolean(),
  })
  .strict();
export type DetailData = z.infer<typeof detailData>;

// old_value / new_value on product_event. every key is optional because each
// event type fills only the keys it is about; the pair is always the same shape.
export const eventValue = z
  .object({
    tracked_price: decimalString.nullable().optional(),
    tracked_price_basis: z.enum(trackedPriceBases).optional(),
    unit_price: decimalString.nullable().optional(),
    bulk_price: decimalString.nullable().optional(),
    unit_size: decimalString.nullable().optional(),
    size_format: z.string().nullable().optional(),
    official_discount: z.boolean().optional(),
    name: z.string().optional(),
    category_ids: z.array(z.string()).optional(),
    detail_scope: z.enum(detailScopes).optional(),
    detail: detailData.optional(),
  })
  .strict();
export type EventValue = z.infer<typeof eventValue>;

export const priceConsistencyIssue = z
  .object({
    unit_price: decimalString,
    bulk_price: decimalString.nullable(),
    reference_price: decimalString.nullable(),
    unit_size: decimalString,
    drained_weight: decimalString.nullable(),
    total_units: decimalString.nullable(),
    size_format: z.string(),
    reference_format: z.string(),
    expected: decimalString,
  })
  .strict();
export type PriceConsistencyIssue = z.infer<typeof priceConsistencyIssue>;
