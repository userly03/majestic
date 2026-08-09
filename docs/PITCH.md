# Majestic — The root-cause investigator for your data ecosystem

> Built for *Build with DataHub: The Agent Hackathon*

## The problem: the blind detective

An alarm goes off: *"Today's sales report is empty."*

With today's tools, solving this is a slow, manual process:

1. A generic alert arrives — the dataset didn't update.
2. You investigate blind, tool by tool: did the ETL fail? (Airflow). Did the source schema change? (Snowflake). Is the owner on vacation? (Slack).
3. After an hour jumping between systems, you find that a change to a marketing table, three lineage hops upstream, broke your sales report.

The problem isn't the alert. It's that no tool connects the dots for you — you get loose signals, not a diagnosis.

## The solution: a root-cause investigator, not another monitor

This agent reads DataHub's graph, cross-references signals of different kinds (freshness, schema changes, ownership) into a single causal chain, and writes that diagnosis back to the graph as auditable metadata. The next time it sees the same structural pattern on another entity, it doesn't investigate from scratch again.

**This isn't "detect and alert faster." It's explaining the *why*, crossing domains that nothing connects today.**

## Why this isn't something DataHub already does

An honest comparison — it matters that it's accurate, not flattering:

| | DataHub (Smart Assertions + Actions Framework) | This project |
|---|---|---|
| Detects anomalies | Yes — with adaptive ML, learns per-dataset thresholds | Doesn't reinvent this; consumes the signals DataHub already exposes |
| Responds to an event | Yes — configurable rules (e.g. "if tag=PII, notify Slack") | Doesn't compete here either |
| Cross-references different problem types into a single root cause (freshness + ownership + schema change) | No | **Yes — this is the real gap** |
| Generalizes a diagnosis from one entity to another by graph structure, not by a predefined rule | No | **Yes** |
| Persists the reasoning as queryable, auditable metadata | Partial (incidents, no causal chain) | **Yes, with traceable evidence** |

We're not saying "we're first in AI governance" — DataHub Cloud already does that in production. We're saying cross-domain causal reasoning with generalizable memory is the gap they don't cover.

## How it works

**Phase 1 — Reconnaissance.** Reads lineage, schemas, ownership, and freshness via DataHub's Python SDK (`DataHubGraph`). The core (`MajesticAgent`/`ImpactSimulator`) doesn't depend on a single frontend: `main.py` is the CLI, and `src/mcp_server.py` exposes `diagnose`/`impact` as MCP tools (`majestic_diagnose`, `majestic_impact`) so other agents can invoke them directly — same core, two surfaces. Computes structural metrics (depth, upstream/downstream count).

**Phase 2 — Diagnosis.** Given an anomaly, it walks the lineage backward looking for real evidence in the graph (no LLM speculation). Up to 3 causal links, each backed by a concrete fact: incident tag, missing owner, stale dataset (freshness), or a recently modified schema — four evidence types implemented today in `src/core/diagnoser.py` (doesn't include DataHub assertions yet). If there's no evidence, the chain stops there. An additional mechanism ("lag-aware", see `LAG_AWARE_DIAGNOSIS.md`) adjusts each evidence weight by recency and upstream inheritance, and ranks up to 3 candidates instead of returning a single answer.

**Phase 3 — Memory.** Saves the diagnosis as `structuredProperties` on the entity: a deterministic pattern signature (`anomaly_type:depth:upstream:downstream:platform`), the diagnosis as text, a **business context / lesson learned** field (free text a human can enrich when closing the incident), and a confidence score. If the agent sees the same signature on another entity, it retrieves the previous diagnosis instead of reasoning from scratch — but the reuse message is explicit that it's a *structural* match, not confirmation that it's the same real incident (the signature without a platform anchor produced false positives across unrelated domains; with platform the problem is reduced but doesn't fully disappear — see `AUDIT_REPORT.md`).

**Impact simulator (bonus, same mechanism inverted).** Phase 1's traversal runs upward (upstream) for diagnosis. The same code, walking downward (downstream), answers before a change is executed: *"if you modify this dataset, N downstream datasets are affected, M of them dashboards — here are the owners to notify."* Minimal marginal cost because it reuses the traversal already built; it isn't a new module, it's the same one with the direction reversed. (Note: today `ImpactSimulator` distinguishes datasets from dashboards, but not subtypes like "ML models" — the original phrasing of this pitch was a conceptual illustration, not the real output format; see `src/impact/simulator.py`.)

## What we did NOT build, and why

A deliberate decision, not a lack of time:

- **Slack bot** — only considered once the core works with comfortable margin. Adds external integration surface (OAuth, webhooks) before validating the essentials.
- **Natural language -> business glossary translator** — depends on the datapack having a populated Business Glossary, which wasn't confirmed. We don't build on top of an unverified assumption.
- **Future-failure prediction ("80% probability in 48h")** — the sample datapacks are a static load, not a real time series. Without real historical data, that figure would be invented, not measured.
- **Time-travel debugging with versioned aspects** — depends on DataHub capabilities not confirmed in this session, and is essentially a second project.
- **Chaos engineering / active fault injection** — implies modifying the data environment under test; real risk of breaking the demo itself before recording the video.

### Technical validation status

> Updated across 4 internal hardening rounds (the last one, live validation against real DataHub).

- [x] `datahub properties upsert` with the episodic memory definition — YAML in `config/agent_memory_property.yaml`. **A real bug was found and fixed here**: the first version used camelCase field names (`displayName`, `entityTypes`) that the SDK's real pydantic model rejects (it expects snake_case) — only caught by installing the SDK and actually parsing the YAML, not by reading the docs. `python3 main.py doctor` now registers it automatically if missing.
- [x] Write-back of `structuredProperties` via the Python SDK — `src/memory/writer.py`, `DatasetPatchBuilder.add_structured_property` + `DataHubGraph.emit_mcps`. Covered by unit tests and by `tests/test_integration.py` (opt-in, against a real instance).
- [x] Reading back the written memory — `DiagnosisWriter.read_diagnosis`, same validation mechanism.
- [x] Upstream/downstream lineage traversal, including multi-page pagination — `src/graph/traversal.py`, BFS over `DataHubGraph.scroll_lineage`. Covered by unit tests (including the pagination path, which initially had no test at all).
- [x] Searching for previous diagnoses across entities by pattern signature (`find_previous_diagnosis`) — **confirmed against a real instance** (2026-08-08): Plan A (structured filter) found the previous diagnosis correctly in the final run; in an earlier run, while Elasticsearch indexing hadn't yet caught up with that document, it automatically fell back to Plan B (free text) without breaking the flow — exactly the behavior this Plan B was designed to cover.
- [x] Resilient connection to DataHub taking a while to come up or being momentarily down — retries with backoff (`tenacity`). **Another real finding**: our own retry multiplied with the SDK's internal retry, pushing the worst case to ~90s before reporting an error; measured and fixed down to ~15s. See "Technical notes" in `README.md`.
- [x] **Full pipeline run end to end against a real DataHub instance** (2026-08-08): `doctor` -> `seed_demo_data.py` -> `diagnose --explain --write` -> `impact` -> memory reuse on a second entity. Found and fixed, along the way, a real UI bug (see `DATAHUB_UI_BUG_REPORT.md`) — the same kind of finding earlier rounds had already anticipated only shows up running against something real.

**The method and class names used (`DataHubGraph.scroll_lineage`, `LineageDirection`, `DatasetPatchBuilder`, `StructuredPropertiesClass`, `StructuredProperties.from_yaml`) were confirmed by installing `acryl-datahub==1.7.0` in an isolated environment and inspecting the SDK directly**, not assumed from documentation — exactly the precaution this section called for, and one that in several concrete cases (the YAML, the retry, and the Round 4 UI bug) found real bugs the documentation wouldn't have revealed.

## Repo structure

See [`../README.md`](../README.md#architecture) for the always-up-to-date version — here's just the high-level summary:

```
Majestic/
├── main.py                # CLI: diagnose / impact / doctor
├── docker-compose.yml      # one command to run everything in a container
├── config/                 # centralized configuration + episodic memory definition
├── src/
│   ├── graph/               # DataHub client + BFS traversal
│   ├── core/                 # orchestration, diagnosis, optional narrative synthesis
│   ├── memory/                # episodic memory write-back and read-back
│   └── impact/                 # downstream impact simulator
├── scripts/                # spikes, demo data seeding, examples/ generator
├── tests/                   # unit tests (mocks) + integration (opt-in, real DataHub)
└── examples/                # example outputs
```

## Setup

See [`../README.md`](../README.md#installation-and-usage) for the complete, always-up-to-date version. Summary:

1. `datahub docker quickstart` — starts DataHub locally.
2. `pip install -r requirements.txt` (use a virtualenv).
3. `cp .env.example .env`
4. `python3 main.py doctor` — a single command that replaces the manual steps of connecting + registering properties + write/read cycle.
5. `python3 scripts/seed_demo_data.py` — seeds a graph with a guaranteed anomaly (doesn't depend on the sample datapack having interesting lineage by chance).
6. `python3 main.py diagnose "<urn>" --explain` — runs the full pipeline.

## Prior art (verified, not assumed)

- [Hermes Agent (Nous Research)](https://github.com/nousresearch/hermes-agent) — persistent memory and skill self-improvement, but conversation memory, not data governance memory.
- [Cognee](https://github.com/topoteretes/cognee) — knowledge graph as agent memory, general-purpose, not designed for enterprise data lineage.
- [Memoria (Matrix Origin)](https://github.com/matrixorigin/Memoria) — "Git for Memory" with snapshots/rollback, focused on conversational memory for coding agents.
- [DataHub Smart Assertions / Actions Framework](https://datahub.com/products/data-observability/) — adaptive detection and event-based automation, without cross-domain causal reasoning or memory generalizable across entities.

None of them combine: an autonomous agent over a *data governance* graph + cross-domain causal reasoning + reasoning persisted as metadata native to the graph itself.

## License

Apache 2.0 — see `LICENSE`. (Hackathon requirement: must be visible in the repo's "About" section on GitHub.)

## Submission checklist (Devpost)

- [ ] Project URL (repo with clear instructions — no deploy required)
- [ ] Public GitHub repo, with Apache 2.0 license visible in "About"
- [x] Project description — this document + `README.md`
- [ ] Demo video <3 min, public YouTube/Vimeo — script ready and rehearsed (internal notes), still needs recording
- [x] `examples/` with real outputs — regenerated on 2026-08-08 by running the full pipeline against a real DataHub instance (not `FakeDataHub`). See `examples/README.md` for the detail and the exact commands used.
- [ ] `examples/structured_property_screenshot.png` — manual screenshot of the DataHub UI (the one piece no script can generate)
- [ ] Optional: opt in to the Bonus Prize survey ($50 x 10)
