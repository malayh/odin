"""Curated entity/relation ontology: normalization + open-extension validation."""

import re

ENTITY_TYPES = frozenset({"Person", "Org", "Project", "Place", "Topic", "Event", "Product"})
PREDICATES = frozenset(
    {"WORKS_AT", "BUILDS", "HAS_A", "RELATED_TO", "PART_OF", "LOCATED_IN", "CREATED_BY", "USES"}
)


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def normalize_type(raw: str) -> tuple[str, bool]:
    s = _collapse(raw)
    for t in ENTITY_TYPES:
        if t.lower() == s.lower():
            return t, False
    return _collapse(s).title().replace(" ", ""), True


def normalize_predicate(raw: str) -> tuple[str, bool]:
    norm = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_").upper()
    return norm, norm not in PREDICATES


def entity_key(name: str, type_: str) -> str:
    canonical, _ = normalize_type(type_)
    return f"{canonical.lower()}:{_collapse(name).lower()}"
