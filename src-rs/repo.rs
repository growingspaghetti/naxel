use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use crate::config::{load_repo_config, RepoConfig};
use crate::encoding::repo_namespace;

#[derive(Clone)]
pub struct AdditionalProp {
    pub name: String,
    pub validation_type: String,
    pub multiline: bool,
}

#[derive(Clone)]
pub struct MandatoryRefProp {
    pub property_name: String,
    pub collection_name: String,
    pub whitelist: HashSet<String>,
}

#[derive(Clone)]
pub struct DynamicCollection {
    pub collection_name: String,
    pub collection_type: String,
}

#[derive(Clone)]
pub struct RepoState {
    pub repo_root: PathBuf,
    pub downloads_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub main_collection: String,
    pub partitioning_property: String,
    pub collections: HashSet<String>,
    pub collection_type: HashMap<String, String>,
    pub additional_props: Vec<String>,
    pub mandatory_ref_props: Vec<MandatoryRefProp>,
    pub field_order: Option<Vec<String>>,
    pub prop_validation_types: HashMap<String, String>,
    pub multiline_props: HashSet<String>,
    pub intro_message: String,
}

pub fn repo_suffix(collection: &str, main_collection: &str) -> &'static str {
    if collection == main_collection { ".txt.gz" } else { ".txt" }
}

pub fn load_additional_properties(repo_root: &Path, filename: &str) -> Vec<AdditionalProp> {
    let path = repo_root.join(filename);
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return vec![],
    };
    let data: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("warning: could not read {filename}: {e}");
            return vec![];
        }
    };
    data.as_array().map(|arr| {
        arr.iter().filter_map(|item| {
            let obj = item.as_object()?;
            let name = obj.get("property_name")?.as_str()?.trim().to_string();
            if name.is_empty() { return None; }
            let vtype = obj.get("validation_type")
                .and_then(|v| v.as_str())
                .unwrap_or("NONE")
                .trim()
                .to_string();
            let multiline = obj.get("multiline")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            Some(AdditionalProp { name, validation_type: vtype, multiline })
        }).collect()
    }).unwrap_or_default()
}

pub fn load_dynamic_collections(repo_root: &Path, filename: &str) -> Vec<serde_json::Value> {
    let path = repo_root.join(filename);
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return vec![],
    };
    let data: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("warning: could not read {filename}: {e}");
            return vec![];
        }
    };
    data.as_array().map(|arr| {
        arr.iter()
            .filter(|item| {
                item.as_object()
                    .and_then(|o| o.get("collection_name"))
                    .and_then(|v| v.as_str())
                    .map(|s| !s.is_empty())
                    .unwrap_or(false)
            })
            .cloned()
            .collect()
    }).unwrap_or_default()
}

pub fn initialize_repo(
    repo_root: &Path,
    downloads_base: &Path,
    cache_base: &Path,
) -> RepoState {
    let ns = repo_namespace(repo_root);
    let downloads_dir = downloads_base.join(&ns);
    let cache_dir = cache_base.join(&ns);

    let RepoConfig {
        collection_name: main_coll,
        partitioning_property,
        property_order,
        additional_props_file,
        ref_collections_file,
        intro_message,
    } = load_repo_config(repo_root);

    let mut collections = HashSet::new();
    collections.insert(main_coll.clone());

    let optional_pairs = load_additional_properties(repo_root, &additional_props_file);
    let mut prop_validation_types: HashMap<String, String> = optional_pairs.iter()
        .filter(|p| p.validation_type != "NONE")
        .map(|p| (p.name.clone(), p.validation_type.clone()))
        .collect();
    let multiline_props: HashSet<String> = optional_pairs.iter()
        .filter(|p| p.multiline)
        .map(|p| p.name.clone())
        .collect();

    let dynamic_colls = load_dynamic_collections(repo_root, &ref_collections_file);
    let mut collection_type: HashMap<String, String> = HashMap::new();

    for dc in &dynamic_colls {
        if let Some(cname) = dc["collection_name"].as_str() {
            collections.insert(cname.to_string());
            collection_type.insert(
                cname.to_string(),
                dc.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            );
            let _ = std::fs::create_dir_all(repo_root.join(cname));
            let _ = std::fs::create_dir_all(cache_dir.join(cname));
        }
    }

    let mandatory_ref_props: Vec<MandatoryRefProp> = dynamic_colls.iter()
        .filter_map(|dc| {
            let pname = dc.get("property_name")?.as_str()?.to_string();
            let cname = dc["collection_name"].as_str()?.to_string();
            let whitelist: HashSet<String> = dc.get("whitelist")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            if pname.is_empty() { return None; }
            Some(MandatoryRefProp { property_name: pname, collection_name: cname, whitelist })
        })
        .collect();

    let optional_prop_names: Vec<String> = optional_pairs.iter().map(|p| p.name.clone()).collect();
    let mandatory_prop_names: Vec<String> = mandatory_ref_props.iter()
        .map(|m| m.property_name.clone())
        .collect();
    // Mandatory props already declared as optional props are not appended again (matches Python behaviour)
    let optional_set: HashSet<&str> = optional_prop_names.iter().map(|s| s.as_str()).collect();
    let all_props: Vec<String> = optional_prop_names.iter()
        .chain(mandatory_prop_names.iter().filter(|m| !optional_set.contains(m.as_str())))
        .cloned()
        .collect();

    let all_fields_set: HashSet<&str> = all_props.iter().map(|s| s.as_str()).collect();

    let field_order = if !property_order.is_empty() {
        let ordered_front: Vec<String> = property_order.iter()
            .filter(|p| all_fields_set.contains(p.as_str()))
            .cloned()
            .collect();
        let ordered_front_set: HashSet<&str> = ordered_front.iter().map(|s| s.as_str()).collect();
        let remaining: Vec<String> = all_props.iter()
            .filter(|p| !ordered_front_set.contains(p.as_str()))
            .cloned()
            .collect();
        Some([ordered_front, remaining].concat())
    } else {
        None
    };

    let additional_props = field_order.clone().unwrap_or_else(|| all_props.clone());

    RepoState {
        repo_root: repo_root.to_path_buf(),
        downloads_dir,
        cache_dir,
        main_collection: main_coll,
        partitioning_property,
        collections,
        collection_type,
        additional_props,
        mandatory_ref_props,
        field_order,
        prop_validation_types,
        multiline_props,
        intro_message,
    }
}

pub fn sync_cache(state: &RepoState) {
    let mut copied = 0usize;
    let mut coll_names: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
    coll_names.sort();

    for coll in coll_names {
        let src_dir = state.repo_root.join(coll);
        let dst_dir = state.cache_dir.join(coll);
        if !src_dir.is_dir() { continue; }
        let _ = std::fs::create_dir_all(&dst_dir);
        let cached: HashSet<String> = std::fs::read_dir(&dst_dir)
            .ok()
            .map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect())
            .unwrap_or_default();
        if let Ok(rd) = std::fs::read_dir(&src_dir) {
            for entry in rd.filter_map(|e| e.ok()) {
                let fname = entry.file_name().to_string_lossy().into_owned();
                if !cached.contains(&fname) {
                    let _ = std::fs::copy(src_dir.join(&fname), dst_dir.join(&fname));
                    copied += 1;
                }
            }
        }
    }
    if copied > 0 {
        println!("cache: synced {copied} file(s)");
    }
}

pub fn build_ref_data(
    cache_dir: &Path,
    mandatory_ref_props: &[MandatoryRefProp],
) -> HashMap<String, HashMap<String, String>> {
    use crate::encoding::decode_name;
    let mut result = HashMap::new();

    for mrp in mandatory_ref_props {
        let col_dir = cache_dir.join(&mrp.collection_name);
        let mut mapping: HashMap<String, String> = HashMap::new();

        if let Ok(rd) = std::fs::read_dir(&col_dir) {
            let mut fnames: Vec<String> = rd
                .filter_map(|e| e.ok())
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|f| f.ends_with(".txt"))
                .collect();
            fnames.sort();
            for fname in fnames {
                let stem = &fname[..fname.len() - 4];
                let parts: Vec<&str> = stem.splitn(2, '.').collect();
                if parts.len() == 2 && parts[1].len() == 4 && parts[1].chars().all(|c| c.is_ascii_digit()) {
                    if let Some(name) = decode_name(parts[0]) {
                        if let Ok(content) = std::fs::read_to_string(col_dir.join(&fname)) {
                            mapping.insert(name, content.trim().to_string());
                        }
                    }
                }
            }
        }
        result.insert(mrp.property_name.clone(), mapping);
    }
    result
}
