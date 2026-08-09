# AUDIT_REPORT.md — Unfiltered judge-style audit

> Written on 2026-08-08, reading the actual source code (`src/`, `main.py`,
> `config/`, `tests/`), not just the documentation — with the context of
> having run the full pipeline against a real DataHub instance that
> same day (internal hardening notes, Round 4). When something deserves a 5, it
> gets a 5.
>
> **Update note (post-audit fixes):** several items flagged below as
> critical gaps have since been closed — see `README.md` ("Technical
> notes") and the commit history for the full detail. In short: an MCP
> server now exists (`src/mcp_server.py`, addresses Section 1.1 and
> Section 2 item 2), `pattern_signature` now anchors the causal node's
> platform (addresses Section 1.4 and Section 2 item 1, mitigates but
> doesn't eliminate the false-positive risk), `_sanitize_urn_lookalikes`
> now has test coverage (Section 2 item 4), the causal-chain path-awareness
> limitation is now documented in the README (Section 2 item 5),
> `requirements.txt`/`requirements-dev.txt` are now split (Section 2 item
> 7), and the test suite grew from 46 to 79 unit tests. The scores and
> analysis below are left as originally written — a snapshot of that
> point in time — rather than rescored, so the audit stays an honest
> record of what was found and when, not a moving target.

---

## Section 1 — Score by criterion

### 1. Use of DataHub — **6/10**

**What helps:**
- It isn't passive reading. `src/memory/writer.py` writes back to the graph (`structuredProperties` via `DatasetPatchBuilder.add_structured_property` + `emit_mcps`) — the criterion itself explicitly says "strong submissions... contribute back to the graph where appropriate," and this meets that literally, not cosmetically.
- Uses multiple real surfaces of DataHub's data model, not just one: lineage (`scroll_lineage`, `src/graph/traversal.py`), tags (`GlobalTagsClass`), ownership (`OwnershipClass`), schema (`SchemaMetadataClass`), and the Structured Properties framework end to end (YAML definition + SDK registration + read/write). That's a genuinely cross-cutting use of the metadata graph, not an isolated `get()`.
- The Structured Properties framework is, literally, the mechanism DataHub recommends for extending its own data model — using it to persist episodic memory is the right choice, not a shortcut.

**What costs points, and it's serious:** the hackathon pitch opens with a specific line — *"With an MCP Server, end-to-end ML lineage, and DataHub Skills that give agents direct access to catalog workflows..."* — and criterion 1 explicitly names **MCP Server, Agent Context Kit, DataHub Skills, Analytics Agent**. Majestic uses none of the four. `PITCH.md` admits it outright: *"via DataHub's Python SDK (`DataHubGraph`, not an MCP Server — evaluated and the direct SDK was chosen instead)"*. That's a defensible engineering decision (the direct SDK is simpler to debug, and it works today), but it's exactly the opposite of what this criterion rewards. There's also no ML lineage (the whole project is datasets/dashboards; zero `MLModel`, `MLFeature`, `MLModelGroup`) despite the hackathon naming it as a DataHub differentiator. A judge who reads the criterion literally and compares it against the code will spot the gap in 30 seconds.

**Why 6 and not higher/lower:** the *conceptual* use of the graph (lineage + write-back + structured properties) is real and non-trivial — not a 3. But completely ignoring the four surfaces the criterion explicitly names, in a hackathon that puts them in the first paragraph of the call, can't be an 8+.

### 2. Technical execution quality — **8/10**

**What helps:**
- Clean, non-overlapping separation of concerns: `src/graph` (client + traversal), `src/core` (orchestration + diagnosis), `src/memory` (persistence), `src/impact` (simulation) — each module has a single reason to change.
- Consistent fail-fast: the 4 classes that depend on DataHub (`LineageTraversal`, `RootCauseDiagnoser`, `ImpactSimulator`, `DiagnosisWriter`) check `client.is_connected` in their own `__init__` and raise `RuntimeError` immediately — nobody ends up half-built.
- The timeout/retry numbers in `config/settings.py` aren't guessed — they're measured (`HTTP_RETRY_MAX_TIMES` lowered from 4 to 2 after measuring 28s->90s against a downed GMS, documented right in the code, lines 29-39).
- Real parallelization where it matters: `RootCauseDiagnoser._collect_evidence_parallel` and `ImpactSimulator._collect_owners` use `ThreadPoolExecutor` to avoid paying linear latency on nodes with wide fan-in — and with a single node, they fall back to the sequential path with no overhead.
- **Validated live today, not just in CI with mocks**: ran `doctor` (3/3), `seed_demo_data.py`, `diagnose --explain --write`, `impact`, and memory reuse on a second entity — against a real instance. Found and fixed 2 real bugs along the way (see Section 2). That's evidence the code delivers what it promises, not just a claim.
- 46/46 unit tests pass; CI runs tests + a Docker build on every push.

**What costs points:**
- The "causal chain" isn't actually *path-aware*. `RootCauseDiagnoser.analyze()` groups upstream nodes by depth (`nodes_by_hop`) and looks for evidence on *any* node at that depth — not along a specific path from the target. If there are two distinct lineage branches, evidence from branch A at hop 2 can appear in the chain even if the node relevant to the real target is in branch B. This isn't broken — it's a reasonable simplification for a hackathon — but it isn't documented anywhere as a limitation either. A judge who reads the code carefully (not just the README) will notice it.
- The function fixed today (`_sanitize_urn_lookalikes` in `src/memory/writer.py`) has **zero tests**. We found the bug, fixed it, verified it manually against the real API — but no test was left to guard against a future regression. That's exactly the kind of gap a technical judge reading the diff would notice.
- `requirements.txt` mixes production dependencies (`acryl-datahub`, `requests`) with `pytest` — the production Docker image loads the test framework without needing it. Cosmetic, but the kind of detail a senior engineer "obsessed with quality" (the project's own self-description in its commit history) would flag in their own project.

### 3. Originality — **7/10**

**What helps:**
- The central idea — cross-referencing evidence from *different domains* (tags, schema, freshness, ownership) into a single causal chain, and generalizing that diagnosis to other entities by structural signature — isn't "another monitor with a configurable threshold." `PITCH.md`'s comparison table is honest about this: DataHub already does anomaly detection and rule-based automation; what Majestic does (cross-domain causal reasoning + generalizable memory) is a real gap, not marketing filler.
- The "memory" mechanism (pattern signature `type:hop:upstream:downstream` -> reuse diagnosis) is a genuinely creative twist, not an obvious copy of a generic agent pattern or an existing DataHub feature.
- Correct composition, not reinvention: the impact simulator (`ImpactSimulator`) is literally the same `LineageTraversal` inverted — not a new module duplicating logic, it's proof the traversal was designed to be reused. That's exactly the kind of "extension/composition" the rules ask for, not a from-scratch rebuild.

**What costs points:**
- The pattern signature (`incident_tag:1:2:1`) is structurally very coarse — see the critical finding in Section 2 about "memory" false positives. An original idea that generalizes poorly in practice loses some of its merit.
- The 4 evidence types are direct heuristics over basic DataHub aspects (tag, owner, timestamp) — there's nothing here a competent data engineer couldn't have written in a day. The originality is in the *composition and memory*, not in the sophistication of individual detection — and that's fine for a hackathon, but it caps the score's ceiling.

### 4. Real-world usefulness — **7/10**

**What helps:**
- The problem ("the sales report is empty, why?", jumping between 3 tools to find out) is real and universally recognizable to anyone who's operated a production data pipeline.
- Disciplined scope: `PITCH.md` explicitly lists what they did NOT build and why (Slack bot, business-glossary translator, failure prediction) — every scope decision has a technical reason, not "we ran out of time." That makes what DOES exist more credible as something that actually works, not a list of half-built features.
- `main.py doctor` and the humanized error messages (`_human_error` in `main.py`) show real operators were considered, not just a demo's happy path.

**What costs points, and it's this audit's most important finding:**
- **"Memory" can produce structural false positives, and this isn't hypothetical — it's mathematically inevitable at scale.** `pattern_signature = f"{evidence_type}:{hop}:{upstream_count}:{downstream_count}"` (`src/core/agent.py::_build_pattern_signature`) captures nothing semantic about the domain, the platform, or the incident's actual content. Two completely unrelated datasets — one in marketing, one in finance — with an incident tag 1 hop away and coincidentally the same upstream/downstream count, produce the SAME signature. Majestic would say "already seen this pattern before" and reuse a diagnosis that has nothing to do with the real one. In a real company with thousands of datasets, this isn't a rare edge case — it's statistically guaranteed to happen regularly. No technical judge who thinks about this for 30 seconds will let it slide, and it's the heart of the project's differentiator (the strongest row in `PITCH.md`'s comparison table).
- The evidence heuristics are *proxy* signals, not real observability: "no owner" doesn't mean something broke, "schema recently modified" doesn't prove causation (temporal coincidence != causation). The project is honest about this in `diagnoser.py`'s comments, which helps section 5 but costs points here — it's a real usefulness limitation, not just a matter of honesty.

### 5. Presentation quality — **7/10 (potential 9/10, conditional)**

**What helps:**
- `README.md` has reproducible step-by-step installation, a clear architecture, and — as of today — a live-validation history with real findings, not generic claims.
- `PITCH.md` is an honest, well-written pitch: problem, explicit comparison with DataHub (without inflating differentiation where there isn't any), what wasn't built and why.
- The transparency about known risks ("Technical notes" in the README, the 4 rounds of internal hardening) is, paradoxically, a presentation strength: a judge trusts a team that knows the exact limits of its own system more.
- `examples/` has real outputs, not invented ones, with the date and exact commands documented in `examples/README.md`.

**Why it isn't higher yet:** the criterion explicitly asks for "demo video quality" and **no video has been recorded**, and "public repo" and **the repository isn't on GitHub yet** (verified: `git remote -v` returns nothing). No matter how polished the documentation is, without those two pieces a judge can't evaluate this criterion — today, literally, there's nothing to judge on those two dimensions. The potential is high because the underlying material (the timed recording script, already validated against the real instance) is solid.

### 6. Bonus — Open-source contribution to DataHub — **1/10**

Zero contributions to the DataHub repository itself (no PR, no issue, no doc fix, no RFC). This is 100% expected for the project's current state — nobody promised this — but as things stand, it adds nothing to this bonus. See Section 3, idea #1: there's a very-low-effort, high-credibility opportunity waiting here, generated by today's own work.

---

## Section 2 — Critical issues found

Ordered by how likely a judge is to find them and how bad it looks if they do.

1. **[CRITICAL] The pattern signature can produce "memory" false positives — the most serious risk because it attacks the project's core differentiator.** Already detailed in Section 1.4. If a judge tries the project with two unrelated entities that happen to share `evidence_type:hop:upstream:downstream`, they'll see Majestic "recognize" a pattern that doesn't exist — and that's worse than having no memory at all, because it's a wrong diagnosis presented with confidence.

2. **[CRITICAL] Zero use of MCP Server / Agent Context Kit / DataHub Skills / Analytics Agent, in a hackathon that names them in the first paragraph of the call.** Already detailed in Section 1.1. This can't be hidden — it's documented by the project itself (`PITCH.md`) as a conscious decision, which is honest, but a judge scoring specifically on this will see the gap no matter how well-written the rest is.

3. **[MEDIUM] Repository isn't on GitHub yet, no video recorded.** Submission blockers, not code-quality ones — but without this there's nothing to evaluate on criteria 1, 5, and 6 (all require a public repo/URL).

4. **[MEDIUM] `_sanitize_urn_lookalikes` (today's fix) has no test.** Low risk of breaking on its own, but exactly the kind of "new code with no coverage" a serious code review flags.

5. **[MEDIUM] The causal chain isn't actually path-aware** (groups by depth, not by a specific path from the target) — not documented as a limitation anywhere. Not a bug, but a gap between what the README implies ("causal chain") and what the code actually guarantees.

6. **[LOW] The DataHub UI bug found today (`FabricType.$UNKNOWN`) is itself proof the project wasn't tested against a real instance until today.** Already fixed and documented (`DATAHUB_UI_BUG_REPORT.md`) — flagged here not as a pending issue, but as evidence it's worth checking whether there are *other* similar UI bugs that haven't triggered yet simply because not every combination of free text the agent might write has been tested (e.g. `--business-context` with arbitrary human-written text).

7. **[LOW] `requirements.txt` doesn't separate prod/dev**, the Docker image loads `pytest` unnecessarily. Cosmetic, low real impact, but cheap to fix.

---

## Section 3 — Standout ideas (beyond the obvious)

### Idea 1 — Report the DataHub bug found today as a public issue
**What it is:** open an issue on `datahub-project/datahub` (GitHub) documenting the `IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN` crash when a string-type structured property contains a URN-shaped substring — with the exact repro (already have it, word for word, in `DATAHUB_UI_BUG_REPORT.md` and in this session's history: the exact GraphQL query, the value that triggers it, the stack trace).
**Why it impresses judges:** the bonus criterion explicitly asks for "fixes" and contributions that extend work done during the hackathon. This isn't a hypothetical idea — it's a real, reproducible bug found *today*, with all the evidence already written up. Reporting it (with or without a fix PR) is the most credible possible open-source contribution because it comes from the project itself, not from hunting for something to check a box.
**Effort:** trivial (30-45 min: translate the already-documented finding into an English-language issue, with the GraphQL repro). If someone's up for sending a fix PR too (likely in the `valueEntities` resolver on the `datahub-graphql-core` side), it goes up to moderate — but the issue alone already counts.
**Risk of breaking something:** none — it's an action entirely external to the Majestic repo.

### Idea 2 — Expose `diagnose`/`impact` as MCP tools
**What it is:** a minimal MCP server (using the official Python `mcp` SDK) wrapping `MajesticAgent.diagnose()` and `ImpactSimulator.simulate()` as two tools (`majestic_diagnose(urn)`, `majestic_impact(urn)`). No need to touch existing logic — `agent.py` and `simulator.py` are already decoupled from the CLI (`main.py` is a thin layer on top), so the MCP server would be a third "frontend" over the same core, same as `main.py` is one today.
**Why it impresses judges:** it's the most direct possible answer to gap #2 in Section 2. Repositions Majestic from "a script that reads DataHub" to "a capability other agents can invoke" — literally what the hackathon call says ("agents that actually ship... composing DataHub"). A judge who asks "where's the MCP?" goes from finding a gap to seeing a concrete answer.
**Effort:** moderate (half a day: install `mcp`, define 2 tools with their schemas, test it with a simple MCP client or the official inspector). Technical risk is low because it doesn't touch existing code, only adds a new adapter.
**Risk of breaking something:** none if implemented as a new module (`src/mcp_server.py` or similar) without modifying `agent.py`/`simulator.py`.

### Idea 3 — Close the memory false-positive gap with a more honest signature
**What it is:** instead of (or in addition to) `evidence_type:hop:upstream:downstream`, include something that anchors the signature to real context — for example, the root cause's `platform` (hive, snowflake, etc.), or require the candidate entity to share at least one tag/domain with the current entity before accepting the reuse. Simpler alternative: when showing "diagnosis already exists," explicitly show how "coarse" the match is (e.g. "same structure, different platform — review before trusting blindly") instead of presenting it as a reliable match with no nuance.
**Why it impresses judges:** turns this audit's most serious problem (Section 2, item 1) into a demonstrated strength — showing the team thought about the false-positive case and handles it explicitly is exactly the kind of rigor that distinguishes a hackathon project "that works in the demo" from one a real data team would actually consider.
**Effort:** moderate if done properly (adjust `_build_pattern_signature` + `find_previous_diagnosis` + tests); trivial if only the visual caveat is added to the message.
**Risk of breaking something:** low-medium — touches the heart of Phase 3, integration tests need to be re-run afterward.

### Idea 4 — Resolve real names in impact, not just URNs
**What it is:** `ImpactSimulator._collect_owners` already fetches `OwnershipClass` for every downstream node — today only the raw URNs (`urn:li:corpuser:...`) are kept. With one extra call to `CorpUserInfoClass` (or `CorpUserEditableInfoClass`) a display name can be shown ("Sarah, from the Finance team, would be notified") instead of an unreadable URN.
**Why it impresses judges:** it's the kind of "visceral" detail the brief asks for — turns `affected_owners: ["urn:li:corpuser:majestic_seed"]` into something a non-technical judge also understands at a glance, without changing any business logic.
**Effort:** trivial (one more `get_aspect` call, the exact pattern already exists in the same file).
**Risk of breaking something:** none — it's additive, with a fallback to the URN if there's no `CorpUserInfo`.

### Idea 5 — A `main.py memory` command listing every persisted diagnosis
**What it is:** a new subcommand that runs `get_urns_by_filter` over `structuredProperties.majestic.patternSignature` with no value filter, and lists every entity with active memory, grouped by signature — a kind of "log" of everything Majestic has already diagnosed on the instance.
**Why it impresses judges:** makes the memory differentiator tangible in a way no single `diagnose` can show — a judge sees at a glance that this isn't "one isolated diagnosis" but a system accumulating knowledge over time. Cheap to demo on video (one command, one table).
**Effort:** trivial-to-moderate (reuses `_search_by_pattern_signature` with a broader filter; the new part is formatting the output).
**Risk of breaking something:** none, it's read-only.

---

## Section 4 — Prioritized action plan

### CRITICAL (without this, the submission is incomplete or vulnerable)
1. **Create the GitHub repo and push** (you already have it, per what we last discussed) — without this, criteria 1, 5, and 6 can't be evaluated.
2. **Record the 3-minute video** following the rehearsed internal script — same reason.
3. **Report the DataHub bug as a GitHub issue (Idea 1, Section 3).** Trivial, already fully documented, and the only concrete action available for Section 6 (bonus) before the deadline.
4. **Add at least one test for `_sanitize_urn_lookalikes`** (Section 2, item 4) — 10 minutes, closes a real, visible gap in today's diff.

### HIGH IMPACT (sets you apart from the competition, worth it if there's half a day more)
5. **Tackle the memory false-positive problem (Idea 3)** — this audit's most serious finding, and it attacks the pitch's core directly. Even the simple version (show the caveat in the message, not a richer signature) is worth doing before anything else on this list.
6. **Minimal MCP server (Idea 2)** — the most direct answer to criterion 1's biggest gap. If there's time for only one "ambitious" thing, this is it.
7. **Resolve real names in `impact` (Idea 4)** — trivial effort, visibly raises demo quality with no risk.
8. **Explicitly document the "causal chain isn't path-aware" limitation** (Section 2, item 5) in the README — 15 minutes, closes an honesty-vs-code gap before a judge finds it on their own.

### BONUS (if time allows)
9. **`main.py memory` command (Idea 5)** — good visual effect for the video, but not critical.
10. **Split `requirements.txt` / `requirements-dev.txt`** — cosmetic, low ROI, but quick.
11. If there's really time to spare: turn the reported issue into a real fix PR, to bump Section 6 from "reported" to "contributed code."
