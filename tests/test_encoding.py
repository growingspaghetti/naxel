import pytest
from pathlib import Path
from app import encode_name, decode_name, latest_in_dir, sync_cache


class TestEncodeDecode:
    def test_roundtrip(self):
        for name in ["sys1", "sc1", "hello", "a-long-name", "x", "abcde"]:
            assert decode_name(encode_name(name)) == name

    def test_no_padding_in_output(self):
        for name in ["a", "ab", "abc", "abcd", "abcde", "abcdef"]:
            assert "=" not in encode_name(name)

    def test_output_is_uppercase(self):
        enc = encode_name("hello")
        assert enc == enc.upper()

    def test_decode_invalid_returns_none(self):
        assert decode_name("!!!") is None


class TestLatestInDir:
    def test_returns_highest_version(self, tmp_path):
        for v in ["0000", "0001", "0002"]:
            (tmp_path / f"ENC.{v}.txt").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt") == tmp_path / "ENC.0002.txt"

    def test_missing_dir_returns_none(self, tmp_path):
        assert latest_in_dir(tmp_path / "nope", "ENC", ".txt") is None

    def test_empty_dir_returns_none(self, tmp_path):
        assert latest_in_dir(tmp_path, "ENC", ".txt") is None

    def test_wrong_suffix_ignored(self, tmp_path):
        (tmp_path / "ENC.0000.txt").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt.gz") is None

    def test_wrong_prefix_ignored(self, tmp_path):
        (tmp_path / "OTHER.0000.txt").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt") is None

    def test_non_digit_version_ignored(self, tmp_path):
        (tmp_path / "ENC.abcd.txt").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt") is None

    def test_gz_suffix(self, tmp_path):
        (tmp_path / "ENC.0000.txt.gz").touch()
        (tmp_path / "ENC.0003.txt.gz").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt.gz") == tmp_path / "ENC.0003.txt.gz"

    def test_single_file(self, tmp_path):
        (tmp_path / "ENC.0007.txt").touch()
        assert latest_in_dir(tmp_path, "ENC", ".txt") == tmp_path / "ENC.0007.txt"


class TestSyncCache:
    def test_copies_missing_files(self, tmp_path):
        repo, cache = tmp_path / "repo", tmp_path / "cache"
        (repo / "systems").mkdir(parents=True)
        (repo / "schedules").mkdir(parents=True)
        (repo / "systems" / "A.0000.txt.gz").write_bytes(b"gz_data")
        (repo / "schedules" / "B.0000.txt").write_text("2020/01/01")
        sync_cache(repo, cache)
        assert (cache / "systems" / "A.0000.txt.gz").read_bytes() == b"gz_data"
        assert (cache / "schedules" / "B.0000.txt").read_text() == "2020/01/01"

    def test_does_not_overwrite_existing(self, tmp_path):
        repo, cache = tmp_path / "repo", tmp_path / "cache"
        (repo / "systems").mkdir(parents=True)
        (repo / "schedules").mkdir(parents=True)
        (cache / "systems").mkdir(parents=True)
        (repo / "systems" / "A.0000.txt.gz").write_bytes(b"new")
        (cache / "systems" / "A.0000.txt.gz").write_bytes(b"old")
        sync_cache(repo, cache)
        assert (cache / "systems" / "A.0000.txt.gz").read_bytes() == b"old"

    def test_prints_count_when_files_copied(self, tmp_path, capsys):
        repo, cache = tmp_path / "repo", tmp_path / "cache"
        (repo / "systems").mkdir(parents=True)
        (repo / "schedules").mkdir(parents=True)
        (repo / "systems" / "A.0000.txt.gz").write_bytes(b"x")
        (repo / "systems" / "B.0000.txt.gz").write_bytes(b"y")
        sync_cache(repo, cache)
        assert "2 file" in capsys.readouterr().out

    def test_silent_when_nothing_to_copy(self, tmp_path, capsys):
        repo, cache = tmp_path / "repo", tmp_path / "cache"
        (repo / "systems").mkdir(parents=True)
        (repo / "schedules").mkdir(parents=True)
        sync_cache(repo, cache)
        assert capsys.readouterr().out == ""

    def test_skips_missing_collection_dir(self, tmp_path):
        repo, cache = tmp_path / "repo", tmp_path / "cache"
        repo.mkdir()
        # neither systems/ nor schedules/ exist in repo — should not crash
        sync_cache(repo, cache)
