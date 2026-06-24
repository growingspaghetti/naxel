use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SerMandatoryRefProp {
    pub property_name: String,
    pub collection_name: String,
    pub whitelist: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PushInfo {
    pub repo_root: PathBuf,
    pub downloads_dir: PathBuf,
    pub main_collection: String,
    pub collection: String,
    pub name: String,
    pub additional_props: Vec<String>,
    pub field_order: Option<Vec<String>>,
    pub prop_validation_types: HashMap<String, String>,
    pub multiline_props: Vec<String>,
    pub mandatory_ref_props: Vec<SerMandatoryRefProp>,
    pub collection_type: HashMap<String, String>,
}

/// All repo state the nx subprocess needs to reconstruct a mini RepoState.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NxInfo {
    pub repo_root: PathBuf,
    pub downloads_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub main_collection: String,
    pub additional_props: Vec<String>,
    pub field_order: Option<Vec<String>>,
    pub multiline_props: Vec<String>,
    pub mandatory_ref_props: Vec<SerMandatoryRefProp>,
    pub collection_type: HashMap<String, String>,
    pub prop_validation_types: HashMap<String, String>,
    pub editor: String,
    /// Temp file the subprocess appends dispatched commands to; REPL polls this for history.
    pub history_file: PathBuf,
}

/// Serializable description of what the table window should display.
/// Passed from the REPL to the table process via stdin JSON.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum TableData {
    Nx {
        collections: Vec<String>,
        nx_info: NxInfo,
    },
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
        push_info: Option<PushInfo>,
    },
    Ref {
        path: PathBuf,
        readonly: bool,
        title: String,
        push_info: Option<PushInfo>,
    },
    Diff {
        columns: Vec<String>,
        deleted: Vec<Vec<String>>,
        added: Vec<Vec<String>>,
        title: String,
    },
    TextEdit {
        path: PathBuf,
        title: String,
        context: TextEditContext,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextEditContext {
    pub action: String,         // "appenditems" | "searchitems" | "removeitems"
    pub existing_path: PathBuf, // path to the current data file in the repo
    pub push_info: PushInfo,
    pub json_mode: bool,
}
