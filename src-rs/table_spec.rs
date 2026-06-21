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
}
