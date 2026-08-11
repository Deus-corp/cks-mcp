"""Unit tests for cks_mcp.pipeline.token_budget.TokenBudget."""

from __future__ import annotations

import pytest

from cks_mcp.pipeline.token_budget import (
    TokenBudget,
    default_max_cost_usd,
    default_max_tokens,
)


def test_consume_within_limit_returns_true_and_tracks_spend():
    budget = TokenBudget(max_tokens=1000, max_cost_usd=100.0, cost_per_token=0.0)
    assert budget.consume(400) is True
    assert budget.tokens_spent == 400
    assert budget.remaining() == 600
    assert budget.exhausted is False


def test_consume_over_token_limit_returns_false_and_does_not_record():
    budget = TokenBudget(max_tokens=100, max_cost_usd=100.0, cost_per_token=0.0)
    assert budget.consume(60) is True
    assert budget.consume(50) is False  # would push total to 110 > 100
    assert budget.tokens_spent == 60  # the failed spend was not recorded
    assert budget.exhausted is True


def test_once_exhausted_stays_exhausted_even_for_small_requests():
    budget = TokenBudget(max_tokens=10, max_cost_usd=100.0, cost_per_token=0.0)
    assert budget.consume(11) is False
    assert budget.exhausted is True
    assert budget.consume(1) is False


def test_consume_over_cost_limit_returns_false():
    budget = TokenBudget(max_tokens=1_000_000, max_cost_usd=0.01, cost_per_token=0.01)
    assert budget.consume(2) is False
    assert budget.exhausted is True


def test_remaining_never_goes_negative():
    budget = TokenBudget(max_tokens=100, max_cost_usd=100.0, cost_per_token=0.0)
    budget.consume(100)
    assert budget.remaining() == 0
    assert budget.consume(1) is False
    assert budget.remaining() == 0


def test_negative_tokens_raises():
    budget = TokenBudget(max_tokens=100, max_cost_usd=100.0)
    with pytest.raises(ValueError):
        budget.consume(-1)


def test_defaults_come_from_environment(monkeypatch):
    monkeypatch.setenv("CKS_PIPELINE_MAX_TOKENS", "12345")
    monkeypatch.setenv("CKS_PIPELINE_MAX_COST_USD", "1.25")
    assert default_max_tokens() == 12345
    assert default_max_cost_usd() == 1.25

    budget = TokenBudget()
    assert budget.max_tokens == 12345
    assert budget.max_cost_usd == 1.25


def test_defaults_fall_back_when_env_unset_or_invalid(monkeypatch):
    monkeypatch.delenv("CKS_PIPELINE_MAX_TOKENS", raising=False)
    monkeypatch.delenv("CKS_PIPELINE_MAX_COST_USD", raising=False)
    assert default_max_tokens() == 100_000
    assert default_max_cost_usd() == 0.50

    monkeypatch.setenv("CKS_PIPELINE_MAX_TOKENS", "not-a-number")
    assert default_max_tokens() == 100_000
