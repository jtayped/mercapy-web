// the domain enums. the postgres enum types in packages/db mirror these lists
// one to one, and the collector's drift test checks the database side against
// the exported json schema, so a value added here has to land in all three.

export const crawlRunStatuses = ['running', 'success', 'degraded', 'failed'] as const;
export type CrawlRunStatus = (typeof crawlRunStatuses)[number];

export const detailScopes = ['unknown', 'global', 'warehouse'] as const;
export type DetailScope = (typeof detailScopes)[number];

export const postalCodeSources = ['seed', 'geonames', 'visitor', 'manual'] as const;
export type PostalCodeSource = (typeof postalCodeSources)[number];

export const trackedPriceBases = ['unit', 'reference'] as const;
export type TrackedPriceBasis = (typeof trackedPriceBases)[number];

export const productEventTypes = [
  'price_decrease',
  'price_increase',
  'official_reduction',
  'size_change',
  'rename',
  'category_move',
  'detail_change',
  'local_arrival',
  'local_disappearance',
  'restoration',
  'national_arrival',
  'national_discontinuation',
] as const;
export type ProductEventType = (typeof productEventTypes)[number];

// queue order, lowest first: new products, descriptive changes, audits of a
// canonical record in other warehouses, then the monthly sample.
export const detailRequestReasons = [
  'first_seen',
  'summary_change',
  'audit',
  'warehouse_divergence',
  'sample',
] as const;
export type DetailRequestReason = (typeof detailRequestReasons)[number];

export const collectionIssueKinds = ['price_consistency', 'identity_review'] as const;
export type CollectionIssueKind = (typeof collectionIssueKinds)[number];
