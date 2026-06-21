import csv
import json
import re
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

_SEP = "🏔" * 20


def _is_label(line: str) -> bool:
    return line.startswith("👉") and line.endswith("👈") and line != _SEP


def _parse_sections(text: str, multiline_cols: frozenset[str] = frozenset()) -> list[dict]:
    """Parse 👉👈 text into a list of ordered dicts."""
    lines = text.splitlines()
    n, i, sections = len(lines), 0, []
    while i < n:
        if lines[i] != _SEP:
            i += 1
            continue
        i += 1
        section: dict[str, str] = {}
        while i < n and lines[i] != _SEP:
            line = lines[i]
            if _is_label(line):
                key = line[1:-1]
                i += 1
                if key in multiline_cols:
                    ml_lines: list[str] = []
                    while i < n and lines[i] != _SEP and not _is_label(lines[i]):
                        ml_lines.append(lines[i])
                        i += 1
                    section[key] = "\n".join(ml_lines)
                else:
                    section[key] = lines[i] if i < n else ""
                    if i < n:
                        i += 1
            else:
                i += 1
        if section:
            sections.append(section)
    return sections


def _sections_to_text(sections: list[dict]) -> str:
    """Serialize ordered dicts back to 👉👈 format."""
    parts: list[str] = []
    for sec in sections:
        parts.append(_SEP)
        for key, val in sec.items():
            parts.append(f"👉{key}👈")
            parts.append(val)
    return "\n".join(parts) + "\n"


def _like_to_regex(pattern: str) -> re.Pattern:
    parts = re.split(r"(%|_)", pattern)
    return re.compile(
        "^" + "".join(
            ".*" if p == "%" else "." if p == "_" else re.escape(p)
            for p in parts
        ) + "$",
        re.IGNORECASE | re.DOTALL,
    )


def _tokenize_where(clause: str) -> list:
    tokens: list = []
    i, n = 0, len(clause)
    while i < n:
        while i < n and clause[i].isspace():
            i += 1
        if i >= n:
            break
        rest = clause[i:]
        m_kw = re.match(r"(and|or)(?=\s|$)", rest, re.IGNORECASE)
        if m_kw:
            tokens.append((m_kw.group(1).upper(),))
            i += m_kw.end()
            continue
        # 'val' in col[.contents] — membership check in comma-separated cell or ref content
        m_in = re.match(
            r"(?:'([^']*)'|\"([^\"]*)\")\s+in\s+(\w+)(?:\.(contents))?(?=\s|$)",
            rest, re.IGNORECASE,
        )
        if m_in:
            value = m_in.group(1) if m_in.group(1) is not None else m_in.group(2)
            is_contents = m_in.group(4) is not None
            tokens.append(("COND", m_in.group(3), "in", value, is_contents))
            i += m_in.end()
            continue
        # col[.contents] op 'val' — .contents means search the ref entry's content string
        m = re.match(
            r"(\w+)(?:\.(contents))?\s*(=|like)\s*(?:'([^']*)'|\"([^\"]*)\")",
            rest, re.IGNORECASE,
        )
        if m:
            value = m.group(4) if m.group(4) is not None else m.group(5)
            is_contents = m.group(2) is not None
            tokens.append(("COND", m.group(1), m.group(3).lower(), value, is_contents))
            i += m.end()
        else:
            i += 1
    return tokens


def _parse_or_expr(tokens: list, columns: list[str], pos: int,
                   ref_data: dict | None = None) -> tuple:
    fn, pos = _parse_and_expr(tokens, columns, pos, ref_data)
    while pos < len(tokens) and tokens[pos][0] == "OR":
        pos += 1
        rf, pos = _parse_and_expr(tokens, columns, pos, ref_data)
        lf = fn
        fn = lambda orig, exp, l=lf, r=rf: l(orig, exp) or r(orig, exp)
    return fn, pos


def _parse_and_expr(tokens: list, columns: list[str], pos: int,
                    ref_data: dict | None = None) -> tuple:
    fn, pos = _parse_factor(tokens, columns, pos, ref_data)
    while pos < len(tokens) and tokens[pos][0] == "AND":
        pos += 1
        rf, pos = _parse_factor(tokens, columns, pos, ref_data)
        lf = fn
        fn = lambda orig, exp, l=lf, r=rf: l(orig, exp) and r(orig, exp)
    return fn, pos


def _parse_factor(tokens: list, columns: list[str], pos: int,
                  ref_data: dict | None = None) -> tuple:
    if pos >= len(tokens) or tokens[pos][0] != "COND":
        return (lambda orig, exp: False), pos
    _, col_name, op, value, is_contents = tokens[pos]
    pos += 1
    col_idx = next((i for i, c in enumerate(columns) if c.lower() == col_name.lower()), None)
    if col_idx is None:
        return (lambda orig, exp: False), pos

    if is_contents:
        # Match against the ref entry's raw content string (e.g. "1234/12/31,2024/01/01")
        rd = ref_data or {}
        if op == "=":
            def fn(orig, exp, idx=col_idx, val=value, col=col_name, r=rd):
                content = r.get(col, {}).get(orig[idx] if idx < len(orig) else "", "")
                return content.lower() == val.lower()
        elif op == "in":
            if "%" in value or "_" in value:
                pat = _like_to_regex(value)
                def fn(orig, exp, idx=col_idx, p=pat, col=col_name, r=rd):
                    content = r.get(col, {}).get(orig[idx] if idx < len(orig) else "", "")
                    return any(p.match(t.strip()) for t in content.split(",") if t.strip())
            else:
                def fn(orig, exp, idx=col_idx, val=value, col=col_name, r=rd):
                    content = r.get(col, {}).get(orig[idx] if idx < len(orig) else "", "")
                    parts = [p.strip().lower() for p in content.split(",") if p.strip()]
                    return val.lower() in parts
        else:  # like
            pat = _like_to_regex(value)
            def fn(orig, exp, idx=col_idx, p=pat, col=col_name, r=rd):
                content = r.get(col, {}).get(orig[idx] if idx < len(orig) else "", "")
                return bool(p.match(content))
        return fn, pos

    if op == "=":
        def fn(orig, exp, idx=col_idx, val=value):
            return idx < len(orig) and orig[idx].lower() == val.lower()
    elif op == "in":
        if "%" in value or "_" in value:
            pat = _like_to_regex(value)
            def fn(orig, exp, idx=col_idx, p=pat):
                cell = orig[idx] if idx < len(orig) else ""
                return any(p.match(t.strip()) for t in cell.split(",") if t.strip())
        else:
            def fn(orig, exp, idx=col_idx, val=value):
                cell = orig[idx] if idx < len(orig) else ""
                parts = [p.strip().lower() for p in cell.split(",") if p.strip()]
                return val.lower() in parts
    else:  # like — match against expanded row for deep ref search
        pat = _like_to_regex(value)
        def fn(orig, exp, idx=col_idx, p=pat):
            return idx < len(exp) and bool(p.match(exp[idx]))
    return fn, pos


_QUERY_PREFIX_RE = re.compile(r"^(?:select\s+(\*|count)\s+)?where\s+", re.IGNORECASE)
_LOOKUP_RE = re.compile(r"^select\s+(\w+)\.([^\s.]+)\.contents\s*$", re.IGNORECASE)


def _parse_query(query: str, columns: list[str], ref_data: dict | None = None) -> tuple:
    """
    Returns (filter_fn, count_only, lookup).
      filter_fn : (orig_row, exp_row) -> bool   — None when lookup is set
      count_only: show count in label only, do not filter treeview
      lookup    : {"prop": str, "entry": str, "values": list[str]} | None

    Supported syntax (case-insensitive keywords):
      plain text                          — substring match across all expanded columns
      [select *] where col = 'val'        — exact match on cell value (no ref expansion)
      [select *] where col like 'pat'     — SQL LIKE (% / _) on expanded value (deep)
      [select *] where col.contents op    — match the ref entry's raw content string
      [select *] where 'val' in col       — 'val' is a comma-separated token in the cell;
                                            if val contains % or _, uses LIKE matching per token
      [select *] where 'val' in col.contents — same but against the ref entry's content
      ... and/or ...                      — boolean combinations; AND binds tighter than OR
      select count where ...              — count matching rows; treeview unchanged
      select <prop>.<entry>.contents      — display ref entry values in treeview
    """
    q = query.strip()
    if not q:
        return (lambda orig, exp: True), False, None

    m = _LOOKUP_RE.match(q)
    if m:
        prop, entry = m.group(1), m.group(2)
        raw = (ref_data or {}).get(prop, {}).get(entry, "")
        values = [v.strip() for v in raw.split(",") if v.strip()] if raw else []
        return None, False, {"prop": prop, "entry": entry, "values": values}

    mq = _QUERY_PREFIX_RE.match(q)
    if mq:
        count_only = ((mq.group(1) or "*").lower() == "count")
        fn, _ = _parse_or_expr(_tokenize_where(q[mq.end():]), columns, 0, ref_data)
        return fn, count_only, None

    lower_q = q.lower()
    return (lambda orig, exp: any(lower_q in cell.lower() for cell in exp)), False, None


class JTable:
    def __init__(self, path: str | Path | None = None, mode: str = "csv",
                 readonly: bool = False, diff_data: dict | None = None,
                 title: str | None = None, multiline_cols: frozenset = frozenset(),
                 ref_data: dict | None = None):
        """
        mode          : "csv" for CSV files, "main_text" for 👉👈 text files
        readonly      : hide Save button and disable editing (cat --jtable)
        diff_data     : {"columns": [...], "deleted": [[...], ...], "added": [[...], ...]}
                        when provided the table shows a read-only diff view
        multiline_cols: set of column names that open a multiline dialog on double-click
        ref_data      : {property_name: {entry_name: content}} for deep reference search
                        (only used when readonly=True)
        """
        self._path = Path(path) if path else None
        self._mode = mode
        self._readonly = readonly
        self._diff_data = diff_data
        self._multiline_cols = multiline_cols
        self._ref_data: dict[str, dict[str, str]] = ref_data or {}
        self._columns: list[str] = []
        self._original: dict[str, dict] = {}   # item_id → original section dict
        self._all_rows: list[tuple] = []        # every data row (original display values)
        self._expanded_rows: list[tuple] = []   # ref columns expanded with content for deep search
        self._all_item_ids: list[str] = []      # ordered item ids for all rows (edit mode)
        self._search_var: tk.StringVar | None = None
        self._edit_search_var: tk.StringVar | None = None
        self._count_label: tk.Label | None = None
        self._original_headings: list[str] | None = None  # saved when in lookup mode

        self._root = tk.Tk()
        self._root.title(title or (self._path.name if self._path else "diff"))
        self._root.geometry("960x540")
        self._build()

    def _build(self):
        if self._mode in ("main_text", "ref") and not self._readonly:
            btn_frame = tk.Frame(self._root)
            btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
            save_cmd = self._save if self._mode == "main_text" else self._save_ref
            tk.Button(btn_frame, text="Save", command=save_cmd).pack(side=tk.RIGHT)
            tk.Button(btn_frame, text="Delete Row", command=self._delete_row).pack(side=tk.LEFT, padx=(0, 2))
            if self._mode == "main_text":
                tk.Button(btn_frame, text="Duplicate Row", command=self._duplicate_row).pack(side=tk.LEFT, padx=(0, 2))
            tk.Button(btn_frame, text="Add Row", command=self._add_row).pack(side=tk.LEFT)

        if self._diff_data is None and (self._readonly or self._mode == "csv"):
            search_frame = tk.Frame(self._root)
            search_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
            tk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
            self._search_var = tk.StringVar()
            self._search_var.trace_add("write", self._on_search_changed)
            ttk.Entry(search_frame, textvariable=self._search_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
            self._count_label = tk.Label(search_frame, text="", anchor="e", width=18)
            self._count_label.pack(side=tk.RIGHT, padx=(4, 0))
        elif self._diff_data is None and self._mode in ("main_text", "ref") and not self._readonly:
            search_frame = tk.Frame(self._root)
            search_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
            tk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
            self._edit_search_var = tk.StringVar()
            self._edit_search_var.trace_add("write", self._on_edit_search_changed)
            ttk.Entry(search_frame, textvariable=self._edit_search_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
            self._count_label = tk.Label(search_frame, text="", anchor="e", width=18)
            self._count_label.pack(side=tk.RIGHT, padx=(4, 0))

        frame = tk.Frame(self._root)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        vsb = ttk.Scrollbar(frame, orient="vertical")
        hsb = ttk.Scrollbar(frame, orient="horizontal")
        self._tree = ttk.Treeview(
            frame,
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="browse",
        )
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._tree.tag_configure("odd", background="#f5f5f5")

        self._tree.bind("<Button-3>", self._on_right_click)
        if self._mode in ("main_text", "ref") and not self._readonly:
            self._tree.bind("<Double-1>", self._on_double_click)

        if self._diff_data is not None:
            self._load_diff()
        elif self._mode == "main_text":
            self._load_systems()
        elif self._mode == "ref":
            self._load_ref()
        else:
            self._load_csv()

    def _load_diff(self):
        data_cols = self._diff_data["columns"]
        all_cols = ["_diff"] + list(data_cols)
        self._columns = all_cols
        self._tree["columns"] = all_cols
        self._tree["show"] = "headings"

        self._tree.heading("_diff", text="")
        self._tree.column("_diff", width=28, minwidth=28, anchor="center", stretch=False)
        for col in data_cols:
            self._tree.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._sort(c, False))
            self._tree.column(col, width=140, minwidth=50, anchor="w", stretch=True)

        self._tree.tag_configure("deleted", background="#ffdddd", foreground="#990000")
        self._tree.tag_configure("added",   background="#ddffdd", foreground="#006600")

        for row in self._diff_data["deleted"]:
            self._tree.insert("", tk.END, values=["-"] + list(row), tags=("deleted",))
        for row in self._diff_data["added"]:
            self._tree.insert("", tk.END, values=["+"] + list(row), tags=("added",))

    def _load_csv(self):
        with self._path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f, skipinitialspace=True))
        if not rows:
            return
        headers = [h.strip() for h in rows[0]]
        self._columns = headers
        self._tree["columns"] = headers
        self._tree["show"] = "headings"
        for col in headers:
            self._tree.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._sort(c, False))
            self._tree.column(col, width=140, minwidth=50, anchor="w", stretch=True)
        data_rows: list[tuple] = []
        for i, row in enumerate(rows[1:]):
            values = [v.strip() for v in row]
            tag = "odd" if i % 2 else ""
            self._tree.insert("", tk.END, values=values, tags=(tag,))
            data_rows.append(tuple(values))
        if self._search_var is not None:
            self._finish_load(data_rows)

    def _load_systems(self):
        sections = _parse_sections(self._path.read_text(encoding="utf-8"), self._multiline_cols)
        if not sections:
            return
        self._columns = list(sections[0].keys())
        self._tree["columns"] = self._columns
        self._tree["show"] = "headings"
        for col in self._columns:
            self._tree.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._sort(c, False))
            self._tree.column(col, width=140, minwidth=50, anchor="w", stretch=True)
        data_rows: list[tuple] = []
        for i, sec in enumerate(sections):
            display = [v.replace("\n", " ") for v in sec.values()]
            tag = "odd" if i % 2 else ""
            iid = self._tree.insert("", tk.END, values=display, tags=(tag,))
            self._original[iid] = sec
            data_rows.append(tuple(display))
            self._all_item_ids.append(iid)
        if self._search_var is not None:
            self._finish_load(data_rows)
        elif self._count_label is not None:
            self._count_label.config(text=f"{len(self._all_item_ids)} rows")

    def _load_ref(self):
        content = self._path.read_text(encoding="utf-8").strip()
        values = [v.strip() for v in content.split(",") if v.strip()] if content else []
        self._columns = ["values"]
        self._tree["columns"] = ["values"]
        self._tree["show"] = "headings"
        self._tree.heading("values", text="values", anchor="w",
                           command=lambda: self._sort("values", False))
        self._tree.column("values", width=280, minwidth=80, anchor="w", stretch=True)
        data_rows: list[tuple] = []
        for i, val in enumerate(values):
            tag = "odd" if i % 2 else ""
            iid = self._tree.insert("", tk.END, values=[val], tags=(tag,))
            self._original[iid] = {"values": val}
            data_rows.append((val,))
            self._all_item_ids.append(iid)
        if self._search_var is not None:
            self._finish_load(data_rows)
        elif self._count_label is not None:
            self._count_label.config(text=f"{len(self._all_item_ids)} rows")

    def _save_ref(self):
        items = self._all_item_ids or list(self._tree.get_children(""))
        values = [str(self._tree.item(item)["values"][0])
                  for item in items
                  if self._tree.item(item)["values"]]
        values = [v for v in values if v]
        self._path.write_text(",".join(values) + "\n" if values else "", encoding="utf-8")
        print(f"saved: {self._path}", flush=True)

    def _finish_load(self, data_rows: list[tuple]):
        self._all_rows = data_rows
        if self._ref_data:
            self._expanded_rows = [self._expand_row(r) for r in data_rows]
        else:
            self._expanded_rows = data_rows
        if self._count_label is not None:
            self._count_label.config(text=f"{len(data_rows)} rows")

    def _expand_row(self, row: tuple) -> tuple:
        expanded = []
        for i, col in enumerate(self._columns):
            val = row[i] if i < len(row) else ""
            ref_content = self._ref_data.get(col, {}).get(val, "") if self._ref_data else ""
            expanded.append(f"{val} {ref_content}" if ref_content else val)
        return tuple(expanded)

    def _on_search_changed(self, *_):
        q = self._search_var.get() if self._search_var else ""
        filter_fn, count_only, lookup = _parse_query(q, self._columns, self._ref_data)

        if lookup is not None:
            if self._original_headings is None and self._columns:
                self._original_headings = [
                    self._tree.heading(col)["text"] for col in self._columns
                ]
            if self._columns:
                self._tree.heading(self._columns[0],
                                   text=f"{lookup['prop']}.{lookup['entry']}")
                for col in self._columns[1:]:
                    self._tree.heading(col, text="")
            values = lookup["values"]
            n = len(values)
            if self._count_label is not None:
                label = f"{n} value{'s' if n != 1 else ''} — {lookup['prop']}.{lookup['entry']}"
                self._count_label.config(text=label)
            self._tree.delete(*self._tree.get_children(""))
            pad = [""] * (len(self._columns) - 1)
            for rank, val in enumerate(values):
                tag = "odd" if rank % 2 else ""
                self._tree.insert("", tk.END, values=[val] + pad, tags=(tag,))
            return

        if self._original_headings is not None:
            for col, text in zip(self._columns, self._original_headings):
                self._tree.heading(col, text=text)
            self._original_headings = None

        matched = [
            i for i, (orig, exp) in enumerate(zip(self._all_rows, self._expanded_rows))
            if filter_fn(orig, exp)
        ]

        total = len(self._all_rows)
        n = len(matched)
        if self._count_label is not None:
            if count_only:
                self._count_label.config(text=f"count: {n} / {total}")
            elif n == total:
                self._count_label.config(text=f"{total} rows")
            else:
                self._count_label.config(text=f"{n} / {total} rows")

        if not count_only:
            self._tree.delete(*self._tree.get_children(""))
            for rank, idx in enumerate(matched):
                tag = "odd" if rank % 2 else ""
                self._tree.insert("", tk.END, values=list(self._all_rows[idx]), tags=(tag,))

    def _on_edit_search_changed(self, *_):
        q = (self._edit_search_var.get() if self._edit_search_var else "").strip().lower()
        for iid in self._all_item_ids:
            self._tree.detach(iid)
        pos = 0
        for iid in self._all_item_ids:
            vals = self._tree.item(iid)["values"]
            if not q or any(q in str(v).lower() for v in vals):
                self._tree.reattach(iid, "", pos)
                pos += 1
        self._restripe()
        total = len(self._all_item_ids)
        if self._count_label:
            if not q or pos == total:
                self._count_label.config(text=f"{total} rows")
            else:
                self._count_label.config(text=f"{pos} / {total} rows")

    def _on_right_click(self, event):
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        self._tree.selection_set(row_id)
        values = [str(v) for v in self._tree.item(row_id)["values"]]
        menu = tk.Menu(self._root, tearoff=0)
        menu.add_command(
            label="Copy row as TSV",
            command=lambda: self._copy_to_clipboard("\t".join(values)),
        )
        menu.add_command(
            label="Copy row as JSON",
            command=lambda: self._copy_to_clipboard(
                json.dumps(dict(zip(self._columns, values)), ensure_ascii=False, indent=2)
            ),
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_to_clipboard(self, text: str):
        self._root.clipboard_clear()
        self._root.clipboard_append(text)

    def _sort(self, col: str, reverse: bool):
        items = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        items.sort(key=lambda t: t[0], reverse=reverse)
        for i, (_, k) in enumerate(items):
            self._tree.move(k, "", i)
            tag = "odd" if i % 2 else ""
            self._tree.item(k, tags=(tag,))
        self._tree.heading(col, command=lambda: self._sort(col, not reverse))

    def _on_double_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col_id = self._tree.identify_column(event.x)
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        col_name = self._tree["columns"][int(col_id[1:]) - 1]
        if col_name in self._multiline_cols:
            self._open_multiline_dialog(row_id, col_name)
            return
        bbox = self._tree.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        current = self._tree.set(row_id, col_name)

        entry = ttk.Entry(self._tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus()

        def confirm(event=None):
            self._tree.set(row_id, col_name, entry.get())
            entry.destroy()

        entry.bind("<Return>", confirm)
        entry.bind("<Tab>", confirm)
        entry.bind("<FocusOut>", confirm)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _open_multiline_dialog(self, row_id: str, col_name: str):
        original_val = self._original.get(row_id, {}).get(col_name, "")

        dlg = tk.Toplevel(self._root)
        dlg.title(f"Edit {col_name}")
        dlg.geometry("480x300")
        dlg.transient(self._root)
        dlg.wait_visibility()
        dlg.grab_set()

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)

        txt = tk.Text(dlg, wrap="word", undo=True)
        vsb = ttk.Scrollbar(dlg, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))
        txt.insert("1.0", original_val)
        txt.focus()

        def ok():
            new_val = txt.get("1.0", "end-1c")
            self._tree.set(row_id, col_name, new_val.replace("\n", " "))
            if row_id in self._original:
                self._original[row_id][col_name] = new_val
            dlg.destroy()

        tk.Button(btn_frame, text="OK", width=8, command=ok).pack(side=tk.RIGHT, padx=(2, 0))
        tk.Button(btn_frame, text="Cancel", width=8, command=dlg.destroy).pack(side=tk.RIGHT)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _restripe(self):
        for i, item in enumerate(self._tree.get_children("")):
            tag = "odd" if i % 2 else ""
            self._tree.item(item, tags=(tag,))

    def _add_row(self):
        if self._edit_search_var:
            self._edit_search_var.set("")  # reattach all rows before inserting
        empty = [""] * len(self._columns)
        selected = self._tree.selection()
        if selected:
            idx = self._tree.index(selected[0]) + 1
            iid = self._tree.insert("", idx, values=empty)
            self._all_item_ids.insert(idx, iid)
        else:
            iid = self._tree.insert("", tk.END, values=empty)
            self._all_item_ids.append(iid)
        self._original[iid] = {col: "" for col in self._columns}
        self._restripe()
        self._tree.selection_set(iid)
        self._tree.see(iid)

    def _duplicate_row(self):
        selected = self._tree.selection()
        if not selected:
            return
        src = selected[0]
        if self._edit_search_var:
            self._edit_search_var.set("")  # reattach all rows before inserting
        idx = self._tree.index(src) + 1
        iid = self._tree.insert("", idx, values=self._tree.item(src)["values"])
        self._original[iid] = self._original.get(src, {}).copy()
        self._all_item_ids.insert(idx, iid)
        self._restripe()
        self._tree.selection_set(iid)
        self._tree.see(iid)

    def _delete_row(self):
        selected = self._tree.selection()
        if not selected:
            return
        iid = selected[0]
        self._original.pop(iid, None)
        try:
            self._all_item_ids.remove(iid)
        except ValueError:
            pass
        self._tree.delete(iid)
        self._restripe()
        if self._count_label and self._edit_search_var is not None:
            q = self._edit_search_var.get().strip().lower()
            total = len(self._all_item_ids)
            visible = len(self._tree.get_children(""))
            if not q or visible == total:
                self._count_label.config(text=f"{total} rows")
            else:
                self._count_label.config(text=f"{visible} / {total} rows")

    def _save(self):
        new_sections: list[dict] = []
        for item in (self._all_item_ids or list(self._tree.get_children(""))):
            values = self._tree.item(item)["values"]
            original = self._original.get(item, {})
            section: dict[str, str] = {}
            for j, col in enumerate(self._columns):
                display_val = str(values[j]) if j < len(values) else ""
                orig_val = original.get(col, "")
                # Restore original multiline value when the cell wasn't edited
                if col in self._multiline_cols and display_val == orig_val.replace("\n", " "):
                    section[col] = orig_val
                else:
                    section[col] = display_val
            new_sections.append(section)
        self._path.write_text(_sections_to_text(new_sections), encoding="utf-8")
        print(f"saved: {self._path}", flush=True)

    def run(self):
        self._root.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]
    readonly = "--readonly" in args
    systems = "--systems" in args
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) != 1:
        print(f"usage: {sys.argv[0]} <file> [--systems] [--readonly]")
        sys.exit(1)
    mode = "main_text" if systems else "csv"
    JTable(positional[0], mode=mode, readonly=readonly).run()
