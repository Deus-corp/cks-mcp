"""
Enrichment Agent support modules: candidate discovery, scoring, and
filtering for growing the knowledge graph from external sources.

See ROADMAP.md's "Enrichment Agent" section and ``cks_mcp.enrichment_agent``
(the claim -> resolve -> complete/fail/dead-letter loop itself, mirroring
``cks_mcp.critic_agent``) for the pieces that use these.

Some of the deterministic, no-network-I/O logic here (URL scoring
heuristics, low-value-URL filtering) is adapted from patterns used in an
unrelated internal crawler project's frontier-quality filters -- reworked
against CKS's own data model, not a code port. That project's CRDT swarm
coordination and recursive-crawl frontier model don't apply here: this
agent does one bounded search -> filter -> ingest -> link pass per task,
not open-ended crawling.
"""

from __future__ import annotations