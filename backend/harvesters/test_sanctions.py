from backend.harvesters.sanctions import _names_match


def test_vessel_name_matching_is_conservative():
    assert _names_match("VISTA III", "Vista-III")
    assert _names_match("SEA FALCON IMO 123", "SEA FALCON")
    assert not _names_match("SAL", "MARSHAL VICTORY")
    assert not _names_match("", "ANY VESSEL")
