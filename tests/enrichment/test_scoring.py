from __future__ import annotations

from cks_mcp.enrichment.scoring import score_candidate


def test_relevant_high_authority_beats_irrelevant_high_authority():
    relevant = score_candidate(
        "https://arxiv.org/abs/2401.12345",
        title="Retrieval Augmented Generation for Knowledge Graphs",
        query="retrieval augmented generation knowledge graphs",
    )
    irrelevant = score_candidate(
        "https://arxiv.org/abs/1999.99999",
        title="A Study of Quantum Gravity",
        query="retrieval augmented generation knowledge graphs",
    )
    assert relevant > irrelevant


def test_high_authority_domain_beats_low_authority_at_equal_relevance():
    wiki = score_candidate(
        "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        title="Retrieval-augmented generation",
        query="retrieval augmented generation",
    )
    random_blog = score_candidate(
        "https://randomblog.example/retrieval-augmented-generation",
        title="Retrieval augmented generation",
        query="retrieval augmented generation",
    )
    assert wiki > random_blog


def test_score_is_bounded():
    score = score_candidate(
        "https://arxiv.org/abs/2401.12345",
        title="retrieval augmented generation " * 20,
        query="retrieval augmented generation",
    )
    assert 0.0 <= score <= 1.0


def test_empty_query_is_neutral_not_zero():
    score = score_candidate("https://example.com/anything", title="", query="")
    assert score > 0.0


def test_unknown_domain_gets_baseline_authority():
    score = score_candidate("https://totally-unknown-domain.example/page", title="x", query="x")
    assert score > 0.0


# Regression: authority alone must not be able to carry a candidate with
# zero query relevance over CKS_ENRICHMENT_MIN_SCORE's default of 0.5 --
# relevance has to be able to veto a candidate, not just rank it, or the
# "filter" step is fiction for the two DEFAULT_ADAPTERS (both high-
# authority domains).
_DEFAULT_MIN_SCORE = 0.5


def test_zero_overlap_arxiv_result_is_rejected_by_default_threshold():
    score = score_candidate(
        "https://arxiv.org/abs/1999.99999",
        title="A Study of Quantum Gravity",
        query="retrieval augmented generation knowledge graphs",
    )
    assert score < _DEFAULT_MIN_SCORE


def test_zero_overlap_wikipedia_result_is_rejected_by_default_threshold():
    score = score_candidate(
        "https://en.wikipedia.org/wiki/Some_Unrelated_Topic",
        title="Some Unrelated Topic",
        query="retrieval augmented generation knowledge graphs",
    )
    assert score < _DEFAULT_MIN_SCORE


def test_relevant_arxiv_result_clears_default_threshold():
    score = score_candidate(
        "https://arxiv.org/abs/2401.12345",
        title="Retrieval Augmented Generation for Knowledge Graphs",
        query="retrieval augmented generation knowledge graphs",
    )
    assert score >= _DEFAULT_MIN_SCORE


def test_candidate_with_no_comparable_text_scores_zero_relevance_component():
    # Query given, but title/url path/query carry nothing to compare it
    # against -- absence of evidence, not neutral, so it should land at
    # the pure-authority floor (0.4 * authority), not higher.
    score = score_candidate("https://arxiv.org/", title="", query="retrieval augmented generation")
    assert score == round(0.4 * 0.92, 4)