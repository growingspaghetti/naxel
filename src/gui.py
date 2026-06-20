import csv
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path


class JTable:
    def __init__(self, csv_path):
        self._path = Path(csv_path)
        self._root = tk.Tk()
        self._root.title(self._path.name)
        self._root.geometry("960x540")
        self._build()

    def _build(self):
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

        self._load_csv()

    def _load_csv(self):
        with self._path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        if not rows:
            return

        headers = [h.strip() for h in rows[0]]
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

    def _sort(self, col: str, reverse: bool):
        items = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        items.sort(key=lambda t: t[0], reverse=reverse)
        for i, (_, k) in enumerate(items):
            self._tree.move(k, "", i)
            tag = "odd" if i % 2 else ""
            self._tree.item(k, tags=(tag,))
        self._tree.heading(col, command=lambda: self._sort(col, not reverse))

    def run(self):
        self._root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <csv_file>")
        sys.exit(1)
    JTable(sys.argv[1]).run()
