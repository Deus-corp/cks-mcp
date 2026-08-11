"""
Phase 1 safety infrastructure: per-pipeline-run token/cost budgeting.

``TokenBudget`` is a small, storage-free guard an orchestrator run
carries for its own lifetime (one instance per ``run_sequential``/
``run_concurrent`` call -- it is *not* meant to be shared across runs
or persisted). Each ``AgentStep.run`` is expected to call ``consume()``
before making its LLM call; once the budget is exhausted every
subsequent step in the same run short-circuits with
``Resolution(False, "budget_exhausted")`` instead of spending more
tokens.

Defaults come from environment variables so a deployment can tune them
without a code change:

- ``CKS_PIPELINE_MAX_TOKENS`` (default 100_000)
- ``CKS_PIPELINE_MAX_COST_USD`` (default 0.50)

Cost tracking is deliberately approximate: callers pass a
``cost_per_token`` (or rely on the default) rather than this module
trying to know per-model pricing itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_DEFAULT_MAX_TOKENS = 100_000
_DEFAULT_MAX_COST_USD = 0.50
# Rough, deliberately conservative blended per-token cost used only
# when a caller doesn't supply its own -- good enough to catch a
# runaway pipeline, not meant to be exact billing.
_DEFAULT_COST_PER_TOKEN = 0.000003


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def default_max_tokens() -> int:
    return _env_int("CKS_PIPELINE_MAX_TOKENS", _DEFAULT_MAX_TOKENS)


def default_max_cost_usd() -> float:
    return _env_float("CKS_PIPELINE_MAX_COST_USD", _DEFAULT_MAX_COST_USD)


@dataclass(slots=True)
class TokenBudget:
    """Tracks tokens (and an approximate USD cost) spent by one
    pipeline run.

    Exhaustion is "whichever limit is hit first": once either the
    token cap or the cost cap is reached, ``consume()`` starts
    returning ``False`` and stays that way -- a ``TokenBudget`` never
    resets itself; callers create a new one per run.
    """

    max_tokens: int = field(default_factory=default_max_tokens)
    max_cost_usd: float = field(default_factory=default_max_cost_usd)
    cost_per_token: float = _DEFAULT_COST_PER_TOKEN
    _tokens_spent: int = field(default=0, init=False, repr=False)
    _cost_spent_usd: float = field(default=0.0, init=False, repr=False)
    _exhausted: bool = field(default=False, init=False, repr=False)

    def consume(self, tokens: int) -> bool:
        """Record ``tokens`` spent and report whether the budget still
        has room.

        Returns ``False`` (without recording the spend) if the budget
        is already exhausted, or if recording this spend would push
        either the token or cost cap over its limit. A caller that
        gets ``False`` back must not proceed with the LLM call it was
        about to make -- the spend was *not* recorded in that case.
        """
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        if self._exhausted:
            return False

        prospective_tokens = self._tokens_spent + tokens
        prospective_cost = self._cost_spent_usd + tokens * self.cost_per_token

        if prospective_tokens > self.max_tokens or prospective_cost > self.max_cost_usd:
            self._exhausted = True
            return False

        self._tokens_spent = prospective_tokens
        self._cost_spent_usd = prospective_cost
        return True

    def remaining(self) -> int:
        """Tokens still available under the token cap (ignores the
        cost cap; a budget can still be cost-exhausted while this is
        positive)."""
        return max(0, self.max_tokens - self._tokens_spent)

    def remaining_cost_usd(self) -> float:
        return max(0.0, self.max_cost_usd - self._cost_spent_usd)

    @property
    def tokens_spent(self) -> int:
        return self._tokens_spent

    @property
    def cost_spent_usd(self) -> float:
        return self._cost_spent_usd

    @property
    def exhausted(self) -> bool:
        return self._exhausted
