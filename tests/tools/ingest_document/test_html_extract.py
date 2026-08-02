import json

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

parser = parse_document_structure(HTML)
print("=== JSON-LD ===")
print(json.dumps(parser.json_ld, indent=2))
print("=== Microdata ===")
print(json.dumps(parser.microdata, indent=2))
print("=== OpenGraph ===")
print(parser.open_graph)
print("=== Twitter ===")
print(parser.twitter)
print("=== Meta ===")
print(parser.meta)
print("=== Tables ===")
print(json.dumps(parser.tables, indent=2))
print("=== Lists ===")
print(json.dumps(parser.lists, indent=2))
print("=== Sections ===")
print(json.dumps(parser.sections, indent=2))