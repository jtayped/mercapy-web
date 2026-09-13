# contributing

## how work lands

short branches off `main`, merged only through a pull request. nobody pushes to
`main` directly, including the maintainer. pull requests are squash merged, so
the pull request title becomes the commit subject.

commit subjects are lowercase conventional commits with a scope:

```
feat(collector): defer details for products seen in more than one warehouse
fix(db): make the crawl_run unique index partial
docs(readme): drop the dead link
```

types in use: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`.

## setup

```sh
pnpm install
uv --project apps/collector sync --all-groups
cp .env.example .env
pnpm exec lefthook install    # pre-commit checks, pre-push lint/typecheck/test
pnpm db:up                    # postgres 18 on 5435, creates mercapy_test too
```

## before you open a pull request

```sh
pnpm lint                     # eslint, file-length gate, ruff, mypy
pnpm typecheck
pnpm test                     # vitest, then pytest against mercapy_test
pnpm format                   # prettier and ruff format
```

ci runs the same four, plus a check that the committed json schema and the
committed migration are what the sources generate.

files warn past 500 lines and fail past 1000, in every language. a file that
long is a sign the module does two things.

comments explain why, not what.

## the two generated trees

they are committed, and ci fails if they drift from their sources.

- schema changes go through `packages/db/src/schema.ts`, then `pnpm db:generate`.
  never hand-write a file in `packages/db/drizzle`.
- contract changes go through `packages/contract/src`, then `pnpm contract:schema`.

## the boundary

the collector is the only writer to the database, and it applies the migrations
itself. anything that needs new data writes it there, not from another process.
