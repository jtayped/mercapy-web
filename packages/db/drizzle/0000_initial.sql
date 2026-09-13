CREATE TYPE "public"."collection_issue_kind" AS ENUM('price_consistency', 'identity_review');--> statement-breakpoint
CREATE TYPE "public"."crawl_run_status" AS ENUM('running', 'success', 'degraded', 'failed');--> statement-breakpoint
CREATE TYPE "public"."detail_request_reason" AS ENUM('first_seen', 'summary_change', 'audit', 'warehouse_divergence', 'sample');--> statement-breakpoint
CREATE TYPE "public"."detail_scope" AS ENUM('unknown', 'global', 'warehouse');--> statement-breakpoint
CREATE TYPE "public"."postal_code_source" AS ENUM('seed', 'geonames', 'visitor', 'manual');--> statement-breakpoint
CREATE TYPE "public"."product_event_type" AS ENUM('price_decrease', 'price_increase', 'official_reduction', 'size_change', 'rename', 'category_move', 'detail_change', 'local_arrival', 'local_disappearance', 'restoration', 'national_arrival', 'national_discontinuation');--> statement-breakpoint
CREATE TYPE "public"."tracked_price_basis" AS ENUM('unit', 'reference');--> statement-breakpoint
CREATE TABLE "category" (
	"id" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"level" smallint,
	"parent_id" text
);
--> statement-breakpoint
CREATE TABLE "collection_issue" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"kind" "collection_issue_kind" NOT NULL,
	"product_id" text,
	"warehouse_code" text,
	"crawl_run_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"data" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"resolved_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "crawl_run" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"warehouse_code" text NOT NULL,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"finished_at" timestamp with time zone,
	"status" "crawl_run_status" DEFAULT 'running' NOT NULL,
	"language" text DEFAULT 'ca' NOT NULL,
	"observed_on" date,
	"reported_count" integer,
	"collected_count" integer,
	"partition_count" integer,
	"error" text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "detail_request" (
	"product_id" text NOT NULL,
	"warehouse_code" text NOT NULL,
	"reason" "detail_request_reason" NOT NULL,
	"priority" smallint NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"attempts" smallint DEFAULT 0 NOT NULL,
	"last_error" text DEFAULT '' NOT NULL,
	"not_before" timestamp with time zone,
	CONSTRAINT "detail_request_product_id_warehouse_code_pk" PRIMARY KEY("product_id","warehouse_code")
);
--> statement-breakpoint
CREATE TABLE "postal_code" (
	"postal_code" text PRIMARY KEY NOT NULL,
	"warehouse_code" text,
	"source" "postal_code_source" DEFAULT 'manual' NOT NULL,
	"resolved_at" timestamp with time zone,
	"last_checked_at" timestamp with time zone,
	"last_error" text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "product" (
	"id" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"name_es" text,
	"brand" text DEFAULT '' NOT NULL,
	"ean" text DEFAULT '' NOT NULL,
	"slug" text DEFAULT '' NOT NULL,
	"thumbnail_file" text DEFAULT '' NOT NULL,
	"first_seen_at" timestamp with time zone NOT NULL,
	"last_seen_any_at" timestamp with time zone NOT NULL,
	"nationally_discontinued_at" timestamp with time zone,
	"detail_scope" "detail_scope" DEFAULT 'unknown' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "product_category" (
	"product_id" text NOT NULL,
	"warehouse_code" text NOT NULL,
	"category_id" text NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"first_seen_at" timestamp with time zone NOT NULL,
	"last_seen_at" timestamp with time zone NOT NULL,
	CONSTRAINT "product_category_product_id_warehouse_code_category_id_pk" PRIMARY KEY("product_id","warehouse_code","category_id")
);
--> statement-breakpoint
CREATE TABLE "product_detail_version" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"product_id" text NOT NULL,
	"warehouse_code" text,
	"valid_from" timestamp with time zone NOT NULL,
	"valid_to" timestamp with time zone,
	"fingerprint" text NOT NULL,
	"data" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "product_event" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"product_id" text NOT NULL,
	"warehouse_code" text,
	"crawl_run_id" uuid,
	"type" "product_event_type" NOT NULL,
	"observed_on" date NOT NULL,
	"occurred_at" timestamp with time zone NOT NULL,
	"old_value" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"new_value" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"amount_delta" numeric(12, 4),
	"percent_delta" numeric(9, 4),
	"visible" boolean DEFAULT true NOT NULL
);
--> statement-breakpoint
CREATE TABLE "product_state" (
	"product_id" text NOT NULL,
	"warehouse_code" text NOT NULL,
	"version_id" bigint NOT NULL,
	"baseline_version_id" bigint,
	"fingerprint" text NOT NULL,
	"name" text NOT NULL,
	"brand" text DEFAULT '' NOT NULL,
	"category_ids" text[] DEFAULT '{}' NOT NULL,
	"unit_price" numeric(12, 4),
	"previous_price" numeric(12, 4),
	"bulk_price" numeric(14, 4),
	"reference_price" numeric(14, 4),
	"tracked_price" numeric(14, 4),
	"tracked_price_basis" "tracked_price_basis" DEFAULT 'unit' NOT NULL,
	"unit_size" numeric(14, 6),
	"size_format" text DEFAULT '' NOT NULL,
	"reference_format" text DEFAULT '' NOT NULL,
	"approximate_size" boolean DEFAULT false NOT NULL,
	"official_discount" boolean DEFAULT false NOT NULL,
	"published" boolean,
	"first_seen_at" timestamp with time zone NOT NULL,
	"last_seen_at" timestamp with time zone NOT NULL,
	"observed_on" date NOT NULL,
	"absent_days" smallint DEFAULT 0 NOT NULL,
	"last_absent_on" date,
	"available" boolean DEFAULT true NOT NULL,
	"unavailable_since" timestamp with time zone,
	CONSTRAINT "product_state_product_id_warehouse_code_pk" PRIMARY KEY("product_id","warehouse_code")
);
--> statement-breakpoint
CREATE TABLE "product_version" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"product_id" text NOT NULL,
	"warehouse_code" text NOT NULL,
	"crawl_run_id" uuid NOT NULL,
	"valid_from" timestamp with time zone NOT NULL,
	"valid_to" timestamp with time zone,
	"fingerprint" text NOT NULL,
	"data" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "warehouse" (
	"code" text PRIMARY KEY NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"verified" boolean DEFAULT false NOT NULL,
	"baseline_days" integer DEFAULT 0 NOT NULL,
	"last_observed_on" date,
	"first_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_success_at" timestamp with time zone,
	"consecutive_failures" integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
ALTER TABLE "category" ADD CONSTRAINT "category_parent_id_category_id_fk" FOREIGN KEY ("parent_id") REFERENCES "public"."category"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collection_issue" ADD CONSTRAINT "collection_issue_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collection_issue" ADD CONSTRAINT "collection_issue_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collection_issue" ADD CONSTRAINT "collection_issue_crawl_run_id_crawl_run_id_fk" FOREIGN KEY ("crawl_run_id") REFERENCES "public"."crawl_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "crawl_run" ADD CONSTRAINT "crawl_run_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "detail_request" ADD CONSTRAINT "detail_request_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "detail_request" ADD CONSTRAINT "detail_request_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "postal_code" ADD CONSTRAINT "postal_code_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_category" ADD CONSTRAINT "product_category_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_category" ADD CONSTRAINT "product_category_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_category" ADD CONSTRAINT "product_category_category_id_category_id_fk" FOREIGN KEY ("category_id") REFERENCES "public"."category"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_detail_version" ADD CONSTRAINT "product_detail_version_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_detail_version" ADD CONSTRAINT "product_detail_version_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_event" ADD CONSTRAINT "product_event_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_event" ADD CONSTRAINT "product_event_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_event" ADD CONSTRAINT "product_event_crawl_run_id_crawl_run_id_fk" FOREIGN KEY ("crawl_run_id") REFERENCES "public"."crawl_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_state" ADD CONSTRAINT "product_state_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_state" ADD CONSTRAINT "product_state_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_state" ADD CONSTRAINT "product_state_version_id_product_version_id_fk" FOREIGN KEY ("version_id") REFERENCES "public"."product_version"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_state" ADD CONSTRAINT "product_state_baseline_version_id_product_version_id_fk" FOREIGN KEY ("baseline_version_id") REFERENCES "public"."product_version"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_version" ADD CONSTRAINT "product_version_product_id_product_id_fk" FOREIGN KEY ("product_id") REFERENCES "public"."product"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_version" ADD CONSTRAINT "product_version_warehouse_code_warehouse_code_fk" FOREIGN KEY ("warehouse_code") REFERENCES "public"."warehouse"("code") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "product_version" ADD CONSTRAINT "product_version_crawl_run_id_crawl_run_id_fk" FOREIGN KEY ("crawl_run_id") REFERENCES "public"."crawl_run"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "collection_issue_open_idx" ON "collection_issue" USING btree ("kind","resolved_at");--> statement-breakpoint
CREATE INDEX "collection_issue_product_idx" ON "collection_issue" USING btree ("product_id","warehouse_code");--> statement-breakpoint
CREATE INDEX "crawl_run_warehouse_started_idx" ON "crawl_run" USING btree ("warehouse_code","started_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "crawl_run_status_idx" ON "crawl_run" USING btree ("status");--> statement-breakpoint
CREATE INDEX "detail_request_queue_idx" ON "detail_request" USING btree ("priority","created_at");--> statement-breakpoint
CREATE INDEX "postal_code_last_checked_idx" ON "postal_code" USING btree ("last_checked_at");--> statement-breakpoint
CREATE INDEX "product_ean_idx" ON "product" USING btree ("ean");--> statement-breakpoint
CREATE INDEX "product_last_seen_any_idx" ON "product" USING btree ("last_seen_any_at");--> statement-breakpoint
CREATE INDEX "product_discontinued_idx" ON "product" USING btree ("nationally_discontinued_at");--> statement-breakpoint
CREATE INDEX "product_category_category_idx" ON "product_category" USING btree ("category_id","warehouse_code","active");--> statement-breakpoint
CREATE INDEX "product_detail_version_lookup_idx" ON "product_detail_version" USING btree ("product_id","warehouse_code","valid_from" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "product_event_feed_idx" ON "product_event" USING btree ("type","visible","occurred_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "product_event_product_idx" ON "product_event" USING btree ("product_id","occurred_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "product_event_day_idx" ON "product_event" USING btree ("warehouse_code","observed_on");--> statement-breakpoint
CREATE INDEX "product_state_warehouse_available_idx" ON "product_state" USING btree ("warehouse_code","available");--> statement-breakpoint
CREATE INDEX "product_state_discount_idx" ON "product_state" USING btree ("official_discount");--> statement-breakpoint
CREATE INDEX "product_state_tracked_price_idx" ON "product_state" USING btree ("tracked_price");--> statement-breakpoint
CREATE INDEX "product_version_lookup_idx" ON "product_version" USING btree ("product_id","warehouse_code","valid_from" DESC NULLS LAST);--> statement-breakpoint
CREATE UNIQUE INDEX "product_version_open_idx" ON "product_version" USING btree ("product_id","warehouse_code") WHERE "product_version"."valid_to" is null;