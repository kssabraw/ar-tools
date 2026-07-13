"""Unit tests for the LeadOff county backfill pure helpers (no network/DB)."""
from services.leadoff_counties import bare_county, county_matches, parse_county


def _census(name, geoid, layer="Counties"):
    return {"result": {"geographies": {layer: [
        {"NAME": name, "BASENAME": name.rsplit(" ", 1)[0], "GEOID": geoid}]}}}


class TestParseCounty:
    def test_parses_name_and_fips(self):
        assert parse_county(_census("Hudson County", "34017")) == \
            ("Hudson County", "34017")

    def test_tolerates_layer_label(self):
        assert parse_county(_census("Orleans Parish", "22071", layer="2020 Census Counties")) == \
            ("Orleans Parish", "22071")

    def test_no_county_layer_is_none(self):
        assert parse_county({"result": {"geographies": {"States": []}}}) is None
        assert parse_county({"result": {"geographies": {}}}) is None
        assert parse_county({}) is None

    def test_missing_fields_is_none(self):
        assert parse_county({"result": {"geographies": {"Counties": [
            {"NAME": "", "GEOID": ""}]}}}) is None
        # name present but no fips → unusable
        assert parse_county({"result": {"geographies": {"Counties": [
            {"NAME": "Cook County"}]}}}) is None

    def test_falls_back_to_basename(self):
        assert parse_county({"result": {"geographies": {"Counties": [
            {"BASENAME": "Cook", "GEOID": "17031"}]}}}) == ("Cook", "17031")

    def test_ignores_county_subdivisions_layer(self):
        # Regression: the real Census response for a coordinate carries BOTH
        # "County Subdivisions" and "Counties" layers. "County Subdivisions"
        # also contains the substring "count", so a bare substring match picks
        # it first — every live row came back as the city's own MCD (e.g.
        # "Jersey City city", a 10-digit GEOID) instead of its real county
        # (Hudson County, 5-digit GEOID). Order the dict as the real API does
        # (subdivision layer listed before the county layer) to prove the fix
        # skips it regardless of iteration order.
        resp = {"result": {"geographies": {
            "County Subdivisions": [{"NAME": "Jersey City city",
                                     "GEOID": "3401736000"}],
            "Counties": [{"NAME": "Hudson County", "GEOID": "34017"}],
        }}}
        assert parse_county(resp) == ("Hudson County", "34017")

    def test_rejects_non_5digit_fips_even_if_layer_key_matches(self):
        # Defense-in-depth: a 10-digit GEOID under a layer key that still
        # slipped past the subdivision filter must be refused, not stored.
        assert parse_county({"result": {"geographies": {"Counties": [
            {"NAME": "Jersey City city", "GEOID": "3401736000"}]}}}) is None


class TestBareCounty:
    def test_strips_governance_suffix(self):
        assert bare_county("Hudson County") == "Hudson"
        assert bare_county("Orleans Parish") == "Orleans"
        assert bare_county("Denali Borough") == "Denali"
        assert bare_county("Prince of Wales-Hyder Census Area") == \
            "Prince of Wales-Hyder"

    def test_leaves_bare_name(self):
        assert bare_county("Hudson") == "Hudson"


class TestCountyMatches:
    def test_full_and_bare_forms(self):
        assert county_matches("Hudson County", "Hudson County")
        assert county_matches("Hudson County", "hudson")
        assert county_matches("Hudson County", "HUDSON COUNTY")
        assert county_matches("Orleans Parish", "orleans")

    def test_non_match(self):
        assert not county_matches("Hudson County", "Bergen")
        assert not county_matches("", "Hudson")
        assert not county_matches("Hudson County", "")
