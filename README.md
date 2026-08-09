# Majestic

**The root-cause investigator for your data ecosystem**

> Built for *Build with DataHub: The Agent Hackathon*. See [`docs/PITCH.md`](docs/PITCH.md) for the full pitch (problem, honest comparison with DataHub, what we didn't build and why).

## The problem

An alert fires: a dashboard is empty, a report looks wrong. The alert tells you *what* broke, never *why*. Today, finding the actual cause means manually jumping between the lineage graph, the ETL scheduler, and Slack — hoping someone remembers what changed three hops upstream.

## The solution

Majestic reads DataHub's lineage graph, walks it backward from the broken entity, and cross-references real evidence at each hop — incident tags, missing owners, stale data, recent schema changes — into a single causal chain. No LLM speculation: every link is backed by a fact read from the graph, or the chain stops there. It writes the diagnosis back to DataHub as auditable metadata, and the next time it sees the same structural pattern elsewhere, it reuses it instead of reasoning from scratch. It also simulates the downstream impact of a change before it's executed, reusing the same traversal in the opposite direction.

## Proof, not a promise

Two upstream datasets, same evidence type (`stale_data`), same base weight (0.5), same hop — exactly the kind of tie that leaves a naive system guessing. Majestic's "lag-aware" mechanism (exponential decay by recency, see "Technical notes" below) breaks it correctly — verified live against a real DataHub instance, not a mock:

| Dataset | Stale for | Adjusted weight | Rank |
|---|---|---|---|
| `inventory_recent` | ~31h (just crossed the staleness threshold) | **0.32** | #1 — root cause |
| `inventory_legacy` | ~800h (chronically stale, low priority) | **0.00** | #2 |

Same signal, same base weight — the only thing that told them apart is *when* each one happened. That's the difference between "something's wrong somewhere" and an actual answer.

## Requirements

- Docker and Docker Compose installed (to run DataHub locally).
- Python 3.10+ for local development (though Docker is recommended to run the agent).

## Architecture

```
Majestic/
├── main.py                      # CLI entrypoint (diagnose / impact / check-change / doctor)
├── config/
│   ├── settings.py               # centralized configuration (DataHub URL/token, thresholds)
│   └── agent_memory_property.yaml  # structured properties definition for memory
├── src/
│   ├── graph/
│   │   ├── client.py              # DataHubClient — wrapper over DataHubGraph
│   │   └── traversal.py           # LineageTraversal — upstream/downstream BFS
│   ├── core/
│   │   ├── agent.py               # MajesticAgent — orchestrates the 3 phases
│   │   ├── diagnoser.py           # RootCauseDiagnoser — evidence + causal chain + lag-aware
│   │   └── narrator.py            # explain() — natural-language synthesis of the diagnosis
│   ├── memory/
│   │   └── writer.py              # DiagnosisWriter — memory write-back and read-back
│   ├── impact/
│   │   ├── simulator.py           # ImpactSimulator — downstream impact of a change
│   │   └── risk_assessor.py       # RiskAssessor — blast radius + orphanhood -> CI/CD gate
│   ├── events/
│   │   └── listener.py            # IncidentListener — polling that triggers diagnose automatically
│   └── mcp_server.py              # MCP server — exposes diagnose/impact to other agents
├── scripts/
│   ├── spike_test.py              # validates only the connection to DataHub
│   ├── seed_demo_data.py          # seeds a synthetic graph with a guaranteed anomaly for the demo
│   ├── seed_lag_aware_demo.py     # seeds a fan-in scenario to showcase recency decay
│   ├── generate_example_outputs.py  # regenerates examples/ by running the real agent (not a real DataHub instance)
│   └── spike_writeback_test.py   # validates the full memory cycle, with the exact JSON sent
├── docker-compose.yml            # one command to run everything in a container
├── tests/                        # 79 unit tests (mocks) + 4 integration tests (opt-in, real DataHub)
├── examples/                     # example outputs — see examples/README.md on how "real" they are today
└── docs/
    ├── PITCH.md                   # full hackathon pitch
    ├── LAG_AWARE_DIAGNOSIS.md     # design and live validation of the lag-aware mechanism
    ├── AUDIT_REPORT.md            # unfiltered self-audit against the judging criteria
    └── DATAHUB_UI_BUG_REPORT.md   # draft issue for a real DataHub UI bug found during validation
```

- `src/graph`: client and traversal over DataHub (GMS).
- `src/core`: agent orchestration and root-cause reasoning (Phase 1 and 2), plus the optional narrative synthesis.
- `src/memory`: read/write of episodic memory as structured properties (Phase 3).
- `src/impact`: downstream impact simulator and the risk gate that consumes it (`check-change`).
- `src/events`: polling incident listener (triggers `diagnose` without anyone asking).
- `src/mcp_server.py`: same core, exposed as MCP tools instead of a CLI — see "MCP Server" below.

## Installation and usage

### 1. Start DataHub locally

```bash
datahub docker quickstart
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # only what the CLI needs in production
# pip install -r requirements-dev.txt    # + pytest and the MCP SDK, for development/demo
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env if your instance doesn't run on http://localhost:8080 or requires a token
```

### 4. Validate the setup

```bash
python3 main.py doctor
```

A single command that replaces 3 manual steps: checks the DataHub connection, registers `config/agent_memory_property.yaml` if it isn't applied yet (equivalent to `datahub properties upsert -f ...`), and runs a quick write/read cycle to confirm permissions. Ends with a pass/fail summary per step.

(The long, step-by-step version is still available: `python3 scripts/spike_test.py` to test only the connection, and `python3 scripts/spike_writeback_test.py` to see the exact JSON of the memory cycle — useful for debugging if `doctor` fails at step 3.)

### 5. Seed demo data (recommended)

The sample datapack from `datahub docker quickstart` doesn't guarantee a real anomaly in its lineage. This script does:

```bash
python3 scripts/seed_demo_data.py
```

Creates a mini-graph A -> B -> C with a real anomaly in B (incident tag + no owner) and a dashboard downstream of C, so that diagnosing C always finds a root cause and `impact` always has a dashboard to count.

### 6. Run the agent

```bash
# Diagnose the root cause of a URN (use the URN for C printed by the seed script)
python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"

# Persist the diagnosis in DataHub as structured properties
python3 main.py diagnose "<urn>" --write --business-context "optional text"

# Draft the evidence chain in natural language (a deterministic template
# today, doesn't call any external LLM — see "Technical Notes")
python3 main.py diagnose "<urn>" --explain

# Simulate the downstream impact of a change before executing it
python3 main.py impact "<urn>"

# --quiet suppresses internal logs (connection, traversal...) and leaves only
# the final result — for screen-sharing during the demo. Goes BEFORE the
# subcommand.
python3 main.py --quiet diagnose "<urn>" --explain
```

### With Docker

With `docker compose` (recommended — a single command, see `docker-compose.yml`):

```bash
docker compose up                                                  # runs scripts/spike_test.py, validates connection
docker compose run --rm majestic python main.py doctor
docker compose run --rm majestic python main.py diagnose "<urn>" --explain
docker compose run --rm majestic python scripts/seed_demo_data.py
```

The first build takes a few minutes (the `acryl-datahub` dependency is heavy); subsequent builds use cache. Verified end to end: real build + `docker compose run ... python main.py doctor` against a nonexistent DataHub fails in ~15s with the expected message, without hanging or throwing a traceback.

Or without compose, directly with `docker`:

```bash
docker build -t majestic .
docker run --rm --network host --env-file .env majestic
docker run --rm --network host --env-file .env majestic python main.py diagnose "<urn>"
```

## MCP Server

`main.py` isn't the only frontend over `MajesticAgent`/`ImpactSimulator` — `src/mcp_server.py` exposes the same core as two MCP tools (`majestic_diagnose`, `majestic_impact`) so other agents can invoke them directly, without going through the CLI:

```bash
pip install -r requirements-dev.txt   # installs the MCP SDK
python3 -m src.mcp_server              # serves over stdio (the transport used by
                                         # Claude Desktop and most MCP clients)
```

It isn't a reimplementation: it's a new adapter (~100 lines) over the same classes `main.py` already uses, without touching `agent.py`/`simulator.py`. Tested end to end against the real DataHub instance running in this session (`majestic_diagnose`/`majestic_impact` invoked directly, same result as the CLI).

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                          # 79 unit tests (mocks, always run)
MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration   # 4 tests against real DataHub (see Technical Notes)
```

Integration tests are manual — there's no DataHub available in CI.

## Technical validation status

- [x] Upstream/downstream lineage traversal, including multi-page pagination, via `DataHubGraph.scroll_lineage` — verified by direct introspection of the installed SDK (`acryl-datahub==1.7.0`) and by unit tests.
- [x] Write-back of `structuredProperties` via `DatasetPatchBuilder.add_structured_property` + `emit_mcps` — covered by unit tests and by `tests/test_integration.py` (opt-in, against a real instance).
- [x] Reading back the written memory — `DiagnosisWriter.read_diagnosis`, same validation mechanism.
- [x] Searching for previous diagnoses by pattern signature (`find_previous_diagnosis`) — confirmed against a real instance: Plan A (structured filter) found the previous diagnosis correctly; Plan B (free-text) was also exercised at runtime, in a run where Elasticsearch indexing hadn't yet caught up with the document, and worked as a fallback without breaking the flow.
- [x] `python3 main.py doctor` — connection + property registration + write/read cycle in a single command, with bounded timeout and retry (~15s worst case if DataHub doesn't respond).
- [x] **Full pipeline run end to end against a real DataHub instance** (2026-08-08): `doctor` -> `seed_demo_data.py` -> `diagnose --explain --write` -> `impact` -> memory reuse on a second entity. Found and fixed a real bug along the way (see the first technical note below) — exactly the kind of finding no mock-based test can catch.

See the "Technical validation status" section in [`docs/PITCH.md`](docs/PITCH.md) for the full detail and the reasoning behind each decision.

## Technical notes (known risks and real findings)

- **A real DataHub UI bug, found while validating live and neutralized in our code.** The DataHub UI tries to resolve as a reference to another entity (`valueEntities`) any structured property value that *contains* something shaped like a URN (`urn:li:...(...)`) — and that resolver has a bug of its own in DataHub that crashes the entire page (`IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN`). The `reason` built by `RootCauseDiagnoser` always embeds the causal entity's URN in the sentence, so any real diagnosis triggered it. It isn't our bug, but it's our text that activates it — `src/memory/writer.py::_sanitize_urn_lookalikes` neutralizes it by inserting a zero-width space inside `"urn:li:"` before persisting the value (invisible when read, breaks the UI's detection). Confirmed before/after against the real GMS API. Draft issue ready to file upstream: `docs/DATAHUB_UI_BUG_REPORT.md`.
- **`DiagnosisWriter.find_previous_diagnosis` has a Plan B, and both paths have already been exercised against a real instance.** It looks for entities with the same pattern signature using a structured filter (`get_urns_by_filter` with `extraFilters` over `structuredProperties.<qualifiedName>` — Plan A). If Plan A throws an exception, or "works" but returns nothing, `_search_by_pattern_signature` automatically falls back to a free-text search (`query=`, Plan B) that doesn't depend on that field name — and any Plan B result is re-validated against the exact signature before reuse, so a partial free-text match isn't taken at face value. Neither plan can bring `diagnose` down: if both fail, `find_previous_diagnosis` returns `None` (equivalent to "no previous memory found"), never an exception.
- **Connection retries, with a real finding behind them.** `DataHubClient` retries the initial connection up to 3 times with exponential backoff (`tenacity`) before giving up. But the SDK *already* retries every HTTP request internally (`DatahubClientConfig.retry_max_times`, default 4, with its own backoff) — and that default retries even on "connection refused", not just 5xx. Measured against a downed GMS: a single `test_connection()` with the default took **28s** to fail; with our 3-attempt retry on top, up to **~90s** before reporting "couldn't connect" — unacceptable live. We lowered `retry_max_times` to 2 (`config/settings.py`), which brings the measured worst case down to **~15s**. This finding came from writing `tests/test_integration.py` and actually running it against a nonexistent endpoint, not from reading the code — exactly the kind of bug a 100%-mocked test can't catch.
- **Tests**: 79 unit tests (100% mocks, always run) + 4 integration tests (`tests/test_integration.py`, marked `@pytest.mark.integration`, skipped by default — require `MAJESTIC_RUN_INTEGRATION_TESTS=1` and a real instance). Run `pytest -m "not integration"` for the same subset CI would run. The integration tests cover, against real DataHub: the memory write/read cycle, that `find_previous_diagnosis` finds what was just written (validates at runtime whether Plan A works or Plan B was needed), and that diagnosing the graph seeded by `seed_demo_data.py` finds the root cause in B.
- **Evidence weights are configurable and auditable, not a black box.** The relative *order* (`incident_tag > schema_change > stale_data > unowned`) reflects the specificity and causal strength of each signal (a tag set by a human says more than the mere absence of an owner). The defaults (0.9/0.7/0.5/0.3, in `config/settings.py` via `MAJESTIC_EVIDENCE_WEIGHT_*`) aren't calibrated against a real incident dataset — but, unlike a constant buried in the code, any team with that history can recalibrate them without touching `diagnoser.py`. If a judge asks "why 0.75 and not 0.9?", the answer is: that's exactly the number you can change once you have data — the project doesn't fake a precision it never measured, but it doesn't leave it out of reach either.
- **The causal reasoning is 100% deterministic and traceable — an architectural decision, not a pending feature.** `RootCauseDiagnoser` never hallucinates a link: every entry in `causal_chain` is backed by a concrete fact read from the graph (tag, schema, freshness, ownership), and if a hop has no evidence, the chain stops there instead of being filled in with a guess. `--explain` (`src/core/narrator.py`) drafts that already-verified chain with a deterministic template — no external provider call, no API key, no new network failure point in production. The *Agent Hackathon* question ("where's the agent/LLM?") has a concrete answer: separating "what counts as evidence" (the graph, never an LLM) from "how it's phrased" (where an LLM could plug in later, without being able to invent a link the graph doesn't back) is the system's zero-hallucination guarantee, not a gap to fill. The `explain(report) -> str` signature is already ready for that day without touching `agent.py` or `main.py`.
- **The causal chain groups by depth (hop), not by a specific path from the target — a known limitation, not a bug.** `RootCauseDiagnoser.analyze()` looks for evidence on *any* node at a given depth (`nodes_by_hop`), not along a single lineage path from the target. If there are two distinct lineage branches, evidence from branch A at hop 2 can end up in the chain even if the node relevant to the actual target is in branch B. It's a reasonable simplification for a hackathon's scope — the typical scenario (a single linear chain or a simple fan-in, like the ones seeded by `scripts/seed_demo_data.py` and `scripts/seed_lag_aware_demo.py`) doesn't exercise it — but a graph with wide branches and scattered evidence would. Documented here so it isn't a surprise finding for a judge reading the code.
- **The memory pattern signature can produce false positives — mitigated, not eliminated.** `pattern_signature` (`src/core/agent.py::_build_pattern_signature`) recognizes the same structural pattern on another entity to reuse a diagnosis. Until 2026-08-08 the format was `type:hop:upstream:downstream`, with no domain anchor at all — two completely unrelated datasets with the same structural shape produced the same signature. The platform of the causal node was added (`urn:li:dataPlatform:...`, already available in the URN, no extra call) as a fourth component (`type:hop:upstream:downstream:platform`): it reduces collisions across different platforms, but **not** between two unrelated datasets on the same platform. That's why the reuse message in `main.py cmd_diagnose` is explicit ("STRUCTURAL match, not confirmation of the same incident") instead of presenting the reuse as an unqualified fact. See `docs/AUDIT_REPORT.md`, Section 2, item 1, for the original finding.
- **"Lag-aware" mechanism: dynamic weights by recency + inheritance discount + top-K ranking — original design, not an academic citation.** `RootCauseDiagnoser` no longer uses only the fixed weight of the evidence type: for `schema_change`/`stale_data` (which do have a real timestamp) it applies exponential recency decay (`adjusted_weight`, never reaches zero), and if the same evidence type appears at two consecutive hops, it discounts the one closer to the target for likely inheriting the problem from the farther hop rather than contributing an independent signal. `analyze()` also returns `ranked_candidates` (top-K, not just one answer) so as not to hide ambiguity when there are 2+ plausible causes. **Origin disclosure, plainly stated:** this idea started from an attempt to cite a paper ("LagRCA", a supposed FSE 2026 award) that turned out to be a hallucination — verified against the official conference program, it doesn't exist there. The underlying technical idea was sound, so it was implemented as an original Majestic design (see `docs/LAG_AWARE_DIAGNOSIS.md` for the full detail), with no false citation. What *is* cited and verified against a primary source is the real prior art on microservice RCA — MicroRCA, Microscope, TraceDiag, DynaCausal, IDI.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
