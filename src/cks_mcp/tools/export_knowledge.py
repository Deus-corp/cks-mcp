"""
export_knowledge: export a session's Knowledge Structure to RDF/JSON-LD/Turtle formats.

Uses cks-core's built-in adapters (CksToJsonLdConverter, CksToRdfConverter)
which are already fully implemented and tested upstream.
"""

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found


def export_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    format = arguments.get("format", "json-ld").lower()
    structure = session.knowledge_structure

    if format == "json-ld":
        from cks.adapters.cks_to_jsonld import CksToJsonLdConverter

        converter = CksToJsonLdConverter(structure)
        result = converter.convert()
        return {"format": "json-ld", "data": result}

    if format in ("turtle", "rdf-xml", "rdf_xml"):
        from cks.adapters.cks_to_rdf import CksToRdfConverter

        converter = CksToRdfConverter(structure)
        if format == "turtle":
            data = converter.to_turtle()
        else:
            data = converter.to_rdfxml()
        return {"format": format, "data": data}

    return {
        "error": "unsupported_format",
        "message": f"Format '{format}' is not supported. Use 'json-ld', 'turtle', or 'rdf-xml'.",
    }
