import gzip
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import app
from app import (
    encode_name,
    cmd_ls, cmd_add, cmd_cat, cmd_get, cmd_clear, cmd_push, cmd_export, cmd_len, cmd_diff,
    cmd_fullcopy, cmd_mkrepo, cmd_partialcopy,
    cmd_searchitems, cmd_removeitems,
    _empty_main_collection_document, _empty_main_collection_json, _text_to_main_collection_json,
)

SEP = "🏔" * 20
M = "👉machine👈"
I = "👉id👈"
S = "👉schedule👈"
C = "👉contact👈"
T = "👉time👈"
N = "👉notes👈"


PROPS = ("p1", "p2")
ISC_PROPS = ("id", "schedule", "contact")
ISC_VALIDATION = {"id": "RE:[^#]+"}

MT_PROPS = ("machine", "time")
MT_VALIDATION = {"machine": "NOT_EMPTY", "time": "HH:MM"}
MTISC_PROPS = MT_PROPS + ISC_PROPS
MTISC_VALIDATION = {**MT_VALIDATION, **ISC_VALIDATION}
NMTISC_PROPS = ("notes",) + MTISC_PROPS
N_ML = frozenset({"notes"})

# mandatory_ref_props tuple covering schedule + contact with no whitelist
_SC_CONTACT_REFS = (
    ("schedule", "schedules", frozenset()),
    ("contact", "contacts", frozenset()),
)


@pytest.fixture(autouse=True)
def _collection_types():
    app.COLLECTION_TYPE.update({"schedules": "DATE", "contacts": "PHONE_NUMBER"})
    yield
    app.COLLECTION_TYPE.pop("schedules", None)
    app.COLLECTION_TYPE.pop("contacts", None)


@pytest.fixture
def dynamic_col(repo, downloads):
    cname = "testcol"
    (repo / cname).mkdir()
    (downloads / cname).mkdir()
    app.COLLECTIONS.add(cname)
    yield cname
    app.COLLECTIONS.discard(cname)
    app.COLLECTION_TYPE.pop(cname, None)


def sys_doc(*rows, props=()):
    """Build a system document from (machine, time, notes) tuples.
    Document format: notes first (core), then machine, time, then other props."""
    parts = []
    for machine, time, notes in rows:
        section = [SEP, N, notes, M, machine, T, time]
        for pname, pval in props:
            section += [f"👉{pname}👈", pval]
        parts += section
    return "\n".join(parts) + "\n"


def put_system(repo, name, version, content, additional_props=(), multiline_props=frozenset()):
    enc = encode_name(name)
    path = repo / "systems" / f"{enc}.{version:04d}.txt.gz"
    if content:
        path.write_bytes(gzip.compress(
            _text_to_main_collection_json(content, additional_props, multiline_props=multiline_props).encode()
        ))
    else:
        path.write_bytes(gzip.compress(b""))
    return path


def put_schedule(repo, name, version, content):
    enc = encode_name(name)
    path = repo / "schedules" / f"{enc}.{version:04d}.txt"
    path.write_text(content)
    return path


def put_contact(repo, name, version, content):
    enc = encode_name(name)
    path = repo / "contacts" / f"{enc}.{version:04d}.txt"
    path.write_text(content)
    return path


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "systems").mkdir()
    (tmp_path / "schedules").mkdir()
    (tmp_path / "contacts").mkdir()
    return tmp_path


@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "downloads"
    d.mkdir()
    (d / "systems").mkdir()
    (d / "schedules").mkdir()
    (d / "contacts").mkdir()
    return d


@pytest.fixture
def cache(tmp_path):
    c = tmp_path / "cache"
    c.mkdir()
    return c


class TestCmdAdd:
    def test_systems_creates_gz(self, repo, capsys):
        cmd_add(repo, "systems", "sys1")
        enc = encode_name("sys1")
        path = repo / "systems" / f"{enc}.0000.txt.gz"
        assert path.exists()
        assert gzip.decompress(path.read_bytes()).decode() == _empty_main_collection_json()
        assert "created: sys1" in capsys.readouterr().out

    def test_schedules_creates_txt(self, repo, capsys):
        cmd_add(repo, "schedules", "sc1")
        enc = encode_name("sc1")
        assert (repo / "schedules" / f"{enc}.0000.txt").exists()
        assert "created: sc1" in capsys.readouterr().out

    def test_already_exists_prints_error(self, repo, capsys):
        cmd_add(repo, "systems", "sys1")
        capsys.readouterr()
        cmd_add(repo, "systems", "sys1")
        assert "already exists" in capsys.readouterr().out

    def test_already_exists_does_not_overwrite(self, repo):
        put_system(repo, "sys1", 0,
                   sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "s1"), ("contact", "cont1")]),
                   NMTISC_PROPS)
        cmd_add(repo, "systems", "sys1")
        enc = encode_name("sys1")
        content = gzip.decompress((repo / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode()
        assert "m1" in content


class TestCmdLs:
    def test_lists_decoded_names(self, repo, capsys):
        put_system(repo, "sys1", 0, "")
        put_system(repo, "sys2", 0, "")
        cmd_ls(repo, "systems")
        out = capsys.readouterr().out.splitlines()
        assert "sys1" in out
        assert "sys2" in out

    def test_deduplicates_across_versions(self, repo, capsys):
        put_system(repo, "sys1", 0, "")
        put_system(repo, "sys1", 1, "")
        put_system(repo, "sys1", 2, "")
        cmd_ls(repo, "systems")
        assert capsys.readouterr().out.splitlines().count("sys1") == 1

    def test_schedules_collection(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "")
        cmd_ls(repo, "schedules")
        assert "sc1" in capsys.readouterr().out

    def test_missing_dir_prints_error(self, tmp_path, capsys):
        cmd_ls(tmp_path, "systems")
        assert "error" in capsys.readouterr().out


class TestCmdCat:
    def test_system_decompresses(self, repo, capsys):
        put_system(repo, "sys1", 0,
                   sys_doc(("m1", "12:00", "some notes"), props=[("id", "id1"), ("schedule", "s1"), ("contact", "cont1")]),
                   NMTISC_PROPS)
        cmd_cat(repo, "systems", "sys1", NMTISC_PROPS)
        assert "m1" in capsys.readouterr().out

    def test_schedule_plain(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        cmd_cat(repo, "schedules", "sc1")
        assert "2020/01/01" in capsys.readouterr().out

    def test_reads_latest_version(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "old-notes")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "new-notes")), ("notes",))
        cmd_cat(repo, "systems", "sys1", ("notes",))
        out = capsys.readouterr().out
        assert "new-notes" in out
        assert "old-notes" not in out

    def test_not_found_prints_error(self, repo, capsys):
        cmd_cat(repo, "systems", "ghost")
        assert "error" in capsys.readouterr().out


class TestCmdGet:
    def test_system_decompresses_to_txt(self, repo, downloads):
        content = sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "s1"), ("contact", "cont1")])
        put_system(repo, "sys1", 2, content, NMTISC_PROPS)
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "systems", "sys1", downloads, "mousepad", NMTISC_PROPS)
        dest = downloads / "systems" / f"{enc}.0002.txt"
        assert dest.exists()
        assert dest.read_text() == content

    def test_schedule_copied_as_txt(self, repo, downloads):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sc1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "schedules", "sc1", downloads, "mousepad")
        assert (downloads / "schedules" / f"{enc}.0000.txt").read_text() == "2020/01/01"

    def test_gets_latest_version(self, repo, downloads):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "old-notes")), ("notes",))
        put_system(repo, "sys1", 3, sys_doc(("m1", "12:00", "new-notes")), ("notes",))
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "systems", "sys1", downloads, "mousepad", ("notes",))
        assert "new-notes" in (downloads / "systems" / f"{enc}.0003.txt").read_text()

    def test_opens_editor(self, repo, downloads):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        with patch.object(app.subprocess, "Popen") as mock_popen:
            cmd_get(repo, "systems", "sys1", downloads, "mousepad", ("notes",))
        mock_popen.assert_called_once()
        assert "mousepad" in mock_popen.call_args[0][0]

    def test_not_found_prints_error(self, repo, downloads, capsys):
        cmd_get(repo, "systems", "ghost", downloads, "mousepad")
        assert "error" in capsys.readouterr().out


class TestCmdClear:
    def test_system_writes_empty_template(self, repo, downloads):
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "n")))
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad")
        assert (downloads / "systems" / f"{enc}.0001.txt").read_text() == _empty_main_collection_document()

    def test_schedule_writes_empty_template(self, repo, downloads):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sc1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "schedules", "sc1", downloads, "mousepad")
        assert (downloads / "schedules" / f"{enc}.0000.txt").read_text() == ""

    def test_uses_latest_version_for_filename(self, repo, downloads):
        put_system(repo, "sys1", 0, "")
        put_system(repo, "sys1", 5, "")
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad")
        assert (downloads / "systems" / f"{enc}.0005.txt").exists()
        assert not (downloads / "systems" / f"{enc}.0000.txt").exists()

    def test_not_found_prints_error(self, repo, downloads, capsys):
        cmd_clear(repo, "systems", "ghost", downloads, "mousepad")
        assert "error" in capsys.readouterr().out


class TestCmdPush:
    def test_system_creates_next_version(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert (repo / "systems" / f"{enc}.0001.txt.gz").exists()
        assert "version 0001" in capsys.readouterr().out

    def test_system_compresses_on_write(self, repo, downloads):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        content = sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(content)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        gz = repo / "systems" / f"{enc}.0001.txt.gz"
        assert gzip.decompress(gz.read_bytes()).decode() == _text_to_main_collection_json(content, NMTISC_PROPS)

    def test_system_invalid_format_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text("not valid")
        cmd_push(repo, "systems", "sys1", downloads)
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_id_with_hash_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "#hash-id")])
        )
        cmd_push(repo, "systems", "sys1", downloads, ("notes", "machine", "time", "id"),
                 prop_validation_types={**MT_VALIDATION, "id": "RE:[^#]+"})
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_missing_schedule_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "ghost_sched"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_whitelisted_schedule_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "everyday"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=(
            ("schedule", "schedules", frozenset({"everyday"})),
            ("contact", "contacts", frozenset()),
        ), prop_validation_types=MTISC_VALIDATION)
        assert "pushed" in capsys.readouterr().out

    def test_system_existing_repo_schedule_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "real_sched", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "real_sched"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "pushed" in capsys.readouterr().out

    def test_system_missing_contact_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "ghost_cont")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_whitelisted_contact_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "on-call")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=(
            ("schedule", "schedules", frozenset()),
            ("contact", "contacts", frozenset({"on-call"})),
        ), prop_validation_types=MTISC_VALIDATION)
        assert "pushed" in capsys.readouterr().out

    def test_system_existing_repo_contact_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "real_cont", 0, "09-9999-9999")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "real_cont")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "pushed" in capsys.readouterr().out

    def test_schedule_increments_version(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "")
        enc = encode_name("sc1")
        (downloads / "schedules" / f"{enc}.0000.txt").write_text("2020/01/01")
        cmd_push(repo, "schedules", "sc1", downloads)
        assert (repo / "schedules" / f"{enc}.0001.txt").exists()
        assert "version 0001" in capsys.readouterr().out

    def test_schedule_invalid_format_rejected(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "")
        enc = encode_name("sc1")
        (downloads / "schedules" / f"{enc}.0000.txt").write_text("not-a-date")
        cmd_push(repo, "schedules", "sc1", downloads)
        assert "rejected" in capsys.readouterr().out

    def test_empty_main_collection_document_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(_empty_main_collection_document())
        cmd_push(repo, "systems", "sys1", downloads)
        assert "pushed" in capsys.readouterr().out
        assert (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_all_rows_deleted_pushes_empty_template(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text("\n")  # GUI saves empty string when all rows deleted
        cmd_push(repo, "systems", "sys1", downloads)
        assert "pushed" in capsys.readouterr().out
        pushed = repo / "systems" / f"{enc}.0001.txt.gz"
        assert pushed.exists()
        assert gzip.decompress(pushed.read_bytes()).decode() == _empty_main_collection_json()

    def test_not_in_downloads_prints_error(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        cmd_push(repo, "systems", "sys1", downloads)
        assert "error" in capsys.readouterr().out

    def test_not_in_repo_prints_error(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("ghost")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("m1", "12:00", "n"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "ghost", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "error" in capsys.readouterr().out

    def test_push_uses_latest_downloads_file(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(
            sys_doc(("old", "12:00", "n"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])
        )
        (downloads / "systems" / f"{enc}.0003.txt").write_text(
            sys_doc(("new", "12:00", "n"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])
        )
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS, mandatory_ref_props=_SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        gz = repo / "systems" / f"{enc}.0001.txt.gz"
        assert "new" in gzip.decompress(gz.read_bytes()).decode()


class TestCmdExport:
    def test_systems_csv_content(self, repo, downloads, cache):
        put_system(repo, "sys1", 0,
                   sys_doc(("m1", "12:00", "some notes"), props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")]),
                   NMTISC_PROPS)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=NMTISC_PROPS,
                       multiline_props=N_ML)
        content = (downloads / "out.csv").read_text()
        assert "system, notes, machine, time, id, schedule, contact" in content
        assert "sys1, some notes, m1, 12:00, id1, sc1, cont1" in content

    def test_systems_multiple_sections_expand_to_rows(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("m1", "08:00", "n1"), ("m2", "09:00", "n2")), MT_PROPS)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=MT_PROPS)
        lines = (downloads / "out.csv").read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 data rows

    def test_systems_multiline_notes_joined(self, repo, downloads, cache):
        content = "\n".join([SEP, N, "line1", "line2"]) + "\n"
        put_system(repo, "sys1", 0, content, ("notes",), N_ML)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad",
                       additional_props=("notes",), multiline_props=N_ML)
        assert "line1 line2" in (downloads / "out.csv").read_text()

    def test_systems_uses_latest_version(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "old-notes")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "new-notes")), ("notes",))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=("notes",))
        content = (downloads / "out.csv").read_text()
        assert "new-notes" in content
        assert "old-notes" not in content

    def test_systems_excludes_initial_state(self, repo, downloads, cache):
        put_system(repo, "empty_sys", 0, _empty_main_collection_document())
        put_system(repo, "real_sys", 0, sys_doc(("m1", "12:00", "some-notes")), ("notes",))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=("notes",))
        content = (downloads / "out.csv").read_text()
        assert "real_sys" in content
        assert "empty_sys" not in content

    def test_schedules_csv_content(self, repo, downloads, cache):
        put_schedule(repo, "sc1", 0, "2020/01/01,2020/06/15")
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "schedules", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "name, values" in content
        assert "sc1, 2020/01/01 2020/06/15" in content

    def test_schedules_excludes_initial_state(self, repo, downloads, cache):
        put_schedule(repo, "empty_sc", 0, "")
        put_schedule(repo, "real_sc", 0, "2020/01/01")
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "schedules", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "real_sc" in content
        assert "empty_sc" not in content

    def test_opens_editor_with_csv_path(self, repo, downloads, cache):
        with patch.object(app.subprocess, "Popen") as mock_popen:
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        mock_popen.assert_called_once()
        called_args = mock_popen.call_args[0][0]
        assert "mousepad" in called_args
        assert "out.csv" in called_args[-1]

    def test_syncs_cache_before_reading(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "some-n")), MT_PROPS)
        assert not (cache / "systems").exists()
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=MT_PROPS)
        assert "sys1" in (downloads / "out.csv").read_text()


class TestAdditionalProps:
    def test_add_creates_template_with_props(self, repo, capsys):
        cmd_add(repo, "systems", "sys1", additional_props=PROPS)
        enc = encode_name("sys1")
        data = json.loads(gzip.decompress((repo / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode())
        assert "p1" in data[0]
        assert "p2" in data[0]

    def test_add_template_matches_empty_main_collection_json(self, repo):
        cmd_add(repo, "systems", "sys1", additional_props=PROPS)
        enc = encode_name("sys1")
        content = gzip.decompress((repo / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode()
        assert content == _empty_main_collection_json(PROPS)

    def test_clear_writes_template_with_props(self, repo, downloads):
        put_system(repo, "sys1", 0,
                   sys_doc(("m1", "12:00", "n"),
                            props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", "v"), ("p2", "")]),
                   NMTISC_PROPS + PROPS)
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad", additional_props=PROPS)
        content = (downloads / "systems" / f"{enc}.0000.txt").read_text()
        assert content == _empty_main_collection_document(PROPS)

    def test_push_accepts_doc_with_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", "val1"), ("p2", "")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, _SC_CONTACT_REFS,
                 prop_validation_types=MTISC_VALIDATION)
        assert "pushed" in capsys.readouterr().out

    def test_push_rejects_doc_missing_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1")])  # no p1/p2
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, prop_validation_types=MTISC_VALIDATION)
        assert "rejected" in capsys.readouterr().out

    def test_push_accepts_initial_state_with_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / "systems" / f"{enc}.0000.txt").write_text(_empty_main_collection_document(PROPS))
        cmd_push(repo, "systems", "sys1", downloads, PROPS)
        assert "pushed" in capsys.readouterr().out

    def test_export_csv_includes_prop_columns(self, repo, downloads, cache):
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", "val1"), ("p2", "val2")])
        put_system(repo, "sys1", 0, doc, additional_props=NMTISC_PROPS + PROPS)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=NMTISC_PROPS + PROPS)
        content = (downloads / "out.csv").read_text()
        assert "system, notes, machine, time, id, schedule, contact, p1, p2" in content
        assert "sys1, notes, m1, 12:00, id1, sc1, cont1, val1, val2" in content

    def test_export_csv_empty_prop_value(self, repo, downloads, cache):
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", ""), ("p2", "v2")])
        put_system(repo, "sys1", 0, doc, additional_props=NMTISC_PROPS + PROPS)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=NMTISC_PROPS + PROPS)
        content = (downloads / "out.csv").read_text()
        assert "sys1, notes, m1, 12:00, id1, sc1, cont1, , v2" in content

    def test_push_not_empty_type_rejects_empty_value(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", ""), ("p2", "val")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, _SC_CONTACT_REFS,
                 prop_validation_types={**MTISC_VALIDATION, "p1": "NOT_EMPTY"})
        assert "rejected" in capsys.readouterr().out

    def test_push_not_empty_type_accepts_non_empty_value(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", "val"), ("p2", "")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, _SC_CONTACT_REFS,
                 prop_validation_types={**MTISC_VALIDATION, "p1": "NOT_EMPTY"})
        assert "pushed" in capsys.readouterr().out

    def test_push_hh_mm_type_accepts_valid_value(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", ""), ("p2", "09:30")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, _SC_CONTACT_REFS,
                 prop_validation_types={**MTISC_VALIDATION, "p2": "HH:MM"})
        assert "pushed" in capsys.readouterr().out

    def test_push_hh_mm_type_rejects_invalid_value(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        put_contact(repo, "cont1", 0, "03-1234-5678")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", ""), ("p2", "not-time")])
        (downloads / "systems" / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, NMTISC_PROPS + PROPS, _SC_CONTACT_REFS,
                 prop_validation_types={**MTISC_VALIDATION, "p2": "HH:MM"})
        assert "rejected" in capsys.readouterr().out

    def test_export_csv_mismatched_props_fill_empty(self, repo, downloads, cache):
        # document was saved with p1 and p3; export configured for p1 and p2 — p2 must be empty
        doc = sys_doc(("m1", "12:00", "notes"),
                      props=[("id", "id1"), ("schedule", "sc1"), ("contact", "cont1"), ("p1", "val1"), ("p3", "val3")])
        put_system(repo, "sys1", 0, doc, additional_props=NMTISC_PROPS + ("p1", "p3"))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=NMTISC_PROPS + PROPS)
        content = (downloads / "out.csv").read_text()
        assert "system, notes, machine, time, id, schedule, contact, p1, p2" in content
        assert "sys1, notes, m1, 12:00, id1, sc1, cont1, val1, " in content


class TestCmdLen:
    def test_systems_counts_non_empty_sections(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(
            ("m1", "08:00", "n1"),
            ("m2", "09:00", "n2"),
        ), MT_PROPS)
        cmd_len(repo, "systems", "sys1")
        assert capsys.readouterr().out.strip() == "2"

    def test_systems_initial_state_is_zero(self, repo, capsys):
        put_system(repo, "sys1", 0, _empty_main_collection_document())
        cmd_len(repo, "systems", "sys1")
        assert capsys.readouterr().out.strip() == "0"

    def test_systems_not_found_prints_error(self, repo, capsys):
        cmd_len(repo, "systems", "ghost")
        assert "error" in capsys.readouterr().out

    def test_schedules_counts_dates(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2020/01/01,2020/06/15,2021/03/10")
        cmd_len(repo, "schedules", "sc1")
        assert capsys.readouterr().out.strip() == "3"

    def test_schedules_empty_content_is_zero(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "")
        cmd_len(repo, "schedules", "sc1")
        assert capsys.readouterr().out.strip() == "0"

    def test_schedules_not_found_prints_error(self, repo, capsys):
        cmd_len(repo, "schedules", "ghost")
        assert "error" in capsys.readouterr().out


class TestCmdDiff:
    # ── systems ───────────────────────────────────────────────────────────────

    def test_systems_added_section(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n1")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "n1"), ("m2", "13:00", "n2")), ("notes",))
        cmd_diff(repo, "systems", "sys1")
        result = json.loads(capsys.readouterr().out)
        assert result["deleted"] == []
        assert len(result["added"]) == 1
        assert result["added"][0]["notes"] == "n2"

    def test_systems_deleted_section(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n1"), ("m2", "13:00", "n2")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "n1")), ("notes",))
        cmd_diff(repo, "systems", "sys1")
        result = json.loads(capsys.readouterr().out)
        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["notes"] == "n2"
        assert result["added"] == []

    def test_systems_modified_section(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "original")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "changed")), ("notes",))
        cmd_diff(repo, "systems", "sys1")
        result = json.loads(capsys.readouterr().out)
        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["notes"] == "original"
        assert len(result["added"]) == 1
        assert result["added"][0]["notes"] == "changed"

    def test_systems_no_change(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_diff(repo, "systems", "sys1")
        result = json.loads(capsys.readouterr().out)
        assert result == {"deleted": [], "added": []}

    def test_systems_not_found_prints_error(self, repo, capsys):
        cmd_diff(repo, "systems", "ghost")
        assert "error" in capsys.readouterr().out

    def test_systems_only_one_version_prints_error(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")))
        cmd_diff(repo, "systems", "sys1")
        assert "error" in capsys.readouterr().out

    # ── schedules ─────────────────────────────────────────────────────────────

    def test_schedules_added_date(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2024/01/01,2024/06/15")
        put_schedule(repo, "sc1", 1, "2024/01/01,2024/06/15,2025/03/20")
        cmd_diff(repo, "schedules", "sc1")
        result = json.loads(capsys.readouterr().out)
        assert result["deleted"] == []
        assert result["added"] == ["2025/03/20"]

    def test_schedules_deleted_date(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2024/01/01,2024/06/15")
        put_schedule(repo, "sc1", 1, "2024/06/15")
        cmd_diff(repo, "schedules", "sc1")
        result = json.loads(capsys.readouterr().out)
        assert result["deleted"] == ["2024/01/01"]
        assert result["added"] == []

    def test_schedules_no_change(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2024/01/01")
        put_schedule(repo, "sc1", 1, "2024/01/01")
        cmd_diff(repo, "schedules", "sc1")
        result = json.loads(capsys.readouterr().out)
        assert result == {"deleted": [], "added": []}

    def test_schedules_not_found_prints_error(self, repo, capsys):
        cmd_diff(repo, "schedules", "ghost")
        assert "error" in capsys.readouterr().out

    def test_schedules_only_one_version_prints_error(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2024/01/01")
        cmd_diff(repo, "schedules", "sc1")
        assert "error" in capsys.readouterr().out

    # ── contacts ──────────────────────────────────────────────────────────────

    def test_contacts_added_number(self, repo, capsys):
        put_contact(repo, "cont1", 0, "03-1234-5678,09012345678")
        put_contact(repo, "cont1", 1, "03-1234-5678,09012345678,+81-0100-0331")
        cmd_diff(repo, "contacts", "cont1")
        result = json.loads(capsys.readouterr().out)
        assert result["deleted"] == []
        assert result["added"] == ["+81-0100-0331"]

    def test_contacts_deleted_number(self, repo, capsys):
        put_contact(repo, "cont1", 0, "03-1234-5678,09012345678")
        put_contact(repo, "cont1", 1, "09012345678")
        cmd_diff(repo, "contacts", "cont1")
        result = json.loads(capsys.readouterr().out)
        assert result["deleted"] == ["03-1234-5678"]
        assert result["added"] == []

    def test_contacts_no_change(self, repo, capsys):
        put_contact(repo, "cont1", 0, "03-1234-5678")
        put_contact(repo, "cont1", 1, "03-1234-5678")
        cmd_diff(repo, "contacts", "cont1")
        result = json.loads(capsys.readouterr().out)
        assert result == {"deleted": [], "added": []}

    def test_contacts_not_found_prints_error(self, repo, capsys):
        cmd_diff(repo, "contacts", "ghost")
        assert "error" in capsys.readouterr().out

    def test_contacts_only_one_version_prints_error(self, repo, capsys):
        put_contact(repo, "cont1", 0, "03-1234-5678")
        cmd_diff(repo, "contacts", "cont1")
        assert "error" in capsys.readouterr().out


class TestCollectionTypeValidation:
    def _put(self, repo, downloads, cname, version, content):
        enc = encode_name("entry1")
        (repo / cname / f"{enc}.{version:04d}.txt").write_text(content)
        (downloads / cname / f"{enc}.{version:04d}.txt").write_text(content)

    def test_date_type_accepts_valid_dates(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "DATE"
        self._put(repo, downloads, dynamic_col, 0, "2024/01/01,2024/06/15")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "pushed" in capsys.readouterr().out

    def test_date_type_rejects_invalid_content(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "DATE"
        self._put(repo, downloads, dynamic_col, 0, "not-a-date")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "rejected" in capsys.readouterr().out

    def test_phone_number_type_accepts_valid_numbers(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "PHONE_NUMBER"
        self._put(repo, downloads, dynamic_col, 0, "03-1234-5678,090-0000-0000")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "pushed" in capsys.readouterr().out

    def test_phone_number_type_rejects_invalid_content(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "PHONE_NUMBER"
        self._put(repo, downloads, dynamic_col, 0, "not-a-number")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "rejected" in capsys.readouterr().out

    def test_note_type_accepts_any_content(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "NOTE"
        self._put(repo, downloads, dynamic_col, 0, "any free-form text!")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "pushed" in capsys.readouterr().out

    def test_no_type_accepts_any_content(self, repo, downloads, capsys, dynamic_col):
        self._put(repo, downloads, dynamic_col, 0, "anything at all")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "pushed" in capsys.readouterr().out

    def test_email_type_accepts_valid_addresses(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "EMAIL"
        self._put(repo, downloads, dynamic_col, 0, "user@example.com,admin@corp.jp")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "pushed" in capsys.readouterr().out

    def test_email_type_rejects_invalid_content(self, repo, downloads, capsys, dynamic_col):
        app.COLLECTION_TYPE[dynamic_col] = "EMAIL"
        self._put(repo, downloads, dynamic_col, 0, "not-an-email")
        cmd_push(repo, dynamic_col, "entry1", downloads)
        assert "rejected" in capsys.readouterr().out


class TestCmdFullcopy:
    def _make_repo(self, path):
        path.mkdir()
        (path / "systems").mkdir()
        (path / "schedules").mkdir()
        (path / "contacts").mkdir()
        return path

    def _write_minimal_config(self, repo):
        (repo / "repository.ini").write_text("")
        (repo / "additional_properties.json").write_text("[]")
        (repo / "additional_mandatory_properties.json").write_text("[]")

    # ── plain copy ────────────────────────────────────────────────────────────

    def test_plain_creates_named_directory(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_fullcopy(repo, str(dest), json_mode=False)
        assert (dest / "my_repo").is_dir()
        assert "copied" in capsys.readouterr().out

    def test_plain_copies_all_versions(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "old")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "new")), ("notes",))
        cmd_fullcopy(repo, str(dest), json_mode=False)
        enc = encode_name("sys1")
        assert (dest / "my_repo" / "systems" / f"{enc}.0000.txt.gz").exists()
        assert (dest / "my_repo" / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_plain_copies_ref_collection_files(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        dest = tmp_path / "dest"
        dest.mkdir()
        put_schedule(repo, "sc1", 0, "2024/01/01")
        cmd_fullcopy(repo, str(dest), json_mode=False)
        enc = encode_name("sc1")
        assert (dest / "my_repo" / "schedules" / f"{enc}.0000.txt").exists()

    def test_plain_dest_not_directory_prints_error(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        cmd_fullcopy(repo, str(tmp_path / "nonexistent"), json_mode=False)
        assert "error" in capsys.readouterr().out

    def test_plain_already_exists_prints_error(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "my_repo").mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=False)
        assert "error" in capsys.readouterr().out

    # ── JSON mode ─────────────────────────────────────────────────────────────

    def test_json_creates_named_json_file(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._write_minimal_config(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=True)
        assert (dest / "my_repo.json").exists()
        assert "exported" in capsys.readouterr().out

    def test_json_config_embeds_repository_ini(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        (repo / "repository.ini").write_text("[main_collection]\ncollection_name = systems\n")
        (repo / "additional_properties.json").write_text("[]")
        (repo / "additional_mandatory_properties.json").write_text("[]")
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert "[main_collection]" in data["config"]["repository_ini"]
        assert "collection_name = systems" in data["config"]["repository_ini"]

    def test_json_config_embeds_additional_properties(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        props = [{"property_name": "notes", "validation_type": "NONE", "multiline": True}]
        (repo / "repository.ini").write_text("")
        (repo / "additional_properties.json").write_text(json.dumps(props))
        (repo / "additional_mandatory_properties.json").write_text("[]")
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["config"]["additional_properties"] == props

    def test_json_config_embeds_reference_collections(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        ref_colls = [{"collection_name": "schedules", "property_name": "schedule", "type": "DATE"}]
        (repo / "repository.ini").write_text("")
        (repo / "additional_properties.json").write_text("[]")
        (repo / "reference_collections.json").write_text(json.dumps(ref_colls))
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["config"]["reference_collections"] == ref_colls

    def test_json_data_main_collection_latest_only(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._write_minimal_config(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "old-notes")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "new-notes")), ("notes",))
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        sections = data["data"]["systems"]["sys1"]
        assert any(s.get("notes") == "new-notes" for s in sections)
        assert not any(s.get("notes") == "old-notes" for s in sections)

    def test_json_data_ref_collection_latest_only(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._write_minimal_config(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_schedule(repo, "sc1", 0, "2024/01/01")
        put_schedule(repo, "sc1", 1, "2024/06/15")
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["data"]["schedules"]["sc1"] == "2024/06/15"

    def test_json_dest_not_directory_prints_error(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        cmd_fullcopy(repo, str(tmp_path / "nonexistent"), json_mode=True)
        assert "error" in capsys.readouterr().out

    def test_json_already_exists_prints_error(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._write_minimal_config(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "my_repo.json").write_text("{}")
        cmd_fullcopy(repo, str(dest), json_mode=True)
        assert "error" in capsys.readouterr().out

    def test_json_missing_config_files_produce_empty_arrays(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        (repo / "repository.ini").write_text("")
        # additional_properties.json and additional_mandatory_properties.json absent
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_fullcopy(repo, str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["config"]["additional_properties"] == []
        assert data["config"]["reference_collections"] == []


class TestCmdMkrepo:
    def _write_fullcopy_json(self, path, name="my_repo", config=None, data=None):
        payload = {
            "config": config or {
                "repository_ini": "[main_collection]\ncollection_name = systems\n",
                "additional_properties": [],
                "reference_collections": [],
            },
            "data": data or {},
        }
        p = path / f"{name}.json"
        p.write_text(json.dumps(payload))
        return p

    # ── happy-path ────────────────────────────────────────────────────────────

    def test_creates_named_directory(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        json_file = self._write_fullcopy_json(src)
        cmd_mkrepo(str(json_file), str(dest))
        assert (dest / "my_repo").is_dir()
        assert "created" in capsys.readouterr().out

    def test_writes_repository_ini(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        ini_text = "[main_collection]\ncollection_name = systems\n"
        json_file = self._write_fullcopy_json(src, config={
            "repository_ini": ini_text,
            "additional_properties": [],
            "reference_collections": [],
        })
        cmd_mkrepo(str(json_file), str(dest))
        assert (dest / "my_repo" / "repository.ini").read_text() == ini_text

    def test_writes_additional_properties_json(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        props = [{"property_name": "notes", "validation_type": "NONE", "multiline": True}]
        json_file = self._write_fullcopy_json(src, config={
            "repository_ini": "",
            "additional_properties": props,
            "reference_collections": [],
        })
        cmd_mkrepo(str(json_file), str(dest))
        written = json.loads((dest / "my_repo" / "additional_properties.json").read_text())
        assert written == props

    def test_writes_reference_collections_json(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        ref_colls = [{"collection_name": "schedules", "property_name": "schedule", "type": "DATE"}]
        json_file = self._write_fullcopy_json(src, config={
            "repository_ini": "",
            "additional_properties": [],
            "reference_collections": ref_colls,
        })
        cmd_mkrepo(str(json_file), str(dest))
        written = json.loads((dest / "my_repo" / "reference_collections.json").read_text())
        assert written == ref_colls


    def test_reconstructs_main_collection_as_gzip(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        sections = [{"notes": "hello world"}]
        json_file = self._write_fullcopy_json(src, data={"systems": {"sys1": sections}})
        cmd_mkrepo(str(json_file), str(dest))
        enc = encode_name("sys1")
        gz_file = dest / "my_repo" / "systems" / f"{enc}.0000.txt.gz"
        assert gz_file.exists()
        assert json.loads(gzip.decompress(gz_file.read_bytes()).decode()) == sections

    def test_reconstructs_ref_collection_as_plain_text(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        json_file = self._write_fullcopy_json(src, data={
            "systems": {},
            "schedules": {"sc1": "2024/01/01,2024/06/15"},
        })
        cmd_mkrepo(str(json_file), str(dest))
        enc = encode_name("sc1")
        txt_file = dest / "my_repo" / "schedules" / f"{enc}.0000.txt"
        assert txt_file.exists()
        assert txt_file.read_text() == "2024/01/01,2024/06/15"

    def test_round_trip_with_fullcopy(self, tmp_path):
        repo = tmp_path / "my_repo"
        repo.mkdir()
        (repo / "systems").mkdir()
        (repo / "schedules").mkdir()
        (repo / "contacts").mkdir()
        (repo / "repository.ini").write_text("[main_collection]\ncollection_name = systems\n")
        (repo / "additional_properties.json").write_text(json.dumps([{"property_name": "notes"}]))
        (repo / "additional_mandatory_properties.json").write_text("[]")
        sections = [{"notes": "round-trip content"}]
        enc = encode_name("sys1")
        body = json.dumps(sections, ensure_ascii=False, indent=2) + "\n"
        (repo / "systems" / f"{enc}.0000.txt.gz").write_bytes(gzip.compress(body.encode()))
        (repo / "schedules" / f"{encode_name('sc1')}.0000.txt").write_text("2024/03/01")

        export_dir = tmp_path / "export"
        export_dir.mkdir()
        cmd_fullcopy(repo, str(export_dir), json_mode=True)

        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        cmd_mkrepo(str(export_dir / "my_repo.json"), str(restore_dir))

        restored = restore_dir / "my_repo"
        assert json.loads(gzip.decompress((restored / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode()) == sections
        assert (restored / "schedules" / f"{encode_name('sc1')}.0000.txt").read_text() == "2024/03/01"

    # ── error cases ───────────────────────────────────────────────────────────

    def test_error_json_not_found(self, tmp_path, capsys):
        dest = tmp_path / "dest"
        dest.mkdir()
        cmd_mkrepo(str(tmp_path / "nonexistent.json"), str(dest))
        assert "error" in capsys.readouterr().out

    def test_error_destination_not_directory(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        json_file = self._write_fullcopy_json(src)
        cmd_mkrepo(str(json_file), str(tmp_path / "nonexistent"))
        assert "error" in capsys.readouterr().out

    def test_error_target_already_exists(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "my_repo").mkdir()
        json_file = self._write_fullcopy_json(src)
        cmd_mkrepo(str(json_file), str(dest))
        assert "error" in capsys.readouterr().out

    def test_error_invalid_json(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        bad = src / "bad.json"
        bad.write_text("not valid json {{{")
        cmd_mkrepo(str(bad), str(dest))
        assert "error" in capsys.readouterr().out

    def test_error_missing_config_key(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        bad = src / "bad.json"
        bad.write_text(json.dumps({"data": {}}))  # missing "config"
        cmd_mkrepo(str(bad), str(dest))
        assert "error" in capsys.readouterr().out


class TestPartialcopy:
    def _make_repo(self, path):
        path.mkdir()
        (path / "systems").mkdir()
        (path / "schedules").mkdir()
        (path / "contacts").mkdir()
        (path / "repository.ini").write_text("")
        return path

    def _setup_collections(self, repo):
        app.MAIN_COLLECTION = "systems"
        app.COLLECTIONS.clear()
        app.COLLECTIONS.update({"systems", "schedules", "contacts"})
        app.COLLECTION_TYPE.clear()

    def test_creates_named_directory(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest))
        assert (dest / "my_repo").is_dir()
        assert "created" in capsys.readouterr().out

    def test_copies_target_entry_files(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        enc = encode_name("sys1")
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        put_system(repo, "sys1", 1, sys_doc(("m1", "12:00", "v2")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest))
        f0 = dest / "my_repo" / "systems" / f"{enc}.0000.txt.gz"
        f1 = dest / "my_repo" / "systems" / f"{enc}.0001.txt.gz"
        assert f0.stat().st_size > 0
        assert f1.stat().st_size > 0

    def test_other_entries_are_gz_empty(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        enc_other = encode_name("sys2")
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        put_system(repo, "sys2", 0, sys_doc(("m2", "09:00", "x")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest))
        other_file = dest / "my_repo" / "systems" / f"{enc_other}.0000.txt.gz"
        assert other_file.exists()
        assert gzip.decompress(other_file.read_bytes()) == b"[]"

    def test_ref_collection_target_is_copied(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        enc = encode_name("sc1")
        put_schedule(repo, "sc1", 0, "2024/01/01")
        cmd_partialcopy(repo, "schedules", "sc1", str(dest))
        f = dest / "my_repo" / "schedules" / f"{enc}.0000.txt"
        assert f.read_text() == "2024/01/01"

    def test_ref_collection_other_entries_are_empty(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        enc_other = encode_name("sc2")
        put_schedule(repo, "sc1", 0, "2024/01/01")
        put_schedule(repo, "sc2", 0, "2024/06/15")
        cmd_partialcopy(repo, "schedules", "sc1", str(dest))
        other_file = dest / "my_repo" / "schedules" / f"{enc_other}.0000.txt"
        assert other_file.exists()
        assert other_file.stat().st_size == 0

    def test_config_files_are_copied(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        (repo / "additional_properties.json").write_text('[{"property_name": "notes"}]')
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest))
        assert (dest / "my_repo" / "repository.ini").exists()
        assert (dest / "my_repo" / "additional_properties.json").read_text() == '[{"property_name": "notes"}]'

    def test_error_dest_not_directory(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        cmd_partialcopy(repo, "systems", "sys1", str(tmp_path / "nonexistent"))
        assert "error" in capsys.readouterr().out

    def test_error_already_exists(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "my_repo").mkdir()
        cmd_partialcopy(repo, "systems", "sys1", str(dest))
        assert "error" in capsys.readouterr().out

    # ── JSON mode ─────────────────────────────────────────────────────────────

    def test_json_creates_named_json_file(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest), json_mode=True)
        assert (dest / "my_repo.json").exists()
        assert "exported" in capsys.readouterr().out

    def test_json_target_entry_has_real_data(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["data"]["systems"]["sys1"] != []

    def test_json_other_main_entries_are_empty_list(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        put_system(repo, "sys2", 0, sys_doc(("m2", "09:00", "x")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["data"]["systems"]["sys2"] == []

    def test_json_target_ref_entry_has_real_data(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_schedule(repo, "sc1", 0, "2024/01/01")
        cmd_partialcopy(repo, "schedules", "sc1", str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["data"]["schedules"]["sc1"] == "2024/01/01"

    def test_json_other_ref_entries_are_empty_string(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        put_schedule(repo, "sc1", 0, "2024/01/01")
        put_schedule(repo, "sc2", 0, "2024/06/15")
        cmd_partialcopy(repo, "schedules", "sc1", str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert data["data"]["schedules"]["sc2"] == ""

    def test_json_includes_config(self, tmp_path):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        (repo / "additional_properties.json").write_text('[{"property_name": "notes"}]')
        (repo / "additional_mandatory_properties.json").write_text("[]")
        dest = tmp_path / "dest"
        dest.mkdir()
        put_system(repo, "sys1", 0, sys_doc(("m1", "12:00", "n")), ("notes",))
        cmd_partialcopy(repo, "systems", "sys1", str(dest), json_mode=True)
        data = json.loads((dest / "my_repo.json").read_text())
        assert "config" in data
        assert data["config"]["additional_properties"] == [{"property_name": "notes"}]

    def test_json_error_already_exists(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "my_repo.json").write_text("{}")
        cmd_partialcopy(repo, "systems", "sys1", str(dest), json_mode=True)
        assert "error" in capsys.readouterr().out

    def test_json_error_dest_not_directory(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path / "my_repo")
        self._setup_collections(repo)
        cmd_partialcopy(repo, "systems", "sys1", str(tmp_path / "nonexistent"), json_mode=True)
        assert "error" in capsys.readouterr().out


class TestSearchitemsRemoveitemsEmptyQuery:
    SEP = "🏔" * 20

    def _write_main(self, repo, name, sections):
        enc = encode_name(name)
        data = gzip.compress(json.dumps(sections).encode())
        (repo / "systems" / f"{enc}.0000.txt.gz").write_bytes(data)

    def _write_ref(self, repo, collection, name, content):
        enc = encode_name(name)
        (repo / collection / f"{enc}.0000.txt").write_text(content)

    def test_searchitems_empty_main_returns_empty_list(self, repo, capsys):
        self._write_main(repo, "sys1", [{"p1": "a", "p2": "b"}])
        cmd_searchitems(repo, "systems", "sys1", ("p1", "p2"),
                        field_order=("p1", "p2"), stdin_content="")
        assert json.loads(capsys.readouterr().out) == []

    def test_searchitems_whitespace_query_returns_empty_list(self, repo, capsys):
        self._write_main(repo, "sys1", [{"p1": "a", "p2": "b"}])
        cmd_searchitems(repo, "systems", "sys1", ("p1", "p2"),
                        field_order=("p1", "p2"), stdin_content="   \n  ")
        assert json.loads(capsys.readouterr().out) == []

    def test_searchitems_empty_json_returns_empty_list(self, repo, capsys):
        self._write_main(repo, "sys1", [{"p1": "a", "p2": "b"}])
        cmd_searchitems(repo, "systems", "sys1", ("p1", "p2"),
                        field_order=("p1", "p2"), json_mode=True, stdin_content="{}")
        assert json.loads(capsys.readouterr().out) == []

    def test_searchitems_empty_ref_returns_empty_list(self, repo, capsys):
        self._write_ref(repo, "schedules", "sche1", "2024/01/01,2024/06/15")
        cmd_searchitems(repo, "schedules", "sche1", stdin_content="")
        assert json.loads(capsys.readouterr().out) == []

    def test_removeitems_empty_main_nothing_removed(self, repo, downloads, capsys):
        self._write_main(repo, "sys1", [{"p1": "a", "p2": "b"}])
        cmd_removeitems(repo, "systems", "sys1", downloads, ("p1", "p2"),
                        field_order=("p1", "p2"), stdin_content="")
        out = capsys.readouterr().out
        assert "nothing removed" in out
        assert "error" not in out

    def test_removeitems_empty_json_nothing_removed(self, repo, downloads, capsys):
        self._write_main(repo, "sys1", [{"p1": "a", "p2": "b"}])
        cmd_removeitems(repo, "systems", "sys1", downloads, ("p1", "p2"),
                        field_order=("p1", "p2"), json_mode=True, stdin_content="{}")
        out = capsys.readouterr().out
        assert "nothing removed" in out
        assert "error" not in out

    def test_removeitems_empty_ref_nothing_removed(self, repo, downloads, capsys):
        self._write_ref(repo, "schedules", "sche1", "2024/01/01,2024/06/15")
        cmd_removeitems(repo, "schedules", "sche1", downloads, stdin_content="")
        out = capsys.readouterr().out
        assert "nothing removed" in out
        assert "error" not in out
