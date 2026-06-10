"""Tests for Zep type-name normalization (app/utils/naming.py)."""

from app.utils.naming import to_pascal_case, to_screaming_snake, normalize_ontology_names


def test_snake_case_with_acronym():
    assert to_pascal_case("AI_Lab_Leader") == "AILabLeader"


def test_plain_snake():
    assert to_pascal_case("Media_Outlet") == "MediaOutlet"


def test_edge_names_screaming_snake():
    assert to_screaming_snake("INVESTS_IN") == "INVESTS_IN"  # idempotent
    assert to_screaming_snake("InvestsIn") == "INVESTS_IN"
    assert to_screaming_snake("reports-on") == "REPORTS_ON"
    assert to_screaming_snake("") == "RELATES_TO"


def test_already_pascal_is_idempotent():
    for name in ("Person", "APIKey", "AILabLeader", "InvestsIn", "UserProfile"):
        assert to_pascal_case(name) == name


def test_spaces_and_hyphens():
    assert to_pascal_case("sovereign investor") == "SovereignInvestor"
    assert to_pascal_case("media-outlet") == "MediaOutlet"


def test_empty_and_digit_start():
    assert to_pascal_case("") == "Entity"
    assert to_pascal_case("3d_printer") == "T3dPrinter"


def test_normalize_ontology_dedupes_and_fixes_source_targets():
    ontology = {
        "entity_types": [
            {"name": "Media_Outlet"},
            {"name": "media outlet"},  # collides after normalization
            {"name": "Investor"},
        ],
        "edge_types": [
            {"name": "REPORTS_ON", "source_targets": [{"source": "Media_Outlet", "target": "Investor"}]},
        ],
    }
    normalize_ontology_names(ontology)
    names = [e["name"] for e in ontology["entity_types"]]
    assert names == ["MediaOutlet", "Investor"]
    edge = ontology["edge_types"][0]
    assert edge["name"] == "REPORTS_ON"
    assert edge["source_targets"][0] == {"source": "MediaOutlet", "target": "Investor"}
