"""
Name normalization for Zep ontology types.

Zep's API enforces two different naming rules (confirmed against the live API,
June 2026):
  - ENTITY type names must be PascalCase, alphanumeric only
    (e.g. 'EntityType', 'UserProfile', 'APIKey')
  - EDGE type names must be SCREAMING_SNAKE_CASE
    (e.g. 'RELATES_TO', 'CREATED_BY')
  - An edge's source/target fields reference entity types, so they follow the
    PascalCase rule.

The LLM does not reliably produce either convention, so everything that sends
type names to Zep, or compares against labels stored by Zep, must pass them
through these converters. Both are idempotent: a name already in the target
convention passes through unchanged.
"""

import re
from typing import Any, Dict

_ACRONYM_MAX_LEN = 4


def to_pascal_case(name: str) -> str:
    """Convert any type name to Zep-valid PascalCase.

    'AI_Lab_Leader' -> 'AILabLeader' (short all-caps tokens kept when the name
    is mixed-case, so deliberate acronyms survive), 'INVESTS_IN' -> 'InvestsIn'
    (an all-caps name is treated as shouting, not acronyms), 'Media Outlet' ->
    'MediaOutlet', 'APIKey' -> 'APIKey'.
    """
    if not name:
        return "Entity"

    has_lowercase = any(c.islower() for c in name)
    tokens = [t for t in re.split(r"[^0-9a-zA-Z]+", name) if t]

    parts = []
    for tok in tokens:
        if tok.isupper() and has_lowercase and len(tok) <= _ACRONYM_MAX_LEN:
            parts.append(tok)
        elif tok.isupper():
            parts.append(tok[0] + tok[1:].lower())
        else:
            parts.append(tok[0].upper() + tok[1:])

    result = "".join(parts) or "Entity"
    if result[0].isdigit():
        result = "T" + result
    return result


def to_screaming_snake(name: str) -> str:
    """Convert any edge type name to Zep-valid SCREAMING_SNAKE_CASE.

    'InvestsIn' -> 'INVESTS_IN', 'reports-on' -> 'REPORTS_ON',
    'INVESTS_IN' -> 'INVESTS_IN' (idempotent).
    """
    if not name:
        return "RELATES_TO"

    # Insert underscores at lower-to-upper camel boundaries, then squash any
    # non-alphanumeric runs into single underscores.
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").upper()
    if not s:
        return "RELATES_TO"
    if s[0].isdigit():
        s = "R_" + s
    return s


def normalize_ontology_names(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize all type names in an ontology dict, in place.

    Entity names become PascalCase; edge names become SCREAMING_SNAKE_CASE;
    each edge's source/target entity references become PascalCase. Collisions
    after conversion (e.g. 'Media_Outlet' and 'media outlet') keep the first
    occurrence and drop the rest.
    """
    seen_entities = set()
    deduped_entities = []
    for entity in ontology.get("entity_types", []):
        entity["name"] = to_pascal_case(entity.get("name", ""))
        if entity["name"] in seen_entities:
            continue
        seen_entities.add(entity["name"])
        deduped_entities.append(entity)
    if "entity_types" in ontology:
        ontology["entity_types"] = deduped_entities

    seen_edges = set()
    deduped_edges = []
    for edge in ontology.get("edge_types", []):
        edge["name"] = to_screaming_snake(edge.get("name", ""))
        for st in edge.get("source_targets", []):
            if st.get("source"):
                st["source"] = to_pascal_case(st["source"])
            if st.get("target"):
                st["target"] = to_pascal_case(st["target"])
        if edge["name"] in seen_edges:
            continue
        seen_edges.add(edge["name"])
        deduped_edges.append(edge)
    if "edge_types" in ontology:
        ontology["edge_types"] = deduped_edges

    return ontology
