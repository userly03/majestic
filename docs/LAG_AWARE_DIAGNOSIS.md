# Majestic's "lag-aware" mechanism — implementation plan

> **Origin disclosure, first and plainly stated:** this idea is NOT based on a
> verified academic paper. It came from a hallucinated citation
> ("LagRCA", a supposed FSE 2026 Distinguished Paper Award) that was
> checked against the primary source (the official conference program)
> and doesn't exist there. The underlying *technical idea*, however,
> is sound and solves a real problem in `RootCauseDiagnoser` — so it's
> implemented as an original Majestic design, with the internal nickname
> "LagRCA" used only as an in-joke/nod to its origin, **never as a
> citation of real research**. It must not appear in `PITCH.md` or
> in the video as "based on the LagRCA paper" — that would be false. It
> can be described as "a mechanism of our own, inspired by how real
> microservice RCA research (MicroRCA, TraceDiag, DynaCausal — those
> ones verified against primary sources) treats time and symptom
> inheritance."

## What real problem this solves (in Majestic's own terms, not the phantom paper's)

1. **Evidence weights are static.** `_EVIDENCE_WEIGHTS` doesn't distinguish
   "this happened 10 minutes ago" from "this happened 3 weeks ago." A
   recent anomaly is more likely to be the active cause than an old one.
2. **No distinction between independent and inherited evidence.** If a
   downstream node shows symptoms because its upstream was already broken,
   treating it as an independent signal inflates the causal chain.
3. **A single answer hides ambiguity** when there are 2+ candidates
   with comparable evidence — `root_cause_urn` is always a single URN, even
   when the runner-up is nearly tied.

## The 3 mechanisms to build

### Mechanism 1 — Recency decay
For evidence types that already compute `age_hours` (`schema_change`,
`stale_data`), apply an exponential decay factor to the weight:

```
adjusted_weight = base_weight * decay(age_hours)
decay(age_hours) = 0.5 ** (age_hours / LAG_DECAY_HALFLIFE_HOURS)
```

Never drops to zero — old evidence weighs less, it isn't discarded. For
`incident_tag` and `unowned` (no reliable timestamp available via the
standard aspects we already read), the weight stays fixed as today — no
fabricated timestamp.

### Mechanism 2 — Upstream inheritance discount
If the same `evidence_type` appears at two consecutive hops of the chain,
the hop closer to the target (downstream) is discounted by
`UPSTREAM_INHERITANCE_DISCOUNT` — it's more likely inheriting the problem
from the farther hop than contributing an independent signal.

### Mechanism 3 — Ranked top-K candidates
`analyze()` adds a new `ranked_candidates` field (up to
`RANKED_CANDIDATES_TOP_K` candidates, each with `urn`/`hop`/
`evidence_type`/`adjusted_weight`), sorted descending. Existing fields
(`root_cause_urn`, `reason`, `confidence`, `causal_chain`) are still
computed the same way as today but using the adjusted weights —
**an additive change**, nothing already consuming the report breaks.

## Implementation checklist

- [x] `config/settings.py` — add `LAG_DECAY_HALFLIFE_HOURS` (default
      48), `UPSTREAM_INHERITANCE_DISCOUNT` (default 0.5),
      `RANKED_CANDIDATES_TOP_K` (default 3). All configurable via env var,
      same pattern as the rest of the file.
- [x] `src/core/diagnoser.py`:
  - [x] `_recency_decay(age_hours) -> float`
  - [x] Apply the decay wherever `age_hours` is computed (schema_change,
        stale_data) when building the evidence dict.
  - [x] `_apply_upstream_inheritance_discount(causal_chain) -> causal_chain`
  - [x] `analyze()`: use the already-adjusted chain to pick `root_cause_urn`
        (still `max(..., key=hop,weight)`, but over adjusted weights)
        and add `ranked_candidates` to the returned dict.
- [x] `tests/test_diagnoser.py` — new cases:
  - [x] decay reduces the weight of old evidence without reaching 0
  - [x] recent evidence (age_hours ~ 0) is barely discounted
  - [x] inheritance discount lowers the downstream hop's score when its
        type matches the upstream hop's
  - [x] `incident_tag`/`unowned` are unaffected by decay
        (no fabricated timestamp)
  - [x] `ranked_candidates` correctly ordered, capped at `RANKED_CANDIDATES_TOP_K`
- [x] Run the 61 existing tests — check whether any assumed an exact
      fixed weight that now changes due to decay (expected that some
      test needs a value adjusted, not the logic).
- [x] Test live against the real DataHub still running: re-diagnose
      `sales_report`, confirm `marketing_etl` still shows up as the root
      cause with the new mechanism.
- [x] `main.py cmd_diagnose` — print `ranked_candidates` when there's
      more than one candidate (optional, only if `len(ranked_candidates) > 1`).
- [x] Document in `README.md` ("Technical notes" section) as a mechanism
      of Majestic's own, with the origin disclosure above.

## Success criterion

Running `diagnose` on today's seeded graph should still find `marketing_etl`
as the root cause of `sales_report` (the result shouldn't change in such a
simple, single-hop-of-evidence case) — the difference shows up in graphs
with evidence at multiple hops or of different ages, which we don't have
seeded today. It may be worth seeding a third demo scenario with old +
new evidence so the mechanism is visible in the video.

## Scenario 3 tested live (2026-08-08)

`scripts/seed_lag_aware_demo.py` seeds `inventory_recent` (~30h stale)
and `inventory_legacy` (~800h stale) as a direct fan-in into
`logistics_report`, same hop and same `evidence_type` (`stale_data`), same
base weight (0.5). Run against real DataHub:

- `inventory_recent` -> `adjusted_weight` 0.3241, ranks #1 (root cause).
- `inventory_legacy` -> `adjusted_weight` ~0.0 (decays but never
  mathematically reaches zero, just rounds to 0.0000 in the output), ranks #2.
- `ranked_candidates` and `main.py cmd_diagnose`'s print both show both
  candidates correctly ordered.

Confirms the success criterion. All 67 tests (4 skipped, integration) were
still green at the time.
