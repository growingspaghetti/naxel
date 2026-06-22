import base64
import configparser
import hashlib
import gzip
import json
import os
import re
from prompt_toolkit import PromptSession
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from gui import JTable

SCRIPT_DIR = Path(__file__).parent.parent


def _launch_jtable(**kwargs):
    threading.Thread(target=lambda: JTable(**kwargs).run(), daemon=True).start()


def load_config():
    config = configparser.ConfigParser()
    config.read(SCRIPT_DIR / "settings.ini")
    return config


def get_repo_root(config):
    return SCRIPT_DIR / config.get("repository", "root", fallback="dummy-repo")


def get_downloads_dir(config):
    return SCRIPT_DIR / config.get("downloads", "dir", fallback="downloads")


def get_cache_dir(config):
    return SCRIPT_DIR / config.get("cache", "dir", fallback="cache")


def get_editor(config):
    return config.get("editor", "command", fallback="mousepad")


def repo_namespace(repo_root: Path) -> str:
    return hashlib.md5(str(repo_root.resolve()).encode()).hexdigest()


def load_repository_config(repo_root: Path) -> tuple[str, str, tuple[str, ...], str, str, str]:
    repo_ini = configparser.ConfigParser()
    repo_ini.read(repo_root / "repository.ini")
    collection_name = repo_ini.get("main_collection", "collection_name", fallback="systems")
    partitioning_property = repo_ini.get("main_collection", "partitioning_property", fallback="system")
    raw = repo_ini.get("main_collection", "property_order", fallback="")
    property_order = tuple(s.strip() for s in raw.split(",") if s.strip())
    additional_props_file = repo_ini.get("additional_properties", "json", fallback="additional_properties.json")
    ref_collections_file = repo_ini.get("reference_collections", "json", fallback="additional_mandatory_properties.json")
    intro_message = repo_ini.get("introduction", "message", fallback="")
    return collection_name, partitioning_property, property_order, additional_props_file, ref_collections_file, intro_message


def load_additional_properties(repo_root: Path, filename: str) -> tuple[tuple[str, str, bool], ...]:
    path = repo_root / filename
    try:
        data = json.loads(path.read_text())
        result = []
        for item in data:
            if isinstance(item, dict):
                name = str(item.get("property_name", "")).strip()
                vtype = str(item.get("validation_type", "NONE")).strip()
                multiline = bool(item.get("multiline", False))
                if name:
                    result.append((name, vtype, multiline))
        return tuple(result)
    except FileNotFoundError:
        return ()
    except Exception as e:
        print(f"warning: could not read {filename}: {e}")
        return ()


def load_dynamic_collections(repo_root: Path, filename: str) -> list[dict]:
    path = repo_root / filename
    try:
        data = json.loads(path.read_text())
        return [d for d in data if isinstance(d, dict) and d.get("collection_name")]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"warning: could not read {filename}: {e}")
        return []


def sync_cache(repo_root: Path, cache_dir: Path):
    copied = 0
    for collection in sorted(COLLECTIONS):
        src_dir = collection_path(repo_root, collection)
        dst_dir = cache_dir / collection
        if not src_dir.is_dir():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        cached = set(os.listdir(dst_dir))
        for fname in os.listdir(src_dir):
            if fname not in cached:
                (dst_dir / fname).write_bytes((src_dir / fname).read_bytes())
                copied += 1
    if copied:
        print(f"cache: synced {copied} file(s)")


def build_ref_data(cache_dir: Path,
                   mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...]
                   ) -> dict[str, dict[str, str]]:
    """Read cache for each reference collection; return {property_name: {entry_name: content}}."""
    result: dict[str, dict[str, str]] = {}
    for pname, cname, _ in mandatory_ref_props:
        col_dir = cache_dir / cname
        mapping: dict[str, str] = {}
        try:
            for fname in sorted(os.listdir(col_dir)):
                if not fname.endswith(".txt"):
                    continue
                stem = fname[:-4]
                parts = stem.split(".")
                if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
                    name = decode_name(parts[0])
                    if name is not None:
                        mapping[name] = (col_dir / fname).read_text().strip()
        except FileNotFoundError:
            pass
        result[pname] = mapping
    return result


MAIN_COLLECTION: str | None = None
PARTITIONING_PROPERTY: str | None = None

COLLECTIONS: set[str] = set()  # populated in main() from repository.ini and reference_collections JSON

COLLECTION_TYPE: dict[str, str] = {}


@dataclass
class RepoState:
    repo_root: Path
    downloads_dir: Path
    cache_dir: Path
    additional_props: tuple[str, ...]
    mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...]
    field_order: tuple[str, ...] | None
    prop_validation_types: dict[str, str]
    multiline_props: frozenset[str]
    intro_message: str


def _repo_suffix(collection: str) -> str:
    return ".txt.gz" if collection == MAIN_COLLECTION else ".txt"


def encode_name(name: str) -> str:
    return base64.b32encode(name.encode()).decode().rstrip("=")


def decode_name(encoded: str) -> str | None:
    # base32 output must be a multiple of 8 chars; restore stripped padding
    padding = (8 - len(encoded) % 8) % 8
    try:
        return base64.b32decode(encoded + "=" * padding).decode()
    except Exception:
        return None


def collection_path(repo_root: Path, collection: str) -> Path:
    return repo_root / collection


def latest_in_dir(directory: Path, encoded: str, suffix: str) -> Path | None:
    prefix = encoded + "."
    total = len(prefix) + 4 + len(suffix)  # encoded + "." + 4-digit version + suffix
    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return None
    matches = sorted(
        f for f in entries
        if len(f) == total
        and f.startswith(prefix)
        and f.endswith(suffix)
        and f[len(prefix):len(prefix) + 4].isdigit()
    )
    return (directory / matches[-1]) if matches else None


def find_latest_file(repo_root: Path, collection: str, name: str) -> Path | None:
    suffix = _repo_suffix(collection)
    return latest_in_dir(collection_path(repo_root, collection), encode_name(name), suffix)


# ── validation ────────────────────────────────────────────────────────────────

_SEPARATOR = "\U0001f3d4" * 20
_FULL_DATE_SEG = r"\d{4}/\d{2}/\d{2}"
_FULL_DATE_RE = re.compile(rf"^{_FULL_DATE_SEG}(,{_FULL_DATE_SEG})*\n?$")
_PHONE_NUMBER_SEG = r"[0-9\-\+]+"
_PHONE_NUMBER_RE = re.compile(rf"^{_PHONE_NUMBER_SEG}(,{_PHONE_NUMBER_SEG})*\n?$")
_EMAIL_SEG = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
_EMAIL_RE = re.compile(rf"^{_EMAIL_SEG}(,{_EMAIL_SEG})*\n?$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_MMDD_RE = re.compile(r"^\d{2}/\d{2}$")
_INT_RE = re.compile(r"^[0-9]+$")
_YEAR_RE = re.compile(r"^\d{4}$")
_YEAR_ENTRY_SEG = r"\d{4}"
_YEAR_ENTRY_RE = re.compile(rf"^{_YEAR_ENTRY_SEG}(,{_YEAR_ENTRY_SEG})*\n?$")
_CORE_LABELS: frozenset[str] = frozenset()
_DEFAULT_CORE: tuple[str, ...] = ()
_DEFAULT_CORE_SET: frozenset[str] = frozenset()


def _is_prop_label(line: str) -> bool:
    """True for any 👉name👈 line that is not the separator or a core field label."""
    return (line.startswith("\U0001f449")
            and line.endswith("\U0001f448")
            and line != _SEPARATOR
            and line not in _CORE_LABELS)


def _is_any_label(line: str) -> bool:
    """True for any 👉name👈 line (core or extra, not the separator)."""
    return (line.startswith("\U0001f449")
            and line.endswith("\U0001f448")
            and line != _SEPARATOR)


def _empty_main_collection_document(additional_props: tuple[str, ...] = (), *,
                            field_order: tuple[str, ...] | None = None) -> str:
    order = field_order if field_order is not None else (_DEFAULT_CORE + additional_props)
    lines = [_SEPARATOR]
    for key in order:
        lines += [f"\U0001f449{key}\U0001f448", ""]
    return "\n".join(lines) + "\n"




def _empty_main_collection_json(additional_props: tuple[str, ...] = (), *,
                        field_order: tuple[str, ...] | None = None) -> str:
    order = field_order if field_order is not None else (_DEFAULT_CORE + additional_props)
    section: dict[str, str] = {key: "" for key in order}
    return json.dumps([section], ensure_ascii=False, indent=2) + "\n"


def _main_collection_sections_to_text(sections: list[dict], additional_props: tuple[str, ...] = (), *,
                               field_order: tuple[str, ...] | None = None) -> str:
    """Convert parsed JSON sections to the human-readable 👉👈 text format."""
    order = field_order if field_order is not None else (_DEFAULT_CORE + additional_props)
    lines = []
    for sec in sections:
        lines.append(_SEPARATOR)
        for key in order:
            lines.append(f"\U0001f449{key}\U0001f448")
            lines.append(sec.get(key, ""))
    return "\n".join(lines) + "\n"


def _text_to_main_collection_json(content: str, additional_props: tuple[str, ...] = (), *,
                          field_order: tuple[str, ...] | None = None,
                          multiline_props: frozenset[str] = frozenset()) -> str:
    """Convert 👉👈 separator text (from downloads) to a JSON string for repo storage."""
    lines = content.splitlines()
    n, i, sections = len(lines), 0, []
    while i < n:
        if lines[i] != _SEPARATOR:
            i += 1
            continue
        i += 1
        section: dict[str, str] = {}
        if field_order is not None:
            for key in field_order:
                label = f"\U0001f449{key}\U0001f448"
                if i >= n or lines[i] != label:
                    section = {}
                    break
                i += 1
                if key in multiline_props:
                    ml_lines: list[str] = []
                    while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                        ml_lines.append(lines[i])
                        i += 1
                    section[key] = "\n".join(ml_lines)
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == len(field_order):
                sections.append(section)
        else:
            found: dict[str, str] = {}
            while i < n and lines[i] != _SEPARATOR:
                line = lines[i]
                if _is_any_label(line):
                    prop_name = line[1:-1]
                    i += 1
                    if prop_name in multiline_props:
                        ml_lines = []
                        while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                            ml_lines.append(lines[i])
                            i += 1
                        found[prop_name] = "\n".join(ml_lines)
                    else:
                        found[prop_name] = lines[i].strip() if i < n else ""
                        if i < n:
                            i += 1
                else:
                    i += 1
            for p in additional_props:
                section[p] = found.get(p, "")
            sections.append(section)
    return json.dumps(sections, ensure_ascii=False, indent=2) + "\n"


def _validate_main_collection(content: str, additional_props: tuple[str, ...] = (),
                     mandatory_prop_names: frozenset[str] = frozenset(), *,
                     field_order: tuple[str, ...] | None = None,
                     prop_validation_types: dict[str, str] = {},
                     multiline_props: frozenset[str] = frozenset()) -> tuple[bool, str]:
    lines = content.splitlines()
    n = len(lines)
    i = 0
    section_count = 0
    order = field_order if field_order is not None else additional_props

    while i < n:
        if lines[i] != _SEPARATOR:
            return False, f"line {i + 1}: expected separator"
        i += 1

        for key in order:
            label = f"\U0001f449{key}\U0001f448"
            if i >= n or lines[i] != label:
                return False, f"line {i + 1}: expected {label!r}"
            i += 1
            if key in multiline_props:
                while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                    i += 1
            else:
                if i >= n:
                    return False, f"line {i + 1}: missing value line for {key!r}"
                if key in mandatory_prop_names:
                    if not lines[i].strip():
                        return False, f"line {i + 1}: value for {key!r} is required"
                else:
                    vtype = prop_validation_types.get(key, "NONE")
                    if vtype == "NOT_EMPTY" and not lines[i].strip():
                        return False, f"line {i + 1}: value for {key!r} is required"
                    elif vtype == "HH:MM" and not _TIME_RE.match(lines[i]):
                        return False, f"line {i + 1}: value for {key!r} must be HH:MM (got {lines[i]!r})"
                    elif vtype == "MM/DD" and not _MMDD_RE.match(lines[i]):
                        return False, f"line {i + 1}: value for {key!r} must be MM/DD (got {lines[i]!r})"
                    elif vtype == "INT" and not _INT_RE.match(lines[i]):
                        return False, f"line {i + 1}: value for {key!r} must be an integer (got {lines[i]!r})"
                    elif vtype == "YYYY" and not _YEAR_RE.match(lines[i]):
                        return False, f"line {i + 1}: value for {key!r} must be YYYY (got {lines[i]!r})"
                    elif vtype.startswith("RE:"):
                        pattern = vtype[3:]
                        if not re.fullmatch(pattern, lines[i]):
                            return False, f"line {i + 1}: value for {key!r} must match /{pattern}/ (got {lines[i]!r})"
                i += 1

        section_count += 1

    if section_count == 0:
        return False, "no sections found"
    return True, ""


def _validate_years(content: str) -> tuple[bool, str]:
    if _YEAR_ENTRY_RE.match(content):
        return True, ""
    return False, "expected: yyyy,yyyy,... (one line)"


def _validate_dates(content: str) -> tuple[bool, str]:
    if _FULL_DATE_RE.match(content):
        return True, ""
    return False, "expected: yyyy/mm/dd,yyyy/mm/dd,... (one line)"


def _validate_phone_numbers(content: str) -> tuple[bool, str]:
    if _PHONE_NUMBER_RE.match(content):
        return True, ""
    return False, "expected: digits/dashes/plus signs separated by commas (one line)"


def _validate_email(content: str) -> tuple[bool, str]:
    if _EMAIL_RE.match(content):
        return True, ""
    return False, "expected: email@domain.tld,email2@domain.tld,... (one line)"


def validate(collection: str, content: str, additional_props: tuple[str, ...] = (),
             mandatory_prop_names: frozenset[str] = frozenset(), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {},
             multiline_props: frozenset[str] = frozenset()) -> tuple[bool, str]:
    if collection == MAIN_COLLECTION:
        return _validate_main_collection(content, additional_props, mandatory_prop_names,
                                field_order=field_order,
                                prop_validation_types=prop_validation_types,
                                multiline_props=multiline_props)
    ctype = COLLECTION_TYPE.get(collection, "")
    if ctype == "DATE":
        return _validate_dates(content)
    if ctype == "PHONE_NUMBER":
        return _validate_phone_numbers(content)
    if ctype == "EMAIL":
        return _validate_email(content)
    if ctype == "YEAR":
        return _validate_years(content)
    return True, ""


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_ls(repo_root: Path, collection: str):
    path = collection_path(repo_root, collection)
    if not path.is_dir():
        print(f"error: directory not found: {path}")
        return
    suffix = _repo_suffix(collection)
    seen: set[str] = set()
    for fname in sorted(os.listdir(path)):
        if not fname.endswith(suffix):
            continue
        stem = fname[: -len(suffix)]  # e.g. "ON4XGMI.0000"
        parts = stem.split(".")
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
            encoded = parts[0]
            if encoded not in seen:
                seen.add(encoded)
                name = decode_name(encoded)
                if name is not None:
                    print(name)


def cmd_add(repo_root: Path, collection: str, name: str,
            additional_props: tuple[str, ...] = (), *,
            field_order: tuple[str, ...] | None = None):
    path = collection_path(repo_root, collection)
    path.mkdir(parents=True, exist_ok=True)
    encoded = encode_name(name)
    suffix = _repo_suffix(collection)
    dest = path / f"{encoded}.0000{suffix}"
    if dest.exists():
        print(f"error: already exists: {name}")
        return
    if suffix == ".txt.gz":
        dest.write_bytes(gzip.compress(
            _empty_main_collection_json(additional_props, field_order=field_order).encode()))
    else:
        dest.write_text("")
    print(f"created: {name}")


def cmd_len(repo_root: Path, collection: str, name: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    if collection == MAIN_COLLECTION:
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        print(sum(1 for s in sections if any(v for v in s.values())))
    else:
        content = filepath.read_text().strip()
        print(len(content.split(",")) if content else 0)


def cmd_cat(repo_root: Path, collection: str, name: str,
            additional_props: tuple[str, ...] = (),
            downloads_dir: Path | None = None, jtable: bool = False, *,
            as_json: bool = False,
            field_order: tuple[str, ...] | None = None,
            multiline_props: frozenset[str] = frozenset(),
            ref_data: dict | None = None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    if jtable:
        dl_dir = downloads_dir / collection
        dl_dir.mkdir(parents=True, exist_ok=True)
        if collection == MAIN_COLLECTION:
            sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
            dl_name = filepath.name[:-3]  # strip .gz
            dest = dl_dir / dl_name
            dest.write_text(_main_collection_sections_to_text(sections, additional_props,
                                                      field_order=field_order))
            print(f"saved: {dest}")
            _launch_jtable(path=dest, mode="main_text", readonly=True,
                           multiline_cols=multiline_props, ref_data=ref_data)
        else:
            dest = dl_dir / filepath.name
            dest.write_text(filepath.read_text())
            print(f"saved: {dest}")
            _launch_jtable(path=dest, mode="ref", readonly=True, title=f"{collection} {name}")
        return
    if as_json:
        if collection == MAIN_COLLECTION:
            sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
            print(json.dumps(sections, ensure_ascii=False, indent=2))
        else:
            raw = filepath.read_text().strip()
            values = [v.strip() for v in raw.split(",") if v.strip()] if raw else []
            print(json.dumps(values, ensure_ascii=False, indent=2))
        return
    if collection == MAIN_COLLECTION and filepath.name.endswith(".gz"):
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        print(_main_collection_sections_to_text(sections, additional_props, field_order=field_order), end="")
    elif filepath.name.endswith(".gz"):
        print(gzip.decompress(filepath.read_bytes()).decode(), end="")
    else:
        content = filepath.read_text()
        print(content, end="" if content.endswith("\n") else "\n")


def cmd_clear(repo_root: Path, collection: str, name: str,
              downloads_dir: Path, editor: str, additional_props: tuple[str, ...] = (),
              jtable: bool = False, *,
              field_order: tuple[str, ...] | None = None,
              multiline_props: frozenset[str] = frozenset(),
              push_callback=None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    dl_dir = downloads_dir / collection
    dl_dir.mkdir(parents=True, exist_ok=True)
    dl_name = filepath.name[:-3] if filepath.name.endswith(".gz") else filepath.name
    dest = dl_dir / dl_name
    if collection == MAIN_COLLECTION:
        template = _empty_main_collection_document(additional_props, field_order=field_order)
    else:
        template = ""
    dest.write_text(template)
    print(f"cleared: {dest}")
    if jtable:
        if collection == MAIN_COLLECTION:
            _launch_jtable(path=dest, mode="main_text", multiline_cols=multiline_props,
                           push_callback=push_callback)
        else:
            _launch_jtable(path=dest, mode="ref", title=f"{collection} {name}",
                           push_callback=push_callback)
    else:
        subprocess.Popen([editor, str(dest)])


def cmd_get(repo_root: Path, collection: str, name: str,
            downloads_dir: Path, editor: str,
            additional_props: tuple[str, ...] = (), jtable: bool = False, *,
            field_order: tuple[str, ...] | None = None,
            multiline_props: frozenset[str] = frozenset(),
            stdin_content: str | None = None,
            push_callback=None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    dl_dir = downloads_dir / collection
    dl_dir.mkdir(parents=True, exist_ok=True)
    dl_name = filepath.name[:-3] if filepath.name.endswith(".gz") else filepath.name
    dest = dl_dir / dl_name
    if stdin_content is not None:
        dest.write_text(stdin_content)
        print(f"saved: {dest}")
        return
    if collection == MAIN_COLLECTION and filepath.name.endswith(".gz"):
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        dest.write_text(_main_collection_sections_to_text(sections, additional_props,
                                                  field_order=field_order))
    elif filepath.name.endswith(".gz"):
        dest.write_text(gzip.decompress(filepath.read_bytes()).decode())
    else:
        dest.write_text(filepath.read_text())
    print(f"saved: {dest}")
    if jtable:
        if collection == MAIN_COLLECTION:
            _launch_jtable(path=dest, mode="main_text", multiline_cols=multiline_props,
                           push_callback=push_callback)
        else:
            _launch_jtable(path=dest, mode="ref", title=f"{collection} {name}",
                           push_callback=push_callback)
    else:
        subprocess.Popen([editor, str(dest)])


def cmd_diff(repo_root: Path, collection: str, name: str,
             additional_props: tuple[str, ...] = (), jtable: bool = False, *,
             field_order: tuple[str, ...] | None = None):
    suffix = _repo_suffix(collection)
    col_path = collection_path(repo_root, collection)
    encoded = encode_name(name)
    prefix = encoded + "."
    total = len(prefix) + 4 + len(suffix)
    try:
        entries = os.listdir(col_path)
    except FileNotFoundError:
        print(f"error: not found: {name}")
        return
    matches = sorted(
        f for f in entries
        if len(f) == total
        and f.startswith(prefix)
        and f.endswith(suffix)
        and f[len(prefix):len(prefix) + 4].isdigit()
    )
    if not matches:
        print(f"error: not found: {name}")
        return
    if len(matches) < 2:
        print(f"error: only one version exists for: {name}")
        return

    if collection == MAIN_COLLECTION:
        prev_sections = json.loads(gzip.decompress((col_path / matches[-2]).read_bytes()).decode())
        curr_sections = json.loads(gzip.decompress((col_path / matches[-1]).read_bytes()).decode())

        def _key(sec: dict) -> str:
            return json.dumps(sec, ensure_ascii=False, sort_keys=True)

        prev_keys = {_key(s) for s in prev_sections}
        curr_keys = {_key(s) for s in curr_sections}
        deleted = [s for s in prev_sections if _key(s) not in curr_keys]
        added = [s for s in curr_sections if _key(s) not in prev_keys]
        if jtable:
            cols = list(field_order) if field_order is not None else list(additional_props)
            _launch_jtable(
                diff_data={
                    "columns": cols,
                    "deleted": [[s.get(k, "") for k in cols] for s in deleted],
                    "added":   [[s.get(k, "") for k in cols] for s in added],
                },
                title=f"diff {collection} {name}",
            )
            return
    else:
        def _parse_entries(path: Path) -> list[str]:
            content = path.read_text().strip()
            return [e.strip() for e in content.split(",") if e.strip()] if content else []

        prev_entries = _parse_entries(col_path / matches[-2])
        curr_entries = _parse_entries(col_path / matches[-1])
        prev_set = set(prev_entries)
        curr_set = set(curr_entries)
        deleted = [e for e in prev_entries if e not in curr_set]
        added = [e for e in curr_entries if e not in prev_set]
        if jtable:
            col_name = "date" if collection == "schedules" else "number" if collection == "contacts" else "value"
            _launch_jtable(
                diff_data={
                    "columns": [col_name],
                    "deleted": [[e] for e in deleted],
                    "added":   [[e] for e in added],
                },
                title=f"diff {collection} {name}",
            )
            return

    print(json.dumps({"deleted": deleted, "added": added}, ensure_ascii=False, indent=2))


def cmd_push(repo_root: Path, collection: str, name: str, downloads_dir: Path,
             additional_props: tuple[str, ...] = (),
             mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...] = (), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {},
             multiline_props: frozenset[str] = frozenset(),
             json_mode: bool = False):
    encoded = encode_name(name)
    src = latest_in_dir(downloads_dir / collection, encoded, ".txt")
    if src is None:
        print(f"error: not found in downloads: {name}")
        return
    if json_mode:
        raw = json.loads(src.read_text())
        if collection == MAIN_COLLECTION:
            content = _main_collection_sections_to_text(raw, additional_props, field_order=field_order)
        else:
            values = [v for v in raw if isinstance(v, str)]
            content = ",".join(values)
    else:
        content = src.read_text()
    if not (collection == MAIN_COLLECTION and _is_initial_state_main_collection(
            content, additional_props, field_order=field_order, multiline_props=multiline_props)):
        mandatory_prop_names = frozenset(pname for pname, _, _ in mandatory_ref_props)
        ok, reason = validate(collection, content, additional_props, mandatory_prop_names,
                              field_order=field_order,
                              prop_validation_types=prop_validation_types,
                              multiline_props=multiline_props)
        if not ok:
            print(f"rejected: {reason}")
            return
        if collection == MAIN_COLLECTION and mandatory_ref_props:
            sections_for_ref = _parse_main_collection_sections(content, additional_props,
                                                       field_order=field_order,
                                                       multiline_props=multiline_props)
            for pname, cname, whitelist in mandatory_ref_props:
                ref_suffix = _repo_suffix(cname)
                ref_dir = collection_path(repo_root, cname)
                try:
                    existing_refs = {
                        f[: -len(ref_suffix)].split(".")[0]
                        for f in os.listdir(ref_dir)
                        if f.endswith(ref_suffix)
                    }
                except FileNotFoundError:
                    existing_refs = set()
                for sec in sections_for_ref:
                    val = sec.get(pname, "")
                    if val and val not in whitelist and encode_name(val) not in existing_refs:
                        print(f"rejected: {pname} {val!r} not found in {cname} collection")
                        return
    col_path = collection_path(repo_root, collection)
    suffix = _repo_suffix(collection)
    latest = latest_in_dir(col_path, encoded, suffix)
    if latest is None:
        print(f"error: not found in repository: {name}")
        return
    current_version = int(latest.name[len(encoded) + 1: len(encoded) + 5])
    new_version = current_version + 1
    dest = col_path / f"{encoded}.{new_version:04d}{suffix}"
    if suffix == ".txt.gz":
        if not content.strip():
            body = _empty_main_collection_json(additional_props, field_order=field_order)
        else:
            body = _text_to_main_collection_json(content, additional_props, field_order=field_order,
                                         multiline_props=multiline_props)
        dest.write_bytes(gzip.compress(body.encode()))
    else:
        dest.write_text(content)
    print(f"pushed: {name} (version {new_version:04d})")


def _parse_main_collection_sections(content: str, additional_props: tuple[str, ...] = (), *,
                             field_order: tuple[str, ...] | None = None,
                             multiline_props: frozenset[str] = frozenset()) -> list[dict]:
    lines = content.splitlines()
    n, i, sections = len(lines), 0, []
    while i < n:
        if lines[i] != _SEPARATOR:
            i += 1
            continue
        i += 1
        section: dict = {}
        if field_order is not None:
            for key in field_order:
                label = f"\U0001f449{key}\U0001f448"
                if i >= n or lines[i] != label:
                    section = {}
                    break
                i += 1
                if key in multiline_props:
                    ml_lines: list[str] = []
                    while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                        ml_lines.append(lines[i])
                        i += 1
                    section[key] = " ".join(ml_lines).strip()
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == len(field_order):
                sections.append(section)
        else:
            found: dict[str, str] = {}
            while i < n and lines[i] != _SEPARATOR:
                line = lines[i]
                if _is_any_label(line):
                    prop_name = line[1:-1]
                    i += 1
                    if prop_name in multiline_props:
                        ml_lines = []
                        while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                            ml_lines.append(lines[i])
                            i += 1
                        found[prop_name] = " ".join(ml_lines).strip()
                    else:
                        found[prop_name] = lines[i].strip() if i < n else ""
                        if i < n:
                            i += 1
                else:
                    i += 1
            for p in additional_props:
                section[p] = found.get(p, "")
            sections.append(section)
    return sections


def _is_initial_state_main_collection(content: str, additional_props: tuple[str, ...] = (), *,
                               field_order: tuple[str, ...] | None = None,
                               multiline_props: frozenset[str] = frozenset()) -> bool:
    if not content.strip():
        return True  # all rows deleted via GUI → treat as cleared
    sections = _parse_main_collection_sections(content, additional_props, field_order=field_order,
                                       multiline_props=multiline_props)
    extra_to_check = tuple(field_order) if field_order is not None else additional_props
    return bool(sections) and all(
        all(not s.get(p) for p in extra_to_check)
        for s in sections
    )


def _csv_field(s: str) -> str:
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_row(*fields: str) -> str:
    return ", ".join(_csv_field(f) for f in fields)


def cmd_export(repo_root: Path, collection: str, filename: str,
               downloads_dir: Path, cache_dir: Path, editor: str,
               additional_props: tuple[str, ...] = (), jtable: bool = False, *,
               field_order: tuple[str, ...] | None = None,
               multiline_props: frozenset[str] = frozenset(),
               mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...] = ()):
    sync_cache(repo_root, cache_dir)
    col_path = cache_dir / collection
    if not col_path.is_dir():
        print(f"error: directory not found: {col_path}")
        return

    suffix = _repo_suffix(collection)
    seen: dict[str, str] = {}  # encoded → latest filename (sorted order gives highest version last)
    for fname in sorted(os.listdir(col_path)):
        if not fname.endswith(suffix):
            continue
        stem = fname[: -len(suffix)]
        parts = stem.split(".")
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
            seen[parts[0]] = fname

    downloads_dir.mkdir(parents=True, exist_ok=True)
    dest = downloads_dir / filename

    if filename.endswith(".json"):
        records: list[dict] = []
        if collection == MAIN_COLLECTION:
            cols = list(field_order) if field_order is not None else list(additional_props)
            name_col = f"{PARTITIONING_PROPERTY}_name"
            for encoded, fname in sorted(seen.items()):
                system_name = decode_name(encoded) or encoded
                sections = json.loads(gzip.decompress((col_path / fname).read_bytes()).decode())
                if all(not any(v for v in s.values()) for s in sections):
                    continue
                for sec in sections:
                    record: dict[str, str] = {name_col: system_name}
                    for f in cols:
                        record[f] = sec.get(f, "")
                    records.append(record)
            dest.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        else:
            for encoded, fname in sorted(seen.items()):
                entry_name = decode_name(encoded) or encoded
                content = (col_path / fname).read_text().strip()
                if not content:
                    continue
                values = [v.strip() for v in content.split(",") if v.strip()]
                records.append({"name": entry_name, "values": values})
            dest.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(f"exported: {dest}")
        subprocess.Popen([editor, str(dest)])
        return

    rows = []
    if collection == MAIN_COLLECTION:
        csv_name_col = f"{PARTITIONING_PROPERTY}_name"
        if field_order is not None:
            rows.append(_csv_row(csv_name_col, *field_order))
        else:
            rows.append(_csv_row(csv_name_col, *additional_props))
        for encoded, fname in sorted(seen.items()):
            system_name = decode_name(encoded) or encoded
            sections = json.loads(gzip.decompress((col_path / fname).read_bytes()).decode())
            if all(not any(v for v in s.values()) for s in sections):
                continue  # initial state: no meaningful data yet
            for sec in sections:
                if field_order is not None:
                    vals: list[str] = []
                    for f in field_order:
                        if f in multiline_props:
                            vals.append(" ".join(sec.get(f, "").splitlines()).strip())
                        else:
                            vals.append(sec.get(f, ""))
                    rows.append(_csv_row(system_name, *vals))
                else:
                    vals = []
                    for p in additional_props:
                        v = sec.get(p, "")
                        if p in multiline_props:
                            v = " ".join(v.splitlines()).strip()
                        vals.append(v)
                    rows.append(_csv_row(system_name, *vals))
    else:
        rows.append(_csv_row("name", "values"))
        for encoded, fname in sorted(seen.items()):
            entry_name = decode_name(encoded) or encoded
            content = (col_path / fname).read_text().strip()
            if not content:
                continue
            values = " ".join(content.split(","))
            rows.append(_csv_row(entry_name, values))

    dest.write_text("\n".join(rows) + "\n")
    print(f"exported: {dest}")
    if jtable:
        ref = build_ref_data(cache_dir, mandatory_ref_props) if mandatory_ref_props else None
        _launch_jtable(path=dest, ref_data=ref)
    else:
        subprocess.Popen([editor, str(dest)])


def cmd_fullcopy(repo_root: Path, destination: str, json_mode: bool):
    dest_base = Path(destination).resolve()
    if not dest_base.is_dir():
        print(f"error: not a directory: {dest_base}")
        return

    repo_name = repo_root.name

    if not json_mode:
        dest_dir = dest_base / repo_name
        if dest_dir.exists():
            print(f"error: already exists: {dest_dir}")
            return
        shutil.copytree(repo_root, dest_dir)
        print(f"copied: {dest_dir}")
        return

    # JSON mode — embed config + latest-version data only (no history)
    repo_ini_cfg = configparser.ConfigParser()
    repo_ini_cfg.read(repo_root / "repository.ini")
    additional_props_file = repo_ini_cfg.get("additional_properties", "json",
                                              fallback="additional_properties.json")
    ref_collections_file = repo_ini_cfg.get("reference_collections", "json",
                                             fallback="additional_mandatory_properties.json")

    repo_ini_path = repo_root / "repository.ini"
    repo_ini_text = repo_ini_path.read_text() if repo_ini_path.exists() else ""

    try:
        additional_props_data = json.loads((repo_root / additional_props_file).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        additional_props_data = []

    try:
        ref_collections_data = json.loads((repo_root / ref_collections_file).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        ref_collections_data = []

    data_section: dict[str, dict] = {}
    for collection in sorted(COLLECTIONS):
        col_path = collection_path(repo_root, collection)
        if not col_path.is_dir():
            continue
        suffix = _repo_suffix(collection)
        seen: dict[str, str] = {}
        try:
            for fname in sorted(os.listdir(col_path)):
                if not fname.endswith(suffix):
                    continue
                stem = fname[: -len(suffix)]
                parts = stem.split(".")
                if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
                    seen[parts[0]] = fname
        except FileNotFoundError:
            pass
        col_data: dict = {}
        for encoded, fname in sorted(seen.items()):
            name = decode_name(encoded) or encoded
            if collection == MAIN_COLLECTION:
                col_data[name] = json.loads(gzip.decompress((col_path / fname).read_bytes()).decode())
            else:
                col_data[name] = (col_path / fname).read_text()
        data_section[collection] = col_data

    output = {
        "config": {
            "repository_ini": repo_ini_text,
            "additional_properties": additional_props_data,
            "reference_collections": ref_collections_data,
        },
        "data": data_section,
    }
    dest_file = dest_base / f"{repo_name}.json"
    if dest_file.exists():
        print(f"error: already exists: {dest_file}")
        return
    dest_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"exported: {dest_file}")


def cmd_partialcopy(repo_root: Path, collection: str, name: str, destination: str,
                    json_mode: bool = False):
    dest_base = Path(destination).resolve()
    if not dest_base.is_dir():
        print(f"error: not a directory: {dest_base}")
        return

    repo_name = repo_root.name
    encoded_target = encode_name(name)

    if json_mode:
        dest_file = dest_base / f"{repo_name}.json"
        if dest_file.exists():
            print(f"error: already exists: {dest_file}")
            return

        repo_ini_cfg = configparser.ConfigParser()
        repo_ini_cfg.read(repo_root / "repository.ini")
        additional_props_file = repo_ini_cfg.get("additional_properties", "json",
                                                  fallback="additional_properties.json")
        ref_collections_file = repo_ini_cfg.get("reference_collections", "json",
                                                 fallback="additional_mandatory_properties.json")

        repo_ini_path = repo_root / "repository.ini"
        repo_ini_text = repo_ini_path.read_text() if repo_ini_path.exists() else ""

        try:
            additional_props_data = json.loads((repo_root / additional_props_file).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            additional_props_data = []

        try:
            ref_collections_data = json.loads((repo_root / ref_collections_file).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            ref_collections_data = []

        data_section: dict[str, dict] = {}
        for col in sorted(COLLECTIONS):
            col_path = collection_path(repo_root, col)
            if not col_path.is_dir():
                continue
            suffix = _repo_suffix(col)
            seen: dict[str, str] = {}
            try:
                for fname in sorted(os.listdir(col_path)):
                    if not fname.endswith(suffix):
                        continue
                    stem = fname[: -len(suffix)]
                    parts = stem.split(".")
                    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
                        seen[parts[0]] = fname
            except FileNotFoundError:
                pass
            col_data: dict = {}
            for encoded, fname in sorted(seen.items()):
                entry_name = decode_name(encoded) or encoded
                if col == collection and encoded == encoded_target:
                    if col == MAIN_COLLECTION:
                        col_data[entry_name] = json.loads(
                            gzip.decompress((col_path / fname).read_bytes()).decode())
                    else:
                        col_data[entry_name] = (col_path / fname).read_text()
                else:
                    col_data[entry_name] = [] if col == MAIN_COLLECTION else ""
            data_section[col] = col_data

        output = {
            "config": {
                "repository_ini": repo_ini_text,
                "additional_properties": additional_props_data,
                "reference_collections": ref_collections_data,
            },
            "data": data_section,
        }
        dest_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(f"exported: {dest_file}")
        return

    dest_dir = dest_base / repo_name
    if dest_dir.exists():
        print(f"error: already exists: {dest_dir}")
        return

    dest_dir.mkdir()

    # Copy root-level config files as-is
    for entry in os.listdir(repo_root):
        src = repo_root / entry
        if src.is_file():
            shutil.copy2(src, dest_dir / entry)

    # Recreate collection directories; copy matching files, touch the rest
    for col in sorted(COLLECTIONS):
        col_src = collection_path(repo_root, col)
        if not col_src.is_dir():
            continue
        col_dst = dest_dir / col
        col_dst.mkdir()
        try:
            files = os.listdir(col_src)
        except FileNotFoundError:
            continue
        for fname in files:
            dst_file = col_dst / fname
            if col == collection and fname.startswith(encoded_target + "."):
                shutil.copy2(col_src / fname, dst_file)
            elif fname.endswith(".gz"):
                dst_file.write_bytes(gzip.compress(b"[]"))
            else:
                dst_file.touch()

    print(f"created: {dest_dir}")


def cmd_mkrepo(json_file: str, destination: str):
    json_path = Path(json_file).resolve()
    if not json_path.exists():
        print(f"error: not found: {json_path}")
        return

    try:
        full_data = json.loads(json_path.read_text())
    except Exception as e:
        print(f"error: could not parse {json_path}: {e}")
        return

    if not isinstance(full_data, dict) or "config" not in full_data or "data" not in full_data:
        print("error: invalid fullcopy JSON (missing 'config' or 'data')")
        return

    dest_base = Path(destination).resolve()
    if not dest_base.is_dir():
        print(f"error: not a directory: {dest_base}")
        return

    repo_name = json_path.stem
    repo_dir = dest_base / repo_name
    if repo_dir.exists():
        print(f"error: already exists: {repo_dir}")
        return

    config = full_data["config"]
    data = full_data["data"]

    repo_ini_text = config.get("repository_ini", "")
    repo_ini_cfg = configparser.ConfigParser()
    repo_ini_cfg.read_string(repo_ini_text)
    main_coll = repo_ini_cfg.get("main_collection", "collection_name", fallback="systems")
    additional_props_file = repo_ini_cfg.get("additional_properties", "json",
                                              fallback="additional_properties.json")
    ref_collections_file = repo_ini_cfg.get("reference_collections", "json",
                                             fallback="additional_mandatory_properties.json")

    repo_dir.mkdir()
    (repo_dir / "repository.ini").write_text(repo_ini_text)
    (repo_dir / additional_props_file).write_text(
        json.dumps(config.get("additional_properties", []), ensure_ascii=False, indent=2) + "\n"
    )
    (repo_dir / ref_collections_file).write_text(
        json.dumps(config.get("reference_collections", []), ensure_ascii=False, indent=2) + "\n"
    )

    for collection_name, entries in data.items():
        col_dir = repo_dir / collection_name
        col_dir.mkdir(exist_ok=True)
        is_main = (collection_name == main_coll)
        suffix = ".txt.gz" if is_main else ".txt"
        for entry_name, entry_data in entries.items():
            encoded = encode_name(entry_name)
            dest_file = col_dir / f"{encoded}.0000{suffix}"
            if is_main:
                body = json.dumps(entry_data, ensure_ascii=False, indent=2) + "\n"
                dest_file.write_bytes(gzip.compress(body.encode()))
            else:
                dest_file.write_text(entry_data)

    print(f"created: {repo_dir}")


# ── REPL ──────────────────────────────────────────────────────────────────────

def initialize_repo(repo_root: Path, downloads_base: Path, cache_base: Path) -> RepoState:
    global MAIN_COLLECTION, PARTITIONING_PROPERTY
    COLLECTIONS.clear()
    COLLECTION_TYPE.clear()

    ns = repo_namespace(repo_root)
    downloads_dir = downloads_base / ns
    cache_dir = cache_base / ns

    main_coll, partition_prop, property_order, additional_props_file, ref_collections_file, intro_message = \
        load_repository_config(repo_root)
    MAIN_COLLECTION = main_coll
    PARTITIONING_PROPERTY = partition_prop
    COLLECTIONS.add(main_coll)

    optional_prop_pairs = load_additional_properties(repo_root, additional_props_file)
    optional_props = tuple(name for name, _, _ in optional_prop_pairs)
    prop_validation_types: dict[str, str] = {
        name: vtype for name, vtype, _ in optional_prop_pairs if vtype != "NONE"
    }
    multiline_props: frozenset[str] = frozenset(name for name, _, ml in optional_prop_pairs if ml)

    dynamic_colls = load_dynamic_collections(repo_root, ref_collections_file)
    for dc in dynamic_colls:
        cname = dc["collection_name"]
        COLLECTIONS.add(cname)
        COLLECTION_TYPE[cname] = dc.get("type", "")
        (repo_root / cname).mkdir(parents=True, exist_ok=True)
        (cache_dir / cname).mkdir(parents=True, exist_ok=True)

    mandatory_ref_props = tuple(
        (dc["property_name"], dc["collection_name"], frozenset(dc.get("whitelist", [])))
        for dc in dynamic_colls
        if dc.get("property_name")
    )
    optional_props_set = set(optional_props)
    all_props = optional_props + tuple(
        pname for pname, _, _ in mandatory_ref_props if pname not in optional_props_set
    )

    all_fields_set = _DEFAULT_CORE_SET | set(all_props)
    ordered_front = [p for p in property_order if p in all_fields_set]
    ordered_front_set = set(ordered_front)
    remaining_core = [p for p in _DEFAULT_CORE if p not in ordered_front_set]
    remaining_extra = [p for p in all_props if p not in ordered_front_set]
    field_order: tuple[str, ...] | None = (
        tuple(ordered_front + remaining_core + remaining_extra) if property_order else None
    )
    additional_props = tuple(p for p in (field_order or (_DEFAULT_CORE + all_props))
                             if p not in _DEFAULT_CORE_SET)

    return RepoState(
        repo_root=repo_root,
        downloads_dir=downloads_dir,
        cache_dir=cache_dir,
        additional_props=additional_props,
        mandatory_ref_props=mandatory_ref_props,
        field_order=field_order,
        prop_validation_types=prop_validation_types,
        multiline_props=multiline_props,
        intro_message=intro_message,
    )


def usage_string() -> str:
    return (
        "commands:\n"
        "  cd <path>\n"
        "  ls <collection>\n"
        "  add <collection> <name>\n"
        "  cat <collection> <name> [--jtable]\n"
        "  get <collection> <name> [--jtable]\n"
        "  clear <collection> <name> [--jtable]\n"
        "  len <collection> <name>\n"
        "  push <collection> <name>\n"
        "  export <collection> <file.csv> [--jtable]\n"
        "  export <collection> <file.json>\n"
        "  diff <collection> <name> [--jtable]\n"
        "  fullcopy <destination-directory> [--json]\n"
        "  mkrepo <json-file> <destination-directory>\n"
        "  partialcopy <collection> <name> <destination-directory> [--json]\n"
        "  exit"
        f"\ncollections: {', '.join(sorted(COLLECTIONS))}"
    )


def dispatch(parts: list[str], repo_root: Path, downloads_dir: Path,
             cache_dir: Path, editor: str, additional_props: tuple[str, ...] = (),
             mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...] = (), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {},
             multiline_props: frozenset[str] = frozenset()) -> bool:
    """Return False to exit."""
    cmd = parts[0]

    if cmd == "exit":
        return False

    if cmd in ("ls", "add", "cat", "get", "clear", "len", "push", "export", "diff", "partialcopy"):
        if len(parts) < 2:
            print("error: missing collection")
            return True
        collection = parts[1]
        if collection not in COLLECTIONS:
            print(f"error: unknown collection '{collection}' (choices: {', '.join(sorted(COLLECTIONS))})")
            return True

    if cmd == "ls":
        if len(parts) != 2:
            print("usage: ls <collection>")
        else:
            cmd_ls(repo_root, collection)

    elif cmd == "add":
        if len(parts) != 3:
            print("usage: add <collection> <name>")
        else:
            cmd_add(repo_root, collection, parts[2], additional_props, field_order=field_order)

    elif cmd == "cat":
        jtable = "--jtable" in parts
        as_json = "--json" in parts
        cat_parts = [p for p in parts if p not in ("--jtable", "--json")]
        if len(cat_parts) != 3:
            print("usage: cat <collection> <name> [--jtable] [--json]")
        elif jtable and as_json:
            print("error: --jtable and --json are mutually exclusive")
        else:
            ref = build_ref_data(cache_dir, mandatory_ref_props) if jtable and collection == MAIN_COLLECTION else None
            cmd_cat(repo_root, collection, cat_parts[2], additional_props,
                    downloads_dir=downloads_dir, jtable=jtable, as_json=as_json,
                    field_order=field_order, multiline_props=multiline_props, ref_data=ref)

    elif cmd == "get":
        jtable = "--jtable" in parts
        stdin_flag = "-" in parts
        get_parts = [p for p in parts if p not in ("--jtable", "-")]
        if len(get_parts) != 3:
            print("usage: get <collection> <name> [--jtable] [-]")
        else:
            stdin_content = sys.stdin.read() if stdin_flag else None
            _name = get_parts[2]
            _push_cb = None
            if jtable:
                def _push_cb(_coll=collection, _n=_name):
                    cmd_push(repo_root, _coll, _n, downloads_dir,
                             additional_props, mandatory_ref_props,
                             field_order=field_order,
                             prop_validation_types=prop_validation_types,
                             multiline_props=multiline_props)
            cmd_get(repo_root, collection, _name, downloads_dir, editor,
                    additional_props, jtable=jtable, field_order=field_order,
                    multiline_props=multiline_props, stdin_content=stdin_content,
                    push_callback=_push_cb)

    elif cmd == "clear":
        jtable = "--jtable" in parts
        clear_parts = [p for p in parts if p != "--jtable"]
        if len(clear_parts) != 3:
            print("usage: clear <collection> <name> [--jtable]")
        else:
            _name = clear_parts[2]
            _push_cb = None
            if jtable:
                def _push_cb(_coll=collection, _n=_name):
                    cmd_push(repo_root, _coll, _n, downloads_dir,
                             additional_props, mandatory_ref_props,
                             field_order=field_order,
                             prop_validation_types=prop_validation_types,
                             multiline_props=multiline_props)
            cmd_clear(repo_root, collection, _name, downloads_dir, editor,
                      additional_props, jtable=jtable, field_order=field_order,
                      multiline_props=multiline_props, push_callback=_push_cb)

    elif cmd == "len":
        if len(parts) != 3:
            print("usage: len <collection> <name>")
        else:
            cmd_len(repo_root, collection, parts[2])

    elif cmd == "push":
        as_json = "--json" in parts
        push_parts = [p for p in parts if p != "--json"]
        if len(push_parts) != 3:
            print("usage: push <collection> <name> [--json]")
        else:
            cmd_push(repo_root, collection, push_parts[2], downloads_dir,
                     additional_props, mandatory_ref_props, field_order=field_order,
                     prop_validation_types=prop_validation_types,
                     multiline_props=multiline_props, json_mode=as_json)

    elif cmd == "export":
        jtable = "--jtable" in parts
        export_parts = [p for p in parts if p != "--jtable"]
        if len(export_parts) != 3:
            print("usage: export <collection> <file.csv> [--jtable] | export <collection> <file.json>")
        else:
            cmd_export(repo_root, collection, export_parts[2], downloads_dir, cache_dir,
                       editor, additional_props, jtable=jtable,
                       field_order=field_order, multiline_props=multiline_props,
                       mandatory_ref_props=mandatory_ref_props)

    elif cmd == "diff":
        jtable = "--jtable" in parts
        diff_parts = [p for p in parts if p != "--jtable"]
        if len(diff_parts) != 3:
            print("usage: diff <collection> <name> [--jtable]")
        else:
            cmd_diff(repo_root, collection, diff_parts[2], additional_props,
                     jtable=jtable, field_order=field_order)

    elif cmd == "fullcopy":
        json_mode = "--json" in parts
        fullcopy_parts = [p for p in parts if p != "--json"]
        if len(fullcopy_parts) != 2:
            print("usage: fullcopy <destination-directory> [--json]")
        else:
            cmd_fullcopy(repo_root, fullcopy_parts[1], json_mode)

    elif cmd == "mkrepo":
        if len(parts) != 3:
            print("usage: mkrepo <json-file> <destination-directory>")
        else:
            cmd_mkrepo(parts[1], parts[2])

    elif cmd == "partialcopy":
        json_mode = "--json" in parts
        pc_parts = [p for p in parts if p != "--json"]
        if len(pc_parts) != 4:
            print("usage: partialcopy <collection> <name> <destination-directory> [--json]")
        else:
            cmd_partialcopy(repo_root, collection, pc_parts[2], pc_parts[3], json_mode)

    else:
        print(f"unknown command: {cmd!r}")
        print(usage_string())

    return True


def _do_cd(path_str: str, downloads_base: Path, cache_base: Path,
           check_repo_ini: bool = True) -> RepoState | None:
    new_path = Path(path_str).resolve()
    if not new_path.is_dir():
        print(f"error: not a directory: {new_path}")
        return None
    if check_repo_ini and not (new_path / "repository.ini").exists():
        print(f"error: not a repository (no repository.ini): {new_path}")
        return None
    state = initialize_repo(new_path, downloads_base, cache_base)
    sync_cache(state.repo_root, state.cache_dir)
    if state.intro_message:
        print(state.intro_message)
    print(f"switched to: {state.repo_root}")
    return state


def main():
    config = load_config()
    repo_root = get_repo_root(config)
    downloads_base = get_downloads_dir(config)
    cache_base = get_cache_dir(config)
    editor = get_editor(config)

    state = initialize_repo(repo_root, downloads_base, cache_base)

    cli_args = sys.argv[1:]
    if cli_args and cli_args[0] == "-c":
        if len(cli_args) < 2:
            print("error: -c requires a command string", file=sys.stderr)
            sys.exit(1)
        sync_cache(state.repo_root, state.cache_dir)
        for raw in cli_args[1].split("&&"):
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            if parts[0] == "cd":
                if len(parts) != 2:
                    print("error: cd requires a path")
                    continue
                new_state = _do_cd(parts[1], downloads_base, cache_base, check_repo_ini=False)
                if new_state is not None:
                    state = new_state
                continue
            if not dispatch(parts, state.repo_root, state.downloads_dir, state.cache_dir, editor,
                            state.additional_props, state.mandatory_ref_props,
                            field_order=state.field_order,
                            prop_validation_types=state.prop_validation_types,
                            multiline_props=state.multiline_props):
                break
        return

    print(f"repo-manipulator  repository={state.repo_root}")
    sync_cache(state.repo_root, state.cache_dir)
    if state.intro_message:
        print(state.intro_message)
    print("Type 'help' for usage or 'exit' to quit.\n")

    session: PromptSession = PromptSession()
    while True:
        try:
            line = session.prompt(f"{state.repo_root.name} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line == "help":
            print(usage_string())
            continue

        parts = line.split()
        if parts[0] == "cd":
            if len(parts) != 2:
                print("usage: cd <path>")
            else:
                new_state = _do_cd(parts[1], downloads_base, cache_base)
                if new_state is not None:
                    state = new_state
            continue

        if not dispatch(parts, state.repo_root, state.downloads_dir, state.cache_dir, editor,
                        state.additional_props, state.mandatory_ref_props,
                        field_order=state.field_order,
                        prop_validation_types=state.prop_validation_types,
                        multiline_props=state.multiline_props):
            break


if __name__ == "__main__":
    main()
