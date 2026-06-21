# naxel — developer notes

## How to run

```
python3 src/app.py
```

Reads `settings.ini` from the project root (one level above `src/`), and `repository.ini` from the repo root.

```
python3 src/app.py -c 'cmd1 && cmd2 && ...'
```

Batch mode: runs the `&&`-separated commands sequentially, then exits without entering the REPL. Useful for scripting and pipelines, e.g.:

```
cat foo_main.txt | python3 src/app.py -c 'add systems foo && get systems foo - && push systems foo && diff systems foo'
```

## Tauri/Rust version

A parallel Rust implementation lives in `src-rs/`. It exposes the same REPL commands and reads the same `settings.ini`, `repository.ini`, and JSON config files. The produced binary is `naxel`.

### How to build and run

```
cargo build                       # debug build → target/debug/naxel
cargo build --release             # release build → target/release/naxel
./target/debug/naxel              # start REPL
./target/debug/naxel -c 'cmd1 && cmd2 && ...'   # batch mode
```

### Tauri project layout

```
src-rs/
  main.rs           REPL entry point; also handles --table mode for table windows
  commands.rs       all command implementations (cmd_ls, cmd_get, cmd_push, …)
  repo.rs           RepoState struct, initialize_repo, sync_cache, build_ref_data
  config.rs         settings.ini loading (AppConfig)
  encoding.rs       base32 encode/decode, latest_in_dir, repo_namespace
  formats.rs        👉👈 ↔ JSON conversion, empty templates
  validation.rs     validate_main_collection, validate_ref_collection
  table_spec.rs     TableData enum + PushInfo struct (serialised between REPL and table window)
  gui/
    mod.rs          Tauri commands (get_table_data, read_file, save_file, save_and_push), show_table
    query.rs        query parser (mirrors the JS parser in frontend/index.html)
frontend/
  index.html        single-file HTML/JS table UI (loaded by the Tauri webview)
Cargo.toml
tauri.conf.json
build.rs
```

### Dual-mode binary

The binary runs in two modes selected by the first argument:

- **REPL mode** (default): reads `settings.ini`, initialises the repo, starts a `rustyline` REPL identical in behaviour to `python3 src/app.py`.
- **Table mode** (`--table`): reads a `TableData` JSON blob from stdin and opens a Tauri webview window. Spawned automatically by the REPL via `spawn_table` whenever a `--jtable` command produces a table to display; the REPL continues immediately (fire-and-forget).

`TableData` (defined in `table_spec.rs`) is the serialisable description passed from the REPL process to the table subprocess:

| Variant      | Used by |
|--------------|---------|
| `Csv`        | `export --jtable` |
| `MainText`   | `cat --jtable` (readonly) and `get --jtable` / `clear --jtable` (editable) on the main collection |
| `Ref`        | `cat --jtable` / `get --jtable` / `clear --jtable` on reference collections |
| `Diff`       | `diff --jtable` |

`MainText` and `Ref` carry an optional `PushInfo` field containing all repo state needed for push (repo root, downloads dir, validation config, mandatory ref props, …). This is populated by `cmd_get` and `cmd_clear` when building editable windows and left `None` for readonly windows (`cat --jtable`). The `save_and_push` Tauri command in `gui/mod.rs` reconstructs a minimal `RepoState` from `PushInfo` and calls `cmd_push` after saving.

## Project layout

```
src/app.py                        single-file Python application (REPL)
src/gui.py                        JTable GUI class (tkinter), imported directly by app.py
settings.ini                      configuration
dummy-repo/                       local NAS substitute for development
  repository.ini                  per-repository configuration (main collection, JSON file paths)
  additional_properties.json      JSON array of optional fields for main-collection sections
  additional_mandatory_properties.json  JSON array defining all reference collections
  <main-collection>/              .txt.gz files named by base32-encoded name + version
  <reference-collection>/         .txt files named by base32-encoded name + version
downloads/                        files staged for editing, organised by repository and collection
  <md5>/                          subdirectory named by MD5 hash of the repo's absolute path
    <collection>/                 plain .txt files for each collection
    <file.csv|file.json>          export output (written directly here, not in a collection subdir)
cache/                            local mirror of the NAS repo, populated at startup and on export
  <md5>/                          subdirectory named by MD5 hash of the repo's absolute path
    <collection>/                 cached repo files for each collection
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

Located at `{repo_root}/{filename}` where `filename` is the value of `[additional_properties] json` in `repository.ini` (default: `additional_properties.json`). A JSON array of objects defining the optional (non-mandatory) fields appended to each main-collection section:

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
| `property_name`   | Field name appended to each main-collection section |
| `validation_type` | `"NONE"` — no validation (value may be empty); `"NOT_EMPTY"` — `push` rejects empty values; `"HH:MM"` — `push` rejects values that don't match `\d{2}:\d{2}`; `"MM/DD"` — `push` rejects values that don't match `\d{2}/\d{2}`; `"INT"` — `push` rejects values that don't match `[0-9]+`; `"YYYY"` — `push` rejects values that don't match `\d{4}`; `"RE:<pattern>"` — `push` rejects values that don't fully match the regex `<pattern>` (via `re.fullmatch`). Defaults to `"NONE"` if omitted. |
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
| `property_name`   | The main-collection field that references this collection; validated on push |
| `type`            | Content validation applied on `push`: `"DATE"` — comma-separated `yyyy/mm/dd` dates; `"PHONE_NUMBER"` — comma-separated `[0-9\-\+]+` strings; `"EMAIL"` — comma-separated `user@domain.tld` addresses; `"YEAR"` — comma-separated `\d{4}` years; `"NOTE"` or absent — no content validation. |
| `whitelist`       | Optional JSON array of string values accepted without checking the collection (e.g. `["everyday", "weekends"]`). Omit or use `[]` for no whitelist. |

At startup the app reads this file and for each entry:
- Adds `collection_name` to `COLLECTIONS`
- Creates the collection directory in both the repo root and the local cache if absent
- Appends `property_name` to `additional_props`, making it a required document field

All reference collections use plain `.txt` storage, no format validation on push, and comma-separated values for `len`/`diff`/`export`. The `export` CSV uses `name, values` column headers. If the file is absent, no reference collections are loaded.

There are no built-in reference collections. `schedules`, `contacts`, and any other reference collection must be declared here. `schedule` and `contact` are appended to `additional_props` and validated as mandatory ref props only when they appear in this file.

**Mandatory property behaviour in the main collection:**

All `property_name` values are appended to `additional_props` at startup and are therefore included in main-collection document templates, the 👉👈 text format, and JSON storage. On `push`, they are validated more strictly than optional properties:
- The label (`👉property_name👈`) must be present (same as optional props).
- The value must be **non-empty**.
- The value must exist as an entry in the corresponding `collection_name` collection (one `os.listdir` call per distinct collection per push, reusing the list across all sections).

**Whitelist**: values listed in the `"whitelist"` array in `additional_mandatory_properties.json` bypass the collection-existence check.

## File naming convention

Every file in the repo is named `{base32(name)}.{version}.{ext}` where:

- `base32(name)` — Python `base64.b32encode`, `=` padding stripped (uppercase letters + digits 2–7, safe for all filesystems)
- `version` — zero-padded 4-digit integer (`0000`–`9999`)
- `ext` — `.txt.gz` for the main collection, `.txt` for all reference collections

`ls`, `cat`, `get`, `clear`, and `push` all resolve to the **highest version** file for a given name (lexicographic sort of `os.listdir`, no per-file stat calls).

## Versioning

- `add` creates version `0000`.
- `push` reads the latest version in the repo, writes `version + 1` as a new file. Old versions are never deleted.

## Compression

- The **main collection** is gzip-compressed in the repo (`.txt.gz`).  
  `get` decompresses to plain `.txt` in `downloads/{main-collection}/`. `push` re-compresses before writing to the repo.  
  `clear` writes the plain-text empty template to `downloads/{main-collection}/` (no compression).
- All **reference collections** are stored as plain `.txt` throughout.

## Downloads

Downloads and cache are namespaced by repository so that switching repositories (via `cd`) never mixes files from different repos. The namespace is the MD5 hex digest of the repository root's absolute path — `repo_namespace(repo_root)` in `app.py` computes it.

`get`, `clear`, and `cat --jtable` write files to `downloads/{md5}/{collection}/` (e.g. `downloads/a3f7.../systems/`). `push` reads from the same subdirectory. Using per-collection subdirectories means same-name entries in different collections (e.g. a "foo" in `schedules` and a "foo" in a dynamic collection) never share a filename and cannot overwrite each other.

`export` is the exception: its output file (CSV or JSON) is written directly to `downloads/{md5}/` (not a collection subdir), because it is not a versioned collection entry.

All files in `downloads/{md5}/` are plain `.txt` regardless of collection, so any text editor can open them directly.

## Cache

Cache is also namespaced: `cache/{md5}/{collection}/`.

On startup `sync_cache` runs: one `os.listdir` per collection on the NAS and one on the cache dir, then copies only the missing files. No per-file stat calls against the NAS.

`export` re-runs `sync_cache` before reading, then reads exclusively from the local cache — no per-file NAS calls during CSV/JSON generation.

## Commands

| Command                                  | Description |
|------------------------------------------|-------------|
| `cd <path>`                              | Switch to a different repository; re-reads all config, resets collections, syncs cache for new repo. Downloads and cache are automatically scoped per-repo via MD5 namespace. |
| `ls <collection>`                        | Print decoded names (one per line, latest-version files only, deduped) |
| `add <collection> <name>`                | Create `{encoded}.0000{ext}` with the empty document template |
| `cat <collection> <name>`               | Print latest version content to stdout (decompresses the main collection) |
| `cat <collection> <name> --jtable`      | Save to `downloads/{collection}/`, open read-only JTable window |
| `cat <collection> <name> --json`        | Print latest version as JSON to stdout: main collection outputs the raw JSON sections array (pretty-printed); reference collections output a JSON array of values. Mutually exclusive with `--jtable`. |
| `get <collection> <name>`               | Copy latest version to `downloads/{collection}/` as `.txt`, open with editor |
| `get <collection> <name> --jtable`      | Save to `downloads/{collection}/`, open editable JTable window. Main collection: Save & Push / Add Row / Duplicate Row / Delete Row. Reference collections: Save & Push / Add Row / Delete Row. |
| `get <collection> <name> -`             | Write stdin to `downloads/{collection}/` (same filename as `get`) without opening an editor; intended for use with `-c` batch mode pipelines |
| `clear <collection> <name>`             | Write empty document template to `downloads/{collection}/` (same filename as `get`), open with editor |
| `clear <collection> <name> --jtable`   | Same as `clear` but opens the empty template in an editable JTable window instead of the editor |
| `len <collection> <name>`               | Print the count of non-empty records in the latest version (sections for the main collection, comma-separated entries for all others) |
| `push <collection> <name>`              | Validate latest `.txt` in `downloads/{collection}/`, write as next version in repo |
| `export <collection> <file.csv>`                      | Sync cache, build CSV from latest versions, save to `downloads/`, open with editor |
| `export <collection> <file.csv> --jtable`             | Same as `export` but opens the CSV in a JTable window instead of the editor |
| `export <collection> <file.json>`                     | Sync cache, build JSON array from latest versions, save to `downloads/`, open with editor |
| `diff <collection> <name>`              | Compare latest and previous repo versions; print JSON with `"deleted"` and `"added"` arrays |
| `diff <collection> <name> --jtable`     | Same comparison but opens a JTable window: deleted rows in red with `−`, added rows in green with `+` |
| `fullcopy <destination-directory>`                    | Copy the entire repository (all versions) into `<destination-directory>/<repo-name>/` |
| `fullcopy <destination-directory> --json`             | Create `<destination-directory>/<repo-name>.json` with config and data sections (latest versions only, no history) |
| `mkrepo <json-file> <destination-directory>`          | Reconstruct a repository from a `fullcopy --json` file into `<destination-directory>/<stem>/` |
| `partialcopy <collection> <name> <destination-directory>` | Copy the repository into `<destination-directory>/<repo-name>/` (all versions), but erase all entries except `<collection> <name>`: other `.txt.gz` files are replaced with `gzip.compress(b"[]")`, other `.txt` files are empty. Config files are copied as-is. |
| `partialcopy <collection> <name> <destination-directory> --json` | Create `<destination-directory>/<repo-name>.json` like `fullcopy --json`, but with only `<collection> <name>` carrying real data; all other main-collection entries are `[]` and reference-collection entries are `""`. |
| `exit`                                   | Quit |

All collections are fully dynamic. The main collection is configured in `repository.ini [main_collection]`; all reference collections come from the file named by `[reference_collections] json`. There are no built-in collections.

## Document formats

### main collection — repo storage (JSON)

Main-collection files in the repo are stored as a JSON array of section objects, compressed with gzip. All values are strings.

```json
[
  {"notes": "line1\nline2", "machine": "m1", "time": "09:00", "id": "id1", "schedule": "sche1", "contact": "cont1", "prop1": "val1"},
  {"notes": "notes", "machine": "m2", "time": "12:00", "id": "id2", "schedule": "sche2", "contact": "cont2", "prop1": ""}
]
```

The empty template written by `add` is a single-element array with all blank string values.

### main collection — user-facing text (👉👈 format)

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
- Each optional additional property label (`additional_properties.json`) must be present; its value is validated according to its `validation_type`: `NONE` — any value (including empty); `NOT_EMPTY` — rejects empty; `HH:MM` — rejects values not matching `\d{2}:\d{2}`; `YYYY` — rejects values not matching `\d{4}`; `RE:<pattern>` — rejects values that don't fully match the regex pattern. Multiline fields (`multiline: true`) consume all lines until the next label or separator.
- Each mandatory property label (`additional_mandatory_properties.json` `property_name`, including `schedule` and `contact` when declared there) must be present with a **non-empty** value, and that value must exist as an entry in the corresponding `collection_name` collection, or appear in the `"whitelist"` array for that prop. One `os.listdir` call per distinct collection per push.
- **Exception:** if every section in the document has all fields blank (initial state as written by `add`/`clear`), **or if the file content is empty/whitespace** (e.g. all rows deleted via the JTable GUI), the push is accepted without validation and the empty template (`_empty_main_collection_json`) is written to the repo.

Empty template (written by `clear`): separator + all configured additional property labels, each with a blank value line.

### reference collections

All reference collections share the same plain `.txt` format: comma-separated values on a single line (optional trailing newline).

Content validation on `push` is determined by the `type` field in `additional_mandatory_properties.json`:

- `"DATE"` (`yyyy/mm/dd` dates): `1234/12/31,2000/06/01`
- `"PHONE_NUMBER"` (`[0-9\-\+]+`): `03-1234-5678,09012345678,+81-0100-0331`
- `"EMAIL"` (`user@domain.tld`): `foo@example.com,bar@example.org`
- `"NOTE"` or absent: no format validation

Empty template: empty string.

## CSV export format

### main collection

```csv
system_name, notes, machine, time, id, schedule, contact, prop1, prop2
sys1, foobarbaz, m1, 09:00, id1, sche3, cont1, val1, val2
sys1, , m2, 12:30, id2, sche7, cont2, , 
```

One row per section. Multiline fields (`multiline: true` in `additional_properties.json`) are joined with a space. Documents where every field in every section is blank are excluded from the CSV. The first column header is `{partitioning_property}_name` from `repository.ini`. Remaining column headers are the field names as declared (no renaming). Column order follows `field_order` (the same order used in the 👉👈 text format), which respects `[main_collection] property_order` in `repository.ini`. If a document was saved with a different set of additional properties (e.g. after a config change), missing columns are filled with empty string rather than dropping the row.

### schedules, contacts, and dynamic collections

```csv
name, values
sche1, 1234/11/12 1234/11/12 1234/12/12
```

All non-main collections use the same `name, values` header. Comma-separated values from the file are converted to space-separated in the CSV. Entries with empty content are excluded.

Fields containing `,`, `"`, or newlines are quoted (RFC 4180 `""`-escaping).

## JSON export format

Triggered when the filename passed to `export` ends with `.json`. Opens with the editor like CSV; `--jtable` is not supported.

### main collection

```json
[
  {"system_name": "sys1", "notes": "foobarbaz", "machine": "m1", "time": "09:00", "id": "id1", "schedule": "sche3", "contact": "cont1"},
  {"system_name": "sys1", "notes": "", "machine": "m2", "time": "12:30", "id": "id2", "schedule": "sche7", "contact": "cont2"}
]
```

One object per section. The first key is `{partitioning_property}_name`. Remaining keys follow `field_order`. Multiline fields keep their `\n` characters (unlike CSV, which joins with a space). Documents where every field in every section is blank are excluded.

### reference collections

```json
[
  {"name": "sche1", "values": ["2024/01/01", "2024/06/15", "2025/03/20"]},
  {"name": "sche2", "values": ["2024/03/01"]}
]
```

Comma-separated values from the file are split into a JSON array (unlike CSV, which joins with a space). Empty entries are excluded.

## fullcopy / mkrepo

### `fullcopy <destination-directory>`

Copies the entire repository tree (all versions of every file plus all config files) into `<destination-directory>/<repo-name>/` via `shutil.copytree`. Errors if the destination does not exist or `<destination-directory>/<repo-name>` already exists.

### `fullcopy <destination-directory> --json`

Creates `<destination-directory>/<repo-name>.json`. History is omitted — only the latest version of each entry is included.

```json
{
  "config": {
    "repository_ini": "...(raw text of repository.ini)...",
    "additional_properties": [...parsed JSON array...],
    "reference_collections": [...parsed JSON array...]
  },
  "data": {
    "<main-collection>": {
      "<entry-name>": [...JSON sections array...],
      ...
    },
    "<ref-collection>": {
      "<entry-name>": "...(raw comma-separated text)...",
      ...
    }
  }
}
```

`config.additional_properties` is read from the file named by `[additional_properties] json` in `repository.ini`; `config.reference_collections` from the file named by `[reference_collections] json`. Missing config files produce empty arrays. Errors if the destination does not exist or `<repo-name>.json` already exists.

### `mkrepo <json-file> <destination-directory>`

Reconstructs a repository from a `fullcopy --json` file into `<destination-directory>/<stem>/` (stem = filename without `.json`):

1. Parses `config.repository_ini` text to determine the main collection name and config filenames (`[additional_properties] json`, `[reference_collections] json`).
2. Writes `repository.ini`, the additional-properties file, and the reference-collections file under the new repo directory.
3. For each collection in `data`, creates the collection directory and writes each entry at version `0000`: main collection as gzip-compressed JSON (`.txt.gz`), reference collections as plain text (`.txt`).

Errors if the JSON file does not exist, the destination is not a directory, the JSON is not a valid fullcopy payload (missing `config` or `data` keys), or `<destination>/<stem>` already exists.

## Key implementation decisions

- `os.listdir()` is used for all directory reads (not `glob` or `iterdir`) to issue a single syscall per directory — important on NAS with many files.
- Collection directories contain no subdirectories, so flat `listdir` is sufficient.
- `push` looks for the latest `.txt` in `downloads/{md5}/{collection}/`; the repo suffix is determined by `_repo_suffix(collection)` — returns `.txt.gz` when `collection == MAIN_COLLECTION`, `.txt` for all others.
- The main collection is stored as JSON in the repo (compressed) but presented as 👉👈 separator text for editing. `get`/`cat` convert JSON→text; `push` validates the text then converts text→JSON before writing.
- `_validate_main_collection` is strict: it requires exactly the configured additional property labels in the document, and enforces non-empty values for mandatory props (passed as a `frozenset[str]`). `_parse_main_collection_sections` is lenient and used only for mandatory-ref-prop-reference checking and initial-state detection (both operate on the 👉👈 text from downloads). `cmd_export` parses JSON directly from cache using `.get(key, "")` fallbacks, so old documents with different props export cleanly after a config change.
- There are **no hardcoded core fields**. Every main-collection field — including `notes`, `machine`, `time`, `id`, `schedule`, `contact` — is an additional property declared in `additional_properties.json` or `additional_mandatory_properties.json`. `notes` is declared in `additional_properties.json` with `"multiline": true`. `id` is not unique — multiple sections or documents can share the same id value.
- `repo_namespace(repo_root)` returns `hashlib.md5(str(repo_root.resolve()).encode()).hexdigest()` — the 32-character hex digest used to namespace downloads and cache directories per repository.
- `initialize_repo(repo_root, downloads_base, cache_base)` bundles all per-repository initialisation: clears and re-populates `MAIN_COLLECTION`, `PARTITIONING_PROPERTY`, `COLLECTIONS`, `COLLECTION_TYPE`; computes namespaced `downloads_dir = downloads_base / md5` and `cache_dir = cache_base / md5`; loads config and returns a `RepoState` dataclass. Called once at startup and again on every `cd`. The `cd` command validates the path (must be a directory; must contain `repository.ini` in REPL mode), then calls `initialize_repo` and `sync_cache` before continuing the REPL.
- `load_repository_config(repo_root)` reads `repository.ini` and returns a 6-tuple: `(collection_name, partitioning_property, property_order, additional_props_file, ref_collections_file, intro_message)`. `MAIN_COLLECTION` and `PARTITIONING_PROPERTY` are module-level globals (start as `None`) set by `initialize_repo`. `COLLECTIONS` starts as an empty `set[str]` and is populated in `initialize_repo` — first with the main collection, then with each reference collection. All command dispatch and `sync_cache` iterate `COLLECTIONS` at call time.
- `load_additional_properties(repo_root, filename)` returns `tuple[tuple[str, str, bool], ...]` — triples of `(name, validation_type, multiline)`. `initialize_repo` derives `optional_props`, `prop_validation_types`, and `multiline_props: frozenset[str]` from it. `multiline_props` is threaded through `dispatch` and all `cmd_*` functions that touch main-collection text; JTable receives it as `multiline_cols`.
- `mandatory_ref_props` (a `tuple[tuple[str, str, frozenset[str]], ...]` of `(property_name, collection_name, whitelist)` triples) is threaded from `main` → `dispatch` → `cmd_push`. The whitelist for each prop is read from the `"whitelist"` array in its `additional_mandatory_properties.json` entry (`dc.get("whitelist", [])`) at startup. `mandatory_prop_names` (the `frozenset` passed to `_validate_main_collection`) is the set of all `property_name` values from `mandatory_ref_props`, meaning the non-empty check applies to every declared reference prop.
- `field_order` is a `tuple[str, ...]` of all main-collection field names in the display/validation order dictated by `[main_collection] property_order` in `repository.ini`. It is computed once in `initialize_repo` and threaded as a keyword-only argument through `dispatch` and every `cmd_*` function and internal parser/serialiser. When `field_order` is `None` (its default in all internal functions) the `additional_props`-based behaviour is used.
- The "Save & Push" button in editable JTable windows (`get --jtable`, `clear --jtable`) saves the downloads file and immediately runs the equivalent of `push`. In the Python version (`gui.py`) this is a `push_callback` closure threaded from `dispatch` into `JTable`. In the Tauri version, `cmd_get` and `cmd_clear` serialise all necessary repo state into a `PushInfo` struct stored in `TableData::MainText`/`TableData::Ref`; the table subprocess exposes a `save_and_push` Tauri command that reconstructs a minimal `RepoState` from `PushInfo` and calls `cmd_push`. Push output (success/rejection messages) goes to the terminal in both versions.

## JTable GUI (`src/gui.py`)

`JTable` is a tkinter `ttk.Treeview`-based table widget imported directly by `app.py` (no subprocess). Constructor:

```python
JTable(path=None, mode="csv", readonly=False, diff_data=None, title=None,
       multiline_cols=frozenset(), ref_data=None, push_callback=None).run()
```

| Parameter      | Values / meaning |
|----------------|-----------------|
| `path`         | File to display (CSV or 👉👈 `.txt`) |
| `mode`         | `"csv"` — parse as CSV (export); `"main_text"` — parse 👉👈 format (main collection); `"ref"` — parse comma-separated `.txt` as a single-column `"values"` table (reference collections) |
| `readonly`     | `True` suppresses Save & Push/row-edit buttons (`cat --jtable`) |
| `push_callback` | Callable invoked after saving; when set, the save button is labelled "Save & Push" and calls this after writing the file. Passed from `dispatch` in `app.py` for `get --jtable` and `clear --jtable`. |
| `diff_data`    | `{"columns": [...], "deleted": [[...], ...], "added": [[...], ...]}` — activates diff view; `path` not needed |
| `title`        | Window title (defaults to filename or `"diff"`) |
| `multiline_cols` | `frozenset[str]` of column names whose cells open a modal text-editor dialog on double-click instead of an inline entry. Passed from `multiline_props` in `app.py`. |
| `ref_data`     | `{property_name: {entry_name: content}}` — reference collection data used by the search bar for deep search. Built by `build_ref_data(cache_dir, mandatory_ref_props)` in `app.py` and passed to `cmd_cat` for `cat --jtable`. |

**Main-collection editable mode** (`mode="main_text"`, `readonly=False`) features: simple search bar at the top, double-click cell to edit inline (Entry overlay), Save & Push button writes 👉👈 format back to the downloads file and immediately calls `push_callback` (if set), Add Row / Duplicate Row / Delete Row buttons with odd/even re-striping. Cells for columns in `multiline_cols` are displayed collapsed (newlines → spaces); double-clicking one opens a modal text-editor dialog (OK / Cancel) — OK updates the treeview and preserves newlines for the next Save & Push.

**Reference-collection mode** (`mode="ref"`): displays the comma-separated `.txt` file as a single-column table with header `"values"` — one row per value. Readonly (`cat --jtable`): sortable, search bar shown. Editable (`get --jtable`): simple search bar at the top, double-click a cell to edit inline, Save & Push writes back as `val1,val2,...\n` (empty rows are excluded) and immediately calls `push_callback`, Add Row / Delete Row buttons. No Duplicate Row button.

**Diff mode** (`diff_data` provided): read-only, deleted rows shown in red with `−`, added rows in green with `+`. Data columns are sortable. No search bar.

**Edit-mode search bar** — shown in editable mode (`mode="main_text"` or `mode="ref"`, `readonly=False`). Simple case-insensitive substring filter across all cell values; non-matching rows are hidden via `tree.detach()` / `tree.reattach()`, so their item IDs remain alive. `_save()` and `_save_ref()` iterate `self._all_item_ids` (populated at load time and kept in sync by Add/Duplicate/Delete Row) rather than `tree.get_children("")`, so hidden rows are always included in the saved output. Add Row and Duplicate Row call `self._edit_search_var.set("")` first to clear the filter and ensure `tree.index()` positions match `self._all_item_ids` positions. No query-syntax support — plain substring only.

**Readonly/CSV search bar** — shown when `readonly=True` (cat --jtable) or `mode="csv"` (export --jtable). A row-count label sits at the right end of the bar. Powered by a custom query parser (`_parse_query` in `gui.py`) and supports the following syntax (all keywords case-insensitive):

| Query | Behaviour |
|-------|-----------|
| `foo bar` | Plain-text substring search across all columns. For ref columns the search also covers the referenced entry's content (deep search). |
| `where col = 'val'` | Exact match (case-insensitive) on the cell value of `col`. No ref expansion. |
| `where col like 'pat'` | SQL LIKE pattern (`%` = any chars, `_` = one char) on `col`. For ref columns, also searches the referenced entry's content (deep search). |
| `where col.contents like 'pat'` | LIKE pattern applied to the raw content string of the ref entry named in `col` (e.g. `"1234/12/31,2024/01/01"`). Useful for searching dates, phone numbers, etc. stored inside a ref entry. |
| `where 'val' in col` | Membership check: `val` must be one of the comma-separated tokens in the cell value of `col` (case-insensitive). If `val` contains `%` or `_`, each token is tested with LIKE matching instead of exact match. |
| `where 'val' in col.contents` | Same membership check but against the content of the ref entry named in `col`. Supports LIKE patterns in `val` the same way. |
| `[select *] where cond` | Explicit `select *` prefix — identical to omitting it. Filters the treeview. |
| `select count where cond` | Same filter logic, but the treeview is **not** updated — only the count label changes to `count: N / total`. Use this to count matches without losing the current view. |
| `select prop.entry.contents` | Lookup mode: displays the comma-split values of the named ref entry (`ref_data[prop][entry]`) as rows in the treeview. Count label shows `N values — prop.entry`. The first column header changes to `prop.entry` and other headers are cleared; they are restored when leaving lookup mode. |
| `cond1 and cond2` | AND combination. AND binds tighter than OR (standard SQL precedence). |
| `cond1 or cond2` | OR combination. |

Deep search detail: for `like` and plain-text queries, ref-column cells are expanded to `"entry_name ref_content"` before matching. This means searching `2024/01/01` will find rows whose `schedule` entry contains that date, even though the cell itself shows only the entry name. The expansion is pre-computed in `_expand_row` and stored in `self._expanded_rows` at load time. Exact-match (`=`) always checks the original cell value only.

`build_ref_data(cache_dir, mandatory_ref_props)` in `app.py` reads the latest file for each reference collection from the local cache and returns the `ref_data` dict. It is called in `dispatch` only when `cat --jtable` is invoked on the main collection (lazy, not at startup).
