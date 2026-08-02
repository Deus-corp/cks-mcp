"""
Draft/scratch version of the structural HTML extractor -- single-pass
HTMLParser that pulls out JSON-LD, OpenGraph/meta/Twitter-card tags,
schema.org microdata, tables, lists, and heading-delimited text
sections all from one parse of the document.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "title"}
_WHITESPACE_RE = re.compile(r"\s+")

_MAX_JSON_LD = 20
_MAX_MICRODATA = 30
_MAX_TABLES = 20
_MAX_TABLE_ROWS = 200
_MAX_LISTS = 30
_MAX_LIST_ITEMS = 100
_MAX_SECTIONS = 50
_MAX_SECTION_CHARS = 3000


def _norm(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


class _Frame:
    """One entry in the open-tag stack, carrying whatever bookkeeping
    the various extractors (microdata/table/list/heading) need while
    this element is open."""

    __slots__ = (
        "is_cell",
        "is_li",
        "is_list",
        "is_table",
        "itemprop_capture_content",
        "itemprop_name",
        "link_prop_name",
        "microdata_ctx",
        "parent_ctx_for_link",
        "tag",
        "text_parts",
    )

    def __init__(self, tag: str):
        self.tag = tag
        self.microdata_ctx: dict | None = None
        self.parent_ctx_for_link: dict | None = None
        self.link_prop_name: str | None = None
        self.itemprop_name: str | None = None
        self.itemprop_capture_content: str | None = None
        self.text_parts: list[str] | None = None
        self.is_table = False
        self.is_cell = False
        self.is_list = False
        self.is_li = False


class DocumentStructureParser(HTMLParser):
    """
    Extracts, in one pass:
      - json_ld: list[dict]            (parsed <script type="application/ld+json">)
      - microdata: list[dict]          ({"type":.., "properties": {...}})
      - open_graph: dict[str, str]     (og:* meta properties)
      - twitter: dict[str, str]        (twitter:* meta names)
      - meta: dict[str, str]           (other <meta name=...> tags)
      - tables: list[dict]             ({"caption":.., "headers": [...], "rows": [[...]]})
      - lists: list[dict]              ({"ordered": bool, "items": [...]})
      - sections: list[dict]           ({"heading":.., "level":.., "content":.., "order": int})
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[dict] = []
        self.microdata: list[dict] = []
        self.open_graph: dict[str, str] = {}
        self.twitter: dict[str, str] = {}
        self.meta: dict[str, str] = {}
        self.tables: list[dict] = []
        self.lists: list[dict] = []
        self.sections: list[dict] = []

        self._stack: list[_Frame] = []
        self._skip_depth = 0

        # JSON-LD
        self._json_ld_depth = 0
        self._json_ld_buffer: list[str] = []

        # Table building (only the outermost table on the stack is built)
        self._table_depth = 0
        self._cur_table: dict | None = None
        self._cur_row: list[str] | None = None
        self._cur_row_is_header = False
        self._in_caption = False
        self._caption_buffer: list[str] = []

        # List building (only the outermost list on the stack is built)
        self._list_depth = 0
        self._cur_list: dict | None = None

        # Section building (heading-delimited)
        self._cur_section: dict | None = None
        self._section_order = 0
        self._text_buffer: list[str] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_default_section(self) -> None:
        if self._cur_section is None and len(self.sections) < _MAX_SECTIONS:
            self._cur_section = {
                "heading": None, "level": None,
                "content_parts": [], "order": self._section_order,
            }
            self._section_order += 1
            self.sections.append(self._cur_section)

    def _flush_text_to_section(self) -> None:
        if self._text_buffer:
            text = _norm(" ".join(self._text_buffer))
            self._text_buffer = []
            if text:
                self._ensure_default_section()
                if self._cur_section is not None:
                    self._cur_section["content_parts"].append(text)

    def _current_microdata_ctx(self) -> dict | None:
        for f in reversed(self._stack):
            if f.microdata_ctx is not None:
                return f.microdata_ctx
        return None

    def _assign_prop(self, props: dict, key: str, value: Any) -> None:
        if key in props:
            if isinstance(props[key], list):
                props[key].append(value)
            else:
                props[key] = [props[key], value]
        else:
            props[key] = value

    # ------------------------------------------------------------------
    # Tag handling
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        frame = _Frame(tag)

        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
            if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
                self._json_ld_depth += 1
                self._json_ld_buffer = []
            self._stack.append(frame)
            return

        if self._skip_depth > 0:
            self._stack.append(frame)
            return

        if tag == "meta":
            self._handle_meta(attrs)
            self._stack.append(frame)
            return

        parent_ctx = self._current_microdata_ctx()

        if "itemprop" in attrs:
            frame.itemprop_name = attrs["itemprop"]
            if "content" in attrs:
                frame.itemprop_capture_content = attrs["content"]
            elif tag in ("a", "link") and "href" in attrs:
                frame.itemprop_capture_content = attrs["href"]
            elif tag == "img" and "src" in attrs:
                frame.itemprop_capture_content = attrs["src"]
            elif tag == "time" and "datetime" in attrs:
                frame.itemprop_capture_content = attrs["datetime"]
            else:
                frame.text_parts = []

        if "itemscope" in attrs:
            itemtype = attrs.get("itemtype", "")
            schema_type = itemtype.rstrip("/").rsplit("/", 1)[-1] if itemtype else None
            ctx = {"type": schema_type, "properties": {}}
            frame.microdata_ctx = ctx
            frame.parent_ctx_for_link = parent_ctx
            frame.link_prop_name = frame.itemprop_name
            frame.itemprop_name = None  # consumed by nested-object link, not text capture
            frame.text_parts = None

        # -- tables --
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1 and len(self.tables) < _MAX_TABLES:
                self._cur_table = {"caption": None, "headers": [], "rows": []}
                frame.is_table = True
            self._stack.append(frame)
            return
        if self._table_depth >= 1:
            if tag == "caption" and self._table_depth == 1:
                self._in_caption = True
                self._caption_buffer = []
            elif tag == "tr" and self._table_depth == 1:
                self._cur_row = []
                self._cur_row_is_header = False
            elif tag in ("td", "th") and self._table_depth == 1:
                frame.is_cell = True
                frame.text_parts = []
                if tag == "th":
                    self._cur_row_is_header = True
            self._stack.append(frame)
            return

        # -- lists --
        if tag in ("ul", "ol"):
            self._list_depth += 1
            if self._list_depth == 1 and len(self.lists) < _MAX_LISTS:
                self._cur_list = {"ordered": tag == "ol", "items": []}
                frame.is_list = True
            self._stack.append(frame)
            return
        if self._list_depth >= 1:
            if tag == "li" and self._list_depth == 1:
                frame.is_li = True
                frame.text_parts = []
            self._stack.append(frame)
            return

        # -- headings (section boundaries); not reached while inside a
        # table/list because those return early above --
        if tag in _HEADING_TAGS:
            self._flush_text_to_section()
            level = int(tag[1])
            self._cur_section = {
                "heading": None, "level": level,
                "content_parts": [], "order": self._section_order,
            }
            self._section_order += 1
            if len(self.sections) < _MAX_SECTIONS:
                self.sections.append(self._cur_section)
            frame.text_parts = []
            self._stack.append(frame)
            return

        self._stack.append(frame)

    def handle_startendtag(self, tag: str, attrs_list) -> None:
        # XHTML-style self-closing tags, e.g. <meta ... />
        self.handle_starttag(tag, attrs_list)
        if tag not in _SKIP_TEXT_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        # Lenient matching: pop until we find the matching tag name, to
        # recover from unbalanced/tag-soup markup instead of desyncing
        # the whole parse on one stray/unclosed tag.
        idx = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                idx = i
                break
        if idx is None:
            return  # stray end tag with no matching open tag; ignore

        # Pop everything down to (and including) the matching frame.
        # Only the LAST popped frame (the deepest nested one, popped
        # first) corresponds to the actual `tag` being closed when the
        # stack was well-formed; any frames popped before it were left
        # unclosed by the source markup (best-effort recovery, no-op
        # for them beyond removing them from the stack).
        frame = None
        while len(self._stack) > idx:
            frame = self._stack.pop()
        assert frame is not None

        if tag in _SKIP_TEXT_TAGS:
            if tag == "script" and self._json_ld_depth > 0:
                self._json_ld_depth -= 1
                if self._json_ld_depth == 0:
                    raw = "".join(self._json_ld_buffer)
                    self._json_ld_buffer = []
                    self._ingest_json_ld(raw)
            self._skip_depth -= 1
            return

        if self._skip_depth > 0:
            return

        # -- microdata close --
        if frame.microdata_ctx is not None:
            ctx = frame.microdata_ctx
            if frame.parent_ctx_for_link is not None and frame.link_prop_name:
                self._assign_prop(frame.parent_ctx_for_link["properties"], frame.link_prop_name, ctx)
            else:
                if len(self.microdata) < _MAX_MICRODATA:
                    self.microdata.append(ctx)
            return

        if frame.itemprop_name:
            parent_ctx = self._current_microdata_ctx()
            if parent_ctx is not None:
                value = (
                    frame.itemprop_capture_content
                    if frame.itemprop_capture_content is not None
                    else _norm("".join(frame.text_parts or []))
                )
                self._assign_prop(parent_ctx["properties"], frame.itemprop_name, value)
            return

        # -- tables --
        if tag == "table":
            self._table_depth -= 1
            if frame.is_table and self._cur_table is not None:
                self.tables.append(self._cur_table)
                self._cur_table = None
            return
        if tag == "caption" and self._in_caption:
            self._in_caption = False
            if self._cur_table is not None:
                self._cur_table["caption"] = _norm("".join(self._caption_buffer)) or None
            self._caption_buffer = []
            return
        if tag in ("td", "th") and frame.is_cell:
            text = _norm("".join(frame.text_parts or []))
            if self._cur_row is not None:
                self._cur_row.append(text)
            return
        if tag == "tr" and self._cur_row is not None:
            if self._cur_table is not None and len(self._cur_table["rows"]) < _MAX_TABLE_ROWS:
                if self._cur_row_is_header and not self._cur_table["headers"]:
                    self._cur_table["headers"] = self._cur_row
                else:
                    self._cur_table["rows"].append(self._cur_row)
            self._cur_row = None
            self._cur_row_is_header = False
            return

        # -- lists --
        if tag in ("ul", "ol"):
            self._list_depth -= 1
            if frame.is_list and self._cur_list is not None:
                self.lists.append(self._cur_list)
                self._cur_list = None
            return
        if tag == "li" and frame.is_li:
            text = _norm("".join(frame.text_parts or []))
            if self._cur_list is not None and text and len(self._cur_list["items"]) < _MAX_LIST_ITEMS:
                self._cur_list["items"].append(text)
            return

        # -- headings --
        if tag in _HEADING_TAGS:
            heading_text = _norm("".join(frame.text_parts or []))
            if self._cur_section is not None:
                self._cur_section["heading"] = heading_text or None
            return

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            if self._json_ld_depth > 0:
                self._json_ld_buffer.append(data)
            return
        if not self._stack:
            self._text_buffer.append(data)
            return

        # Feed every open frame that is itself directly collecting text
        # (heading / cell / li / text-valued itemprop) -- not just the
        # innermost one, so e.g. `<td><b>text</b></td>` still reaches
        # the cell's buffer even though `<b>` is the immediate parent.
        collected = False
        for f in reversed(self._stack):
            if f.text_parts is not None:
                f.text_parts.append(data)
                collected = True
            if f.is_table or f.is_list or f.tag in _HEADING_TAGS or f.itemprop_name:
                # Stop climbing once we hit the frame that "owns" this
                # text context (cell/li/heading/itemprop element) --
                # anything above it (e.g. the containing table/list) is
                # a different scope and should not also receive it.
                break
            if f is self._stack[0]:
                break

        if self._in_caption:
            self._caption_buffer.append(data)
            return

        if not collected and self._table_depth == 0 and self._list_depth == 0:
            self._text_buffer.append(data)

    # ------------------------------------------------------------------
    # meta / JSON-LD
    # ------------------------------------------------------------------

    def _handle_meta(self, attrs: dict[str, str]) -> None:
        content = attrs.get("content")
        if content is None:
            return
        prop = attrs.get("property", "")
        name = attrs.get("name", "")
        if prop.startswith("og:"):
            self.open_graph[prop[3:]] = content
        elif name.startswith("twitter:"):
            self.twitter[name[len("twitter:"):]] = content
        elif name:
            self.meta[name] = content

    def _ingest_json_ld(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return
        self._flatten_json_ld(parsed)

    def _flatten_json_ld(self, parsed: Any) -> None:
        if len(self.json_ld) >= _MAX_JSON_LD:
            return
        if isinstance(parsed, list):
            for item in parsed:
                self._flatten_json_ld(item)
            return
        if isinstance(parsed, dict):
            if isinstance(parsed.get("@graph"), list):
                for item in parsed["@graph"]:
                    self._flatten_json_ld(item)
                return
            self.json_ld.append(parsed)

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        self._flush_text_to_section()
        for section in self.sections:
            content = " ".join(section.pop("content_parts", []))
            section["content"] = content[:_MAX_SECTION_CHARS]
        # Drop fully-empty sections (no heading, no content) -- can
        # happen for a leading default section when the document has
        # no preamble text before its first heading.
        self.sections = [s for s in self.sections if s["heading"] or s["content"]]


def parse_document_structure(html: str) -> DocumentStructureParser:
    parser = DocumentStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: S110 — best-effort parser: ignore any parsing failure
        pass
    parser.finalize()
    return parser