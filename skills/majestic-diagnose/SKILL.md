---
name: majestic-diagnose
description: |
  Use this skill when a dataset or dashboard looks broken and you need
  the ROOT CAUSE, not just the raw lineage graph — cross-domain evidence
  (incident tags, recent schema changes, staleness, missing ownership)
  chained into a single causal explanation, with memory of prior
  diagnoses so the same structural pattern is recognized on other
  entities instead of re-reasoned from scratch. Also covers blast-radius
  simulation before a change, and a CI-friendly gate that blocks risky
  changes automatically.
  Triggers on: "why is X broken", "root cause of X", "what changed
  upstream of X", "what breaks if I change X", "is it safe to touch X",
  "have we seen this failure before". Complements datahub-lineage — use
  that skill for raw graph exploration and multi-hop traversal; use this
  one when you need a verdict backed by evidence, not just the graph
  shape.
user-invocable: true
allowed-tools: Bash(python3 main.py *), Bash(python3 -m src.events.listener *)
---

# Majestic — root cause diagnosis, blast radius, and change gating

Majestic is a small Python agent that sits on top of a DataHub instance.
It does not replace `datahub-lineage` or `datahub-search` — it consumes
the same lineage graph they expose, but adds three things those skills
don't: (1) cross-domain evidence correlation into one causal chain, (2)
persisted memory keyed by a structural pattern signature so a repeat
failure is recognized instead of re-diagnosed, and (3) a downstream
blast-radius simulator that can gate changes before they land.

Run everything from the repo root. All commands are read-mostly; only
`diagnose --write` and `check-change` persist anything, and both are
explicit opt-in (see "What this skill will never do" below).

## When to reach for this vs. `datahub-lineage`

| Need | Use |
|---|---|
| "Show me what feeds into X" | `datahub-lineage` |
| "Why is X broken — what's the actual cause?" | **this skill** (`diagnose`) |
| "What breaks if I touch X?" | **this skill** (`impact`) |
| "Is it safe to merge this change?" | **this skill** (`check-change`) |
| "Have we seen this exact kind of failure before?" | **this skill** (memory reuse, automatic inside `diagnose`) |

## Step 1 — Confirm the setup is healthy

Before diagnosing anything for the first time in a session, run:

```bash
python3 main.py doctor
```

This checks the DataHub connection, registers Majestic's structured
property definitions if missing, and round-trips a write/read cycle.
If it fails, fix that first — every other command depends on it. If
DataHub itself isn't up: `datahub docker quickstart`.

## Step 2 — Get the target URN

Resolve the entity URN the same way `datahub-lineage`/`datahub-search`
would (search by name, or the user already has it). Majestic takes a
full DataHub URN, e.g.:

```
urn:li:dataset:(urn:li:dataPlatform:hive,my_db.my_table,PROD)
```

## Step 3 — Diagnose

```bash
python3 main.py diagnose "<urn>" --explain
```

- Walks the lineage **upstream** from `<urn>`, hop by hop, looking for
  concrete evidence at each hop: an incident tag, a schema change in
  the last 24h (configurable), stale data, or a dataset with no owner.
  Stops as soon as a hop has no evidence — the chain is never padded.
- `--explain` adds a natural-language paragraph on top of the same
  evidence (deterministic template today, not an LLM call — see the
  main README's "Notas técnicas" if asked whether this uses an LLM).
- If DataHub already has a diagnosis for the same structural pattern
  (`pattern_signature` in the output) on a different entity, it prints
  a `♻️ Ya existe un diagnóstico...` block automatically — no separate
  command needed, this is always checked.
- Add `--write` to persist the diagnosis back to DataHub as structured
  properties (`majestic.*`) on the entity, and optionally
  `--business-context "<free text>"` to attach a human note.

Read `root_cause_urn` and `reason` from the JSON output — those are the
answer. `confidence` is a heuristic ranking (evidence specificity), not
a calibrated probability; don't present it as one.

## Step 4 — Simulate impact (before touching something)

```bash
python3 main.py impact "<urn>"
```

Walks the **same traversal, downstream**, and reports how many
datasets/dashboards are affected and who owns them. Use this before
recommending a change, not after something already broke.

## Step 5 — Gate a change (CI-friendly)

```bash
python3 main.py check-change --urn "<urn>"
echo $?   # 0 = safe, 1 = blocked
```

Combines the blast radius from step 4 with how much of the downstream
has an owner assigned (a fully-owned downstream is safer to touch than
an orphaned one with the same blast radius, because there's someone to
notify). Threshold is configurable via `MAJESTIC_CHECK_CHANGE_RISK_THRESHOLD`.
Use this as a pass/fail gate in a pipeline, not just for reading.

## Step 6 (optional) — Continuous mode

```bash
python3 -m src.events.listener --once   # one polling cycle, for testing
python3 -m src.events.listener          # runs continuously
```

Polls DataHub for datasets that just got an incident tag and haven't
been seen yet, and auto-diagnoses each one. This is polling, not a
Kafka subscription — don't describe it as real-time streaming.

## What this skill will never do

- Never invent a root cause without a concrete evidence hop in the
  graph — if `causal_chain` is empty, the honest answer is "no evidence
  found," not a guess.
- Never write to DataHub unless `--write` (diagnose) or the implicit
  read-only evaluation of `check-change` — `check-change` itself never
  writes, it only reads lineage and ownership.
- Never treat `confidence` or `risk_score` as calibrated probabilities
  in front of a user — both are explicitly documented heuristics.

## Common mistakes

- Running `diagnose` on a URN that was never diagnosed before and
  expecting a memory hit — memory reuse only fires when another entity
  was *already* diagnosed with `--write` and shares the same
  `pattern_signature` (same evidence type, same hop depth, same
  upstream/downstream counts).
- Forgetting `python3 main.py doctor` after a fresh `datahub docker
  quickstart` — GMS can take a while to warm up right after starting;
  `doctor` surfaces that clearly instead of a raw timeout later.
- Reading `pattern_signature` as a semantic fingerprint — it's
  structural (evidence type + graph shape), not content-aware. Two
  unrelated incidents can share a signature; don't present a memory
  hit as certain without checking the recalled `reason` makes sense
  for the current context.
