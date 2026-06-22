use configparser::ini::Ini;
use std::path::{Path, PathBuf};

pub struct AppConfig {
    pub repo_root: PathBuf,
    pub downloads_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub editor: String,
}

pub fn load_app_config(script_dir: &Path) -> AppConfig {
    let mut ini = Ini::new();
    let _ = ini.load(script_dir.join("settings.ini").to_str().unwrap_or(""));

    let repo_root = script_dir.join(
        ini.get("repository", "root").unwrap_or_else(|| "dummy-repo".into()),
    );
    let downloads_dir = script_dir.join(
        ini.get("downloads", "dir").unwrap_or_else(|| "downloads".into()),
    );
    let cache_dir = script_dir.join(
        ini.get("cache", "dir").unwrap_or_else(|| "cache".into()),
    );
    let editor = ini.get("editor", "command").unwrap_or_else(|| "mousepad".into());

    AppConfig { repo_root, downloads_dir, cache_dir, editor }
}

pub struct RepoConfig {
    pub collection_name: String,
    pub partitioning_property: String,
    pub property_order: Vec<String>,
    pub intro_message: String,
}

pub fn load_repo_config(repo_root: &Path) -> RepoConfig {
    let mut ini = Ini::new();
    let _ = ini.load(repo_root.join("repository.ini").to_str().unwrap_or(""));

    let collection_name = ini.get("main_collection", "collection_name")
        .unwrap_or_else(|| "systems".into());
    let partitioning_property = ini.get("main_collection", "partitioning_property")
        .unwrap_or_else(|| "system".into());
    let raw_order = ini.get("main_collection", "property_order").unwrap_or_default();
    let property_order: Vec<String> = raw_order
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    let intro_message = ini.get("introduction", "message").unwrap_or_default();

    RepoConfig {
        collection_name,
        partitioning_property,
        property_order,
        intro_message,
    }
}
