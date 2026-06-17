import base64
import configparser
import gzip
import os
import re
import subprocess
import sys
from pathlib import Path

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


def get_schedule_whitelist(config) -> set[str]:
    raw = config.get("schedule", "whitelist", fallback="")
    return {s.strip() for s in raw.split(",") if s.strip()}


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


COLLECTIONS = {"systems", "schedules"}

REPO_SUFFIX = {
    "systems": ".txt.gz",
    "schedules": ".txt",
}


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

_SEPARATOR = "\U0001f449" * 10 + "\U0001f448" * 10
_DATE_SEG = r"\d{4}/\d{2}/\d{2}"
_SCHEDULE_RE = re.compile(rf"^{_DATE_SEG}(,{_DATE_SEG})*\n?$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

_EMPTY_DOCUMENTS = {
    "systems": (
        f"{_SEPARATOR}\n"
        "\U0001f449machine\U0001f448\n"
        "\n"
        "\U0001f449schedule\U0001f448\n"
        "\n"
        "\U0001f449time\U0001f448\n"
        "\n"
        "\U0001f449notes\U0001f448\n"
        "\n"
    ),
    "schedules": "",
}


def _validate_system(content: str) -> tuple[bool, str]:
    lines = content.splitlines()
    n = len(lines)
    i = 0
    section_count = 0

    while i < n:
        if lines[i] != _SEPARATOR:
            return False, f"line {i + 1}: expected separator"
        i += 1

        for label in ("\U0001f449machine\U0001f448",
                      "\U0001f449schedule\U0001f448",
                      "\U0001f449time\U0001f448",
                      "\U0001f449notes\U0001f448"):
            if i >= n or lines[i] != label:
                return False, f"line {i + 1}: expected {label!r}"
            i += 1
            if label == "\U0001f449notes\U0001f448":
                notes_start = i
                while i < n and lines[i] != _SEPARATOR:
                    i += 1
                if i == notes_start:
                    return False, f"section {section_count + 1}: notes is empty"
            else:
                if i >= n or not lines[i].strip():
                    return False, f"line {i + 1}: value after {label!r} is missing"
                if label == "\U0001f449time\U0001f448" and not _TIME_RE.match(lines[i]):
                    return False, f"line {i + 1}: time must be dd:dd (got {lines[i]!r})"
                i += 1

        section_count += 1

    if section_count == 0:
        return False, "no sections found"
    return True, ""


def _validate_schedule(content: str) -> tuple[bool, str]:
    if _SCHEDULE_RE.match(content):
        return True, ""
    return False, "expected: yyyy/mm/dd,yyyy/mm/dd,... (one line)"


_VALIDATORS: dict = {
    "systems": _validate_system,
    "schedules": _validate_schedule,
}


def validate(collection: str, content: str) -> tuple[bool, str]:
    fn = _VALIDATORS.get(collection)
    return fn(content) if fn else (True, "")


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


def cmd_add(repo_root: Path, collection: str, name: str):
    path = collection_path(repo_root, collection)
    path.mkdir(parents=True, exist_ok=True)
    encoded = encode_name(name)
    suffix = REPO_SUFFIX.get(collection, ".txt")
    dest = path / f"{encoded}.0000{suffix}"
    if dest.exists():
        print(f"error: already exists: {name}")
        return
    template = _EMPTY_DOCUMENTS.get(collection, "")
    if suffix == ".txt.gz":
        dest.write_bytes(gzip.compress(template.encode()))
    else:
        dest.write_text(template)
    print(f"created: {name}")


def cmd_cat(repo_root: Path, collection: str, name: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    if filepath.name.endswith(".gz"):
        print(gzip.decompress(filepath.read_bytes()).decode(), end="")
    else:
        print(filepath.read_text(), end="")


def cmd_clear(repo_root: Path, collection: str, name: str,
              downloads_dir: Path, editor: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    downloads_dir.mkdir(parents=True, exist_ok=True)
    dl_name = filepath.name[:-3] if filepath.name.endswith(".gz") else filepath.name
    dest = downloads_dir / dl_name
    dest.write_text(_EMPTY_DOCUMENTS.get(collection, ""))
    print(f"cleared: {dest}")
    subprocess.Popen([editor, str(dest)])


def cmd_get(repo_root: Path, collection: str, name: str,
            downloads_dir: Path, editor: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    downloads_dir.mkdir(parents=True, exist_ok=True)
    if filepath.name.endswith(".gz"):
        dl_name = filepath.name[:-3]  # strip .gz so user edits plain text
        content = gzip.decompress(filepath.read_bytes()).decode()
        dest = downloads_dir / dl_name
        dest.write_text(content)
    else:
        dest = downloads_dir / filepath.name
        dest.write_text(filepath.read_text())
    print(f"saved: {dest}")
    subprocess.Popen([editor, str(dest)])


def cmd_push(repo_root: Path, collection: str, name: str, downloads_dir: Path,
             schedule_whitelist: set[str]):
    encoded = encode_name(name)
    src = latest_in_dir(downloads_dir, encoded, ".txt")
    if src is None:
        print(f"error: not found in downloads: {name}")
        return
    content = src.read_text()
    if not (collection == "systems" and _is_initial_state_system(content)):
        ok, reason = validate(collection, content)
        if not ok:
            print(f"rejected: {reason}")
            return
        if collection == "systems":
            sched_suffix = REPO_SUFFIX["schedules"]
            sched_dir = collection_path(repo_root, "schedules")
            try:
                existing = {
                    f[: -len(sched_suffix)].split(".")[0]
                    for f in os.listdir(sched_dir)
                    if f.endswith(sched_suffix)
                }
            except FileNotFoundError:
                existing = set()
            for sec in _parse_system_sections(content):
                sched = sec["schedule"]
                if sched not in schedule_whitelist and encode_name(sched) not in existing:
                    print(f"rejected: schedule {sched!r} not found in repository or whitelist")
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
        dest.write_bytes(gzip.compress(content.encode()))
    else:
        dest.write_text(content)
    print(f"pushed: {name} (version {new_version:04d})")


def _parse_system_sections(content: str) -> list[dict]:
    lines = content.splitlines()
    n, i, sections = len(lines), 0, []
    while i < n:
        if lines[i] != _SEPARATOR:
            i += 1
            continue
        i += 1
        section: dict = {}
        for key in ("machine", "schedule", "time", "notes"):
            label = f"\U0001f449{key}\U0001f448"
            if i >= n or lines[i] != label:
                section = {}
                break
            i += 1
            if key == "notes":
                note_lines = []
                while i < n and lines[i] != _SEPARATOR:
                    note_lines.append(lines[i])
                    i += 1
                section["notes"] = " ".join(note_lines).strip()
            else:
                section[key] = lines[i].strip() if i < n else ""
                i += 1
        if len(section) == 4:
            sections.append(section)
    return sections


def _is_initial_state_system(content: str) -> bool:
    sections = _parse_system_sections(content)
    return bool(sections) and all(
        not s["machine"] and not s["schedule"] and not s["time"] and not s["notes"]
        for s in sections
    )


def _csv_field(s: str) -> str:
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_row(*fields: str) -> str:
    return ", ".join(_csv_field(f) for f in fields)


def cmd_export(repo_root: Path, collection: str, filename: str,
               downloads_dir: Path, cache_dir: Path, editor: str):
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
        rows.append(_csv_row("system_name", "machine_name", "schedule_name", "time", "notes"))
        for encoded, fname in sorted(seen.items()):
            system_name = decode_name(encoded) or encoded
            content = gzip.decompress((col_path / fname).read_bytes()).decode()
            sections = _parse_system_sections(content)
            if all(not s["machine"] and not s["schedule"] for s in sections):
                continue  # initial state: no meaningful data yet
            for sec in sections:
                rows.append(_csv_row(system_name, sec["machine"], sec["schedule"], sec["time"], sec["notes"]))
    elif collection == "schedules":
        rows.append(_csv_row("schedule_name", "dates"))
        for encoded, fname in sorted(seen.items()):
            schedule_name = decode_name(encoded) or encoded
            content = (col_path / fname).read_text().strip()
            if not content:
                continue  # initial state: empty document
            dates = " ".join(content.split(","))
            rows.append(_csv_row(schedule_name, dates))

    downloads_dir.mkdir(parents=True, exist_ok=True)
    dest = downloads_dir / filename
    dest.write_text("\n".join(rows) + "\n")
    print(f"exported: {dest}")
    subprocess.Popen([editor, str(dest)])


# ── REPL ──────────────────────────────────────────────────────────────────────

USAGE = (
    "commands:\n"
    "  ls <collection>\n"
    "  add <collection> <name>\n"
    "  cat <collection> <name>\n"
    "  get <collection> <name>\n"
    "  clear <collection> <name>\n"
    "  push <collection> <name>\n"
    "  export <collection> <file.csv>\n"
    "  exit\n"
    "collections: systems, schedules"
)


def dispatch(parts: list[str], repo_root: Path, downloads_dir: Path,
             cache_dir: Path, editor: str, schedule_whitelist: set[str]) -> bool:
    """Return False to exit."""
    cmd = parts[0]

    if cmd == "exit":
        return False

    if cmd in ("ls", "add", "cat", "get", "clear", "push", "export"):
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
            cmd_add(repo_root, collection, parts[2])

    elif cmd == "cat":
        if len(parts) != 3:
            print("usage: cat <collection> <name>")
        else:
            cmd_cat(repo_root, collection, parts[2])

    elif cmd == "get":
        if len(parts) != 3:
            print("usage: get <collection> <name>")
        else:
            cmd_get(repo_root, collection, parts[2], downloads_dir, editor)

    elif cmd == "clear":
        if len(parts) != 3:
            print("usage: clear <collection> <name>")
        else:
            cmd_clear(repo_root, collection, parts[2], downloads_dir, editor)

    elif cmd == "push":
        if len(parts) != 3:
            print("usage: push <collection> <name>")
        else:
            cmd_push(repo_root, collection, parts[2], downloads_dir, schedule_whitelist)

    elif cmd == "export":
        if len(parts) != 3:
            print("usage: export <collection> <file.csv>")
        else:
            cmd_export(repo_root, collection, parts[2], downloads_dir, cache_dir, editor)

    else:
        print(f"unknown command: {cmd!r}")
        print(USAGE)

    return True


def main():
    config = load_config()
    repo_root = get_repo_root(config)
    downloads_dir = get_downloads_dir(config)
    cache_dir = get_cache_dir(config)
    editor = get_editor(config)
    schedule_whitelist = get_schedule_whitelist(config)

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
            print(USAGE)
            continue

        parts = line.split()
        if not dispatch(parts, repo_root, downloads_dir, cache_dir, editor, schedule_whitelist):
            break


if __name__ == "__main__":
    main()
