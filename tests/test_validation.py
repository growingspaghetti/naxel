import json
import pytest
from pathlib import Path
import app
from app import (
    _validate_system, _validate_schedule, _validate_contact, _validate_email,
    validate, _parse_system_sections,
    _csv_field, _csv_row, _empty_system_document,
    _text_to_system_json, _system_sections_to_text, _empty_system_json,
    load_additional_properties,
)


@pytest.fixture(autouse=True)
def _collection_types():
    app.COLLECTION_TYPE.update({"schedules": "DATE", "contacts": "PHONE_NUMBER"})
    yield
    app.COLLECTION_TYPE.pop("schedules", None)
    app.COLLECTION_TYPE.pop("contacts", None)

SEP = "🏔" * 20
M = "👉machine👈"
I = "👉id👈"
S = "👉schedule👈"
C = "👉contact👈"
T = "👉time👈"
N = "👉notes👈"


def sys_doc(*rows, props=()):
    """Build a system document from (machine, id, schedule, contact, time, notes) tuples."""
    parts = []
    for machine, id_, schedule, contact, time, notes in rows:
        section = [SEP, M, machine, I, id_, T, time, N, notes, S, schedule, C, contact]
        for pname, pval in props:
            section += [f"👉{pname}👈", pval]
        parts += section
    return "\n".join(parts) + "\n"


class TestValidateSystem:
    def test_single_section_valid(self):
        ok, _ = _validate_system(sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes")), ("schedule", "contact"))
        assert ok

    def test_multiple_sections_valid(self):
        ok, _ = _validate_system(
            sys_doc(("m1", "id1", "s1", "cont1", "08:00", "n1"), ("m2", "id2", "s2", "cont2", "09:00", "n2")),
            ("schedule", "contact"),
        )
        assert ok

    def test_multiline_notes_valid(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "line1", "line2", S, "s1", C, "cont1"]) + "\n"
        ok, _ = _validate_system(content, ("schedule", "contact"))
        assert ok

    def test_empty_content_rejected(self):
        ok, msg = _validate_system("")
        assert not ok
        assert "no sections" in msg

    def test_missing_separator_rejected(self):
        content = "\n".join([M, "m1", I, "id1", T, "12:00", N, "notes"]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "separator" in msg

    def test_empty_machine_value_rejected(self):
        content = "\n".join([SEP, M, "", I, "id1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_whitespace_only_machine_rejected(self):
        content = "\n".join([SEP, M, "   ", I, "id1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_empty_id_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_id_with_hash_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "#id1", T, "12:00", N, "notes"]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "#" in msg

    def test_id_without_hash_accepted(self):
        ok, _ = _validate_system(sys_doc(("m1", "anything", "s1", "cont1", "12:00", "notes")), ("schedule", "contact"))
        assert ok

    def test_empty_schedule_value_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "notes", S, ""]) + "\n"
        ok, _ = _validate_system(content, ("schedule",), mandatory_prop_names=frozenset({"schedule"}))
        assert not ok

    def test_empty_contact_value_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "notes", S, "s1", C, ""]) + "\n"
        ok, _ = _validate_system(content, ("schedule", "contact"), mandatory_prop_names=frozenset({"contact"}))
        assert not ok

    def test_empty_notes_accepted(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N]) + "\n"
        ok, _ = _validate_system(content)
        assert ok

    def test_invalid_time_format_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "9:00", N, "notes"]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "dd:dd" in msg

    def test_time_with_letters_rejected(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "ab:cd", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_valid_time_accepted(self):
        ok, _ = _validate_system(sys_doc(("m1", "id1", "s1", "cont1", "00:00", "notes")), ("schedule", "contact"))
        assert ok

    def test_wrong_label_rejected(self):
        content = "\n".join([SEP, "👉wrong👈", "m1", I, "id1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_error_includes_line_number(self):
        content = "\n".join([SEP, M, "", I, "id1", T, "12:00", N, "notes"]) + "\n"
        _, msg = _validate_system(content)
        assert "line" in msg


class TestValidateSchedule:
    def test_single_date_valid(self):
        ok, _ = _validate_schedule("2000/01/01")
        assert ok

    def test_multiple_dates_valid(self):
        ok, _ = _validate_schedule("1234/12/31,2000/06/01")
        assert ok

    def test_trailing_newline_valid(self):
        ok, _ = _validate_schedule("2000/01/01\n")
        assert ok

    def test_empty_rejected(self):
        ok, _ = _validate_schedule("")
        assert not ok

    def test_dash_separator_rejected(self):
        ok, _ = _validate_schedule("2000-01-01")
        assert not ok

    def test_space_separator_rejected(self):
        ok, _ = _validate_schedule("2000/01/01 2000/02/02")
        assert not ok

    def test_short_year_rejected(self):
        ok, _ = _validate_schedule("200/01/01")
        assert not ok

    def test_plain_text_rejected(self):
        ok, _ = _validate_schedule("not a date")
        assert not ok


class TestValidateEmail:
    def test_single_address_valid(self):
        ok, _ = _validate_email("user@example.com")
        assert ok

    def test_multiple_addresses_valid(self):
        ok, _ = _validate_email("a@b.com,c@d.org,e@f.co.jp")
        assert ok

    def test_trailing_newline_valid(self):
        ok, _ = _validate_email("user@example.com\n")
        assert ok

    def test_plus_in_local_part_valid(self):
        ok, _ = _validate_email("user+tag@example.com")
        assert ok

    def test_dots_in_local_part_valid(self):
        ok, _ = _validate_email("first.last@example.com")
        assert ok

    def test_empty_rejected(self):
        ok, _ = _validate_email("")
        assert not ok

    def test_no_at_sign_rejected(self):
        ok, _ = _validate_email("userexample.com")
        assert not ok

    def test_no_domain_dot_rejected(self):
        ok, _ = _validate_email("user@examplecom")
        assert not ok

    def test_plain_text_rejected(self):
        ok, _ = _validate_email("not an email")
        assert not ok

    def test_space_separator_rejected(self):
        ok, _ = _validate_email("a@b.com c@d.com")
        assert not ok


class TestValidateDispatch:
    def test_systems_routes_correctly(self):
        ok, _ = validate("systems", sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes")), ("schedule", "contact"))
        assert ok

    def test_schedules_routes_correctly(self):
        ok, _ = validate("schedules", "2000/01/01")
        assert ok

    def test_unknown_collection_passes(self):
        ok, _ = validate("unknown", "anything")
        assert ok


class TestParseSystemSections:
    def test_single_section(self):
        sections = _parse_system_sections(
            sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes")),
            ("schedule", "contact"),
        )
        assert len(sections) == 1
        assert sections[0] == {"machine": "m1", "id": "id1", "schedule": "s1", "contact": "cont1", "time": "12:00", "notes": "notes"}

    def test_multiple_sections(self):
        sections = _parse_system_sections(
            sys_doc(("m1", "id1", "s1", "cont1", "08:00", "n1"), ("m2", "id2", "s2", "cont2", "09:00", "n2")),
            ("schedule", "contact"),
        )
        assert len(sections) == 2
        assert sections[0]["machine"] == "m1"
        assert sections[1]["machine"] == "m2"

    def test_multiline_notes_joined_with_space(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "line1", "line2", "line3"]) + "\n"
        sections = _parse_system_sections(content)
        assert sections[0]["notes"] == "line1 line2 line3"

    def test_empty_template_has_blank_fields(self):
        content = "\n".join([SEP, M, "", I, "", T, "", N, "", S, "", C, ""]) + "\n"
        sections = _parse_system_sections(content, ("schedule", "contact"))
        assert sections[0] == {"machine": "", "id": "", "schedule": "", "contact": "", "time": "", "notes": ""}

    def test_empty_content_returns_no_sections(self):
        assert _parse_system_sections("") == []


class TestCsvHelpers:
    def test_plain_field_unchanged(self):
        assert _csv_field("hello") == "hello"

    def test_field_with_comma_quoted(self):
        assert _csv_field("a,b") == '"a,b"'

    def test_field_with_double_quote_escaped(self):
        assert _csv_field('say "hi"') == '"say ""hi"""'

    def test_field_with_newline_quoted(self):
        assert _csv_field("a\nb") == '"a\nb"'

    def test_row_joins_with_comma_space(self):
        assert _csv_row("a", "b", "c") == "a, b, c"

    def test_row_quotes_field_containing_comma(self):
        assert _csv_row("a,b", "c") == '"a,b", c'

    def test_row_empty_field(self):
        assert _csv_row("a", "", "c") == "a, , c"


PROPS = ("p1", "p2")


class TestAdditionalPropsValidation:
    def test_valid_with_props(self):
        doc = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"), props=[("p1", "v1"), ("p2", "v2")])
        ok, _ = _validate_system(doc, ("schedule", "contact") + PROPS)
        assert ok

    def test_empty_prop_value_valid(self):
        doc = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"), props=[("p1", ""), ("p2", "")])
        ok, _ = _validate_system(doc, ("schedule", "contact") + PROPS)
        assert ok

    def test_missing_prop_label_rejected(self):
        doc = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"))  # no props in document
        ok, msg = _validate_system(doc, ("schedule", "contact") + PROPS)
        assert not ok
        assert "p1" in msg

    def test_wrong_prop_label_rejected(self):
        doc = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"), props=[("wrong", "v"), ("p2", "v")])
        ok, msg = _validate_system(doc, ("schedule", "contact") + PROPS)
        assert not ok

    def test_notes_terminated_by_prop_label(self):
        doc = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "line1"), props=[("p1", "v1"), ("p2", "")])
        sections = _parse_system_sections(doc, ("schedule", "contact") + PROPS)
        assert sections[0]["notes"] == "line1"
        assert sections[0]["p1"] == "v1"

    def test_multiline_notes_terminated_before_props(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "line1", "line2",
                              S, "s1", C, "cont1", "👉p1👈", "val", "👉p2👈", ""]) + "\n"
        sections = _parse_system_sections(content, ("schedule", "contact") + PROPS)
        assert sections[0]["notes"] == "line1 line2"
        assert sections[0]["p1"] == "val"

    def test_empty_template_includes_props(self):
        doc = _empty_system_document(PROPS)
        assert "👉p1👈" in doc
        assert "👉p2👈" in doc

    def test_parse_empty_template_with_props(self):
        doc = _empty_system_document(PROPS)
        sections = _parse_system_sections(doc, PROPS)
        assert sections[0] == {"machine": "", "id": "", "time": "", "notes": "", "p1": "", "p2": ""}

    def test_parse_mismatch_fills_missing_with_empty(self):
        # document has p1 and p3, config asks for p1 and p2 — p2 should be ""
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "notes",
                              "👉p1👈", "val1", "👉p3👈", "val3"]) + "\n"
        sections = _parse_system_sections(content, ("p1", "p2"))
        assert sections[0]["p1"] == "val1"
        assert sections[0]["p2"] == ""

    def test_parse_completely_different_props_fills_all_empty(self):
        # document has p3 and p4, config asks for p1 and p2 — both should be ""
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "notes",
                              "👉p3👈", "val3", "👉p4👈", "val4"]) + "\n"
        sections = _parse_system_sections(content, ("p1", "p2"))
        assert sections[0]["p1"] == ""
        assert sections[0]["p2"] == ""
        assert len(sections) == 1  # section still included

    def test_parse_notes_not_contaminated_by_unknown_props(self):
        # document has unknown prop labels; notes must not consume them
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "real notes",
                              "👉p3👈", "val"]) + "\n"
        sections = _parse_system_sections(content, ("p1",))
        assert sections[0]["notes"] == "real notes"


class TestTextToSystemJson:
    def test_basic_section(self):
        content = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"))
        data = json.loads(_text_to_system_json(content, ("schedule", "contact")))
        assert data == [{"machine": "m1", "id": "id1", "time": "12:00", "notes": "notes", "schedule": "s1", "contact": "cont1"}]

    def test_multiline_notes_preserved_with_newlines(self):
        content = "\n".join([SEP, M, "m1", I, "id1", T, "12:00", N, "line1", "line2"]) + "\n"
        data = json.loads(_text_to_system_json(content))
        assert data[0]["notes"] == "line1\nline2"

    def test_additional_props_included(self):
        content = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "n"), props=[("p1", "v1"), ("p2", "")])
        data = json.loads(_text_to_system_json(content, ("schedule", "contact", "p1", "p2")))
        assert data[0]["p1"] == "v1"
        assert data[0]["p2"] == ""

    def test_multiple_sections(self):
        content = sys_doc(("m1", "id1", "s1", "cont1", "08:00", "n1"), ("m2", "id2", "s2", "cont2", "09:00", "n2"))
        data = json.loads(_text_to_system_json(content))
        assert len(data) == 2
        assert data[1]["machine"] == "m2"

    def test_empty_content_returns_empty_array(self):
        data = json.loads(_text_to_system_json(""))
        assert data == []

    def test_round_trip(self):
        content = sys_doc(("m1", "id1", "s1", "cont1", "12:00", "notes"), props=[("p1", "val")])
        props = ("schedule", "contact", "p1")
        result = _system_sections_to_text(json.loads(_text_to_system_json(content, props)), props)
        assert result == content


class TestSystemSectionsToText:
    def test_basic_conversion(self):
        sections = [{"machine": "m1", "id": "id1", "schedule": "s1", "contact": "cont1", "time": "12:00", "notes": "notes"}]
        text = _system_sections_to_text(sections)
        assert SEP in text
        assert "m1" in text
        assert "id1" in text

    def test_multiline_notes_expanded(self):
        sections = [{"machine": "m1", "id": "id1", "schedule": "s1", "contact": "cont1", "time": "12:00", "notes": "line1\nline2"}]
        text = _system_sections_to_text(sections)
        lines = text.splitlines()
        notes_idx = lines.index(N)
        assert lines[notes_idx + 1] == "line1"
        assert lines[notes_idx + 2] == "line2"

    def test_missing_additional_prop_appended_empty(self):
        sections = [{"machine": "m1", "id": "id1", "schedule": "s1", "contact": "cont1", "time": "12:00", "notes": "n"}]
        text = _system_sections_to_text(sections, ("p1", "p2"))
        assert "👉p1👈" in text
        assert "👉p2👈" in text

    def test_empty_sections_returns_empty_string(self):
        assert _system_sections_to_text([]) == "\n"


class TestEmptySystemJson:
    def test_returns_valid_json_array(self):
        data = json.loads(_empty_system_json())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_all_core_fields_blank(self):
        data = json.loads(_empty_system_json())
        sec = data[0]
        assert sec["machine"] == ""
        assert sec["id"] == ""
        assert sec["time"] == ""
        assert sec["notes"] == ""

    def test_additional_props_included_blank(self):
        data = json.loads(_empty_system_json(("p1", "p2")))
        assert data[0]["p1"] == ""
        assert data[0]["p2"] == ""


class TestLoadAdditionalProperties:
    def test_reads_json_array(self, tmp_path):
        (tmp_path / "additional_properties.json").write_text('["p1", "p2"]')
        assert load_additional_properties(tmp_path) == ("p1", "p2")

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_additional_properties(tmp_path) == ()

    def test_empty_array_returns_empty(self, tmp_path):
        (tmp_path / "additional_properties.json").write_text("[]")
        assert load_additional_properties(tmp_path) == ()
