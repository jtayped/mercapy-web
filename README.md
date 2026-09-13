# mercapy web

an unofficial history of mercadona's online warehouse catalogs, in catalan.
it separates local prices from national summaries, tells mercadona's own
reduction markers apart from price changes we observed ourselves, and records
only what changed instead of copying an unchanged catalog every day.

the product, architecture, collection and policy decisions are kept in private
design notes. they put the collector first, because history is the one part that
cannot be recovered later. that is what exists so far.

## layout

| path                   | contents                                                            |
| ---------------------- | ------------------------------------------------------------------- |
| `apps/collector`       | python 3.12. reads catalogs with `mercapy`, writes explicit sql     |
| `packages/db`          | drizzle schema and generated migrations, the only source of the ddl |
| `packages/contract`    | zod schemas for the json columns and enums, exported to json schema |
| `packages/config`      | shared tsconfig, eslint and prettier bases                          |
| `scripts`              | file-length gate, dev database init                                 |
| `compose.dev.yaml`     | postgres 18 on port 5435 with a `mercapy_test` database             |
| `compose.yaml`         | production: db, migrate, collector                                  |
| `Dockerfile.collector` | the collector image; `supercronic` runs `apps/collector/crontab`    |
| `.github`              | ci, the ghcr release of the collector image, issue templates        |

`apps/web` (next.js) arrives once there is history to show.

## the boundary

the collector is the only writer and applies migrations itself
(`collector migrate`, journal-compatible with drizzle's). `packages/db` owns
the schema; the collector's drift test compares the columns it writes with the
migrated database, and the postgres enums with the contract. the json the
collector writes is validated in its tests against `packages/contract/schema`.

## working on it

```sh
pnpm install
uv --project apps/collector sync --all-groups
cp .env.example .env
pnpm db:up                   # postgres 18 on 5435, creates mercapy_test too
pnpm collector migrate
pnpm collector collect --warehouse bcn1
pnpm collector details --limit 20

pnpm lint                    # eslint, file-length gate, ruff, mypy
pnpm typecheck
pnpm test                    # vitest, then pytest against mercapy_test
pnpm db:generate             # after editing packages/db/src/schema.ts
pnpm contract:schema         # after editing packages/contract/src
```

files warn past 500 lines and fail past 1000, in every language.

## policy

this project is not affiliated with mercadona, and it will never carry ads,
affiliate links or paid features. the collector identifies itself with a
contact address, keeps half a second between requests, respects `Retry-After`,
and stops if blocked.

to report a vulnerability, see [`SECURITY.md`](SECURITY.md). to contribute, see
[`CONTRIBUTING.md`](CONTRIBUTING.md); everything lands through a pull request.
