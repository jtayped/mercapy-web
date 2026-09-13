// writes packages/contract/schema/*.json. the collector's tests validate the
// json it produces against these files, which is the whole python/typescript
// boundary: no code generation, one committed artefact per json column.
import { mkdirSync, writeFileSync } from 'node:fs';
import { z } from 'zod';
import * as enums from './enums.ts';
import { detailData, eventValue, priceConsistencyIssue, summaryData } from './json.ts';

const schemas = {
  'summary-data': summaryData,
  'detail-data': detailData,
  'event-value': eventValue,
  'price-consistency-issue': priceConsistencyIssue,
  enums: z.object({
    crawl_run_status: z.enum(enums.crawlRunStatuses),
    detail_scope: z.enum(enums.detailScopes),
    postal_code_source: z.enum(enums.postalCodeSources),
    tracked_price_basis: z.enum(enums.trackedPriceBases),
    product_event_type: z.enum(enums.productEventTypes),
    detail_request_reason: z.enum(enums.detailRequestReasons),
    collection_issue_kind: z.enum(enums.collectionIssueKinds),
  }),
};

const out = new URL('../schema/', import.meta.url);
mkdirSync(out, { recursive: true });
for (const [name, schema] of Object.entries(schemas)) {
  const json = z.toJSONSchema(schema, { target: 'draft-2020-12' });
  writeFileSync(new URL(`${name}.json`, out), `${JSON.stringify(json, null, 2)}\n`);
}
