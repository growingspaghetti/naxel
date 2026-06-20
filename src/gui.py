import csv
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

_SEP = "👉" * 10 + "👈" * 10


def _is_label(line: str) -> bool:
    return line.startswith("👉") and line.endswith("👈") and line != _SEP


def _parse_sections(text: str) -> list[dict]:
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
                if key == "notes":
                    note_lines: list[str] = []
                    while i < n and lines[i] != _SEP and not _is_label(lines[i]):
                        note_lines.append(lines[i])
                        i += 1
                    section[key] = "\n".join(note_lines)
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


class JTable:
    def __init__(self, path: str | Path | None = None, mode: str = "csv",
                 readonly: bool = False, diff_data: dict | None = None,
                 title: str | None = None):
        """
        mode      : "csv" for CSV files, "systems" for 👉👈 text files
        readonly  : hide Save button and disable editing (cat --jtable)
        diff_data : {"columns": [...], "deleted": [[...], ...], "added": [[...], ...]}
                    when provided the table shows a read-only diff view
        """
        self._path = Path(path) if path else None
        self._mode = mode
        self._readonly = readonly
        self._diff_data = diff_data
        self._columns: list[str] = []
        self._original: dict[str, dict] = {}   # item_id → original section dict

        self._root = tk.Tk()
        self._root.title(title or (self._path.name if self._path else "diff"))
        self._root.geometry("960x540")
        self._build()

    def _build(self):
        if self._mode == "systems" and not self._readonly:
            btn_frame = tk.Frame(self._root)
            btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
            tk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT)
            tk.Button(btn_frame, text="Delete Row", command=self._delete_row).pack(side=tk.LEFT, padx=(0, 2))
            tk.Button(btn_frame, text="Duplicate Row", command=self._duplicate_row).pack(side=tk.LEFT, padx=(0, 2))
            tk.Button(btn_frame, text="Add Row", command=self._add_row).pack(side=tk.LEFT)

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

        if self._mode == "systems" and not self._readonly:
            self._tree.bind("<Double-1>", self._on_double_click)

        if self._diff_data is not None:
            self._load_diff()
        elif self._mode == "systems":
            self._load_systems()
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
            rows = list(csv.reader(f))
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
        for i, row in enumerate(rows[1:]):
            values = [v.strip() for v in row]
            tag = "odd" if i % 2 else ""
            self._tree.insert("", tk.END, values=values, tags=(tag,))

    def _load_systems(self):
        sections = _parse_sections(self._path.read_text(encoding="utf-8"))
        if not sections:
            return
        self._columns = list(sections[0].keys())
        self._tree["columns"] = self._columns
        self._tree["show"] = "headings"
        for col in self._columns:
            self._tree.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._sort(c, False))
            self._tree.column(col, width=140, minwidth=50, anchor="w", stretch=True)
        for i, sec in enumerate(sections):
            display = [v.replace("\n", " ") for v in sec.values()]
            tag = "odd" if i % 2 else ""
            iid = self._tree.insert("", tk.END, values=display, tags=(tag,))
            self._original[iid] = sec

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
        bbox = self._tree.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        col_name = self._tree["columns"][int(col_id[1:]) - 1]
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

    def _restripe(self):
        for i, item in enumerate(self._tree.get_children("")):
            tag = "odd" if i % 2 else ""
            self._tree.item(item, tags=(tag,))

    def _add_row(self):
        empty = [""] * len(self._columns)
        selected = self._tree.selection()
        idx = self._tree.index(selected[0]) + 1 if selected else tk.END
        iid = self._tree.insert("", idx, values=empty)
        self._original[iid] = {col: "" for col in self._columns}
        self._restripe()
        self._tree.selection_set(iid)
        self._tree.see(iid)

    def _duplicate_row(self):
        selected = self._tree.selection()
        if not selected:
            return
        src = selected[0]
        iid = self._tree.insert("", self._tree.index(src) + 1,
                                values=self._tree.item(src)["values"])
        self._original[iid] = self._original.get(src, {}).copy()
        self._restripe()
        self._tree.selection_set(iid)
        self._tree.see(iid)

    def _delete_row(self):
        selected = self._tree.selection()
        if not selected:
            return
        self._original.pop(selected[0], None)
        self._tree.delete(selected[0])
        self._restripe()

    def _save(self):
        new_sections: list[dict] = []
        for item in self._tree.get_children(""):
            values = self._tree.item(item)["values"]
            original = self._original.get(item, {})
            section: dict[str, str] = {}
            for j, col in enumerate(self._columns):
                display_val = str(values[j]) if j < len(values) else ""
                orig_val = original.get(col, "")
                # Restore original multiline notes when the cell wasn't edited
                if col == "notes" and display_val == orig_val.replace("\n", " "):
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
    mode = "systems" if systems else "csv"
    JTable(positional[0], mode=mode, readonly=readonly).run()
