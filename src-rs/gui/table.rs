use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use iced::widget::{
    button, column, container, row, scrollable, text, text_editor, text_input,
};
use iced::{color, Alignment, Color, Element, Length, Padding, Task, Theme};

use super::query::{parse_query, QueryResult};
use crate::formats::{is_prop_label, label_name, SEPARATOR};
use crate::table_spec::TableData;

const COL_W: f32 = 160.0;
const CELL_INPUT_ID: &str = "cell-editor";
const SEARCH_INPUT_ID: &str = "search-box";

#[derive(Debug, Clone)]
pub enum Mode {
    Csv,
    MainText,
    Ref,
    Diff,
}

#[derive(Debug, Clone)]
struct DiffMeta {
    deleted_count: usize,
}

#[derive(Debug, Clone)]
struct RowMeta {
    deleted: bool,
    added: bool,
}

#[derive(Debug, Clone)]
pub enum Message {
    Search(String),
    CellClicked(usize, usize),
    EditChanged(String),
    EditConfirm,
    EditCancel,
    MultilineOpen(usize, usize),
    MultilineChanged(text_editor::Action),
    MultilineConfirm,
    MultilineCancel,
    Sort(usize),
    Save,
    AddRow,
    DuplicateRow,
    DeleteRow,
    CopyTsv,
    ClipboardWritten,
}

pub struct TableApp {
    mode: Mode,
    readonly: bool,
    path: Option<PathBuf>,
    title_str: String,

    columns: Vec<String>,
    rows: Vec<Vec<String>>,
    row_meta: Vec<RowMeta>,
    original_multiline: HashMap<(usize, usize), String>,
    multiline_cols: HashSet<String>,
    ref_data: HashMap<String, HashMap<String, String>>,
    expanded_rows: Vec<Vec<String>>,
    original_headings: Option<Vec<String>>,

    search: String,
    visible: Vec<usize>,

    sort_col: Option<usize>,
    sort_asc: bool,

    editing: Option<(usize, usize)>,
    edit_value: String,

    ml_editing: Option<(usize, usize)>,
    ml_content: text_editor::Content,

    lookup_display: Option<(String, Vec<String>)>, // (label, values) when in lookup mode

    selected: Option<usize>,
}

impl TableApp {
    pub fn new(data: TableData) -> Self {
        let mut app = TableApp {
            mode: Mode::Csv,
            readonly: false,
            path: None,
            title_str: String::new(),
            columns: vec![],
            rows: vec![],
            row_meta: vec![],
            original_multiline: HashMap::new(),
            multiline_cols: HashSet::new(),
            ref_data: HashMap::new(),
            expanded_rows: vec![],
            original_headings: None,
            search: String::new(),
            visible: vec![],
            sort_col: None,
            sort_asc: true,
            editing: None,
            edit_value: String::new(),
            ml_editing: None,
            ml_content: text_editor::Content::new(),
            lookup_display: None,
            selected: None,
        };
        app.load(data);
        app
    }

    fn load(&mut self, data: TableData) {
        match data {
            TableData::Csv { path, ref_data, title } => {
                self.mode = Mode::Csv;
                self.readonly = true;
                self.title_str = title;
                self.ref_data = ref_data;
                self.path = Some(path.clone());
                self.load_csv(&path);
            }
            TableData::MainText { path, readonly, multiline_cols, ref_data, title } => {
                self.mode = Mode::MainText;
                self.readonly = readonly;
                self.multiline_cols = multiline_cols;
                self.ref_data = ref_data;
                self.title_str = title;
                self.path = Some(path.clone());
                self.load_main_text(&path);
            }
            TableData::Ref { path, readonly, title } => {
                self.mode = Mode::Ref;
                self.readonly = readonly;
                self.title_str = title;
                self.path = Some(path.clone());
                self.load_ref(&path);
            }
            TableData::Diff { columns, deleted, added, title } => {
                self.mode = Mode::Diff;
                self.readonly = true;
                self.title_str = title;
                let del_count = deleted.len();
                self.columns = std::iter::once("_diff".to_string()).chain(columns).collect();
                self.rows = deleted.iter()
                    .map(|r| std::iter::once("−".to_string()).chain(r.iter().cloned()).collect())
                    .chain(added.iter()
                        .map(|r| std::iter::once("+".to_string()).chain(r.iter().cloned()).collect()))
                    .collect();
                self.row_meta = (0..del_count).map(|_| RowMeta { deleted: true, added: false })
                    .chain((0..added.len()).map(|_| RowMeta { deleted: false, added: true }))
                    .collect();
                self.rebuild_visible();
            }
        }
    }

    fn load_csv(&mut self, path: &PathBuf) {
        let text = std::fs::read_to_string(path).unwrap_or_default();
        let mut rdr = csv::ReaderBuilder::new()
            .has_headers(true)
            .trim(csv::Trim::All)
            .from_reader(text.as_bytes());
        if let Ok(headers) = rdr.headers() {
            self.columns = headers.iter().map(|s| s.to_string()).collect();
        }
        for result in rdr.records() {
            if let Ok(record) = result {
                self.rows.push(record.iter().map(|s| s.to_string()).collect());
                self.row_meta.push(RowMeta { deleted: false, added: false });
            }
        }
        self.rebuild_visible();
        self.build_expanded();
    }

    fn load_main_text(&mut self, path: &PathBuf) {
        let text = std::fs::read_to_string(path).unwrap_or_default();
        let lines: Vec<&str> = text.lines().collect();
        let n = lines.len();
        let mut i = 0;
        let mut sections: Vec<HashMap<String, String>> = vec![];
        let mut col_order: Vec<String> = vec![];
        let mut col_seen: HashSet<String> = HashSet::new();

        while i < n {
            if lines[i] != SEPARATOR { i += 1; continue; }
            i += 1;
            let mut sec: HashMap<String, String> = HashMap::new();
            while i < n && lines[i] != SEPARATOR {
                if is_prop_label(lines[i]) {
                    let key = label_name(lines[i]).to_string();
                    if !col_seen.contains(&key) {
                        col_order.push(key.clone());
                        col_seen.insert(key.clone());
                    }
                    i += 1;
                    if self.multiline_cols.contains(&key) {
                        let mut ml = vec![];
                        while i < n && lines[i] != SEPARATOR && !is_prop_label(lines[i]) {
                            ml.push(lines[i]);
                            i += 1;
                        }
                        sec.insert(key, ml.join("\n"));
                    } else {
                        let val = if i < n { lines[i].to_string() } else { String::new() };
                        sec.insert(key, val);
                        if i < n { i += 1; }
                    }
                } else {
                    i += 1;
                }
            }
            if !sec.is_empty() { sections.push(sec); }
        }

        self.columns = col_order;
        for (row_idx, sec) in sections.iter().enumerate() {
            let mut display_row: Vec<String> = vec![];
            for (col_idx, col) in self.columns.iter().enumerate() {
                let val = sec.get(col).cloned().unwrap_or_default();
                if self.multiline_cols.contains(col) {
                    self.original_multiline.insert((row_idx, col_idx), val.clone());
                    display_row.push(val.replace('\n', " "));
                } else {
                    display_row.push(val);
                }
            }
            self.rows.push(display_row);
            self.row_meta.push(RowMeta { deleted: false, added: false });
        }
        self.rebuild_visible();
        self.build_expanded();
    }

    fn load_ref(&mut self, path: &PathBuf) {
        let text = std::fs::read_to_string(path).unwrap_or_default();
        let t = text.trim();
        self.columns = vec!["values".to_string()];
        if !t.is_empty() {
            for val in t.split(',') {
                let v = val.trim();
                if !v.is_empty() {
                    self.rows.push(vec![v.to_string()]);
                    self.row_meta.push(RowMeta { deleted: false, added: false });
                }
            }
        }
        self.rebuild_visible();
        self.build_expanded();
    }

    fn rebuild_visible(&mut self) {
        if self.search.is_empty() {
            self.lookup_display = None;
            self.visible = (0..self.rows.len()).collect();
        } else {
            self.apply_search();
        }
    }

    fn apply_search(&mut self) {
        let cols_for_search: Vec<String> = self.columns.iter()
            .filter(|c| *c != "_diff")
            .cloned()
            .collect();
        let actual_cols = if self.columns.first().map(|c| c == "_diff").unwrap_or(false) {
            &self.columns[1..]
        } else {
            &self.columns[..]
        };
        match parse_query(&self.search, actual_cols, &self.ref_data) {
            QueryResult::Filter { func, count_only: _ } => {
                self.lookup_display = None;
                let exp = if self.expanded_rows.is_empty() { &self.rows } else { &self.expanded_rows };
                self.visible = (0..self.rows.len())
                    .filter(|&i| {
                        let orig = &self.rows[i];
                        let expanded = exp.get(i).unwrap_or(orig);
                        let offset = if self.columns.first().map(|c| c == "_diff").unwrap_or(false) { 1 } else { 0 };
                        let orig_trim: Vec<String> = orig[offset..].to_vec();
                        let exp_trim: Vec<String> = expanded[offset..].to_vec();
                        func(&orig_trim, &exp_trim)
                    })
                    .collect();
            }
            QueryResult::Lookup { prop, entry, values } => {
                let label = format!("{prop}.{entry}");
                let len = values.len();
                self.lookup_display = Some((label, values));
                self.visible = (0..len).collect();
            }
        }
    }

    fn build_expanded(&mut self) {
        if self.ref_data.is_empty() {
            self.expanded_rows = self.rows.clone();
            return;
        }
        self.expanded_rows = self.rows.iter().map(|row| {
            self.columns.iter().enumerate().map(|(i, col)| {
                let val = row.get(i).map(|s| s.as_str()).unwrap_or("");
                if let Some(content) = self.ref_data.get(col).and_then(|m| m.get(val)) {
                    if !content.is_empty() {
                        return format!("{val} {content}");
                    }
                }
                val.to_string()
            }).collect()
        }).collect();
    }

    fn do_sort(&mut self, col_idx: usize) {
        if self.sort_col == Some(col_idx) {
            self.sort_asc = !self.sort_asc;
        } else {
            self.sort_col = Some(col_idx);
            self.sort_asc = true;
        }
        let asc = self.sort_asc;
        let col = col_idx;
        self.rows.sort_by(|a, b| {
            let va = a.get(col).map(|s| s.as_str()).unwrap_or("");
            let vb = b.get(col).map(|s| s.as_str()).unwrap_or("");
            if asc { va.cmp(vb) } else { vb.cmp(va) }
        });
        self.row_meta.sort_by(|_, _| std::cmp::Ordering::Equal); // parallel — left as is (diff doesn't sort)
        self.rebuild_visible();
        self.build_expanded();
    }

    fn save_main(&self) {
        let path = match &self.path { Some(p) => p, None => return };
        let mut out = String::new();
        for (row_idx, row) in self.rows.iter().enumerate() {
            out.push_str(SEPARATOR);
            out.push('\n');
            for (col_idx, col) in self.columns.iter().enumerate() {
                out.push_str(&format!("👉{col}👈\n"));
                if self.multiline_cols.contains(col) {
                    let orig = self.original_multiline.get(&(row_idx, col_idx));
                    let display = row.get(col_idx).map(|s| s.as_str()).unwrap_or("");
                    if let Some(orig_val) = orig {
                        let display_collapsed = orig_val.replace('\n', " ");
                        if display == display_collapsed {
                            out.push_str(orig_val);
                        } else {
                            out.push_str(display);
                        }
                    } else {
                        out.push_str(display);
                    }
                } else {
                    out.push_str(row.get(col_idx).map(|s| s.as_str()).unwrap_or(""));
                }
                out.push('\n');
            }
        }
        let _ = std::fs::write(path, &out);
        println!("saved: {}", path.display());
    }

    fn save_ref(&self) {
        let path = match &self.path { Some(p) => p, None => return };
        let values: Vec<&str> = self.rows.iter()
            .filter_map(|r| r.first().map(|s| s.as_str()))
            .filter(|s| !s.is_empty())
            .collect();
        let out = if values.is_empty() { String::new() } else { values.join(",") + "\n" };
        let _ = std::fs::write(path, &out);
        println!("saved: {}", path.display());
    }

    // ── view helpers ──────────────────────────────────────────────────────────

    fn view_search_bar(&self) -> Element<'_, Message> {
        let count_txt = if let Some((label, values)) = &self.lookup_display {
            format!("{} values — {label}", values.len())
        } else {
            let total = self.rows.len();
            let visible = self.visible.len();
            if visible == total {
                format!("{total} rows")
            } else {
                format!("{visible} / {total} rows")
            }
        };

        row![
            text("Search:").size(13),
            text_input("", &self.search)
                .id(text_input::Id::new(SEARCH_INPUT_ID))
                .on_input(Message::Search)
                .size(13)
                .width(Length::Fill),
            text(count_txt).size(12),
        ]
        .spacing(6)
        .align_y(Alignment::Center)
        .padding(Padding::new(4.0))
        .into()
    }

    fn view_header(&self) -> Element<'_, Message> {
        if let Some((label, _)) = &self.lookup_display {
            let btn = button(text(label.clone()).size(12))
                .width(Length::Fixed(COL_W))
                .padding([3, 6])
                .style(button::secondary);
            return row![btn].spacing(1).into();
        }
        let cells: Vec<Element<'_, Message>> = self.columns.iter().enumerate().map(|(i, col)| {
            if col == "_diff" {
                container(text("").size(12))
                    .width(Length::Fixed(32.0))
                    .into()
            } else {
                let label = if self.sort_col == Some(i) {
                    format!("{col} {}", if self.sort_asc { "▲" } else { "▼" })
                } else {
                    col.clone()
                };
                button(text(label).size(12))
                    .on_press(Message::Sort(i))
                    .width(Length::Fixed(COL_W))
                    .padding([3, 6])
                    .style(button::secondary)
                    .into()
            }
        }).collect();
        row(cells).spacing(1).into()
    }

    fn cell_bg(row_idx: usize, meta: &RowMeta) -> Color {
        if meta.deleted {
            Color::from_rgb(1.0, 0.88, 0.88)
        } else if meta.added {
            Color::from_rgb(0.88, 1.0, 0.88)
        } else if row_idx % 2 == 0 {
            Color::WHITE
        } else {
            Color::from_rgb(0.95, 0.95, 0.97)
        }
    }

    fn view_lookup_rows(&self, values: &[String]) -> Vec<Element<'_, Message>> {
        values.iter().enumerate().map(|(i, val)| {
            let bg = if i % 2 == 0 { Color::WHITE } else { Color::from_rgb(0.95, 0.95, 0.97) };
            let cell = container(text(val.clone()).size(13))
                .width(Length::Fixed(COL_W))
                .height(Length::Fixed(24.0))
                .padding([2, 6])
                .style(move |_| container::Style {
                    background: Some(iced::Background::Color(bg)),
                    ..Default::default()
                });
            row![cell].spacing(1).into()
        }).collect()
    }

    fn view_data_rows(&self) -> Vec<Element<'_, Message>> {
        let rows: Vec<Element<'_, Message>> = self.visible.iter().copied().map(|row_idx| {
            let row_data = &self.rows[row_idx];
            let meta = &self.row_meta[row_idx];
            let bg = Self::cell_bg(row_idx, meta);

            let selected = self.selected == Some(row_idx);

            let cells: Vec<Element<'_, Message>> = self.columns.iter().enumerate().map(|(col_idx, col)| {
                if col == "_diff" {
                    let sym = row_data.get(col_idx).map(|s| s.as_str()).unwrap_or("");
                    let fg = if meta.deleted { color!(0x990000) } else { color!(0x006600) };
                    container(text(sym).size(12).color(fg))
                        .center(Length::Fixed(32.0))
                        .height(Length::Fixed(24.0))
                        .into()
                } else if self.editing == Some((row_idx, col_idx)) {
                    text_input("", &self.edit_value)
                        .id(text_input::Id::new(CELL_INPUT_ID))
                        .on_input(Message::EditChanged)
                        .on_submit(Message::EditConfirm)
                        .size(12)
                        .width(Length::Fixed(COL_W))
                        .into()
                } else {
                    let val = row_data.get(col_idx).map(|s| s.as_str()).unwrap_or("");
                    let cell_bg = if selected { Color::from_rgb(0.85, 0.92, 1.0) } else { bg };
                    let is_ml = self.multiline_cols.contains(col);
                    let press_msg = if is_ml && !self.readonly {
                        Message::MultilineOpen(row_idx, col_idx)
                    } else if !self.readonly && !matches!(self.mode, Mode::Diff | Mode::Csv) {
                        Message::CellClicked(row_idx, col_idx)
                    } else {
                        Message::CellClicked(row_idx, col_idx) // selection only when readonly
                    };
                    container(
                        button(
                            text(val).size(12).width(Length::Fixed(COL_W - 12.0))
                        )
                        .on_press(press_msg)
                        .padding([2u16, 6])
                        .width(Length::Fixed(COL_W))
                        .style(move |_theme: &Theme, _status| {
                            button::Style {
                                background: Some(iced::Background::Color(cell_bg)),
                                text_color: Color::BLACK,
                                border: iced::Border {
                                    color: Color::TRANSPARENT,
                                    width: 0.0,
                                    radius: 0.0.into(),
                                },
                                ..Default::default()
                            }
                        }),
                    )
                    .height(Length::Fixed(24.0))
                    .into()
                }
            }).collect();

            row(cells).spacing(1).into()
        }).collect();

        rows
    }

    fn view_buttons(&self) -> Element<'_, Message> {
        let save_btn = button(text("Save").size(13))
            .on_press(Message::Save)
            .style(button::primary)
            .padding([4u16, 12]);
        let add_btn = button(text("Add Row").size(13))
            .on_press(Message::AddRow)
            .padding([4u16, 10]);
        let del_btn = button(text("Delete Row").size(13))
            .on_press(Message::DeleteRow)
            .padding([4u16, 10]);

        let mut btns: Vec<Element<'_, Message>> = vec![
            add_btn.into(),
            del_btn.into(),
        ];

        if matches!(self.mode, Mode::MainText) {
            let dup_btn = button(text("Duplicate Row").size(13))
                .on_press(Message::DuplicateRow)
                .padding([4u16, 10]);
            btns.push(dup_btn.into());
        }

        btns.push(save_btn.into());

        row(btns).spacing(6).padding([4u16, 4]).into()
    }

    fn view_multiline_dialog(&self) -> Element<'_, Message> {
        let (row_idx, col_idx) = match self.ml_editing {
            Some(pos) => pos,
            None => return column![].into(),
        };
        let col_name = self.columns.get(col_idx).map(|s| s.as_str()).unwrap_or("field");

        let title_txt = text(format!("Edit: {col_name}")).size(14);
        let area = text_editor(&self.ml_content)
            .on_action(Message::MultilineChanged)
            .size(13)
            .height(Length::Fixed(200.0));
        let ok_btn = button(text("OK").size(13))
            .on_press(Message::MultilineConfirm)
            .style(button::primary)
            .padding([4u16, 12]);
        let cancel_btn = button(text("Cancel").size(13))
            .on_press(Message::MultilineCancel)
            .padding([4u16, 12]);

        let dialog = container(
            column![
                title_txt,
                area,
                row![cancel_btn, ok_btn].spacing(6),
            ]
            .spacing(8)
            .padding(12),
        )
        .style(|_| container::Style {
            background: Some(iced::Background::Color(Color::WHITE)),
            border: iced::Border {
                color: Color::from_rgb(0.6, 0.6, 0.6),
                width: 1.0,
                radius: 4.0.into(),
            },
            ..Default::default()
        })
        .width(Length::Fixed(520.0));

        container(dialog)
            .center(Length::Fill)
            .style(|_| container::Style {
                background: Some(iced::Background::Color(Color { r: 0.0, g: 0.0, b: 0.0, a: 0.4 })),
                ..Default::default()
            })
            .width(Length::Fill)
            .height(Length::Fill)
            .into()
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Search(q) => {
                self.search = q;
                self.apply_search();
            }
            Message::CellClicked(row_idx, col_idx) => {
                if self.readonly || matches!(self.mode, Mode::Diff | Mode::Csv) {
                    self.selected = Some(row_idx);
                    self.editing = None;
                } else {
                    if self.editing != Some((row_idx, col_idx)) {
                        if let Some(_) = self.editing { /* confirm current silently */ }
                        let val = self.rows.get(row_idx)
                            .and_then(|r| r.get(col_idx))
                            .cloned()
                            .unwrap_or_default();
                        self.editing = Some((row_idx, col_idx));
                        self.edit_value = val;
                        self.selected = Some(row_idx);
                        return text_input::focus(text_input::Id::new(CELL_INPUT_ID));
                    }
                }
            }
            Message::EditChanged(v) => {
                self.edit_value = v;
            }
            Message::EditConfirm => {
                if let Some((row_idx, col_idx)) = self.editing.take() {
                    if let Some(row) = self.rows.get_mut(row_idx) {
                        if let Some(cell) = row.get_mut(col_idx) {
                            *cell = self.edit_value.clone();
                        }
                    }
                    self.build_expanded();
                }
            }
            Message::EditCancel => {
                self.editing = None;
                self.edit_value.clear();
            }
            Message::MultilineOpen(row_idx, col_idx) => {
                let original = self.original_multiline
                    .get(&(row_idx, col_idx))
                    .cloned()
                    .unwrap_or_else(|| {
                        self.rows.get(row_idx)
                            .and_then(|r| r.get(col_idx))
                            .cloned()
                            .unwrap_or_default()
                    });
                self.ml_editing = Some((row_idx, col_idx));
                self.ml_content = text_editor::Content::with_text(&original);
            }
            Message::MultilineChanged(action) => {
                self.ml_content.perform(action);
            }
            Message::MultilineConfirm => {
                if let Some((row_idx, col_idx)) = self.ml_editing.take() {
                    let new_val = self.ml_content.text();
                    // strip trailing newline that text_editor always appends
                    let new_val = new_val.trim_end_matches('\n').to_string();
                    self.original_multiline.insert((row_idx, col_idx), new_val.clone());
                    if let Some(row) = self.rows.get_mut(row_idx) {
                        if let Some(cell) = row.get_mut(col_idx) {
                            *cell = new_val.replace('\n', " ");
                        }
                    }
                    self.build_expanded();
                }
                self.ml_content = text_editor::Content::new();
            }
            Message::MultilineCancel => {
                self.ml_editing = None;
                self.ml_content = text_editor::Content::new();
            }
            Message::Sort(col_idx) => {
                if !matches!(self.mode, Mode::Diff) {
                    self.do_sort(col_idx);
                }
            }
            Message::Save => {
                match self.mode {
                    Mode::MainText => self.save_main(),
                    Mode::Ref => self.save_ref(),
                    _ => {}
                }
            }
            Message::AddRow => {
                let empty = vec![String::new(); self.columns.len()];
                let insert_at = self.selected.map(|s| s + 1).unwrap_or(self.rows.len());
                let insert_at = insert_at.min(self.rows.len());
                self.rows.insert(insert_at, empty);
                self.row_meta.insert(insert_at, RowMeta { deleted: false, added: false });
                // Re-index original_multiline keys
                let shifted: HashMap<(usize, usize), String> = self.original_multiline.drain()
                    .map(|((r, c), v)| {
                        let new_r = if r >= insert_at { r + 1 } else { r };
                        ((new_r, c), v)
                    })
                    .collect();
                self.original_multiline = shifted;
                self.selected = Some(insert_at);
                self.search.clear();
                self.rebuild_visible();
                self.build_expanded();
            }
            Message::DuplicateRow => {
                if let Some(src) = self.selected {
                    let dup = self.rows.get(src).cloned().unwrap_or_default();
                    let insert_at = (src + 1).min(self.rows.len());
                    self.rows.insert(insert_at, dup);
                    self.row_meta.insert(insert_at, RowMeta { deleted: false, added: false });
                    let shifted: HashMap<(usize, usize), String> = self.original_multiline.drain()
                        .map(|((r, c), v)| {
                            let new_r = if r >= insert_at { r + 1 } else { r };
                            ((new_r, c), v)
                        })
                        .collect();
                    self.original_multiline = shifted;
                    // Duplicate multiline values from source row
                    let mut new_ml: HashMap<(usize, usize), String> = HashMap::new();
                    for col_idx in 0..self.columns.len() {
                        if let Some(orig) = self.original_multiline.get(&(src, col_idx)) {
                            new_ml.insert((insert_at, col_idx), orig.clone());
                        }
                    }
                    self.original_multiline.extend(new_ml);
                    self.selected = Some(insert_at);
                    self.search.clear();
                    self.rebuild_visible();
                    self.build_expanded();
                }
            }
            Message::DeleteRow => {
                if let Some(sel) = self.selected {
                    if sel < self.rows.len() {
                        self.rows.remove(sel);
                        self.row_meta.remove(sel);
                        let shifted: HashMap<(usize, usize), String> = self.original_multiline.drain()
                            .filter_map(|((r, c), v)| {
                                if r == sel { None }
                                else { Some(((if r > sel { r - 1 } else { r }, c), v)) }
                            })
                            .collect();
                        self.original_multiline = shifted;
                        self.selected = if self.rows.is_empty() { None }
                            else { Some(sel.saturating_sub(1).min(self.rows.len() - 1)) };
                        self.rebuild_visible();
                        self.build_expanded();
                    }
                }
            }
            Message::CopyTsv => {} // handled by platform clipboard
            Message::ClipboardWritten => {}
        }
        Task::none()
    }

    pub fn view(&self) -> Element<'_, Message> {
        let show_search = self.readonly || matches!(self.mode, Mode::Csv | Mode::MainText | Mode::Ref);

        let header = self.view_header();
        let data_rows = if let Some((_, values)) = &self.lookup_display {
            self.view_lookup_rows(values)
        } else {
            self.view_data_rows()
        };

        let mut table_children: Vec<Element<'_, Message>> = vec![header];
        table_children.extend(data_rows);

        // Single 2D scrollable: header and data rows scroll together
        let table = scrollable(
            column(table_children).spacing(1)
        )
        .direction(scrollable::Direction::Both {
            vertical: scrollable::Scrollbar::default(),
            horizontal: scrollable::Scrollbar::default(),
        })
        .height(Length::Fill);

        let mut content: Vec<Element<'_, Message>> = vec![];

        if show_search {
            content.push(self.view_search_bar());
        }

        content.push(table.into());

        if !self.readonly && !matches!(self.mode, Mode::Diff | Mode::Csv) {
            content.push(self.view_buttons());
        }

        let main: Element<'_, Message> = column(content)
            .width(Length::Fill)
            .height(Length::Fill)
            .into();

        if self.ml_editing.is_some() {
            iced::widget::stack![main, self.view_multiline_dialog()].into()
        } else {
            main
        }
    }
}

pub fn run(data: TableData) -> iced::Result {
    let title_str = match &data {
        TableData::Csv { title, .. } => title.clone(),
        TableData::MainText { title, .. } => title.clone(),
        TableData::Ref { title, .. } => title.clone(),
        TableData::Diff { title, .. } => title.clone(),
    };

    iced::application(
        move |_state: &TableApp| title_str.clone(),
        TableApp::update,
        TableApp::view,
    )
    .window(iced::window::Settings {
        size: iced::Size::new(960.0, 540.0),
        ..Default::default()
    })
    .theme(|_| Theme::Light)
    .run_with(move || (TableApp::new(data.clone()), Task::none()))
}
