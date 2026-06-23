# naxel — Specifications

## Overview

naxel is a command-line tool for managing structured documents and reference data stored on a NAS or local filesystem. It operates interactively via a REPL, or non-interactively via batch mode (`-c`). Operations include fetching, editing, validating, pushing, comparing, and exporting data. All collection types and names are defined entirely through configuration files.

### Starting the app

Two implementations are available — a Python version (`src/app.py`) and a Rust/Tauri binary (`naxel`). They share the same command set, file formats, and configuration files.

```
python3 src/app.py                    # Python — interactive REPL
python3 src/app.py -c 'cmd1 && cmd2' # Python — batch mode
python3 src/app.py init <dest>        # Python — new-repository wizard
python3 src/app.py update <dest>      # Python — existing-repository update wizard

./naxel                               # Rust/Tauri — interactive REPL
./naxel -c 'cmd1 && cmd2'            # Rust/Tauri — batch mode
./naxel init <dest>                   # Rust/Tauri — new-repository wizard
./naxel update <dest>                 # Rust/Tauri — existing-repository update wizard
```

`init` and `update` are top-level CLI subcommands that run outside the REPL. They are not available inside the REPL or in `-c` batch mode.

In batch mode the `&&`-separated commands are executed sequentially, then the process exits. Batch mode can be combined with shell pipelines:

```
cat foo_main.txt | python3 src/app.py -c 'add systems foo && get systems foo - && push systems foo && diff systems foo'
```

### Prompt

In interactive mode the prompt displays the current repository's directory name:

```
dummy-repo > 
```

When the repository is switched with `cd` the prompt updates automatically.

### Downloads and cache directory layout

Downloads and cache files are namespaced per repository so that switching repositories never mixes files. The subdirectory name (repository ID) is the MD5 hex digest of the repository's absolute path.

```
downloads/
  {repo-id}/
    {collection}/    # files written by get / clear / cat --jtable
    {file}.csv       # export output (not inside a collection subdirectory)
cache/
  {repo-id}/
    {collection}/    # local mirror of the NAS repository
```

---

## Collections

All managed data is organised into **collections**. Collections are entirely defined in configuration files; there are no built-in collections.

| Type | Description | Configured in |
|---|---|---|
| Main collection | Multi-section structured documents (gzip-compressed) | `repository.ini [main_collection]` |
| Reference collections | Comma-separated value lists (plain text) | `reference_collections.json` |

`schedules`, `contacts`, and any other reference collection must be declared in `reference_collections.json` to be used — they are not built in.

---

## Command Reference

### CLI subcommands (run outside the REPL)

| Command | Description |
|---|---|
| `init <destination-directory>` | Bootstrap a new repository via an interactive wizard. Creates the directory if absent. Errors if `repository.ini` already exists. |
| `update <destination-directory>` | Modify an existing repository's config via an interactive wizard. Errors if `repository.ini` does not exist. |

### REPL commands

| Command | Description |
|---|---|
| `cd <path>` | Switch to a different repository; re-reads all config, resets collections, syncs cache for the new repo. |
| `ls <collection>` | List all entry names in the collection. |
| `add <collection> <name>` | Create a new entry with a blank document template. |
| `cat <collection> <name>` | Print the latest version to stdout. |
| `cat <collection> <name> --version=N` | Print a specific version to stdout. |
| `cat <collection> <name> --jtable` | Save to `downloads/` and open in a read-only JTable window. |
| `cat <collection> <name> --version=N --jtable` | Save a specific version to `downloads/` and open read-only JTable. |
| `cat <collection> <name> --json` | Print the latest version as JSON: main collection outputs the raw JSON sections array (pretty-printed); reference collections output a JSON array of values. Mutually exclusive with `--jtable`. |
| `cat <collection> <name> --version=N --json` | Print a specific version as JSON. |
| `get <collection> <name>` | Download the latest version to `downloads/` and open in the editor. |
| `get <collection> <name> --jtable` | Download and open in an editable JTable window. |
| `get <collection> <name> -` | Write stdin to `downloads/` (no editor); intended for `-c` batch mode pipelines. |
| `clear <collection> <name>` | Write a blank document template to `downloads/` and open in the editor. |
| `clear <collection> <name> --jtable` | Write a blank template and open in an editable JTable window. |
| `len <collection> <name>` | Print the count of non-empty records in the latest version. |
| `push <collection> <name>` | Validate the downloaded file and write it as the next version in the repo. |
| `push <collection> <name> --json` | Same, but treat the downloaded `.txt` as JSON and convert to text first (main: JSON sections array → 👉👈 text; ref: JSON string array → comma-separated). |
| `export <collection> <file.csv>` | Sync cache, build a CSV from all entries, save to `downloads/`, open in the editor. |
| `export <collection> <file.csv> --jtable` | Same but open the CSV in a JTable window. |
| `export <collection> <file.json>` | Sync cache, build a JSON file from all entries, save to `downloads/`, open in the editor. |
| `diff <collection> <name>` | Compare the latest and previous versions; print JSON with `"deleted"` and `"added"` arrays. |
| `diff <collection> <name> --jtable` | Same comparison in a colour-coded JTable window (deleted: red, added: green). |
| `appenditems <collection> <name> [-] [--json]` | Open a text editor with a blank record template; save-and-close appends the new records to the existing entry and pushes. If the entry is in its initial all-blank state the blank template is replaced rather than extended. Default input: main collection uses 👉👈 text; reference collection uses comma-separated values. `--json`: main uses JSON array of section objects; ref uses JSON array of strings. `-`: read from stdin instead of opening an editor. |
| `searchitems <collection> <name> [-] [--json]` | Open a filter query editor; save-and-close prints matching records as a JSON array to stdout. Output is always JSON. Default query syntax: backtick mode. `--json`: query is a JSON object. `-`: read query from stdin. |
| `removeitems <collection> <name> [-] [--json]` | Same query editor; save-and-close removes matching records, pushes, and prints "removed N items". An empty query (no conditions) is rejected to prevent accidental wipeout. Same `--json` and `-` semantics. |
| `fullcopy <dest-dir>` | Copy the entire repository (all versions) into `<dest-dir>/<repo-name>/`. |
| `fullcopy <dest-dir> --json` | Snapshot the repository (latest versions only) as a single JSON file at `<dest-dir>/<repo-name>.json`. |
| `mkrepo <json-file> <dest-dir>` | Reconstruct a repository from a `fullcopy --json` file into `<dest-dir>/<stem>/`. |
| `partialcopy <collection> <name> <dest-dir>` | Copy the repo (all versions) into `<dest-dir>/<repo-name>/`, blanking all entries except `<collection> <name>`. |
| `partialcopy <collection> <name> <dest-dir> --json` | Same as a JSON snapshot, but only `<collection> <name>` carries real data. |
| `exit` | Quit the tool. |

`--jtable` is not supported for `.json` exports.

---

## init Wizard

Running `init <destination-directory>` launches an interactive wizard. The destination directory is created if absent.

Wizard questions in order:

1. **Main collection name** (default: `systems`)
2. **Partitioning property name** (default: `system`) — the first CSV/JSON column header (entry-name column)
3. **Column definitions** (repeating) — enter `n` to finish
   - Column name
   - Is it a reference to another collection? (`y` / `n`)
     - **Reference:** reference collection name, content type (`string` / `date` / `phone_number` / `email` / `year`), whitelist values (comma-separated, optional)
     - **Non-reference:** is it a multiline field, validation type (`none` / `not_empty` / `hh:mm` / `mm/dd` / `int` / `yyyy` / `re:<pattern>`)
4. **Column display order** — asked only when there are two or more columns. Enter numbers in the desired order (Enter keeps the current order).
5. **Introduction message** (default: main collection name) — displayed at startup and after `cd`.

Files and directories created on completion:

| File / Directory | Contents |
|---|---|
| `repository.ini` | `collection_name`, `partitioning_property`, `property_order` (if reordered), `[introduction] message` |
| `additional_properties.json` | Definitions for non-reference columns |
| `reference_collections.json` | Definitions for reference collections |
| `<main-collection>/` | Data directory for the main collection |
| `<ref-collection>/` | Data directory for each reference collection |

---

## update Wizard

Running `update <destination-directory>` displays the current configuration then launches an interactive wizard. Errors if `repository.ini` does not exist.

The wizard has three sections:

**1. Add columns** (same flow as `init`)

- Enter `n` to skip; otherwise: column name → reference or not → details as above.

**2. Change the introduction message**

- Shows the current value and asks whether to change it. If yes, enter a new message (default: current value).

**3. Change column validation types**

- For each existing non-reference column, shows the current validation type and asks whether to change it. Enter the new type (`none` to remove validation).

Write-back behaviour on completion:

| File | Behaviour |
|---|---|
| `repository.ini` | Preserves `collection_name` and `partitioning_property`. Appends new columns to existing `property_order`. Updates `[introduction] message`. |
| `additional_properties.json` | Preserves existing column definitions, appends new columns, reflects validation-type changes. |
| `reference_collections.json` | Preserves existing definitions, appends new reference columns. |
| New reference collection directories | Created for each added reference collection. |

---

## Versioning

Each entry is versioned.

- `add` creates a file at version `0000`.
- `push` reads the latest version in the repo and writes a new file at `version + 1`. Old versions are never deleted.
- `ls`, `cat`, `get`, `push`, and all other commands target the **latest version** (highest version number in the directory).

---

## Typical Edit Flow (main collection)

```
get <main-collection> <name>        # download latest version and open in editor
  (edit and save the file)
push <main-collection> <name>       # validate and push as next version
```

With `--jtable`, edit in a GUI table and use Save & Push to save and push in one step:

```
get <main-collection> <name> --jtable
  (double-click cells to edit, then click Save & Push)
```

For bulk-importing new entries via a pipeline, use `-c` batch mode with `get … -`:

```
cat file.txt | python3 src/app.py -c 'add systems foo && get systems foo - && push systems foo'
```

`get … -` writes stdin directly to the downloads file without opening an editor.

---

## Document Formats

### Main collection — 👉👈 text format

`get`, `cat`, and `clear` output this separator format. `push` accepts it and converts to JSON before writing to the repo.

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
```

There are no hardcoded core fields. Every field — including `notes`, `machine`, `time`, `id`, `schedule`, and `contact` — is an additional property declared in `additional_properties.json` or `reference_collections.json`. Field display order is controlled by `[main_collection] property_order` in `repository.ini`.

#### Validation rules enforced on `push`

| Field type | Rule |
|---|---|
| Optional additional property | Label must be present. Value is checked according to `validation_type`: `NONE` — any value (including empty); `NOT_EMPTY` — rejects empty; `HH:MM` — must match `\d{2}:\d{2}`; `MM/DD` — must match `\d{2}/\d{2}`; `INT` — must match `[0-9]+`; `YYYY` — must match `\d{4}`; `RE:<pattern>` — must fully match the regex. Multiline fields (`multiline: true`) consume all lines until the next label or separator. |
| Mandatory reference property | Label must be present, value must be non-empty, and the value must exist as an entry in the corresponding reference collection (or appear in its `whitelist`). |

**Exception:** if every section in the document has all fields blank (initial state written by `add`/`clear`), or if the file content is empty/whitespace, the push is accepted without validation and the empty template is written to the repo.

### Reference collections — plain text format

Comma-separated values on a single line (optional trailing newline):

```
2024/01/01,2024/06/15,2025/03/20
```

Content validation on `push` is determined by `type` in `reference_collections.json`:
- `"DATE"`: each value must match `yyyy/mm/dd`
- `"PHONE_NUMBER"`: each value must match `[0-9\-\+]+`
- `"EMAIL"`: each value must match `user@domain.tld`
- `"YEAR"`: each value must match `\d{4}`
- `"STRING"` or absent: no validation

---

## CSV Export Format

### Main collection

```csv
system, notes, machine, time, id, schedule, contact, prop1, prop2
sys1, note content, m1, 09:00, id1, sche1, cont1, val1, val2
sys1, , m2, 12:30, id2, sche2, cont2, ,
```

- One row per section.
- The first column header is `partitioning_property` from `repository.ini`.
- Remaining column headers are the field names as declared (no renaming).
- `multiline: true` fields are joined with a space.
- Documents where every field in every section is blank are excluded.
- Column order follows `property_order` in `repository.ini`.
- Values containing `,`, `"`, or newlines are quoted per RFC 4180.

### Reference collections

```csv
name, values
sche1, 2024/01/01 2024/06/15 2025/03/20
```

All non-main collections use the `name, values` header. Comma-separated values from the file are converted to space-separated in the CSV. Empty entries are excluded.

---

## JSON Export Format

Triggered when the filename passed to `export` ends with `.json`. Opens in the editor (`--jtable` is not supported).

### Main collection

```json
[
  {"system": "sys1", "notes": "note content", "machine": "m1", "time": "09:00", "id": "id1", "schedule": "sche1", "contact": "cont1"},
  {"system": "sys1", "notes": "", "machine": "m2", "time": "12:30", "id": "id2", "schedule": "sche2", "contact": "cont2"}
]
```

- One object per section.
- The first key is the `partitioning_property` value.
- Remaining keys follow `field_order`.
- `multiline: true` fields keep their `\n` characters (unlike CSV, which joins with a space).
- Documents where every field in every section is blank are excluded.

### Reference collections

```json
[
  {"name": "sche1", "values": ["2024/01/01", "2024/06/15", "2025/03/20"]},
  {"name": "sche2", "values": ["2024/03/01"]}
]
```

Comma-separated values from the file are split into a JSON array. Empty entries are excluded.

---

## fullcopy / mkrepo

### `fullcopy <destination-directory>`

Copies the entire repository tree (all versions of every file plus all config files) into `<destination-directory>/<repo-name>/` via `shutil.copytree`. Errors if the destination does not exist or `<destination-directory>/<repo-name>` already exists.

### `fullcopy <destination-directory> --json`

Creates `<destination-directory>/<repo-name>.json`. Only the latest version of each entry is included; history is omitted.

Output JSON structure:

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

Errors if the destination does not exist or `<repo-name>.json` already exists.

### `mkrepo <json-file> <destination-directory>`

Reconstructs a repository from a `fullcopy --json` file into `<destination-directory>/<stem>/` (stem = filename without `.json`):

1. Parses `config.repository_ini` to determine the main collection name.
2. Writes `repository.ini`, `additional_properties.json`, and `reference_collections.json`.
3. For each collection in `data`, creates the collection directory and writes each entry at version `0000`: main collection as gzip-compressed JSON (`.txt.gz`), reference collections as plain text (`.txt`).

Errors if the JSON file does not exist, the destination is not a directory, the JSON is not a valid fullcopy payload (missing `config` or `data` keys), or `<dest>/<stem>` already exists.

---

## partialcopy

### `partialcopy <collection> <name> <destination-directory>`

Copies the entire repository (all versions) into `<destination-directory>/<repo-name>/`, but blanks all entries except `<collection> <name>`:

- The specified entry's files (all versions) are copied as-is.
- Other main-collection `.txt.gz` files are replaced with `gzip.compress(b"[]")` (treated as empty by `export`).
- Other reference-collection `.txt` files are created empty.
- Config files in the repo root (`repository.ini`, etc.) are copied as-is.

Errors if the destination does not exist or the target directory already exists.

### `partialcopy <collection> <name> <destination-directory> --json`

Creates `<destination-directory>/<repo-name>.json` with the same `config`/`data` structure as `fullcopy --json`, but only `<collection> <name>` carries real data:

- The specified entry holds the latest-version real data.
- All other main-collection entries are `[]` (empty array).
- All other reference-collection entries are `""` (empty string).

Errors if the destination does not exist or the output file already exists.

---

## appenditems / searchitems / removeitems

These commands operate on individual records within an entry without requiring a full `get` → edit → `push` cycle.

### appenditems

Opens a text editor pre-filled with a blank record template. After saving and closing, the new records are appended to the existing entry and pushed automatically.

- If the entry is in its initial all-blank state (`add`/`clear` just ran) the blank template is replaced rather than extended.
- `--json`: changes the input format — main collection expects a JSON array of section objects; reference collection expects a JSON array of strings.
- `-`: reads content from stdin instead of opening an editor (for `-c` pipelines).

### searchitems / removeitems

Opens a filter query editor. After saving and closing, the query is applied to the records.

- `searchitems`: prints matching records as a JSON array to stdout (output is always JSON).
- `removeitems`: deletes matching records, pushes, and prints "removed N items". An empty query (no conditions) is rejected to prevent accidental wipeout.

### Filter query syntax — default (backtick mode)

```
`column`='exact value'
`column` like 'prefix%'
`column`='val1' and `column2` like 'pat%'
`column`='val1' or `column2`='val2'
```

| Operator | Behaviour |
|---|---|
| `=` | Exact match (case-insensitive) |
| `like` | SQL LIKE pattern: `%` = any chars, `_` = one char |
| `and` | AND (binds tighter than OR) |
| `or` | OR |

An empty query (no conditions) matches everything in `searchitems`. In `removeitems` an empty query is an error.

### Filter query syntax — `--json` (JSON object mode)

```json
{"column1": "exact value", "column2": "prefix%"}
```

- All key-value pairs are ANDed.
- Values containing `%` or `_` are treated as LIKE patterns automatically.
- An empty object `{}` matches everything (`removeitems` treats this as a full-wipe and proceeds — unlike the backtick empty query, it is not rejected).

### Querying reference collections

Use `values` as the column name:

```
`values`='2024/01/01'
`values` like '2024%'
```

### Batch-mode examples

```sh
# Append a new record from stdin
cat new-section.txt | python3 src/app.py -c 'appenditems systems web-01 -'

# Search with a JSON query
echo '{"status": "active"}' | python3 src/app.py -c 'searchitems systems web-01 - --json'

# Remove records matching a backtick query
echo '`status`='"'"'deprecated'"'"'' | python3 src/app.py -c 'removeitems systems web-01 -'
```

---

## Configuration Files

### settings.ini

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[repository]` | `root` | `dummy-repo` | Path to the repository (NAS) root |
| `[editor]` | `command` | `mousepad` | Editor opened by `get` / `clear` / `export` |

### repository.ini

Located at `{repo_root}/repository.ini`.

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[main_collection]` | `collection_name` | `systems` | Name of the main (gzip-compressed, multi-section) collection |
| `[main_collection]` | `partitioning_property` | `system` | First CSV/JSON column header (entry-name column) |
| `[main_collection]` | `property_order` | *(empty)* | Comma-separated field names that appear first; others follow in default order |
| `[introduction]` | `message` | *(empty)* | Message displayed at startup and after `cd` |

#### Example

```ini
# settings.ini
[repository]
root = /mnt/nas/repo

[editor]
command = gedit
```

```ini
# repository.ini (at the repository root)
[main_collection]
collection_name = systems
partitioning_property = system
property_order = team,notes,id
```

---

## Additional Properties Configuration

### Optional properties — `additional_properties.json`

A JSON array of objects defining optional fields appended to every main-collection section:

```json
[
  {"property_name": "notes", "validation_type": "NONE", "multiline": true},
  {"property_name": "id",    "validation_type": "RE:[^#]+"},
  {"property_name": "prop1", "validation_type": "NONE"},
  {"property_name": "prop2", "validation_type": "NOT_EMPTY"},
  {"property_name": "prop3", "validation_type": "HH:MM"}
]
```

| Field | Meaning |
|---|---|
| `property_name` | Field name |
| `validation_type` | Validation on `push`: `"NONE"` — any value (including empty); `"NOT_EMPTY"` — rejects empty; `"HH:MM"` — rejects values not matching `\d{2}:\d{2}`; `"MM/DD"` — rejects values not matching `\d{2}/\d{2}`; `"INT"` — rejects values not matching `[0-9]+`; `"YYYY"` — rejects values not matching `\d{4}`; `"RE:<pattern>"` — rejects values that don't fully match the regex (via `re.fullmatch`). Defaults to `"NONE"` if omitted. |
| `multiline` | `true` — value spans multiple lines until the next label; stored with `"\n"` in JSON, joined with `" "` in CSV export. In JTable editable mode, double-clicking opens a modal text-editor dialog instead of inline editing. `false` or absent — single-line field. |

Non-object entries in the array are silently ignored. If the file is absent, no additional properties are loaded.

### Mandatory properties and dynamic collections — `reference_collections.json`

A JSON array of objects, each defining a reference collection:

```json
[
  {"collection_name": "teams",     "property_name": "team",     "type": "STRING",         "whitelist": []},
  {"collection_name": "schedules", "property_name": "schedule", "type": "DATE",           "whitelist": ["everyday", "weekends"]},
  {"collection_name": "contacts",  "property_name": "contact",  "type": "PHONE_NUMBER",   "whitelist": ["none"]}
]
```

| Field | Meaning |
|---|---|
| `collection_name` | Directory name in the repo; also the collection name used in commands |
| `property_name` | Main-collection field that references this collection; validated on `push` |
| `type` | Content validation on `push`: `"DATE"` — comma-separated `yyyy/mm/dd`; `"PHONE_NUMBER"` — comma-separated `[0-9\-\+]+`; `"EMAIL"` — comma-separated `user@domain.tld`; `"YEAR"` — comma-separated `\d{4}`; `"STRING"` or absent — no validation |
| `whitelist` | Values accepted without checking the collection. Omit or use `[]` for no whitelist. |

- All defined collections become available at startup.
- All `property_name` values become mandatory fields in the main-collection document.
- On `push`, each `property_name` value must be non-empty and must exist as an entry in the corresponding `collection_name` collection, or appear in `whitelist`.

If the file is absent, no reference collections are loaded.

---

## JTable GUI

`--jtable` commands open a table-view window instead of a text editor.

### `cat --jtable` — read-only

- View content in a table.
- Click column headers to sort.
- No editing or saving.
- A **search bar** is shown at the top (see Read-only search bar below).

### `export --jtable` — CSV view (read-only)

- View the exported CSV as a table.
- No editing or saving.
- A **search bar** is shown at the top.

### `get <main-collection> <name> --jtable` — editable (main collection)

- Double-click a cell to edit it inline.
- For columns with `multiline: true` (e.g. `notes`), double-clicking opens a modal text-editor dialog.
- **Save & Push** writes the 👉👈 format back to the downloads file and immediately pushes.
- **Add Row** inserts an empty row after the selection (or at the end).
- **Duplicate Row** copies the selected row.
- **Delete Row** removes the selected row.
- A **search bar** is shown at the top (see Edit-mode search bar below).

### `get <ref-collection> <name> --jtable` — editable (reference collection)

- Displays the comma-separated `.txt` file as a single-column table with header `"values"`.
- Double-click a cell to edit inline.
- **Save & Push** writes back as `val1,val2,...\n` (empty rows excluded) and pushes.
- **Add Row** / **Delete Row** available. No Duplicate Row.
- A **search bar** is shown at the top.

### `clear --jtable` — editable (blank template)

Same as `get --jtable` but starts from a blank template. Full edit and Save & Push functionality is available for both main and reference collections.

### `diff --jtable` — diff view (read-only)

Deleted rows shown in red with `−`, added rows in green with `+`. Columns are sortable. No search bar.

---

### Edit-mode search bar

Shown in editable mode (`get --jtable` / `clear --jtable`). Case-insensitive substring filter across all cell values; non-matching rows are hidden (not deleted). A hit count is shown at the right (`N / total rows`).

- Filtering affects **display only** — hidden rows are still saved when Save & Push is clicked.
- **Add Row** / **Duplicate Row** clear the search filter first to ensure correct row positioning.
- **Delete Row** permanently deletes the currently selected (visible) row; hidden rows are unaffected.

---

### Read-only search bar

Shown in read-only mode (`cat --jtable`, `export --jtable`). Supports a rich query syntax; the table updates in real time.

#### Query syntax

All keywords are case-insensitive.

| Query | Behaviour |
|---|---|
| `foo bar` | Substring search across all columns. For reference-collection columns the search also covers the referenced entry's content (deep search). |
| `where col = 'val'` | Exact match (case-insensitive) on `col`. No deep search. |
| `where col like 'pat%'` | SQL LIKE pattern on `col` (`%` = any chars, `_` = one char). Deep search for reference columns. |
| `where col.contents like 'pat'` | LIKE pattern applied to the raw content string of the ref entry named in `col` (e.g. `"2024/01/01,2025/06/15"`). |
| `where 'val' in col` | Membership check: `val` must be one of the comma-separated tokens in `col`. If `val` contains `%` or `_`, LIKE matching is used per token. |
| `where 'val' in col.contents` | Membership check against the content of the ref entry named in `col`. Supports LIKE patterns in `val`. |
| `[select *] where cond` | `select *` prefix is optional — identical to omitting it. |
| `select count where cond` | Count matches without updating the table view; only the count label changes to `count: N / total`. |
| `select prop.entry.contents` | Lookup mode: displays the comma-split values of `ref_data[prop][entry]` as rows. Count label shows `N values — prop.entry`. The first column header changes to `prop.entry`. |
| `cond1 and cond2` | AND (binds tighter than OR). |
| `cond1 or cond2` | OR. |

#### Deep search (reference-collection columns)

For `like` and plain-text queries, reference-column cells are expanded to `"entry_name ref_content"` before matching. For example, searching `2024/01/01` will match rows whose `schedule` entry contains that date, even though the cell displays only the entry name. Exact-match (`=`) always checks the original cell value only.

#### Query examples

```
where schedule like '%2024%'
  → rows whose schedule entry content contains "2024"

where schedule.contents like '%/01%'
  → rows whose schedule entry content string contains "/01"

where '2024/01/01' in schedule.contents
  → rows whose schedule entry contains "2024/01/01" as one of the comma-separated values

where '2044%' in schedule.contents
  → same but with LIKE matching — tokens starting with "2044"

select schedule.everyday.contents
  → lookup mode: shows the values of the "everyday" schedule entry

select count where team = 'alpha' and notes like '%urgent%'
  → counts rows matching both conditions without changing the view

where team = 'alpha' or team = 'beta'
  → rows where team is "alpha" or "beta"
```
