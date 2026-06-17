import base64
import configparser
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


def latest_in_dir(directory: Path, encoded: str) -> Path | None:
    prefix = encoded + "."
    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return None
    matches = sorted(
        f for f in entries
        if f.startswith(prefix) and f.endswith(".txt")
        and len(f) == len(prefix) + 8  # 4-digit version + ".txt"
        and f[len(prefix):-4].isdigit()
    )
    return (directory / matches[-1]) if matches else None


def find_latest_file(repo_root: Path, collection: str, name: str) -> Path | None:
    return latest_in_dir(collection_path(repo_root, collection), encode_name(name))


# ── validation ────────────────────────────────────────────────────────────────

_SEPARATOR = "\U0001f449" * 10 + "\U0001f448" * 10
_DATE_SEG = r"\d{4}/\d{2}/\d{2}"
_SCHEDULE_RE = re.compile(rf"^{_DATE_SEG}(,{_DATE_SEG})*\n?$")


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
    seen: set[str] = set()
    for fname in sorted(os.listdir(path)):
        if not fname.endswith(".txt"):
            continue
        parts = fname[:-4].split(".")  # strip .txt then split encoded.version
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
    dest = path / f"{encoded}.0000.txt"
    if dest.exists():
        print(f"error: already exists: {name}")
        return
    dest.touch()
    print(f"created: {name}")


def cmd_cat(repo_root: Path, collection: str, name: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    print(filepath.read_text(), end="")


def cmd_get(repo_root: Path, collection: str, name: str,
            downloads_dir: Path, editor: str):
    filepath = find_latest_file(repo_root, collection, name)
    if filepath is None:
        print(f"error: not found: {name}")
        return
    downloads_dir.mkdir(parents=True, exist_ok=True)
    dest = downloads_dir / filepath.name
    dest.write_text(filepath.read_text())
    print(f"saved: {dest}")
    subprocess.Popen([editor, str(dest)])


def cmd_push(repo_root: Path, collection: str, name: str, downloads_dir: Path):
    encoded = encode_name(name)
    src = latest_in_dir(downloads_dir, encoded)
    if src is None:
        print(f"error: not found in downloads: {name}")
        return
    content = src.read_text()
    ok, reason = validate(collection, content)
    if not ok:
        print(f"rejected: {reason}")
        return
    col_path = collection_path(repo_root, collection)
    latest = latest_in_dir(col_path, encoded)
    if latest is None:
        print(f"error: not found in repository: {name}")
        return
    current_version = int(latest.stem.split(".")[1])
    new_version = current_version + 1
    dest = col_path / f"{encoded}.{new_version:04d}.txt"
    dest.write_text(content)
    print(f"pushed: {name} (version {new_version:04d})")


# ── REPL ──────────────────────────────────────────────────────────────────────

USAGE = (
    "commands:\n"
    "  ls <collection>\n"
    "  add <collection> <name>\n"
    "  cat <collection> <name>\n"
    "  get <collection> <name>\n"
    "  push <collection> <name>\n"
    "  exit\n"
    "collections: systems, schedules"
)


def dispatch(parts: list[str], repo_root: Path,
             downloads_dir: Path, editor: str) -> bool:
    """Return False to exit."""
    cmd = parts[0]

    if cmd == "exit":
        return False

    if cmd in ("ls", "add", "cat", "get", "push"):
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

    elif cmd == "push":
        if len(parts) != 3:
            print("usage: push <collection> <name>")
        else:
            cmd_push(repo_root, collection, parts[2], downloads_dir)

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
        if not dispatch(parts, repo_root, downloads_dir, editor):
            break


if __name__ == "__main__":
    main()
