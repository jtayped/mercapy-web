import {
  collectionIssueKinds,
  crawlRunStatuses,
  detailRequestReasons,
  detailScopes,
  postalCodeSources,
  productEventTypes,
  trackedPriceBases,
  type DetailData,
  type EventValue,
  type SummaryData,
} from '@mercapy/contract';
import { sql } from 'drizzle-orm';
import {
  bigint,
  bigserial,
  boolean,
  date,
  index,
  integer,
  jsonb,
  numeric,
  pgEnum,
  pgTable,
  primaryKey,
  smallint,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  type AnyPgColumn,
} from 'drizzle-orm/pg-core';

// every instant is timestamptz in utc. `observed_on` columns are the calendar
// day in Europe/Madrid, computed by the collector at write time, because the
// public series and the event rules count days, not runs (PRODUCT.md).
const instant = (name: string) => timestamp(name, { withTimezone: true, mode: 'string' });
const money = (name: string) => numeric(name, { precision: 12, scale: 4 });
const perUnit = (name: string) => numeric(name, { precision: 14, scale: 4 });

export const crawlRunStatus = pgEnum('crawl_run_status', crawlRunStatuses);
export const detailScope = pgEnum('detail_scope', detailScopes);
export const postalCodeSource = pgEnum('postal_code_source', postalCodeSources);
export const trackedPriceBasis = pgEnum('tracked_price_basis', trackedPriceBases);
export const productEventType = pgEnum('product_event_type', productEventTypes);
export const detailRequestReason = pgEnum('detail_request_reason', detailRequestReasons);
export const collectionIssueKind = pgEnum('collection_issue_kind', collectionIssueKinds);

export const warehouse = pgTable('warehouse', {
  code: text('code').primaryKey(),
  active: boolean('active').notNull().default(true),
  // verified: at least one complete collection. baseline_days: distinct
  // observation days with a complete collection; arrivals wait for two.
  verified: boolean('verified').notNull().default(false),
  baselineDays: integer('baseline_days').notNull().default(0),
  lastObservedOn: date('last_observed_on'),
  firstSeenAt: instant('first_seen_at').notNull().defaultNow(),
  lastSuccessAt: instant('last_success_at'),
  consecutiveFailures: integer('consecutive_failures').notNull().default(0),
});

export const postalCode = pgTable(
  'postal_code',
  {
    postalCode: text('postal_code').primaryKey(),
    warehouseCode: text('warehouse_code').references(() => warehouse.code, {
      onDelete: 'set null',
    }),
    source: postalCodeSource('source').notNull().default('manual'),
    resolvedAt: instant('resolved_at'),
    lastCheckedAt: instant('last_checked_at'),
    lastError: text('last_error').notNull().default(''),
  },
  (table) => [index('postal_code_last_checked_idx').on(table.lastCheckedAt)],
);

export const product = pgTable(
  'product',
  {
    // the full upstream identifier including the decimal suffix. 11632.1 and
    // 11632.2 are siblings, never merged (PRODUCT.md).
    id: text('id').primaryKey(),
    name: text('name').notNull(),
    nameEs: text('name_es'),
    brand: text('brand').notNull().default(''),
    ean: text('ean').notNull().default(''),
    slug: text('slug').notNull().default(''),
    thumbnailFile: text('thumbnail_file').notNull().default(''),
    firstSeenAt: instant('first_seen_at').notNull(),
    lastSeenAnyAt: instant('last_seen_any_at').notNull(),
    nationallyDiscontinuedAt: instant('nationally_discontinued_at'),
    detailScope: detailScope('detail_scope').notNull().default('unknown'),
    // warehouses whose record matched the global one. COLLECTION.md schedules
    // two; once reached, further first-seen requests for the product are
    // dropped without a fetch so the daily budget reaches new products.
    detailAudits: smallint('detail_audits').notNull().default(0),
  },
  (table) => [
    index('product_ean_idx').on(table.ean),
    index('product_last_seen_any_idx').on(table.lastSeenAnyAt),
    index('product_discontinued_idx').on(table.nationallyDiscontinuedAt),
  ],
);

export const category = pgTable('category', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  level: smallint('level'),
  parentId: text('parent_id').references((): AnyPgColumn => category.id, {
    onDelete: 'set null',
  }),
});

export const crawlRun = pgTable(
  'crawl_run',
  {
    id: uuid('id')
      .primaryKey()
      .default(sql`gen_random_uuid()`),
    warehouseCode: text('warehouse_code')
      .notNull()
      .references(() => warehouse.code),
    startedAt: instant('started_at').notNull().defaultNow(),
    finishedAt: instant('finished_at'),
    status: crawlRunStatus('status').notNull().default('running'),
    language: text('language').notNull().default('ca'),
    observedOn: date('observed_on'),
    reportedCount: integer('reported_count'),
    collectedCount: integer('collected_count'),
    partitionCount: integer('partition_count'),
    error: text('error').notNull().default(''),
  },
  (table) => [
    index('crawl_run_warehouse_started_idx').on(table.warehouseCode, table.startedAt.desc()),
    index('crawl_run_status_idx').on(table.status),
  ],
);

export const productVersion = pgTable(
  'product_version',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    warehouseCode: text('warehouse_code')
      .notNull()
      .references(() => warehouse.code, { onDelete: 'cascade' }),
    crawlRunId: uuid('crawl_run_id')
      .notNull()
      .references(() => crawlRun.id),
    validFrom: instant('valid_from').notNull(),
    validTo: instant('valid_to'),
    fingerprint: text('fingerprint').notNull(),
    data: jsonb('data').$type<SummaryData>().notNull(),
  },
  (table) => [
    index('product_version_lookup_idx').on(
      table.productId,
      table.warehouseCode,
      table.validFrom.desc(),
    ),
    uniqueIndex('product_version_open_idx')
      .on(table.productId, table.warehouseCode)
      .where(sql`${table.validTo} is null`),
  ],
);

export const productState = pgTable(
  'product_state',
  {
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    warehouseCode: text('warehouse_code')
      .notNull()
      .references(() => warehouse.code, { onDelete: 'cascade' }),
    // the open version holds the full json; the state only points at it.
    // baseline_version is the version current at the end of the previous
    // observation day, which is what today's events are derived against.
    versionId: bigint('version_id', { mode: 'number' })
      .notNull()
      .references(() => productVersion.id),
    baselineVersionId: bigint('baseline_version_id', { mode: 'number' }).references(
      () => productVersion.id,
    ),
    fingerprint: text('fingerprint').notNull(),
    name: text('name').notNull(),
    brand: text('brand').notNull().default(''),
    categoryIds: text('category_ids').array().notNull().default([]),
    unitPrice: money('unit_price'),
    previousPrice: money('previous_price'),
    bulkPrice: perUnit('bulk_price'),
    referencePrice: perUnit('reference_price'),
    trackedPrice: perUnit('tracked_price'),
    trackedPriceBasis: trackedPriceBasis('tracked_price_basis').notNull().default('unit'),
    unitSize: numeric('unit_size', { precision: 14, scale: 6 }),
    sizeFormat: text('size_format').notNull().default(''),
    referenceFormat: text('reference_format').notNull().default(''),
    approximateSize: boolean('approximate_size').notNull().default(false),
    officialDiscount: boolean('official_discount').notNull().default(false),
    published: boolean('published'),
    firstSeenAt: instant('first_seen_at').notNull(),
    lastSeenAt: instant('last_seen_at').notNull(),
    observedOn: date('observed_on').notNull(),
    absentDays: smallint('absent_days').notNull().default(0),
    lastAbsentOn: date('last_absent_on'),
    available: boolean('available').notNull().default(true),
    unavailableSince: instant('unavailable_since'),
  },
  (table) => [
    primaryKey({ columns: [table.productId, table.warehouseCode] }),
    index('product_state_warehouse_available_idx').on(table.warehouseCode, table.available),
    index('product_state_discount_idx').on(table.officialDiscount),
    index('product_state_tracked_price_idx').on(table.trackedPrice),
  ],
);

export const productCategory = pgTable(
  'product_category',
  {
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    warehouseCode: text('warehouse_code')
      .notNull()
      .references(() => warehouse.code, { onDelete: 'cascade' }),
    categoryId: text('category_id')
      .notNull()
      .references(() => category.id, { onDelete: 'cascade' }),
    active: boolean('active').notNull().default(true),
    firstSeenAt: instant('first_seen_at').notNull(),
    lastSeenAt: instant('last_seen_at').notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.productId, table.warehouseCode, table.categoryId] }),
    index('product_category_category_idx').on(table.categoryId, table.warehouseCode, table.active),
  ],
);

export const productDetailVersion = pgTable(
  'product_detail_version',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    // null while the record is global; set once warehouses diverge.
    warehouseCode: text('warehouse_code').references(() => warehouse.code, {
      onDelete: 'cascade',
    }),
    validFrom: instant('valid_from').notNull(),
    validTo: instant('valid_to'),
    fingerprint: text('fingerprint').notNull(),
    data: jsonb('data').$type<DetailData>().notNull(),
  },
  (table) => [
    index('product_detail_version_lookup_idx').on(
      table.productId,
      table.warehouseCode,
      table.validFrom.desc(),
    ),
  ],
);

export const productEvent = pgTable(
  'product_event',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    // null for national events.
    warehouseCode: text('warehouse_code').references(() => warehouse.code, {
      onDelete: 'cascade',
    }),
    crawlRunId: uuid('crawl_run_id').references(() => crawlRun.id, { onDelete: 'set null' }),
    type: productEventType('type').notNull(),
    observedOn: date('observed_on').notNull(),
    occurredAt: instant('occurred_at').notNull(),
    oldValue: jsonb('old_value').$type<EventValue>().notNull().default({}),
    newValue: jsonb('new_value').$type<EventValue>().notNull().default({}),
    amountDelta: money('amount_delta'),
    percentDelta: numeric('percent_delta', { precision: 9, scale: 4 }),
    visible: boolean('visible').notNull().default(true),
  },
  (table) => [
    index('product_event_feed_idx').on(table.type, table.visible, table.occurredAt.desc()),
    index('product_event_product_idx').on(table.productId, table.occurredAt.desc()),
    index('product_event_day_idx').on(table.warehouseCode, table.observedOn),
  ],
);

export const detailRequest = pgTable(
  'detail_request',
  {
    productId: text('product_id')
      .notNull()
      .references(() => product.id, { onDelete: 'cascade' }),
    warehouseCode: text('warehouse_code')
      .notNull()
      .references(() => warehouse.code, { onDelete: 'cascade' }),
    reason: detailRequestReason('reason').notNull(),
    priority: smallint('priority').notNull(),
    createdAt: instant('created_at').notNull().defaultNow(),
    attempts: smallint('attempts').notNull().default(0),
    lastError: text('last_error').notNull().default(''),
    notBefore: instant('not_before'),
  },
  (table) => [
    primaryKey({ columns: [table.productId, table.warehouseCode] }),
    index('detail_request_queue_idx').on(table.priority, table.createdAt),
  ],
);

export const collectionIssue = pgTable(
  'collection_issue',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    kind: collectionIssueKind('kind').notNull(),
    productId: text('product_id').references(() => product.id, { onDelete: 'cascade' }),
    warehouseCode: text('warehouse_code').references(() => warehouse.code, {
      onDelete: 'cascade',
    }),
    crawlRunId: uuid('crawl_run_id').references(() => crawlRun.id, { onDelete: 'set null' }),
    createdAt: instant('created_at').notNull().defaultNow(),
    data: jsonb('data').$type<Record<string, unknown>>().notNull().default({}),
    resolvedAt: instant('resolved_at'),
  },
  (table) => [
    index('collection_issue_open_idx').on(table.kind, table.resolvedAt),
    index('collection_issue_product_idx').on(table.productId, table.warehouseCode),
  ],
);
