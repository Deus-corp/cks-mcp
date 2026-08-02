"""
Tests for the single-pass structural HTML extractor
(``cks_mcp.tools.ingest_document.html_extract``).

Replaces the earlier version of this file, which only printed parser
output and contained no ``test_*`` functions or assertions -- pytest
collected zero tests from it (see CHANGELOG v1.20.1, which claimed
test coverage that this file did not actually provide).
"""
from __future__ import annotations

from cks_mcp.tools.ingest_document.html_extract import parse_document_structure

HTML = """
<html>
<head>
<title>Photosynthesis Basics</title>
<meta name="description" content="An intro to photosynthesis.">
<meta name="author" content="Jane Doe">
<meta property="og:title" content="Photosynthesis Basics (OG)">
<meta property="og:description" content="OG description here">
<meta property="og:image" content="https://example.com/img.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Photosynthesis Basics",
  "author": {"@type": "Person", "name": "Jane Doe"}
}
</script>
</head>
<body>
<div itemscope itemtype="https://schema.org/Product">
  <span itemprop="name">Solar Widget</span>
  <span itemprop="price">19.99</span>
</div>

<h1>Introduction</h1>
<p>Photosynthesis is the process by which plants convert light into energy.</p>
<p>It occurs mainly in the leaves.</p>

<h2>Key Stages</h2>
<p>There are two main stages: light-dependent reactions and the Calvin cycle.</p>

<table>
<caption>Stage Comparison</caption>
<tr><th>Stage</th><th>Location</th></tr>
<tr><td>Light reactions</td><td>Thylakoid membrane</td></tr>
<tr><td>Calvin cycle</td><td>Stroma</td></tr>
</table>

<ul>
<li>Chlorophyll absorbs light</li>
<li>Water is split</li>
<li>Oxygen is released</li>
</ul>

<h2>Conclusion</h2>
<p>Photosynthesis is essential for life on Earth.</p>
</body>
</html>
"""


def test_json_ld_extracted():
    parser = parse_document_structure(HTML)
    assert len(parser.json_ld) == 1
    assert parser.json_ld[0]["@type"] == "Article"
    assert parser.json_ld[0]["headline"] == "Photosynthesis Basics"


def test_microdata_extracted():
    parser = parse_document_structure(HTML)
    assert len(parser.microdata) == 1
    item = parser.microdata[0]
    assert item["type"] == "Product"
    assert item["properties"]["name"] == "Solar Widget"
    assert item["properties"]["price"] == "19.99"


def test_open_graph_and_twitter_extracted():
    parser = parse_document_structure(HTML)
    assert parser.open_graph["title"] == "Photosynthesis Basics (OG)"
    assert parser.open_graph["description"] == "OG description here"
    assert parser.open_graph["image"] == "https://example.com/img.png"
    assert parser.twitter["card"] == "summary_large_image"


def test_plain_meta_extracted():
    parser = parse_document_structure(HTML)
    assert parser.meta["description"] == "An intro to photosynthesis."
    assert parser.meta["author"] == "Jane Doe"


def test_table_extracted():
    parser = parse_document_structure(HTML)
    assert len(parser.tables) == 1
    table = parser.tables[0]
    assert table["caption"] == "Stage Comparison"
    assert table["headers"] == ["Stage", "Location"]
    assert table["rows"] == [
        ["Light reactions", "Thylakoid membrane"],
        ["Calvin cycle", "Stroma"],
    ]


def test_list_extracted():
    parser = parse_document_structure(HTML)
    assert len(parser.lists) == 1
    lst = parser.lists[0]
    assert lst["ordered"] is False
    assert lst["items"] == [
        "Chlorophyll absorbs light",
        "Water is split",
        "Oxygen is released",
    ]


def test_sections_extracted_and_heading_delimited():
    parser = parse_document_structure(HTML)
    headings = [s["heading"] for s in parser.sections]
    assert headings == ["Introduction", "Key Stages", "Conclusion"]

    intro = parser.sections[0]
    assert intro["level"] == 1
    assert "process by which plants convert light" in intro["content"]

    # Text inside the table/list must not leak into the surrounding section.
    key_stages = parser.sections[1]
    assert "Thylakoid membrane" not in key_stages["content"]
    assert "Chlorophyll absorbs light" not in key_stages["content"]


def test_empty_html_does_not_raise():
    parser = parse_document_structure("")
    assert parser.json_ld == []
    assert parser.microdata == []
    assert parser.tables == []
    assert parser.lists == []
    assert parser.sections == []


def test_malformed_html_does_not_raise():
    # Unbalanced/unclosed tags should be handled leniently, not crash.
    parser = parse_document_structure("<div><h1>Oops<p>no closing tags")
    assert isinstance(parser.sections, list)
