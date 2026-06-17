import pytest
from app import _validate_system, _validate_schedule, validate, _parse_system_sections, _csv_field, _csv_row

SEP = "👉" * 10 + "👈" * 10
M = "👉machine👈"
S = "👉schedule👈"
N = "👉notes👈"


T = "👉time👈"


def sys_doc(*rows):
    """Build a system document from (machine, schedule, time, notes) tuples."""
    parts = []
    for machine, schedule, time, notes in rows:
        parts += [SEP, M, machine, S, schedule, T, time, N, notes]
    return "\n".join(parts) + "\n"


class TestValidateSystem:
    def test_single_section_valid(self):
        ok, _ = _validate_system(sys_doc(("m1", "s1", "12:00", "notes")))
        assert ok

    def test_multiple_sections_valid(self):
        ok, _ = _validate_system(sys_doc(("m1", "s1", "08:00", "n1"), ("m2", "s2", "09:00", "n2")))
        assert ok

    def test_multiline_notes_valid(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "12:00", N, "line1", "line2"]) + "\n"
        ok, _ = _validate_system(content)
        assert ok

    def test_empty_content_rejected(self):
        ok, msg = _validate_system("")
        assert not ok
        assert "no sections" in msg

    def test_missing_separator_rejected(self):
        content = "\n".join([M, "m1", S, "s1", T, "12:00", N, "notes"]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "separator" in msg

    def test_empty_machine_value_rejected(self):
        content = "\n".join([SEP, M, "", S, "s1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_whitespace_only_machine_rejected(self):
        content = "\n".join([SEP, M, "   ", S, "s1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_empty_schedule_value_rejected(self):
        content = "\n".join([SEP, M, "m1", S, "", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_empty_notes_rejected(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "12:00", N]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "notes is empty" in msg

    def test_invalid_time_format_rejected(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "9:00", N, "notes"]) + "\n"
        ok, msg = _validate_system(content)
        assert not ok
        assert "dd:dd" in msg

    def test_time_with_letters_rejected(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "ab:cd", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_valid_time_accepted(self):
        ok, _ = _validate_system(sys_doc(("m1", "s1", "00:00", "notes")))
        assert ok

    def test_wrong_label_rejected(self):
        content = "\n".join([SEP, "👉wrong👈", "m1", S, "s1", T, "12:00", N, "notes"]) + "\n"
        ok, _ = _validate_system(content)
        assert not ok

    def test_error_includes_line_number(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "12:00", N]) + "\n"
        _, msg = _validate_system(content)
        assert "section 1" in msg or "line" in msg


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


class TestValidateDispatch:
    def test_systems_routes_correctly(self):
        ok, _ = validate("systems", sys_doc(("m1", "s1", "12:00", "notes")))
        assert ok

    def test_schedules_routes_correctly(self):
        ok, _ = validate("schedules", "2000/01/01")
        assert ok

    def test_unknown_collection_passes(self):
        ok, _ = validate("unknown", "anything")
        assert ok


class TestParseSystemSections:
    def test_single_section(self):
        sections = _parse_system_sections(sys_doc(("m1", "s1", "12:00", "notes")))
        assert len(sections) == 1
        assert sections[0] == {"machine": "m1", "schedule": "s1", "time": "12:00", "notes": "notes"}

    def test_multiple_sections(self):
        sections = _parse_system_sections(sys_doc(("m1", "s1", "08:00", "n1"), ("m2", "s2", "09:00", "n2")))
        assert len(sections) == 2
        assert sections[0]["machine"] == "m1"
        assert sections[1]["machine"] == "m2"

    def test_multiline_notes_joined_with_space(self):
        content = "\n".join([SEP, M, "m1", S, "s1", T, "12:00", N, "line1", "line2", "line3"]) + "\n"
        sections = _parse_system_sections(content)
        assert sections[0]["notes"] == "line1 line2 line3"

    def test_empty_template_has_blank_fields(self):
        content = "\n".join([SEP, M, "", S, "", T, "", N, ""]) + "\n"
        sections = _parse_system_sections(content)
        assert sections[0] == {"machine": "", "schedule": "", "time": "", "notes": ""}

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
