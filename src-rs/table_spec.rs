use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use serde::{Deserialize, Serialize};

/// Serializable description of what the table window should display.
/// Passed from the REPL to the table process via stdin JSON.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum TableData {
    Csv {
        path: PathBuf,
        ref_data: HashMap<String, HashMap<String, String>>,
        title: String,
    },
    MainText {
        path: PathBuf,
        readonly: bool,
        multiline_cols: HashSet<String>,
        ref_data: HashMap<String, HashMap<String, String>>,
        title: String,
    },
    Ref {
        path: PathBuf,
        readonly: bool,
        title: String,
    },
    Diff {
        columns: Vec<String>,
        deleted: Vec<Vec<String>>,
        added: Vec<Vec<String>>,
        title: String,
    },
}
