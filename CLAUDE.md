# repo-manipulator — developer notes

## How to run

```
python3 src/app.py
```

Reads `settings.ini` from the project root (one level above `src/`).

## Project layout

```
src/app.py          single-file Python application (REPL)
settings.ini        configuration
dummy-repo/         local NAS substitute for development
  systems/          .txt.gz files named by base32-encoded system name + version
  schedules/        .txt files named by base32-encoded schedule name + version
downloads/          files staged for editing (always plain .txt)
cache/              local mirror of the NAS repo, populated at startup and on export
```

## settings.ini keys

| Section        | Key                     | Default      | Meaning                                                  |
|----------------|-------------------------|--------------|----------------------------------------------------------|
| `[repository]` | `root`                  | `dummy-repo` | Path to the NAS repo root                                |
| `[downloads]`  | `dir`                   | `downloads`  | Where edited files are staged                            |
| `[cache]`      | `dir`                   | `cache`      | Local mirror of the NAS repo                             |
| `[editor]`     | `command`               | `mousepad`   | Editor launched by get/clear/export                      |
| `[schedule]`   | `whitelist`             | *(empty)*    | Comma-separated schedule names always accepted on push   |
| `[system]`     | `additional_properties` | *(empty)*    | Comma-separated extra field names appended to each section |

## File naming convention

Every file in the repo is named `{base32(name)}.{version}.{ext}` where:

- `base32(name)` — Python `base64.b32encode`, `=` padding stripped (uppercase letters + digits 2–7, safe for all filesystems)
- `version` — zero-padded 4-digit integer (`0000`–`9999`)
- `ext` — `.txt.gz` for systems, `.txt` for schedules

`ls`, `cat`, `get`, `clear`, and `push` all resolve to the **highest version** file for a given name (lexicographic sort of `os.listdir`, no per-file stat calls).

## Versioning

- `add` creates version `0000`.
- `push` reads the latest version in the repo, writes `version + 1` as a new file. Old versions are never deleted.

## Compression

- **systems** files are gzip-compressed in the repo (`.txt.gz`).  
  `get` decompresses to plain `.txt` in downloads. `push` re-compresses before writing to the repo.  
  `clear` writes the plain-text empty template to downloads (no compression).
- **schedules** files are stored as plain `.txt` throughout.

## Cache

On startup `sync_cache` runs: one `os.listdir` per collection on the NAS and one on the cache dir, then copies only the missing files. No per-file stat calls against the NAS.

`export` re-runs `sync_cache` before reading, then reads exclusively from the local cache — no per-file NAS calls during CSV generation.

## Commands

| Command                        | Description |
|--------------------------------|-------------|
| `ls <collection>`              | Print decoded names (one per line, latest-version files only, deduped) |
| `add <collection> <name>`      | Create `{encoded}.0000{ext}` with the empty document template |
| `cat <collection> <name>`      | Print latest version content to stdout (decompresses systems) |
| `get <collection> <name>`      | Copy latest version to downloads as `.txt`, open with editor |
| `clear <collection> <name>`    | Write empty document template to downloads (same filename as `get`), open with editor |
| `push <collection> <name>`     | Validate latest `.txt` in downloads, write as next version in repo |
| `export <collection> <file>`   | Sync cache, build CSV from latest versions, save to downloads, open with editor |
| `exit`                         | Quit |

Collections: `systems`, `schedules`.

## Document formats

### systems

One or more sections, each starting with the separator line (10 × 👉 + 10 × 👈):

```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
machine_value
👉schedule👈
schedule_value
👉time👈
12:00
👉notes👈
notes line 1
notes line 2
👉prop1👈
prop1_value
👉prop2👈
prop2_value
```

The additional fields after `👉notes👈` are determined by `[system] additional_properties` in `settings.ini`. Their values may be empty. If no additional properties are configured the section ends after the notes content.

Validation rules enforced on `push`:
- Every section must begin with the exact separator.
- `👉machine👈` and `👉schedule👈` values must be non-empty (after strip).
- `👉time👈` value must be non-empty and match `dd:dd` (two digits, colon, two digits).
- `👉notes👈` must be followed by at least one line.
- Each configured additional property label must be present (value may be empty).
- Each `👉schedule👈` value must either exist as an entry in the repo's `schedules/` collection, or appear in `[schedule] whitelist` in `settings.ini`. The schedules directory is read with a single `os.listdir` call per push.
- **Exception:** if every section in the document has all fields blank (initial state as written by `add`/`clear`), the push is accepted without validation — this allows saving a cleared document back to the repo.

Empty template (written by `add` / `clear`): separator + all core labels + all configured additional property labels, each with a blank value line.

### schedules

One line (optional trailing newline) of `yyyy/mm/dd` dates separated by commas:

```
1234/12/31,2000/06/01
```

Empty template: empty string.

## CSV export format

### systems

```csv
system_name, machine_name, schedule_name, time, notes, prop1, prop2
sys1, m1, sche3, 09:00, foobarbaz, val1, val2
sys1, m2, sche7, 12:30, , , 
```

One row per section. Multi-line notes are joined with a space. Entries still in initial state (all sections have empty machine + schedule + time + notes + additional properties) are excluded. Additional property columns appear in the order defined by `[system] additional_properties`. If a document was saved with a different set of additional properties (e.g. after a config change), missing columns are filled with empty string rather than dropping the row.

### schedules

```csv
schedule_name, dates
sche1, 1234/11/12 1234/11/12 1234/12/12
```

Comma-separated dates from the file are converted to space-separated in the CSV. Entries with empty content are excluded.

Fields containing `,`, `"`, or newlines are quoted (RFC 4180 `""`-escaping).

## Key implementation decisions

- `os.listdir()` is used for all directory reads (not `glob` or `iterdir`) to issue a single syscall per directory — important on NAS with many files.
- The NAS `systems/` and `schedules/` directories contain no subdirectories, so flat `listdir` is sufficient.
- Downloads always hold plain `.txt` regardless of collection, so mousepad can open them directly.
- `push` looks for the latest `.txt` in downloads (always suffix `.txt`); the repo suffix is determined by `REPO_SUFFIX[collection]`.
- `_validate_system` is strict: it requires exactly the configured additional property labels in the document. `_parse_system_sections` is lenient: it collects whatever prop labels are present and maps them to the configured names, defaulting to `""` for any mismatch. This means old documents with different props export cleanly after a config change.
