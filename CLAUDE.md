# repo-manipulator — developer notes

## How to run

```
python3 src/app.py
```

Reads `settings.ini` from the project root (one level above `src/`), and `repository.ini` from the repo root.

## Project layout

```
src/app.py                        single-file Python application (REPL)
src/gui.py                        JTable GUI class (tkinter), imported directly by app.py
settings.ini                      configuration
dummy-repo/                       local NAS substitute for development
  repository.ini                  per-repository configuration (main collection, JSON file paths)
  additional_properties.json      JSON array of extra field names for system sections
  additional_mandatory_properties.json  JSON array defining dynamic collections (see below)
  systems/                        .txt.gz files named by base32-encoded system name + version
  schedules/                      .txt files named by base32-encoded schedule name + version
  contacts/                       .txt files named by base32-encoded contact name + version
  <collection>/                   .txt files for each dynamic collection
downloads/                        files staged for editing, organised by collection
  systems/                        plain .txt files for system entries
  schedules/                      plain .txt files for schedule entries
  contacts/                       plain .txt files for contact entries
  <collection>/                   plain .txt files for each dynamic collection
cache/                            local mirror of the NAS repo, populated at startup and on export
```

## settings.ini keys

| Section        | Key         | Default      | Meaning                                                |
|----------------|-------------|--------------|--------------------------------------------------------|
| `[repository]` | `root`      | `dummy-repo` | Path to the NAS repo root                              |
| `[downloads]`  | `dir`       | `downloads`  | Where edited files are staged                          |
| `[cache]`      | `dir`       | `cache`      | Local mirror of the NAS repo                           |
| `[editor]`     | `command`   | `mousepad`   | Editor launched by get/clear/export                    |

## repository.ini

Located at `{repo_root}/repository.ini`. Configures the main collection and paths to the JSON definition files.

| Section                   | Key                     | Default                                | Meaning |
|---------------------------|-------------------------|----------------------------------------|---------|
| `[main_collection]`       | `collection_name`       | `systems`                              | Name of the main (gzip-compressed, multi-section) collection |
| `[main_collection]`       | `partitioning_property` | `system`                               | Prefix for the first CSV column header: `{partitioning_property}_name` |
| `[main_collection]`       | `property_order`        | *(empty)*                              | Comma-separated field names that appear first in main-collection documents, in the listed order. Remaining fields follow in their default relative order. Unknown names are silently ignored. |
| `[additional_properties]` | `json`                  | `additional_properties.json`           | Filename (relative to repo root) of the optional-properties definition |
| `[reference_collections]` | `json`                  | `additional_mandatory_properties.json` | Filename (relative to repo root) of the dynamic collections definition |

## additional_properties.json

Located at `{repo_root}/{filename}` where `filename` is the value of `[additional_properties] json` in `repository.ini` (default: `additional_properties.json`). A JSON array of objects defining the optional (non-mandatory) fields appended to each system section:

```json
[
  {"property_name": "notes", "validation_type": "NONE", "multiline": true},
  {"property_name": "id",    "validation_type": "RE:[^#]+"},
  {"property_name": "prop1", "validation_type": "NONE"},
  {"property_name": "prop2", "validation_type": "NOT_EMPTY"},
  {"property_name": "prop3", "validation_type": "HH:MM"}
]
```

| Field             | Meaning |
|-------------------|---------|
| `property_name`   | Field name appended to each system section |
| `validation_type` | `"NONE"` — no validation (value may be empty); `"NOT_EMPTY"` — `push` rejects empty values; `"HH:MM"` — `push` rejects values that don't match `\d{2}:\d{2}`; `"RE:<pattern>"` — `push` rejects values that don't fully match the regex `<pattern>` (via `re.fullmatch`). Defaults to `"NONE"` if omitted. |
| `multiline`       | `true` — field value spans multiple lines until the next label; stored with `"\n"` in JSON, joined with `" "` in CSV export. `false` or absent — single-line field. In JTable editable mode, double-clicking a multiline cell opens a modal text-editor dialog instead of an inline entry. |

If the file is absent, no additional properties are used. Non-object entries in the array are silently ignored.

## additional_mandatory_properties.json

Located at `{repo_root}/{filename}` where `filename` is the value of `[reference_collections] json` in `repository.ini` (default: `additional_mandatory_properties.json`). A JSON array of objects, each defining a **dynamic collection**:

```json
[
  {"collection_name": "teams",     "property_name": "team",     "type": "NOTE",         "whitelist": []},
  {"collection_name": "schedules", "property_name": "schedule", "type": "DATE",         "whitelist": ["everyday", "weekends"]},
  {"collection_name": "contacts",  "property_name": "contact",  "type": "PHONE_NUMBER", "whitelist": []}
]
```

| Field             | Meaning |
|-------------------|---------|
| `collection_name` | Directory name in the repo (e.g. `teams/`); also the collection name used in commands |
| `property_name`   | The system-section field that references this collection; validated on push |
| `type`            | Content validation applied on `push`: `"DATE"` — comma-separated `yyyy/mm/dd` dates; `"PHONE_NUMBER"` — comma-separated `[0-9\-\+]+` strings; `"EMAIL"` — comma-separated `user@domain.tld` addresses; `"NOTE"` or absent — no content validation. |
| `whitelist`       | Optional JSON array of string values accepted without checking the collection (e.g. `["everyday", "weekends"]`). Omit or use `[]` for no whitelist. |

At startup the app reads this file and for each entry:
- Adds `collection_name` to the valid collection set
- Registers `.txt` as its repo file suffix
- Creates the collection directory in both the repo root and the local cache if absent
- Appends `property_name` to `additional_props`, making it a required document field

`schedule` and `contact` must be declared in `additional_mandatory_properties.json` to be required. When declared, they are appended to `additional_props` and validated like any other mandatory ref prop (non-empty check + collection-existence check).

Dynamic collections behave like the built-in `schedules`/`contacts`: plain `.txt` storage, no format validation on push, comma-separated values for `len`/`diff`/`export`. The `export` CSV uses `name, values` column headers. If the file is absent, no dynamic collections are loaded.

**Mandatory property behaviour in systems:**

All `property_name` values are appended to `additional_props` at startup and are therefore included in system document templates, the 👉👈 text format, and JSON storage. On `push`, they are validated more strictly than optional properties:
- The label (`👉property_name👈`) must be present (same as optional props).
- The value must be **non-empty**.
- The value must exist as an entry in the corresponding `collection_name` collection (one `os.listdir` call per distinct collection per push, reusing the list across all sections).

**Whitelist**: values listed in the `"whitelist"` array in `additional_mandatory_properties.json` bypass the collection-existence check.

## File naming convention

Every file in the repo is named `{base32(name)}.{version}.{ext}` where:

- `base32(name)` — Python `base64.b32encode`, `=` padding stripped (uppercase letters + digits 2–7, safe for all filesystems)
- `version` — zero-padded 4-digit integer (`0000`–`9999`)
- `ext` — `.txt.gz` for systems, `.txt` for schedules, contacts, and dynamic collections

`ls`, `cat`, `get`, `clear`, and `push` all resolve to the **highest version** file for a given name (lexicographic sort of `os.listdir`, no per-file stat calls).

## Versioning

- `add` creates version `0000`.
- `push` reads the latest version in the repo, writes `version + 1` as a new file. Old versions are never deleted.

## Compression

- **systems** files are gzip-compressed in the repo (`.txt.gz`).  
  `get` decompresses to plain `.txt` in `downloads/systems/`. `push` re-compresses before writing to the repo.  
  `clear` writes the plain-text empty template to `downloads/systems/` (no compression).
- **schedules**, **contacts**, and **dynamic collections** are stored as plain `.txt` throughout.

## Downloads

`get`, `clear`, and `cat --jtable` write files to `downloads/{collection}/` (e.g. `downloads/systems/`, `downloads/schedules/`). `push` reads from the same subdirectory. Using per-collection subdirectories means same-name entries in different collections (e.g. a "foo" in `schedules` and a "foo" in a dynamic collection) never share a filename and cannot overwrite each other.

`export` is the exception: its output CSV is written directly to `downloads/` (not a subdirectory), because it is not a versioned collection entry.

All files in `downloads/` are plain `.txt` regardless of collection, so any text editor can open them directly.

## Cache

On startup `sync_cache` runs: one `os.listdir` per collection on the NAS and one on the cache dir, then copies only the missing files. No per-file stat calls against the NAS.

`export` re-runs `sync_cache` before reading, then reads exclusively from the local cache — no per-file NAS calls during CSV generation.

## Commands

| Command                                  | Description |
|------------------------------------------|-------------|
| `ls <collection>`                        | Print decoded names (one per line, latest-version files only, deduped) |
| `add <collection> <name>`                | Create `{encoded}.0000{ext}` with the empty document template |
| `cat <collection> <name>`               | Print latest version content to stdout (decompresses systems) |
| `cat systems <name> --jtable`            | Save to `downloads/systems/`, open read-only JTable window |
| `get <collection> <name>`               | Copy latest version to `downloads/{collection}/` as `.txt`, open with editor |
| `get systems <name> --jtable`            | Save to `downloads/systems/`, open editable JTable window with Save / Add Row / Duplicate Row / Delete Row buttons |
| `clear <collection> <name>`             | Write empty document template to `downloads/{collection}/` (same filename as `get`), open with editor |
| `len <collection> <name>`               | Print the count of non-empty records in the latest version (sections for systems, comma-separated entries for all others) |
| `push <collection> <name>`              | Validate latest `.txt` in `downloads/{collection}/`, write as next version in repo |
| `export <collection> <file>`            | Sync cache, build CSV from latest versions, save to `downloads/`, open with editor |
| `export <collection> <file> --jtable`   | Same as `export` but opens the CSV in a JTable window instead of the editor |
| `diff <collection> <name>`              | Compare latest and previous repo versions; print JSON with `"deleted"` and `"added"` arrays |
| `diff <collection> <name> --jtable`     | Same comparison but opens a JTable window: deleted rows in red with `−`, added rows in green with `+` |
| `exit`                                   | Quit |

Built-in collections: `systems`, `schedules`, `contacts`. Dynamic collections are added at startup from `additional_mandatory_properties.json`.

`--jtable` on `cat`/`get` is only supported for `systems`.

## Document formats

### systems — repo storage (JSON)

Systems files in the repo are stored as a JSON array of section objects, compressed with gzip. All values are strings.

```json
[
  {"notes": "line1\nline2", "machine": "m1", "time": "09:00", "id": "id1", "schedule": "sche1", "contact": "cont1", "prop1": "val1"},
  {"notes": "notes", "machine": "m2", "time": "12:00", "id": "id2", "schedule": "sche2", "contact": "cont2", "prop1": ""}
]
```

The empty template written by `add` is a single-element array with all blank string values.

### systems — user-facing text (👉👈 format)

`get`, `cat`, and `clear` present the 👉👈 separator format. `push` accepts it and converts back to JSON before writing to the repo.

One or more sections, each starting with the separator line (20 × 🏔):

```
🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔
👉notes👈
notes line 1
notes line 2
👉machine👈
machine_value
👉time👈
12:00
👉id👈
id_value
👉schedule👈
schedule_value
👉contact👈
contact_value
👉prop1👈
prop1_value
👉prop2👈
prop2_value
```

There are no hardcoded core fields. All fields — including `notes`, `machine`, `time`, `id`, `schedule`, and `contact` — are additional properties loaded from config. Fields from `additional_properties.json` come first (in declaration order), followed by fields from `additional_mandatory_properties.json`. The full order is controlled by `[main_collection] property_order` in `repository.ini` — any field listed there moves to the front. All fields must still be present; only the order changes. If `property_order` is empty the default order is used.

Validation rules enforced on `push` (applied to the 👉👈 text before conversion):
- Every section must begin with the exact separator.
- Each optional additional property label (`additional_properties.json`) must be present; its value is validated according to its `validation_type`: `NONE` — any value (including empty); `NOT_EMPTY` — rejects empty; `HH:MM` — rejects values not matching `\d{2}:\d{2}`; `RE:<pattern>` — rejects values that don't fully match the regex pattern. Multiline fields (`multiline: true`) consume all lines until the next label or separator.
- Each mandatory property label (`additional_mandatory_properties.json` `property_name`, including `schedule` and `contact` when declared there) must be present with a **non-empty** value, and that value must exist as an entry in the corresponding `collection_name` collection, or appear in the `"whitelist"` array for that prop. One `os.listdir` call per distinct collection per push.
- **Exception:** if every section in the document has all fields blank (initial state as written by `add`/`clear`), **or if the file content is empty/whitespace** (e.g. all rows deleted via the JTable GUI), the push is accepted without validation and the empty template (`_empty_system_json`) is written to the repo.

Empty template (written by `clear`): separator + all configured additional property labels, each with a blank value line.

### schedules

One line (optional trailing newline) of `yyyy/mm/dd` dates separated by commas:

```
1234/12/31,2000/06/01
```

Empty template: empty string.

### contacts

One line (optional trailing newline) of phone/contact strings matching `[0-9\-\+]+`, separated by commas:

```
03-1234-5678,09012345678,+81-0100-0331
```

Empty template: empty string.

## CSV export format

### systems

```csv
system_name, notes, machine, time, id, schedule, contact, prop1, prop2
sys1, foobarbaz, m1, 09:00, id1, sche3, cont1, val1, val2
sys1, , m2, 12:30, id2, sche7, cont2, , 
```

One row per section. Multiline fields (`multiline: true` in `additional_properties.json`) are joined with a space. Documents where every field in every section is blank are excluded from the CSV. The first column header is `{partitioning_property}_name` from `repository.ini`. Remaining column headers are the field names as declared (no renaming). Column order follows `field_order` (the same order used in the 👉👈 text format), which respects `[main_collection] property_order` in `repository.ini`. If a document was saved with a different set of additional properties (e.g. after a config change), missing columns are filled with empty string rather than dropping the row.

### schedules

```csv
schedule_name, dates
sche1, 1234/11/12 1234/11/12 1234/12/12
```

Comma-separated dates from the file are converted to space-separated in the CSV. Entries with empty content are excluded.

### contacts

```csv
contact_name, numbers
cont1, 03-1234-5678 09012345678 +81-0100-0331
```

Comma-separated contact strings from the file are converted to space-separated in the CSV. Entries with empty content are excluded.

### dynamic collections

```csv
name, values
teamA, value1 value2 value3
```

Comma-separated values from the file are converted to space-separated in the CSV. Entries with empty content are excluded.

Fields containing `,`, `"`, or newlines are quoted (RFC 4180 `""`-escaping).

## Key implementation decisions

- `os.listdir()` is used for all directory reads (not `glob` or `iterdir`) to issue a single syscall per directory — important on NAS with many files.
- The NAS `systems/` and `schedules/` directories contain no subdirectories, so flat `listdir` is sufficient.
- `push` looks for the latest `.txt` in `downloads/{collection}/`; the repo suffix is determined by `REPO_SUFFIX[collection]`.
- Systems are stored as JSON in the repo (compressed) but presented as 👉👈 separator text for editing. `get`/`cat` convert JSON→text; `push` validates the text then converts text→JSON before writing.
- `_validate_system` is strict: it requires exactly the configured additional property labels in the document, and enforces non-empty values for mandatory props (passed as a `frozenset[str]`). `_parse_system_sections` is lenient and used only for mandatory-ref-prop-reference checking and initial-state detection (both operate on the 👉👈 text from downloads). `cmd_export` parses JSON directly from cache using `.get(key, "")` fallbacks, so old documents with different props export cleanly after a config change.
- There are **no hardcoded core fields**. Every system field — including `notes`, `machine`, `time`, `id`, `schedule`, `contact` — is an additional property declared in `additional_properties.json` or `additional_mandatory_properties.json`. `notes` is declared in `additional_properties.json` with `"multiline": true`. `id` is not unique — multiple sections or systems can share the same id value.
- `load_repository_config(repo_root)` reads `repository.ini` and returns a 5-tuple: `(collection_name, partitioning_property, property_order, additional_props_file, ref_collections_file)`, with fallbacks to the previous defaults. `MAIN_COLLECTION` and `PARTITIONING_PROPERTY` are module-level globals set by `main()` from this call; `COLLECTIONS` and `REPO_SUFFIX` are updated in-place when `collection_name` differs from the default `"systems"`.
- `load_additional_properties(repo_root, filename)` returns `tuple[tuple[str, str, bool], ...]` — triples of `(name, validation_type, multiline)`. `main()` derives `optional_props`, `prop_validation_types`, and `multiline_props: frozenset[str]` from it. `multiline_props` is threaded through `dispatch` and all `cmd_*` functions that touch system text; JTable receives it as `multiline_cols`.
- `MAIN_COLLECTION` and `PARTITIONING_PROPERTY` are module-level globals (defaulting to `"systems"` / `"system"`) set in `main()` from `repository.ini`. All `collection == "systems"` comparisons use `MAIN_COLLECTION`; the CSV first-column header is built as `f"{PARTITIONING_PROPERTY}_name"`.
- `COLLECTIONS` and `REPO_SUFFIX` are mutable module-level globals, initialized with the three built-in collections and extended at startup by `load_dynamic_collections`. All command dispatch and `sync_cache` iterate `COLLECTIONS` at call time, so adding to it before the REPL starts is sufficient to make dynamic collections fully usable. `mandatory_ref_props` (a `tuple[tuple[str, str, frozenset[str]], ...]` of `(property_name, collection_name, whitelist)` triples) is threaded from `main` → `dispatch` → `cmd_push`. The whitelist for each prop is read from the `"whitelist"` array in its `additional_mandatory_properties.json` entry (`dc.get("whitelist", [])`) at startup. `schedule` and `contact` are loaded from `additional_mandatory_properties.json` like any other field, appended to `additional_props`, and included in `mandatory_ref_props` with non-empty + collection-existence checks. `mandatory_prop_names` (the `frozenset` passed to `_validate_system`) is the set of all `property_name` values from `mandatory_ref_props`, meaning the non-empty check applies to `schedule` and `contact` when declared.
- `field_order` is a `tuple[str, ...]` of all system field names in the display/validation order dictated by `[main_collection] property_order` in `repository.ini`. It is computed once in `main()` and threaded as a keyword-only argument through `dispatch` and every `cmd_*` function and internal parser/serialiser. When `field_order` is `None` (its default in all internal functions) the `additional_props`-based behaviour is used.

## JTable GUI (`src/gui.py`)

`JTable` is a tkinter `ttk.Treeview`-based table widget imported directly by `app.py` (no subprocess). Constructor:

```python
JTable(path=None, mode="csv", readonly=False, diff_data=None, title=None, multiline_cols=frozenset()).run()
```

| Parameter      | Values / meaning |
|----------------|-----------------|
| `path`         | File to display (CSV or 👉👈 `.txt`) |
| `mode`         | `"csv"` — parse as CSV (export); `"systems"` — parse 👉👈 format |
| `readonly`     | `True` suppresses Save/row-edit buttons (`cat --jtable`) |
| `diff_data`    | `{"columns": [...], "deleted": [[...], ...], "added": [[...], ...]}` — activates diff view; `path` not needed |
| `title`        | Window title (defaults to filename or `"diff"`) |
| `multiline_cols` | `frozenset[str]` of column names whose cells open a modal text-editor dialog on double-click instead of an inline entry. Passed from `multiline_props` in `app.py`. |

**Systems editable mode** (`mode="systems"`, `readonly=False`) features: double-click cell to edit inline (Entry overlay), Save button writes 👉👈 format back to the downloads file, Add Row / Duplicate Row / Delete Row buttons with odd/even re-striping. Cells for columns in `multiline_cols` are displayed collapsed (newlines → spaces); double-clicking one opens a modal text-editor dialog (OK / Cancel) — OK updates the treeview and preserves newlines for the next Save.

**Diff mode** (`diff_data` provided): read-only, deleted rows shown in red with `−`, added rows in green with `+`. Data columns are sortable.
