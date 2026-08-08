# Vendored hosted-documentation UI assets

These files are the exact upstream distribution assets the controller embeds
at compile time (via `include_str!`) and serves from `/docs` and `/redoc`.
They are not fetched at runtime; there is no controller startup/runtime
network dependency on either upstream origin. `docs/openapi.json` remains the
only API specification source and is unaffected by this directory.

Do not edit these files by hand. To upgrade a package, replace the file with
the exact unmodified upstream distribution output for the new pinned
version, update the version number in this manifest and in
`crates/controller-api/src/http/docs_ui.rs`, and update the SHA-256 digest
pinned in `tests/test_hosted_docs_contract.py`.

## swagger-ui-dist 5.32.11 (Apache License 2.0)

Source: `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/`

| File | SHA-256 |
| --- | --- |
| `swagger-ui/5.32.11/swagger-ui.css` | `ca238f7d7c2cf4480c1e77a9c3b9da915ab216e96ffd354e69076560c650c6de` |
| `swagger-ui/5.32.11/swagger-ui-bundle.js` | `fcb81e2c79e7e3b76ddb9bd7fc791552045040fde05c19d3f98f9213e7f7724d` |
| `swagger-ui/5.32.11/swagger-ui-standalone-preset.js` | `ea327dbf3a0a047290f6b9cf4e4b86a63bb8534b43d416c6c07ee8d14269d9ff` |

License notice: `swagger-ui/5.32.11/LICENSE` (verbatim upstream Apache-2.0 text).

## redoc 2.5.3 (MIT)

Source: `https://cdn.redoc.ly/redoc/v2.5.3/bundles/redoc.standalone.js`

| File | SHA-256 |
| --- | --- |
| `redoc/2.5.3/redoc.standalone.js` | `1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0` |

License notice: `redoc/2.5.3/LICENSE` (verbatim upstream MIT text).

## Known non-functional gap after local hosting

`redoc.standalone.js` conditionally renders a small "powered by Redocly"
badge by fetching `https://cdn.redoc.ly/redoc/logo-mini.svg` at runtime. The
controller's tightened CSP (`img-src data:`, no external origins) blocks that
request; ReDoc's own `onError` handler hides the badge when the image fails
to load, so this is a silent, non-breaking cosmetic omission, not an error
surfaced to the operator. No other functional or script dependency on either
upstream origin remains.
