# Real DataHub bug, found while validating Majestic live

> Draft issue for `datahub-project/datahub`, ready to copy/paste or adapt.
> **Not filed yet** — filing it is an action visible on a third party's
> public repository, so it's left to whoever files it (needs their own
> GitHub account / `gh auth login`, not available in this environment).
> See `AUDIT_REPORT.md`, Section 3, Idea 1.

## Suggested title

`Entity page/search crashes with "IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN" when a structured property STRING value contains a URN-shaped substring`

## Version

`v1.7.0` (`acryldata/datahub-gms:v1.7.0`, `acryldata/datahub-frontend-react:v1.7.0`, via `datahub docker quickstart`).

## Summary

The GraphQL resolver that builds `valueEntities` for structured properties
tries to interpret *any* `STRING`-type value that contains a substring
shaped like a DataHub URN (`urn:li:...(...)`) as a reference to another
entity — not only values that are *entirely* a URN. When it tries to parse
a substring that isn't a valid, complete URN, the parser throws
`IllegalArgumentException: No enum constant
com.linkedin.common.FabricType.$UNKNOWN` instead of treating the value as
free text. That exception isn't handled gracefully: it crashes the entire
entity page, and any search/listing that includes it, with a generic
"Something went wrong" in the UI.

## How to reproduce it

1. Define a `STRING`-type structured property on any entity (dataset,
   dashboard, etc.) — any definition works, nothing special needed in the
   YAML.
2. Assign it a free-text value that **contains**, as a substring, something
   shaped like a DataHub URN — for example, a sentence embedding another
   entity's URN:

   ```
   "urn:li:dataset:(urn:li:dataPlatform:hive,marketing_etl,PROD) (hop 1): stale for 30.0h"
   ```

   (This is literally the kind of value a tool-generated explanatory text —
   not just a "bare" URN — produces naturally: the sentence is valid as
   text, but has a complete URN embedded inside it.)
3. Emit that structured property on the entity (via the Python SDK,
   `DatasetPatchBuilder.add_structured_property` + `emit_mcps`, or
   equivalent).
4. Open that entity's page in the UI, or list it in a search that includes
   that property.

**Expected result:** the property is shown as free text.

**Actual result:** the page throws "Something went wrong"; the GMS log
shows `IllegalArgumentException: No enum constant
com.linkedin.common.FabricType.$UNKNOWN` in the resolver that builds
`valueEntities` from the value.

## Impact

Any product/integration that writes dynamically generated free text
(explanations, summaries, logs) as a `STRING`-type structured property,
where that text mentions another entity's URN as part of the sentence (a
common pattern: "the cause is in `<urn>`"), can break the DataHub UI
without realizing it — the bug is on DataHub's side, not the property
writer's, but the trigger is easy to produce by accident.

## Workaround applied (on the emitter side, doesn't fix the root cause)

Insert a zero-width space (`​`) inside the `urn:li:` substring before
persisting the value — invisible when read, but breaks the UI/resolver's
URN detection. See `src/memory/writer.py::_sanitize_urn_lookalikes` in
this repo (`majestic`) for the exact implementation. Confirmed before/after
against the real GMS API: with the zero-width space, the same entity loads
without error.

## Suggested fix (on DataHub's side, not implemented here)

In the `valueEntities` resolver (on the `datahub-graphql-core` side), when
trying to parse a URN-shaped substring, catch the parsing exception (or
validate that the substring is a complete, valid URN before attempting to
resolve it as an entity) and, if it fails, treat the value as plain text
instead of propagating the exception into the GraphQL response.
