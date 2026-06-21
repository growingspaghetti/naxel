use data_encoding::BASE32;
use std::path::Path;

pub fn encode_name(name: &str) -> String {
    BASE32.encode(name.as_bytes()).trim_end_matches('=').to_string()
}

pub fn decode_name(encoded: &str) -> Option<String> {
    let pad = (8 - encoded.len() % 8) % 8;
    let padded = format!("{}{}", encoded.to_uppercase(), "=".repeat(pad));
    BASE32.decode(padded.as_bytes()).ok()
        .and_then(|b| String::from_utf8(b).ok())
}

pub fn repo_namespace(repo_root: &Path) -> String {
    let path_str = repo_root.to_str().unwrap_or("");
    format!("{:x}", md5::compute(path_str.as_bytes()))
}

/// Returns the latest versioned file for `encoded` base name + `suffix` in `dir`.
/// Files are named `{encoded}.{4-digit-version}{suffix}`.
pub fn latest_in_dir(dir: &Path, encoded: &str, suffix: &str) -> Option<std::path::PathBuf> {
    let prefix = format!("{}.", encoded);
    let total_len = prefix.len() + 4 + suffix.len();

    let entries = std::fs::read_dir(dir).ok()?;
    let mut matches: Vec<String> = entries
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|f| {
            f.len() == total_len
                && f.starts_with(&prefix)
                && f.ends_with(suffix)
                && f[prefix.len()..prefix.len() + 4].chars().all(|c| c.is_ascii_digit())
        })
        .collect();
    matches.sort();
    matches.last().map(|f| dir.join(f))
}
