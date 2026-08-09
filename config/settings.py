"""
Centralized configuration for Majestic.
Every module should read configuration from here instead of calling
os.getenv() directly, so there's a single place to see/change defaults.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- DataHub connection ---
DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
DATAHUB_GMS_TOKEN = os.getenv("DATAHUB_GMS_TOKEN")

# Retries when establishing the connection, in our own layer (tenacity, in
# client.py). If DataHub "blips" while the agent is starting up, this
# avoids dying on the first attempt.
CONNECT_RETRY_ATTEMPTS = int(os.getenv("MAJESTIC_CONNECT_RETRY_ATTEMPTS", "3"))
CONNECT_RETRY_WAIT_MIN_SECONDS = float(os.getenv("MAJESTIC_CONNECT_RETRY_WAIT_MIN", "1"))
CONNECT_RETRY_WAIT_MAX_SECONDS = float(os.getenv("MAJESTIC_CONNECT_RETRY_WAIT_MAX", "10"))

# Per-HTTP-request timeout toward the GMS. Without this, DatahubClientConfig
# applies no limit of its own — a hung GMS could leave the agent waiting
# indefinitely, exactly the kind of thing that can't happen live.
HTTP_TIMEOUT_SECONDS = float(os.getenv("MAJESTIC_HTTP_TIMEOUT_SECONDS", "10"))

# The SDK's own internal per-HTTP-request retries (urllib3, with its own
# exponential backoff). IMPORTANT: the default is 4, and it DOES trigger on
# "connection refused" too, not just 5xx — measured against a downed GMS, a
# single test_connection() with the default took 28s to fail. Since we
# already retry the connection in our own layer (CONNECT_RETRY_ATTEMPTS),
# leaving both layers at their default multiplies the wait (3 x 28s ~= 90s
# before reporting "couldn't connect" — unacceptable live). We lower it to
# a small value: it still absorbs an isolated transient blip during a
# normal operation, without turning "DataHub is down" into a minute-and-a-
# half hang.
HTTP_RETRY_MAX_TIMES = int(os.getenv("MAJESTIC_HTTP_RETRY_MAX_TIMES", "2"))

# --- Lineage traversal ---
DEFAULT_MAX_HOPS = int(os.getenv("MAJESTIC_MAX_HOPS", "3"))

# Max concurrent get_aspect calls per hop (diagnosis) or per batch
# (impact). Narrow graphs never notice; in wide graphs it keeps perceived
# latency from growing linearly with a node's fan-in.
MAX_PARALLEL_REQUESTS = int(os.getenv("MAJESTIC_MAX_PARALLEL_REQUESTS", "8"))

# --- Diagnosis (Phase 2) ---
# Max number of evidenced causal links pursued upstream.
MAX_CAUSAL_LINKS = int(os.getenv("MAJESTIC_MAX_CAUSAL_LINKS", "3"))

# If a dataset hasn't been updated in more than this threshold, it's
# treated as "stale data" evidence (a possible downed ETL). An initial
# heuristic, meant to be tuned with real incident data once the agent is
# in use.
FRESHNESS_THRESHOLD_HOURS = int(os.getenv("MAJESTIC_FRESHNESS_THRESHOLD_HOURS", "24"))

# Relative weight of each evidence type (see the full reasoning in
# src/core/diagnoser.py, next to _EVIDENCE_WEIGHTS). The default ORDER
# (incident_tag > schema_change > stale_data > unowned) is meant to be
# correct in most cases; the absolute values aren't calibrated against a
# real incident dataset — that's why they're configurable here instead of
# a constant buried in the code. A team that does have that history can
# recalibrate them without touching diagnoser.py.
EVIDENCE_WEIGHT_INCIDENT_TAG = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_INCIDENT_TAG", "0.9"))
EVIDENCE_WEIGHT_SCHEMA_CHANGE = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_SCHEMA_CHANGE", "0.7"))
EVIDENCE_WEIGHT_STALE_DATA = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_STALE_DATA", "0.5"))
EVIDENCE_WEIGHT_UNOWNED = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_UNOWNED", "0.3"))

# Substrings (case-insensitive) that, if present in one of the dataset's
# tags, are treated as direct evidence of a known incident.
INCIDENT_TAG_KEYWORDS = ["error", "broken", "incident", "deprecated", "anomaly"]

# --- "lag-aware" mechanism (see docs/LAG_AWARE_DIAGNOSIS.md) ---
# Half-life, in hours, of the exponential decay applied to the weight of
# evidence with a real timestamp (schema_change, stale_data): older
# evidence weighs less when picking the root cause, never reaching zero.
# Doesn't apply to incident_tag/unowned (no reliable timestamp available).
LAG_DECAY_HALFLIFE_HOURS = float(os.getenv("MAJESTIC_LAG_DECAY_HALFLIFE_HOURS", "48"))

# If two consecutive hops of the causal chain have the same evidence_type,
# the hop closer to the target gets multiplied by this factor — it's more
# likely inheriting the problem from the farther hop than contributing an
# independent signal.
UPSTREAM_INHERITANCE_DISCOUNT = float(os.getenv("MAJESTIC_UPSTREAM_INHERITANCE_DISCOUNT", "0.5"))

# How many ranked root-cause candidates to return (ranked_candidates),
# not just the top one.
RANKED_CANDIDATES_TOP_K = int(os.getenv("MAJESTIC_RANKED_CANDIDATES_TOP_K", "3"))

# --- check-change (RiskAssessor) ---
# risk_score >= this threshold => check-change blocks (exit 1) instead of
# approving. A heuristic, same as _EVIDENCE_WEIGHTS in diagnoser.py: the
# default isn't calibrated against real incidents, but it IS configurable
# (unlike _EVIDENCE_WEIGHTS, which are code constants) because here the
# cost of tuning it per organization is legitimate: how risk-tolerant a
# team is is a business decision, not a property of the algorithm.
CHECK_CHANGE_RISK_THRESHOLD = float(os.getenv("MAJESTIC_CHECK_CHANGE_RISK_THRESHOLD", "0.5"))

# --- Incident listener (src/events/listener.py) ---
# Seconds between each poll to DataHub looking for datasets with a new
# incident tag. 5s by default: fast enough for a live demo, without
# hammering the GMS in prolonged real usage.
LISTENER_POLL_INTERVAL_SECONDS = float(os.getenv("MAJESTIC_LISTENER_POLL_INTERVAL_SECONDS", "5"))
