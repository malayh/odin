from odin.services import ontology


def test_known_type_normalizes_case_insensitively():
    assert ontology.normalize_type("person") == ("Person", False)
    assert ontology.normalize_type("ORG") == ("Org", False)


def test_novel_type_is_accepted_and_flagged():
    norm, is_new = ontology.normalize_type("space station")
    assert is_new is True
    assert norm == "SpaceStation"


def test_known_predicate_normalizes():
    assert ontology.normalize_predicate("works at") == ("WORKS_AT", False)
    assert ontology.normalize_predicate("BUILDS") == ("BUILDS", False)


def test_novel_predicate_is_accepted_and_flagged():
    norm, is_new = ontology.normalize_predicate("founded by")
    assert (norm, is_new) == ("FOUNDED_BY", True)


def test_entity_key_is_deterministic_and_scope_agnostic():
    a = ontology.entity_key("  Acme   Corp ", "Org")
    b = ontology.entity_key("acme corp", "org")
    assert a == b == "org:acme corp"


def test_entity_key_includes_type():
    assert ontology.entity_key("Mercury", "Place") != ontology.entity_key("Mercury", "Product")
