import gzip
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import app
from app import (
    encode_name,
    cmd_ls, cmd_add, cmd_cat, cmd_get, cmd_clear, cmd_push, cmd_export,
    _EMPTY_DOCUMENTS, _empty_system_document,
)

SEP = "👉" * 10 + "👈" * 10
M = "👉machine👈"
S = "👉schedule👈"
T = "👉time👈"
N = "👉notes👈"


PROPS = ("p1", "p2")


def sys_doc(*rows, props=()):
    parts = []
    for machine, schedule, time, notes in rows:
        section = [SEP, M, machine, S, schedule, T, time, N, notes]
        for pname, pval in props:
            section += [f"👉{pname}👈", pval]
        parts += section
    return "\n".join(parts) + "\n"


def put_system(repo, name, version, content):
    enc = encode_name(name)
    path = repo / "systems" / f"{enc}.{version:04d}.txt.gz"
    path.write_bytes(gzip.compress(content.encode()))
    return path


def put_schedule(repo, name, version, content):
    enc = encode_name(name)
    path = repo / "schedules" / f"{enc}.{version:04d}.txt"
    path.write_text(content)
    return path


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "systems").mkdir()
    (tmp_path / "schedules").mkdir()
    return tmp_path


@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "downloads"
    d.mkdir()
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
        assert gzip.decompress(path.read_bytes()).decode() == _EMPTY_DOCUMENTS["systems"]
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
        put_system(repo, "sys1", 0, sys_doc(("m1", "s1", "12:00", "notes")))
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
        put_system(repo, "sys1", 0, sys_doc(("m1", "s1", "12:00", "some notes")))
        cmd_cat(repo, "systems", "sys1")
        assert "m1" in capsys.readouterr().out

    def test_schedule_plain(self, repo, capsys):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        cmd_cat(repo, "schedules", "sc1")
        assert "2020/01/01" in capsys.readouterr().out

    def test_reads_latest_version(self, repo, capsys):
        put_system(repo, "sys1", 0, sys_doc(("old", "s1", "12:00", "n")))
        put_system(repo, "sys1", 1, sys_doc(("new", "s1", "12:00", "n")))
        cmd_cat(repo, "systems", "sys1")
        out = capsys.readouterr().out
        assert "new" in out
        assert "old" not in out

    def test_not_found_prints_error(self, repo, capsys):
        cmd_cat(repo, "systems", "ghost")
        assert "error" in capsys.readouterr().out


class TestCmdGet:
    def test_system_decompresses_to_txt(self, repo, downloads):
        content = sys_doc(("m1", "s1", "12:00", "notes"))
        put_system(repo, "sys1", 2, content)
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "systems", "sys1", downloads, "mousepad")
        dest = downloads / f"{enc}.0002.txt"
        assert dest.exists()
        assert dest.read_text() == content

    def test_schedule_copied_as_txt(self, repo, downloads):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sc1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "schedules", "sc1", downloads, "mousepad")
        assert (downloads / f"{enc}.0000.txt").read_text() == "2020/01/01"

    def test_gets_latest_version(self, repo, downloads):
        put_system(repo, "sys1", 0, sys_doc(("old", "s1", "12:00", "n")))
        put_system(repo, "sys1", 3, sys_doc(("new", "s1", "12:00", "n")))
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_get(repo, "systems", "sys1", downloads, "mousepad")
        assert "new" in (downloads / f"{enc}.0003.txt").read_text()

    def test_opens_editor(self, repo, downloads):
        put_system(repo, "sys1", 0, sys_doc(("m1", "s1", "12:00", "n")))
        with patch.object(app.subprocess, "Popen") as mock_popen:
            cmd_get(repo, "systems", "sys1", downloads, "mousepad")
        mock_popen.assert_called_once()
        assert "mousepad" in mock_popen.call_args[0][0]

    def test_not_found_prints_error(self, repo, downloads, capsys):
        cmd_get(repo, "systems", "ghost", downloads, "mousepad")
        assert "error" in capsys.readouterr().out


class TestCmdClear:
    def test_system_writes_empty_template(self, repo, downloads):
        put_system(repo, "sys1", 1, sys_doc(("m1", "s1", "12:00", "n")))
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad")
        assert (downloads / f"{enc}.0001.txt").read_text() == _EMPTY_DOCUMENTS["systems"]

    def test_schedule_writes_empty_template(self, repo, downloads):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sc1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "schedules", "sc1", downloads, "mousepad")
        assert (downloads / f"{enc}.0000.txt").read_text() == _EMPTY_DOCUMENTS["schedules"]

    def test_uses_latest_version_for_filename(self, repo, downloads):
        put_system(repo, "sys1", 0, "")
        put_system(repo, "sys1", 5, "")
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad")
        assert (downloads / f"{enc}.0005.txt").exists()
        assert not (downloads / f"{enc}.0000.txt").exists()

    def test_not_found_prints_error(self, repo, downloads, capsys):
        cmd_clear(repo, "systems", "ghost", downloads, "mousepad")
        assert "error" in capsys.readouterr().out


class TestCmdPush:
    def test_system_creates_next_version(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("m1", "sc1", "12:00", "notes")))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert (repo / "systems" / f"{enc}.0001.txt.gz").exists()
        assert "version 0001" in capsys.readouterr().out

    def test_system_compresses_on_write(self, repo, downloads):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        content = sys_doc(("m1", "sc1", "12:00", "notes"))
        (downloads / f"{enc}.0000.txt").write_text(content)
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        gz = repo / "systems" / f"{enc}.0001.txt.gz"
        assert gzip.decompress(gz.read_bytes()).decode() == content

    def test_system_invalid_format_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text("not valid")
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_missing_schedule_rejected(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("m1", "ghost_sched", "12:00", "notes")))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert "rejected" in capsys.readouterr().out
        assert not (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_system_whitelisted_schedule_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("m1", "everyday", "12:00", "notes")))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist={"everyday"})
        assert "pushed" in capsys.readouterr().out

    def test_system_existing_repo_schedule_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "real_sched", 0, "2020/01/01")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("m1", "real_sched", "12:00", "notes")))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert "pushed" in capsys.readouterr().out

    def test_schedule_increments_version(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "")
        enc = encode_name("sc1")
        (downloads / f"{enc}.0000.txt").write_text("2020/01/01")
        cmd_push(repo, "schedules", "sc1", downloads, schedule_whitelist=set())
        assert (repo / "schedules" / f"{enc}.0001.txt").exists()
        assert "version 0001" in capsys.readouterr().out

    def test_schedule_invalid_format_rejected(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "")
        enc = encode_name("sc1")
        (downloads / f"{enc}.0000.txt").write_text("not-a-date")
        cmd_push(repo, "schedules", "sc1", downloads, schedule_whitelist=set())
        assert "rejected" in capsys.readouterr().out

    def test_empty_system_document_accepted(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(_EMPTY_DOCUMENTS["systems"])
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert "pushed" in capsys.readouterr().out
        assert (repo / "systems" / f"{enc}.0001.txt.gz").exists()

    def test_not_in_downloads_prints_error(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        assert "error" in capsys.readouterr().out

    def test_not_in_repo_prints_error(self, repo, downloads, capsys):
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("ghost")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("m1", "sc1", "12:00", "n")))
        cmd_push(repo, "systems", "ghost", downloads, schedule_whitelist=set())
        assert "error" in capsys.readouterr().out

    def test_push_uses_latest_downloads_file(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(sys_doc(("old", "sc1", "12:00", "n")))
        (downloads / f"{enc}.0003.txt").write_text(sys_doc(("new", "sc1", "12:00", "n")))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set())
        gz = repo / "systems" / f"{enc}.0001.txt.gz"
        assert "new" in gzip.decompress(gz.read_bytes()).decode()


class TestCmdExport:
    def test_systems_csv_content(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("m1", "sc1", "12:00", "some notes")))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "system_name, machine_name, schedule_name, time, notes" in content
        assert "sys1, m1, sc1, 12:00, some notes" in content

    def test_systems_multiple_sections_expand_to_rows(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("m1", "sc1", "08:00", "n1"), ("m2", "sc2", "09:00", "n2")))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        lines = (downloads / "out.csv").read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 data rows

    def test_systems_multiline_notes_joined(self, repo, downloads, cache):
        content = "\n".join([SEP, M, "m1", S, "sc1", T, "12:00", N, "line1", "line2"]) + "\n"
        put_system(repo, "sys1", 0, content)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        assert "line1 line2" in (downloads / "out.csv").read_text()

    def test_systems_uses_latest_version(self, repo, downloads, cache):
        put_system(repo, "sys1", 0, sys_doc(("old", "sc1", "12:00", "n")))
        put_system(repo, "sys1", 1, sys_doc(("new", "sc1", "12:00", "n")))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "new" in content
        assert "old" not in content

    def test_systems_excludes_initial_state(self, repo, downloads, cache):
        put_system(repo, "empty_sys", 0, _EMPTY_DOCUMENTS["systems"])
        put_system(repo, "real_sys", 0, sys_doc(("m1", "sc1", "12:00", "n")))
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "real_sys" in content
        assert "empty_sys" not in content

    def test_schedules_csv_content(self, repo, downloads, cache):
        put_schedule(repo, "sc1", 0, "2020/01/01,2020/06/15")
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "schedules", "out.csv", downloads, cache, "mousepad")
        content = (downloads / "out.csv").read_text()
        assert "schedule_name, dates" in content
        assert "sc1, 2020/01/01 2020/06/15" in content

    def test_schedules_excludes_initial_state(self, repo, downloads, cache):
        put_schedule(repo, "empty_sc", 0, _EMPTY_DOCUMENTS["schedules"])
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
        put_system(repo, "sys1", 0, sys_doc(("m1", "sc1", "12:00", "n")))
        # cache is empty — export must sync it first
        assert not (cache / "systems").exists()
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad")
        assert "sys1" in (downloads / "out.csv").read_text()


class TestAdditionalProps:
    def test_add_creates_template_with_props(self, repo, capsys):
        cmd_add(repo, "systems", "sys1", additional_props=PROPS)
        enc = encode_name("sys1")
        content = gzip.decompress((repo / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode()
        assert "👉p1👈" in content
        assert "👉p2👈" in content

    def test_add_template_matches_empty_system_document(self, repo):
        cmd_add(repo, "systems", "sys1", additional_props=PROPS)
        enc = encode_name("sys1")
        content = gzip.decompress((repo / "systems" / f"{enc}.0000.txt.gz").read_bytes()).decode()
        assert content == _empty_system_document(PROPS)

    def test_clear_writes_template_with_props(self, repo, downloads):
        put_system(repo, "sys1", 0, sys_doc(("m1", "sc1", "12:00", "n"), props=[("p1", "v"), ("p2", "")]))
        enc = encode_name("sys1")
        with patch.object(app.subprocess, "Popen"):
            cmd_clear(repo, "systems", "sys1", downloads, "mousepad", additional_props=PROPS)
        content = (downloads / f"{enc}.0000.txt").read_text()
        assert content == _empty_system_document(PROPS)

    def test_push_accepts_doc_with_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "sc1", "12:00", "notes"), props=[("p1", "val1"), ("p2", "")])
        (downloads / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set(), additional_props=PROPS)
        assert "pushed" in capsys.readouterr().out

    def test_push_rejects_doc_missing_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        put_schedule(repo, "sc1", 0, "2020/01/01")
        enc = encode_name("sys1")
        doc = sys_doc(("m1", "sc1", "12:00", "notes"))  # no additional props in document
        (downloads / f"{enc}.0000.txt").write_text(doc)
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set(), additional_props=PROPS)
        assert "rejected" in capsys.readouterr().out

    def test_push_accepts_initial_state_with_props(self, repo, downloads, capsys):
        put_system(repo, "sys1", 0, "")
        enc = encode_name("sys1")
        (downloads / f"{enc}.0000.txt").write_text(_empty_system_document(PROPS))
        cmd_push(repo, "systems", "sys1", downloads, schedule_whitelist=set(), additional_props=PROPS)
        assert "pushed" in capsys.readouterr().out

    def test_export_csv_includes_prop_columns(self, repo, downloads, cache):
        doc = sys_doc(("m1", "sc1", "12:00", "notes"), props=[("p1", "val1"), ("p2", "val2")])
        put_system(repo, "sys1", 0, doc)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=PROPS)
        content = (downloads / "out.csv").read_text()
        assert "system_name, machine_name, schedule_name, time, notes, p1, p2" in content
        assert "sys1, m1, sc1, 12:00, notes, val1, val2" in content

    def test_export_csv_empty_prop_value(self, repo, downloads, cache):
        doc = sys_doc(("m1", "sc1", "12:00", "notes"), props=[("p1", ""), ("p2", "v2")])
        put_system(repo, "sys1", 0, doc)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=PROPS)
        content = (downloads / "out.csv").read_text()
        assert "sys1, m1, sc1, 12:00, notes, , v2" in content

    def test_export_csv_mismatched_props_fill_empty(self, repo, downloads, cache):
        # document was saved with p1 and p3; export configured for p1 and p2
        doc = sys_doc(("m1", "sc1", "12:00", "notes"), props=[("p1", "val1"), ("p3", "val3")])
        put_system(repo, "sys1", 0, doc)
        with patch.object(app.subprocess, "Popen"):
            cmd_export(repo, "systems", "out.csv", downloads, cache, "mousepad", additional_props=PROPS)
        content = (downloads / "out.csv").read_text()
        assert "system_name, machine_name, schedule_name, time, notes, p1, p2" in content
        assert "sys1, m1, sc1, 12:00, notes, val1, " in content
