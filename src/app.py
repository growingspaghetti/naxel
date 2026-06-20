import base64
import configparser
import gzip
import json
import os
import re
import readline  # noqa: F401 — enables up/down arrow history in input()
import subprocess
import sys
from pathlib import Path

from gui import JTable

SCRIPT_DIR = Path(__file__).parent.parent


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


def get_property_order(config) -> tuple[str, ...]:
    raw = config.get("system", "property_order", fallback="")
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def load_additional_properties(repo_root: Path) -> tuple[tuple[str, str], ...]:
    path = repo_root / "additional_properties.json"
    try:
        data = json.loads(path.read_text())
        result = []
        for item in data:
            if isinstance(item, dict):
                name = str(item.get("property_name", "")).strip()
                vtype = str(item.get("validation_type", "NONE")).strip()
                if name:
                    result.append((name, vtype))
            elif isinstance(item, str) and item.strip():
                result.append((item.strip(), "NONE"))
        return tuple(result)
    except FileNotFoundError:
        return ()
    except Exception as e:
        print(f"warning: could not read additional_properties.json: {e}")
        return ()


def load_dynamic_collections(repo_root: Path) -> list[dict]:
    path = repo_root / "additional_mandatory_properties.json"
    try:
        data = json.loads(path.read_text())
        return [d for d in data if isinstance(d, dict) and d.get("collection_name")]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"warning: could not read additional_mandatory_properties.json: {e}")
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


COLLECTIONS: set[str] = {"systems", "schedules", "contacts"}

REPO_SUFFIX: dict[str, str] = {
    "systems": ".txt.gz",
    "schedules": ".txt",
    "contacts": ".txt",
}

COLLECTION_TYPE: dict[str, str] = {}


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
    suffix = REPO_SUFFIX.get(collection, ".txt")
    return latest_in_dir(collection_path(repo_root, collection), encode_name(name), suffix)


# ── validation ────────────────────────────────────────────────────────────────

_SEPARATOR = "\U0001f3d4" * 20
_DATE_SEG = r"\d{4}/\d{2}/\d{2}"
_SCHEDULE_RE = re.compile(rf"^{_DATE_SEG}(,{_DATE_SEG})*\n?$")
_CONTACT_SEG = r"[0-9\-\+]+"
_CONTACT_RE = re.compile(rf"^{_CONTACT_SEG}(,{_CONTACT_SEG})*\n?$")
_EMAIL_SEG = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
_EMAIL_RE = re.compile(rf"^{_EMAIL_SEG}(,{_EMAIL_SEG})*\n?$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_CORE_LABELS = frozenset({
    "\U0001f449machine\U0001f448",
    "\U0001f449id\U0001f448",
    "\U0001f449time\U0001f448",
    "\U0001f449notes\U0001f448",
})

_DEFAULT_CORE = ("machine", "id", "time", "notes")
_DEFAULT_CORE_SET = frozenset(_DEFAULT_CORE)

# CSV column name overrides for core fields
_CSV_FIELD_NAME: dict[str, str] = {
    "machine": "machine_name",
}


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


def _empty_system_document(additional_props: tuple[str, ...] = (), *,
                            field_order: tuple[str, ...] | None = None) -> str:
    order = field_order if field_order is not None else (_DEFAULT_CORE + additional_props)
    lines = [_SEPARATOR]
    for key in order:
        lines += [f"\U0001f449{key}\U0001f448", ""]
    return "\n".join(lines) + "\n"


_EMPTY_DOCUMENTS = {
    "systems": _empty_system_document(),
    "schedules": "",
    "contacts": "",
}


def _empty_system_json(additional_props: tuple[str, ...] = (), *,
                        field_order: tuple[str, ...] | None = None) -> str:
    order = field_order if field_order is not None else (_DEFAULT_CORE + additional_props)
    section: dict[str, str] = {key: "" for key in order}
    return json.dumps([section], ensure_ascii=False, indent=2) + "\n"


def _system_sections_to_text(sections: list[dict], additional_props: tuple[str, ...] = (), *,
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


def _text_to_system_json(content: str, additional_props: tuple[str, ...] = (), *,
                          field_order: tuple[str, ...] | None = None) -> str:
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
                if key == "notes":
                    note_lines: list[str] = []
                    while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                        note_lines.append(lines[i])
                        i += 1
                    section["notes"] = "\n".join(note_lines)
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == len(field_order):
                sections.append(section)
        else:
            for key in ("machine", "id", "time", "notes"):
                label = f"\U0001f449{key}\U0001f448"
                if i >= n or lines[i] != label:
                    section = {}
                    break
                i += 1
                if key == "notes":
                    note_lines = []
                    while i < n and lines[i] != _SEPARATOR and not _is_prop_label(lines[i]):
                        note_lines.append(lines[i])
                        i += 1
                    section["notes"] = "\n".join(note_lines)
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == 4:
                found: dict[str, str] = {}
                while i < n and lines[i] != _SEPARATOR:
                    line = lines[i]
                    if _is_prop_label(line):
                        prop_name = line[1:-1]
                        i += 1
                        found[prop_name] = lines[i].strip() if i < n else ""
                        if i < n:
                            i += 1
                    else:
                        i += 1
                for p in additional_props:
                    section[p] = found.get(p, "")
                sections.append(section)
    return json.dumps(sections, ensure_ascii=False, indent=2) + "\n"


def _validate_system(content: str, additional_props: tuple[str, ...] = (),
                     mandatory_prop_names: frozenset[str] = frozenset(), *,
                     field_order: tuple[str, ...] | None = None,
                     prop_validation_types: dict[str, str] = {}) -> tuple[bool, str]:
    lines = content.splitlines()
    n = len(lines)
    i = 0
    section_count = 0

    if field_order is not None:
        order = field_order
        use_any_label = True
    else:
        order = _DEFAULT_CORE + additional_props
        use_any_label = False

    while i < n:
        if lines[i] != _SEPARATOR:
            return False, f"line {i + 1}: expected separator"
        i += 1

        for key in order:
            label = f"\U0001f449{key}\U0001f448"
            if i >= n or lines[i] != label:
                return False, f"line {i + 1}: expected {label!r}"
            i += 1
            if key == "notes":
                if use_any_label:
                    while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                        i += 1
                else:
                    while i < n and lines[i] != _SEPARATOR and not _is_prop_label(lines[i]):
                        i += 1
            elif key == "machine":
                if i >= n or not lines[i].strip():
                    return False, f"line {i + 1}: value after {label!r} is missing"
                i += 1
            elif key == "id":
                if i >= n or not lines[i].strip():
                    return False, f"line {i + 1}: value after {label!r} is missing"
                if lines[i].startswith("#"):
                    return False, f"line {i + 1}: id must not start with '#' (got {lines[i]!r})"
                i += 1
            elif key == "time":
                if i >= n or not lines[i].strip():
                    return False, f"line {i + 1}: value after {label!r} is missing"
                if not _TIME_RE.match(lines[i]):
                    return False, f"line {i + 1}: time must be dd:dd (got {lines[i]!r})"
                i += 1
            else:
                # Extra prop
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
                i += 1

        section_count += 1

    if section_count == 0:
        return False, "no sections found"
    return True, ""


def _validate_schedule(content: str) -> tuple[bool, str]:
    if _SCHEDULE_RE.match(content):
        return True, ""
    return False, "expected: yyyy/mm/dd,yyyy/mm/dd,... (one line)"


def _validate_contact(content: str) -> tuple[bool, str]:
    if _CONTACT_RE.match(content):
        return True, ""
    return False, "expected: digits/dashes/plus signs separated by commas (one line)"


def _validate_email(content: str) -> tuple[bool, str]:
    if _EMAIL_RE.match(content):
        return True, ""
    return False, "expected: email@domain.tld,email2@domain.tld,... (one line)"


def validate(collection: str, content: str, additional_props: tuple[str, ...] = (),
             mandatory_prop_names: frozenset[str] = frozenset(), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {}) -> tuple[bool, str]:
    if collection == "systems":
        return _validate_system(content, additional_props, mandatory_prop_names,
                                field_order=field_order,
                                prop_validation_types=prop_validation_types)
    ctype = COLLECTION_TYPE.get(collection, "")
    if ctype == "DATE":
        return _validate_schedule(content)
    if ctype == "PHONE_NUMBER":
        return _validate_contact(content)
    if ctype == "EMAIL":
        return _validate_email(content)
    return True, ""


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_ls(repo_root: Path, collection: str):
    path = collection_path(repo_root, collection)
    if not path.is_dir():
        print(f"error: directory not found: {path}")
        return
    suffix = REPO_SUFFIX.get(collection, ".txt")
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
    suffix = REPO_SUFFIX.get(collection, ".txt")
    dest = path / f"{encoded}.0000{suffix}"
    if dest.exists():
        print(f"error: already exists: {name}")
        return
    if suffix == ".txt.gz":
        dest.write_bytes(gzip.compress(
            _empty_system_json(additional_props, field_order=field_order).encode()))
    else:
        dest.write_text(_EMPTY_DOCUMENTS.get(collection, ""))
    print(f"created: {name}")


def cmd_len(repo_root: Path, collection: str, name: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    if collection == "systems":
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        print(sum(1 for s in sections if s.get("machine")))
    else:
        content = filepath.read_text().strip()
        print(len(content.split(",")) if content else 0)


def cmd_cat(repo_root: Path, collection: str, name: str,
            additional_props: tuple[str, ...] = (),
            downloads_dir: Path | None = None, jtable: bool = False, *,
            field_order: tuple[str, ...] | None = None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    if jtable:
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        dl_name = filepath.name[:-3]  # strip .gz
        dl_dir = downloads_dir / collection
        dl_dir.mkdir(parents=True, exist_ok=True)
        dest = dl_dir / dl_name
        dest.write_text(_system_sections_to_text(sections, additional_props,
                                                  field_order=field_order))
        print(f"saved: {dest}")
        JTable(dest, mode="systems", readonly=True).run()
        return
    if collection == "systems" and filepath.name.endswith(".gz"):
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        print(_system_sections_to_text(sections, additional_props, field_order=field_order), end="")
    elif filepath.name.endswith(".gz"):
        print(gzip.decompress(filepath.read_bytes()).decode(), end="")
    else:
        print(filepath.read_text(), end="")


def cmd_clear(repo_root: Path, collection: str, name: str,
              downloads_dir: Path, editor: str, additional_props: tuple[str, ...] = (), *,
              field_order: tuple[str, ...] | None = None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    dl_dir = downloads_dir / collection
    dl_dir.mkdir(parents=True, exist_ok=True)
    dl_name = filepath.name[:-3] if filepath.name.endswith(".gz") else filepath.name
    dest = dl_dir / dl_name
    if collection == "systems":
        template = _empty_system_document(additional_props, field_order=field_order)
    else:
        template = _EMPTY_DOCUMENTS.get(collection, "")
    dest.write_text(template)
    print(f"cleared: {dest}")
    subprocess.Popen([editor, str(dest)])


def cmd_get(repo_root: Path, collection: str, name: str,
            downloads_dir: Path, editor: str,
            additional_props: tuple[str, ...] = (), jtable: bool = False, *,
            field_order: tuple[str, ...] | None = None):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    dl_dir = downloads_dir / collection
    dl_dir.mkdir(parents=True, exist_ok=True)
    if collection == "systems" and filepath.name.endswith(".gz"):
        dl_name = filepath.name[:-3]
        sections = json.loads(gzip.decompress(filepath.read_bytes()).decode())
        dest = dl_dir / dl_name
        dest.write_text(_system_sections_to_text(sections, additional_props,
                                                  field_order=field_order))
    elif filepath.name.endswith(".gz"):
        dl_name = filepath.name[:-3]
        dest = dl_dir / dl_name
        dest.write_text(gzip.decompress(filepath.read_bytes()).decode())
    else:
        dest = dl_dir / filepath.name
        dest.write_text(filepath.read_text())
    print(f"saved: {dest}")
    if jtable:
        JTable(dest, mode="systems").run()
    else:
        subprocess.Popen([editor, str(dest)])


def cmd_diff(repo_root: Path, collection: str, name: str,
             additional_props: tuple[str, ...] = (), jtable: bool = False, *,
             field_order: tuple[str, ...] | None = None):
    suffix = REPO_SUFFIX.get(collection, ".txt")
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

    if collection == "systems":
        prev_sections = json.loads(gzip.decompress((col_path / matches[-2]).read_bytes()).decode())
        curr_sections = json.loads(gzip.decompress((col_path / matches[-1]).read_bytes()).decode())

        def _key(sec: dict) -> str:
            return json.dumps(sec, ensure_ascii=False, sort_keys=True)

        prev_keys = {_key(s) for s in prev_sections}
        curr_keys = {_key(s) for s in curr_sections}
        deleted = [s for s in prev_sections if _key(s) not in curr_keys]
        added = [s for s in curr_sections if _key(s) not in prev_keys]
        if jtable:
            cols = list(field_order) if field_order is not None else (list(_DEFAULT_CORE) + list(additional_props))
            JTable(
                diff_data={
                    "columns": cols,
                    "deleted": [[s.get(k, "") for k in cols] for s in deleted],
                    "added":   [[s.get(k, "") for k in cols] for s in added],
                },
                title=f"diff systems {name}",
            ).run()
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
            JTable(
                diff_data={
                    "columns": [col_name],
                    "deleted": [[e] for e in deleted],
                    "added":   [[e] for e in added],
                },
                title=f"diff {collection} {name}",
            ).run()
            return

    print(json.dumps({"deleted": deleted, "added": added}, ensure_ascii=False, indent=2))


def cmd_push(repo_root: Path, collection: str, name: str, downloads_dir: Path,
             additional_props: tuple[str, ...] = (),
             mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...] = (), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {}):
    encoded = encode_name(name)
    src = latest_in_dir(downloads_dir / collection, encoded, ".txt")
    if src is None:
        print(f"error: not found in downloads: {name}")
        return
    content = src.read_text()
    if not (collection == "systems" and _is_initial_state_system(
            content, additional_props, field_order=field_order)):
        mandatory_prop_names = frozenset(
            pname for pname, _, _ in mandatory_ref_props
            if pname not in _DEFAULT_CORE_SET
        )
        ok, reason = validate(collection, content, additional_props, mandatory_prop_names,
                              field_order=field_order,
                              prop_validation_types=prop_validation_types)
        if not ok:
            print(f"rejected: {reason}")
            return
        if collection == "systems" and mandatory_ref_props:
            sections_for_ref = _parse_system_sections(content, additional_props,
                                                       field_order=field_order)
            for pname, cname, whitelist in mandatory_ref_props:
                ref_suffix = REPO_SUFFIX.get(cname, ".txt")
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
    suffix = REPO_SUFFIX.get(collection, ".txt")
    latest = latest_in_dir(col_path, encoded, suffix)
    if latest is None:
        print(f"error: not found in repository: {name}")
        return
    current_version = int(latest.name[len(encoded) + 1: len(encoded) + 5])
    new_version = current_version + 1
    dest = col_path / f"{encoded}.{new_version:04d}{suffix}"
    if suffix == ".txt.gz":
        if not content.strip():
            body = _empty_system_json(additional_props, field_order=field_order)
        else:
            body = _text_to_system_json(content, additional_props, field_order=field_order)
        dest.write_bytes(gzip.compress(body.encode()))
    else:
        dest.write_text(content)
    print(f"pushed: {name} (version {new_version:04d})")


def _parse_system_sections(content: str, additional_props: tuple[str, ...] = (), *,
                             field_order: tuple[str, ...] | None = None) -> list[dict]:
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
                if key == "notes":
                    note_lines: list[str] = []
                    while i < n and lines[i] != _SEPARATOR and not _is_any_label(lines[i]):
                        note_lines.append(lines[i])
                        i += 1
                    section["notes"] = " ".join(note_lines).strip()
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == len(field_order):
                sections.append(section)
        else:
            for key in ("machine", "id", "time", "notes"):
                label = f"\U0001f449{key}\U0001f448"
                if i >= n or lines[i] != label:
                    section = {}
                    break
                i += 1
                if key == "notes":
                    note_lines = []
                    while i < n and lines[i] != _SEPARATOR and not _is_prop_label(lines[i]):
                        note_lines.append(lines[i])
                        i += 1
                    section["notes"] = " ".join(note_lines).strip()
                else:
                    section[key] = lines[i].strip() if i < n else ""
                    i += 1
            if len(section) == 4:
                # Collect all prop label-value pairs present in the document
                found: dict[str, str] = {}
                while i < n and lines[i] != _SEPARATOR:
                    line = lines[i]
                    if _is_prop_label(line):
                        prop_name = line[1:-1]  # strip the single 👉 and 👈 characters
                        i += 1
                        found[prop_name] = lines[i].strip() if i < n else ""
                        if i < n:
                            i += 1
                    else:
                        i += 1
                # Map configured props to found values; default to "" for any mismatch
                for p in additional_props:
                    section[p] = found.get(p, "")
                sections.append(section)
    return sections


def _is_initial_state_system(content: str, additional_props: tuple[str, ...] = (), *,
                               field_order: tuple[str, ...] | None = None) -> bool:
    if not content.strip():
        return True  # all rows deleted via GUI → treat as cleared
    sections = _parse_system_sections(content, additional_props, field_order=field_order)
    extra_to_check = (
        tuple(k for k in field_order if k not in _DEFAULT_CORE_SET)
        if field_order is not None else additional_props
    )
    return bool(sections) and all(
        not s["machine"] and not s["id"] and not s["time"] and not s["notes"]
        and all(not s.get(p) for p in extra_to_check)
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
               field_order: tuple[str, ...] | None = None):
    sync_cache(repo_root, cache_dir)
    col_path = cache_dir / collection
    if not col_path.is_dir():
        print(f"error: directory not found: {col_path}")
        return

    suffix = REPO_SUFFIX.get(collection, ".txt")
    seen: dict[str, str] = {}  # encoded → latest filename (sorted order gives highest version last)
    for fname in sorted(os.listdir(col_path)):
        if not fname.endswith(suffix):
            continue
        stem = fname[: -len(suffix)]
        parts = stem.split(".")
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
            seen[parts[0]] = fname

    rows = []
    if collection == "systems":
        if field_order is not None:
            csv_col_names = [_CSV_FIELD_NAME.get(f, f) for f in field_order]
            rows.append(_csv_row("system_name", *csv_col_names))
        else:
            rows.append(_csv_row("system_name", "id", "machine_name", "time", "notes",
                                  *[_CSV_FIELD_NAME.get(p, p) for p in additional_props]))
        for encoded, fname in sorted(seen.items()):
            system_name = decode_name(encoded) or encoded
            sections = json.loads(gzip.decompress((col_path / fname).read_bytes()).decode())
            if all(not s.get("machine") for s in sections):
                continue  # initial state: no meaningful data yet
            for sec in sections:
                if field_order is not None:
                    vals: list[str] = []
                    for f in field_order:
                        if f == "notes":
                            vals.append(" ".join(sec.get("notes", "").splitlines()).strip())
                        else:
                            vals.append(sec.get(f, ""))
                    rows.append(_csv_row(system_name, *vals))
                else:
                    notes_str = " ".join(sec.get("notes", "").splitlines()).strip()
                    rows.append(_csv_row(
                        system_name, sec.get("id", ""), sec.get("machine", ""),
                        sec.get("time", ""), notes_str,
                        *[sec.get(p, "") for p in additional_props]))
    elif collection == "schedules":
        rows.append(_csv_row("schedule_name", "dates"))
        for encoded, fname in sorted(seen.items()):
            schedule_name = decode_name(encoded) or encoded
            content = (col_path / fname).read_text().strip()
            if not content:
                continue  # initial state: empty document
            dates = " ".join(content.split(","))
            rows.append(_csv_row(schedule_name, dates))
    elif collection == "contacts":
        rows.append(_csv_row("contact_name", "numbers"))
        for encoded, fname in sorted(seen.items()):
            contact_name = decode_name(encoded) or encoded
            content = (col_path / fname).read_text().strip()
            if not content:
                continue  # initial state: empty document
            entries = " ".join(content.split(","))
            rows.append(_csv_row(contact_name, entries))
    else:
        rows.append(_csv_row("name", "values"))
        for encoded, fname in sorted(seen.items()):
            entry_name = decode_name(encoded) or encoded
            content = (col_path / fname).read_text().strip()
            if not content:
                continue
            values = " ".join(content.split(","))
            rows.append(_csv_row(entry_name, values))

    downloads_dir.mkdir(parents=True, exist_ok=True)
    dest = downloads_dir / filename
    dest.write_text("\n".join(rows) + "\n")
    print(f"exported: {dest}")
    if jtable:
        JTable(dest).run()
    else:
        subprocess.Popen([editor, str(dest)])


# ── REPL ──────────────────────────────────────────────────────────────────────

_USAGE_COMMANDS = (
    "commands:\n"
    "  ls <collection>\n"
    "  add <collection> <name>\n"
    "  cat systems <name> [--jtable]\n"
    "  get systems <name> [--jtable]\n"
    "  clear <collection> <name>\n"
    "  len <collection> <name>\n"
    "  push <collection> <name>\n"
    "  export <collection> <file.csv> [--jtable]\n"
    "  diff <collection> <name> [--jtable]\n"
    "  exit"
)


def usage_string() -> str:
    return _USAGE_COMMANDS + f"\ncollections: {', '.join(sorted(COLLECTIONS))}"


def dispatch(parts: list[str], repo_root: Path, downloads_dir: Path,
             cache_dir: Path, editor: str, additional_props: tuple[str, ...] = (),
             mandatory_ref_props: tuple[tuple[str, str, frozenset[str]], ...] = (), *,
             field_order: tuple[str, ...] | None = None,
             prop_validation_types: dict[str, str] = {}) -> bool:
    """Return False to exit."""
    cmd = parts[0]

    if cmd == "exit":
        return False

    if cmd in ("ls", "add", "cat", "get", "clear", "len", "push", "export", "diff"):
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
        cat_parts = [p for p in parts if p != "--jtable"]
        if len(cat_parts) != 3:
            print("usage: cat <collection> <name> [--jtable]")
        elif jtable and collection != "systems":
            print("error: --jtable is only supported for systems")
        else:
            cmd_cat(repo_root, collection, cat_parts[2], additional_props,
                    downloads_dir=downloads_dir, jtable=jtable, field_order=field_order)

    elif cmd == "get":
        jtable = "--jtable" in parts
        get_parts = [p for p in parts if p != "--jtable"]
        if len(get_parts) != 3:
            print("usage: get <collection> <name> [--jtable]")
        elif jtable and collection != "systems":
            print("error: --jtable is only supported for systems")
        else:
            cmd_get(repo_root, collection, get_parts[2], downloads_dir, editor,
                    additional_props, jtable=jtable, field_order=field_order)

    elif cmd == "clear":
        if len(parts) != 3:
            print("usage: clear <collection> <name>")
        else:
            cmd_clear(repo_root, collection, parts[2], downloads_dir, editor,
                      additional_props, field_order=field_order)

    elif cmd == "len":
        if len(parts) != 3:
            print("usage: len <collection> <name>")
        else:
            cmd_len(repo_root, collection, parts[2])

    elif cmd == "push":
        if len(parts) != 3:
            print("usage: push <collection> <name>")
        else:
            cmd_push(repo_root, collection, parts[2], downloads_dir,
                     additional_props, mandatory_ref_props, field_order=field_order,
                     prop_validation_types=prop_validation_types)

    elif cmd == "export":
        jtable = "--jtable" in parts
        export_parts = [p for p in parts if p != "--jtable"]
        if len(export_parts) != 3:
            print("usage: export <collection> <file.csv> [--jtable]")
        else:
            cmd_export(repo_root, collection, export_parts[2], downloads_dir, cache_dir,
                       editor, additional_props, jtable=jtable, field_order=field_order)

    elif cmd == "diff":
        jtable = "--jtable" in parts
        diff_parts = [p for p in parts if p != "--jtable"]
        if len(diff_parts) != 3:
            print("usage: diff <collection> <name> [--jtable]")
        else:
            cmd_diff(repo_root, collection, diff_parts[2], additional_props,
                     jtable=jtable, field_order=field_order)

    else:
        print(f"unknown command: {cmd!r}")
        print(usage_string())

    return True


def main():
    config = load_config()
    repo_root = get_repo_root(config)
    downloads_dir = get_downloads_dir(config)
    cache_dir = get_cache_dir(config)
    editor = get_editor(config)
    optional_prop_pairs = load_additional_properties(repo_root)
    optional_props = tuple(name for name, _ in optional_prop_pairs)
    prop_validation_types: dict[str, str] = {
        name: vtype for name, vtype in optional_prop_pairs if vtype != "NONE"
    }

    dynamic_colls = load_dynamic_collections(repo_root)
    for dc in dynamic_colls:
        cname = dc["collection_name"]
        COLLECTIONS.add(cname)
        REPO_SUFFIX.setdefault(cname, ".txt")
        COLLECTION_TYPE[cname] = dc.get("type", "")
        (repo_root / cname).mkdir(parents=True, exist_ok=True)
        (cache_dir / cname).mkdir(parents=True, exist_ok=True)

    mandatory_ref_props = tuple(
        (dc["property_name"], dc["collection_name"], frozenset(dc.get("whitelist", [])))
        for dc in dynamic_colls
        if dc.get("property_name")
    )
    all_props = optional_props + tuple(
        pname for pname, _, _ in mandatory_ref_props if pname not in _DEFAULT_CORE_SET
    )

    # Compute full field order respecting property_order from settings.ini.
    # Fields listed in property_order come first (core or extra); remaining fields
    # follow in their default relative order (core fields, then extra props).
    property_order = get_property_order(config)
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

    print(f"repo-manipulator  repository={repo_root}")
    sync_cache(repo_root, cache_dir)
    print("Type 'help' for usage or 'exit' to quit.\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line == "help":
            print(usage_string())
            continue

        parts = line.split()
        if not dispatch(parts, repo_root, downloads_dir, cache_dir, editor,
                        additional_props, mandatory_ref_props,
                        field_order=field_order,
                        prop_validation_types=prop_validation_types):
            break


if __name__ == "__main__":
    main()
