use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use crate::encoding::{decode_name, encode_name, latest_in_dir};
use crate::formats::*;
use crate::repo::{repo_suffix, MandatoryRefProp, RepoState};
use crate::validation::{validate_main_collection, validate_ref_collection};

fn col_path(repo_root: &Path, collection: &str) -> PathBuf {
    repo_root.join(collection)
}

fn find_latest(repo_root: &Path, main_coll: &str, collection: &str, name: &str) -> Option<PathBuf> {
    let suffix = repo_suffix(collection, main_coll);
    let encoded = encode_name(name);
    latest_in_dir(&col_path(repo_root, collection), &encoded, suffix)
}

// ── ls ─────────────────────────────────────────────────────────────────────────

pub fn cmd_ls(repo_root: &Path, main_coll: &str, collection: &str) {
    let path = col_path(repo_root, collection);
    if !path.is_dir() {
        eprintln!("error: directory not found: {}", path.display());
        return;
    }
    let suffix = repo_suffix(collection, main_coll);
    let mut seen: HashSet<String> = HashSet::new();
    let mut fnames: Vec<String> = std::fs::read_dir(&path)
        .unwrap_or_else(|_| panic!())
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    fnames.sort();
    for fname in fnames {
        if !fname.ends_with(suffix) { continue; }
        let stem = &fname[..fname.len() - suffix.len()];
        let parts: Vec<&str> = stem.splitn(2, '.').collect();
        if parts.len() == 2 && parts[1].len() == 4 && parts[1].chars().all(|c| c.is_ascii_digit()) {
            let encoded = parts[0];
            if seen.insert(encoded.to_string()) {
                if let Some(name) = decode_name(encoded) {
                    println!("{name}");
                }
            }
        }
    }
}

// ── add ────────────────────────────────────────────────────────────────────────

pub fn cmd_add(
    repo_root: &Path,
    main_coll: &str,
    collection: &str,
    name: &str,
    field_order: &[String],
) {
    let path = col_path(repo_root, collection);
    let _ = std::fs::create_dir_all(&path);
    let encoded = encode_name(name);
    let suffix = repo_suffix(collection, main_coll);
    let dest = path.join(format!("{encoded}.0000{suffix}"));
    if dest.exists() {
        eprintln!("error: already exists: {name}");
        return;
    }
    if suffix == ".txt.gz" {
        let json = empty_main_collection_json(field_order);
        match gzip_compress(json.as_bytes()) {
            Ok(bytes) => { let _ = std::fs::write(&dest, bytes); }
            Err(e) => { eprintln!("error: {e}"); return; }
        }
    } else {
        let _ = std::fs::write(&dest, b"");
    }
    println!("created: {name}");
}

// ── len ────────────────────────────────────────────────────────────────────────

pub fn cmd_len(repo_root: &Path, main_coll: &str, collection: &str, name: &str) {
    let filepath = match find_latest(repo_root, main_coll, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return; }
    };
    if collection == main_coll {
        let bytes = std::fs::read(&filepath).unwrap_or_default();
        match gzip_decompress(&bytes).and_then(|b| Ok(serde_json::from_slice::<serde_json::Value>(&b)?)) {
            Ok(v) => {
                let count = v.as_array().map(|arr| {
                    arr.iter().filter(|s| {
                        s.as_object().map(|o| o.values().any(|v| !v.as_str().unwrap_or("").is_empty())).unwrap_or(false)
                    }).count()
                }).unwrap_or(0);
                println!("{count}");
            }
            Err(e) => eprintln!("error: {e}"),
        }
    } else {
        let content = std::fs::read_to_string(&filepath).unwrap_or_default();
        let content = content.trim();
        let count = if content.is_empty() { 0 } else { content.split(',').count() };
        println!("{count}");
    }
}

// ── cat ────────────────────────────────────────────────────────────────────────

pub fn cmd_cat(
    state: &RepoState,
    collection: &str,
    name: &str,
    jtable: bool,
    as_json: bool,
) -> Option<crate::table_spec::TableData> {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return None; }
    };
    if jtable {
        let dl_dir = state.downloads_dir.join(collection);
        let _ = std::fs::create_dir_all(&dl_dir);
        if collection == state.main_collection {
            let bytes = std::fs::read(&filepath).unwrap_or_default();
            let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
            let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
            let text = sections_to_text(&sections, field_order);
            let dl_name = filepath.file_name().unwrap().to_string_lossy();
            let dl_name = dl_name.strip_suffix(".gz").unwrap_or(&dl_name);
            let dest = dl_dir.join(dl_name);
            let _ = std::fs::write(&dest, &text);
            println!("saved: {}", dest.display());
            let ref_data = crate::repo::build_ref_data(&state.cache_dir, &state.mandatory_ref_props);
            return Some(crate::table_spec::TableData::MainText {
                path: dest,
                readonly: true,
                multiline_cols: state.multiline_props.clone(),
                ref_data,
                title: format!("{collection} {name}"),
                push_info: None,
            });
        } else {
            let dest = dl_dir.join(filepath.file_name().unwrap());
            let _ = std::fs::copy(&filepath, &dest);
            println!("saved: {}", dest.display());
            return Some(crate::table_spec::TableData::Ref {
                path: dest,
                readonly: true,
                title: format!("{collection} {name}"),
                push_info: None,
            });
        }
    }
    // Plain cat — lock stdout for the whole write+flush so rustyline's
    // next prompt cannot interleave before our content is rendered.
    use std::io::Write;
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    if as_json {
        if collection == state.main_collection {
            let bytes = std::fs::read(&filepath).unwrap_or_default();
            let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
            let json_str = serde_json::to_string_pretty(&sections).unwrap_or_default();
            let _ = writeln!(out, "{json_str}");
        } else {
            match std::fs::read_to_string(&filepath) {
                Ok(s) => {
                    let values: Vec<&str> = s.trim().split(',')
                        .map(|v| v.trim())
                        .filter(|v| !v.is_empty())
                        .collect();
                    let json_str = serde_json::to_string_pretty(&values).unwrap_or_default();
                    let _ = writeln!(out, "{json_str}");
                }
                Err(e) => eprintln!("error: {e}"),
            }
        }
    } else if collection == state.main_collection {
        let bytes = std::fs::read(&filepath).unwrap_or_default();
        let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_default();
        let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
        let text = sections_to_text(&sections, field_order);
        let _ = write!(out, "{text}");
    } else {
        match std::fs::read_to_string(&filepath) {
            Ok(s) => {
                let _ = write!(out, "{s}");
                if !s.ends_with('\n') {
                    let _ = writeln!(out);
                }
            }
            Err(e) => eprintln!("error: {e}"),
        }
    }
    let _ = out.flush();
    None
}

// ── get ────────────────────────────────────────────────────────────────────────

pub fn cmd_get(
    state: &RepoState,
    collection: &str,
    name: &str,
    editor: &str,
    jtable: bool,
    stdin_content: Option<String>,
) -> Option<crate::table_spec::TableData> {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return None; }
    };
    let dl_dir = state.downloads_dir.join(collection);
    let _ = std::fs::create_dir_all(&dl_dir);
    let dl_name = filepath.file_name().unwrap().to_string_lossy();
    let dl_name = dl_name.strip_suffix(".gz").unwrap_or(&dl_name);
    let dest = dl_dir.join(dl_name);

    if let Some(content) = stdin_content {
        let _ = std::fs::write(&dest, content);
        println!("saved: {}", dest.display());
        return None;
    }

    if collection == state.main_collection {
        let bytes = std::fs::read(&filepath).unwrap_or_default();
        let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_default();
        let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
        let _ = std::fs::write(&dest, sections_to_text(&sections, field_order));
    } else {
        let _ = std::fs::copy(&filepath, &dest);
    }
    println!("saved: {}", dest.display());

    if jtable {
        let push_info = Some(crate::table_spec::PushInfo {
            repo_root: state.repo_root.clone(),
            downloads_dir: state.downloads_dir.clone(),
            main_collection: state.main_collection.clone(),
            collection: collection.to_string(),
            name: name.to_string(),
            additional_props: state.additional_props.clone(),
            field_order: state.field_order.clone(),
            prop_validation_types: state.prop_validation_types.clone(),
            multiline_props: state.multiline_props.iter().cloned().collect(),
            mandatory_ref_props: state.mandatory_ref_props.iter().map(|m| {
                crate::table_spec::SerMandatoryRefProp {
                    property_name: m.property_name.clone(),
                    collection_name: m.collection_name.clone(),
                    whitelist: m.whitelist.iter().cloned().collect(),
                }
            }).collect(),
            collection_type: state.collection_type.clone(),
        });
        if collection == state.main_collection {
            return Some(crate::table_spec::TableData::MainText {
                path: dest,
                readonly: false,
                multiline_cols: state.multiline_props.clone(),
                ref_data: HashMap::new(),
                title: format!("{collection} {name}"),
                push_info,
            });
        } else {
            return Some(crate::table_spec::TableData::Ref {
                path: dest,
                readonly: false,
                title: format!("{collection} {name}"),
                push_info,
            });
        }
    }
    let _ = std::process::Command::new(editor).arg(&dest).spawn();
    None
}

// ── clear ──────────────────────────────────────────────────────────────────────

pub fn cmd_clear(
    state: &RepoState,
    collection: &str,
    name: &str,
    editor: &str,
    jtable: bool,
) -> Option<crate::table_spec::TableData> {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return None; }
    };
    let dl_dir = state.downloads_dir.join(collection);
    let _ = std::fs::create_dir_all(&dl_dir);
    let dl_name = filepath.file_name().unwrap().to_string_lossy();
    let dl_name = dl_name.strip_suffix(".gz").unwrap_or(&dl_name);
    let dest = dl_dir.join(dl_name);

    let template = if collection == state.main_collection {
        let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
        empty_main_collection_document(field_order)
    } else {
        String::new()
    };
    let _ = std::fs::write(&dest, &template);
    println!("cleared: {}", dest.display());

    if jtable {
        let push_info = Some(crate::table_spec::PushInfo {
            repo_root: state.repo_root.clone(),
            downloads_dir: state.downloads_dir.clone(),
            main_collection: state.main_collection.clone(),
            collection: collection.to_string(),
            name: name.to_string(),
            additional_props: state.additional_props.clone(),
            field_order: state.field_order.clone(),
            prop_validation_types: state.prop_validation_types.clone(),
            multiline_props: state.multiline_props.iter().cloned().collect(),
            mandatory_ref_props: state.mandatory_ref_props.iter().map(|m| {
                crate::table_spec::SerMandatoryRefProp {
                    property_name: m.property_name.clone(),
                    collection_name: m.collection_name.clone(),
                    whitelist: m.whitelist.iter().cloned().collect(),
                }
            }).collect(),
            collection_type: state.collection_type.clone(),
        });
        if collection == state.main_collection {
            return Some(crate::table_spec::TableData::MainText {
                path: dest,
                readonly: false,
                multiline_cols: state.multiline_props.clone(),
                ref_data: HashMap::new(),
                title: format!("{collection} {name}"),
                push_info,
            });
        } else {
            return Some(crate::table_spec::TableData::Ref {
                path: dest,
                readonly: false,
                title: format!("{collection} {name}"),
                push_info,
            });
        }
    }
    let _ = std::process::Command::new(editor).arg(&dest).spawn();
    None
}

// ── push ───────────────────────────────────────────────────────────────────────

pub fn cmd_push(state: &RepoState, collection: &str, name: &str, json_mode: bool) {
    let encoded = encode_name(name);
    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
    let src = match latest_in_dir(&state.downloads_dir.join(collection), &encoded, ".txt") {
        Some(p) => p,
        None => { eprintln!("error: not found in downloads: {name}"); return; }
    };
    let raw_text = std::fs::read_to_string(&src).unwrap_or_default();
    let content = if json_mode {
        let parsed: serde_json::Value = match serde_json::from_str(&raw_text) {
            Ok(v) => v,
            Err(e) => { eprintln!("error: invalid JSON: {e}"); return; }
        };
        if collection == state.main_collection {
            let sections = parsed.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
            sections_to_text(sections, field_order)
        } else {
            let values: Vec<&str> = parsed.as_array()
                .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
                .unwrap_or_default();
            values.join(",")
        }
    } else {
        raw_text
    };

    let skip_validation = collection == state.main_collection
        && is_initial_state(&content, field_order, &state.multiline_props);

    if !skip_validation {
        let mandatory_prop_names: HashSet<String> = state.mandatory_ref_props.iter()
            .map(|m| m.property_name.clone())
            .collect();

        if collection == state.main_collection {
            if let Err(e) = validate_main_collection(
                &content,
                field_order,
                &mandatory_prop_names,
                &state.prop_validation_types,
                &state.multiline_props,
            ) {
                eprintln!("rejected: {e}");
                return;
            }
            // Reference validation
            if !state.mandatory_ref_props.is_empty() {
                let sections = parse_sections_lenient(&content, field_order, &state.multiline_props);
                for mrp in &state.mandatory_ref_props {
                    let ref_dir = col_path(&state.repo_root, &mrp.collection_name);
                    let ref_suffix = repo_suffix(&mrp.collection_name, &state.main_collection);
                    let existing: HashSet<String> = std::fs::read_dir(&ref_dir)
                        .ok()
                        .map(|rd| {
                            rd.filter_map(|e| e.ok())
                                .map(|e| e.file_name().to_string_lossy().into_owned())
                                .filter(|f| f.ends_with(ref_suffix))
                                .map(|f| {
                                    let stem = &f[..f.len() - ref_suffix.len()];
                                    stem.splitn(2, '.').next().unwrap_or("").to_string()
                                })
                                .collect()
                        })
                        .unwrap_or_default();

                    for sec in &sections {
                        let val = sec.get(&mrp.property_name)
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if !val.is_empty()
                            && !mrp.whitelist.contains(val)
                            && !existing.contains(&encode_name(val))
                        {
                            eprintln!(
                                "rejected: {} {:?} not found in {} collection",
                                mrp.property_name, val, mrp.collection_name
                            );
                            return;
                        }
                    }
                }
            }
        } else {
            let ctype = state.collection_type.get(collection).map(|s| s.as_str()).unwrap_or("");
            if let Err(e) = validate_ref_collection(ctype, &content) {
                eprintln!("rejected: {e}");
                return;
            }
        }
    }

    let col_dir = col_path(&state.repo_root, collection);
    let suffix = repo_suffix(collection, &state.main_collection);
    let latest = match latest_in_dir(&col_dir, &encoded, suffix) {
        Some(p) => p,
        None => { eprintln!("error: not found in repository: {name}"); return; }
    };
    let fname = latest.file_name().unwrap().to_string_lossy();
    let version_str = &fname[encoded.len() + 1..encoded.len() + 5];
    let version: u32 = version_str.parse().unwrap_or(0);
    let new_version = version + 1;
    let dest = col_dir.join(format!("{encoded}.{new_version:04}{suffix}"));

    if suffix == ".txt.gz" {
        let body = if content.trim().is_empty() {
            empty_main_collection_json(field_order)
        } else {
            let sections = text_to_sections(&content, field_order, &state.multiline_props);
            serde_json::to_string_pretty(&sections).unwrap() + "\n"
        };
        match gzip_compress(body.as_bytes()) {
            Ok(bytes) => { let _ = std::fs::write(&dest, bytes); }
            Err(e) => { eprintln!("error: {e}"); return; }
        }
    } else {
        let _ = std::fs::write(&dest, &content);
    }
    println!("pushed: {name} (version {new_version:04})");
}

// ── diff ───────────────────────────────────────────────────────────────────────

pub fn cmd_diff(
    state: &RepoState,
    collection: &str,
    name: &str,
    jtable: bool,
) -> Option<crate::table_spec::TableData> {
    let encoded = encode_name(name);
    let suffix = repo_suffix(collection, &state.main_collection);
    let col_dir = col_path(&state.repo_root, collection);
    let prefix = format!("{encoded}.");
    let total_len = prefix.len() + 4 + suffix.len();

    let mut matches: Vec<String> = std::fs::read_dir(&col_dir)
        .ok()
        .map(|rd| {
            rd.filter_map(|e| e.ok())
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|f| {
                    f.len() == total_len
                        && f.starts_with(&prefix)
                        && f.ends_with(suffix)
                        && f[prefix.len()..prefix.len() + 4].chars().all(|c| c.is_ascii_digit())
                })
                .collect()
        })
        .unwrap_or_default();
    matches.sort();

    if matches.is_empty() {
        eprintln!("error: not found: {name}");
        return None;
    }
    if matches.len() < 2 {
        eprintln!("error: only one version exists for: {name}");
        return None;
    }

    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);

    if collection == state.main_collection {
        let load = |fname: &str| -> Vec<serde_json::Value> {
            let bytes = std::fs::read(col_dir.join(fname)).unwrap_or_default();
            gzip_decompress(&bytes)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default()
        };
        let prev = load(&matches[matches.len() - 2]);
        let curr = load(&matches[matches.len() - 1]);

        let key_of = |s: &serde_json::Value| -> String {
            serde_json::to_string(s).unwrap_or_default()
        };
        let prev_keys: HashSet<String> = prev.iter().map(key_of).collect();
        let curr_keys: HashSet<String> = curr.iter().map(key_of).collect();
        let deleted_secs: Vec<&serde_json::Value> = prev.iter()
            .filter(|s| !curr_keys.contains(&key_of(s)))
            .collect();
        let added_secs: Vec<&serde_json::Value> = curr.iter()
            .filter(|s| !prev_keys.contains(&key_of(s)))
            .collect();

        if jtable {
            let deleted: Vec<Vec<String>> = deleted_secs.iter()
                .map(|s| field_order.iter().map(|k| s.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string()).collect())
                .collect();
            let added: Vec<Vec<String>> = added_secs.iter()
                .map(|s| field_order.iter().map(|k| s.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string()).collect())
                .collect();
            return Some(crate::table_spec::TableData::Diff {
                columns: field_order.to_vec(),
                deleted,
                added,
                title: format!("diff {collection} {name}"),
            });
        }
        let result = serde_json::json!({"deleted": deleted_secs, "added": added_secs});
        println!("{}", serde_json::to_string_pretty(&result).unwrap());
    } else {
        let parse = |fname: &str| -> Vec<String> {
            let text = std::fs::read_to_string(col_dir.join(fname)).unwrap_or_default();
            let t = text.trim();
            if t.is_empty() { vec![] }
            else { t.split(',').map(|e| e.trim().to_string()).filter(|e| !e.is_empty()).collect() }
        };
        let prev = parse(&matches[matches.len() - 2]);
        let curr = parse(&matches[matches.len() - 1]);
        let prev_set: HashSet<&str> = prev.iter().map(|s| s.as_str()).collect();
        let curr_set: HashSet<&str> = curr.iter().map(|s| s.as_str()).collect();
        let deleted: Vec<String> = prev.iter().filter(|s| !curr_set.contains(s.as_str())).cloned().collect();
        let added: Vec<String> = curr.iter().filter(|s| !prev_set.contains(s.as_str())).cloned().collect();

        if jtable {
            let col_name = match collection {
                "schedules" => "date",
                "contacts" => "number",
                _ => "value",
            };
            return Some(crate::table_spec::TableData::Diff {
                columns: vec![col_name.to_string()],
                deleted: deleted.iter().map(|e| vec![e.clone()]).collect(),
                added: added.iter().map(|e| vec![e.clone()]).collect(),
                title: format!("diff {collection} {name}"),
            });
        }
        let result = serde_json::json!({"deleted": deleted, "added": added});
        println!("{}", serde_json::to_string_pretty(&result).unwrap());
    }
    None
}

// ── export ─────────────────────────────────────────────────────────────────────

pub fn cmd_export(
    state: &RepoState,
    collection: &str,
    filename: &str,
    editor: &str,
    jtable: bool,
) -> Option<crate::table_spec::TableData> {
    crate::repo::sync_cache(state);
    let col_path_dir = state.cache_dir.join(collection);
    if !col_path_dir.is_dir() {
        eprintln!("error: directory not found: {}", col_path_dir.display());
        return None;
    }
    let suffix = repo_suffix(collection, &state.main_collection);
    let mut seen: HashMap<String, String> = HashMap::new();
    let mut fnames: Vec<String> = std::fs::read_dir(&col_path_dir)
        .unwrap_or_else(|_| panic!())
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    fnames.sort();
    for fname in fnames {
        if !fname.ends_with(suffix) { continue; }
        let stem = &fname[..fname.len() - suffix.len()];
        let parts: Vec<&str> = stem.splitn(2, '.').collect();
        if parts.len() == 2 && parts[1].len() == 4 && parts[1].chars().all(|c| c.is_ascii_digit()) {
            seen.insert(parts[0].to_string(), fname);
        }
    }

    let _ = std::fs::create_dir_all(&state.downloads_dir);
    let dest = state.downloads_dir.join(filename);
    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
    let json_mode = filename.ends_with(".json");

    if json_mode {
        let mut records: Vec<serde_json::Value> = vec![];
        if collection == state.main_collection {
            let name_col = state.partitioning_property.clone();
            let mut sorted: Vec<(&String, &String)> = seen.iter().collect();
            sorted.sort_by_key(|(k, _)| k.as_str());
            for (encoded, fname) in sorted {
                let system_name = decode_name(encoded).unwrap_or_else(|| encoded.clone());
                let bytes = std::fs::read(col_path_dir.join(fname)).unwrap_or_default();
                let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
                    .ok()
                    .and_then(|b| serde_json::from_slice(&b).ok())
                    .unwrap_or_default();
                if sections_all_blank(&sections) { continue; }
                for sec in &sections {
                    let mut record = serde_json::Map::new();
                    record.insert(name_col.clone(), serde_json::Value::String(system_name.clone()));
                    for f in field_order {
                        record.insert(f.clone(), sec.get(f).cloned().unwrap_or(serde_json::Value::String(String::new())));
                    }
                    records.push(serde_json::Value::Object(record));
                }
            }
        } else {
            let mut sorted: Vec<(&String, &String)> = seen.iter().collect();
            sorted.sort_by_key(|(k, _)| k.as_str());
            for (encoded, fname) in sorted {
                let entry_name = decode_name(encoded).unwrap_or_else(|| encoded.clone());
                let content = std::fs::read_to_string(col_path_dir.join(fname)).unwrap_or_default();
                let t = content.trim();
                if t.is_empty() { continue; }
                let values: Vec<serde_json::Value> = t.split(',')
                    .filter_map(|v| { let v = v.trim(); if v.is_empty() { None } else { Some(serde_json::Value::String(v.to_string())) } })
                    .collect();
                records.push(serde_json::json!({"name": entry_name, "values": values}));
            }
        }
        let json_str = serde_json::to_string_pretty(&records).unwrap() + "\n";
        let _ = std::fs::write(&dest, &json_str);
        println!("exported: {}", dest.display());
        let _ = std::process::Command::new(editor).arg(&dest).spawn();
        return None;
    }

    // CSV mode
    let mut rows: Vec<String> = vec![];
    if collection == state.main_collection {
        let name_col = state.partitioning_property.clone();
        let header_fields: Vec<&str> = std::iter::once(name_col.as_str())
            .chain(field_order.iter().map(|s| s.as_str()))
            .collect();
        rows.push(csv_row(&header_fields));

        let mut sorted: Vec<(&String, &String)> = seen.iter().collect();
        sorted.sort_by_key(|(k, _)| k.as_str());
        for (encoded, fname) in sorted {
            let system_name = decode_name(encoded).unwrap_or_else(|| encoded.clone());
            let bytes = std::fs::read(col_path_dir.join(fname)).unwrap_or_default();
            let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
            if sections_all_blank(&sections) { continue; }
            for sec in &sections {
                let mut fields = vec![system_name.as_str().to_string()];
                for f in field_order {
                    let v = sec.get(f).and_then(|v| v.as_str()).unwrap_or("");
                    let v = if state.multiline_props.contains(f) {
                        v.lines().collect::<Vec<_>>().join(" ").trim().to_string()
                    } else {
                        v.to_string()
                    };
                    fields.push(v);
                }
                let refs: Vec<&str> = fields.iter().map(|s| s.as_str()).collect();
                rows.push(csv_row(&refs));
            }
        }
    } else {
        rows.push(csv_row(&["name", "values"]));
        let mut sorted: Vec<(&String, &String)> = seen.iter().collect();
        sorted.sort_by_key(|(k, _)| k.as_str());
        for (encoded, fname) in sorted {
            let entry_name = decode_name(encoded).unwrap_or_else(|| encoded.clone());
            let content = std::fs::read_to_string(col_path_dir.join(fname)).unwrap_or_default();
            let t = content.trim();
            if t.is_empty() { continue; }
            let values = t.split(',').collect::<Vec<_>>().join(" ");
            rows.push(csv_row(&[&entry_name, &values]));
        }
    }

    let csv_text = rows.join("\n") + "\n";
    let _ = std::fs::write(&dest, &csv_text);
    println!("exported: {}", dest.display());

    if jtable {
        let ref_data = if !state.mandatory_ref_props.is_empty() {
            crate::repo::build_ref_data(&state.cache_dir, &state.mandatory_ref_props)
        } else {
            HashMap::new()
        };
        return Some(crate::table_spec::TableData::Csv {
            path: dest,
            ref_data,
            title: filename.to_string(),
        });
    }
    let _ = std::process::Command::new(editor).arg(&dest).spawn();
    None
}

// ── fullcopy ───────────────────────────────────────────────────────────────────

pub fn cmd_fullcopy(state: &RepoState, destination: &str, json_mode: bool) {
    let dest_base = std::path::Path::new(destination);
    if !dest_base.is_dir() {
        eprintln!("error: not a directory: {}", dest_base.display());
        return;
    }
    let repo_name = state.repo_root.file_name().unwrap().to_string_lossy();

    if !json_mode {
        let dest_dir = dest_base.join(repo_name.as_ref());
        if dest_dir.exists() {
            eprintln!("error: already exists: {}", dest_dir.display());
            return;
        }
        match copy_dir_all(&state.repo_root, &dest_dir) {
            Ok(()) => println!("copied: {}", dest_dir.display()),
            Err(e) => eprintln!("error: {e}"),
        }
        return;
    }

    let dest_file = dest_base.join(format!("{repo_name}.json"));
    if dest_file.exists() {
        eprintln!("error: already exists: {}", dest_file.display());
        return;
    }

    let repo_ini_text = std::fs::read_to_string(state.repo_root.join("repository.ini")).unwrap_or_default();
    let ap_file = state.repo_root.join("additional_properties.json");
    let rc_file = state.repo_root.join("reference_collections.json");
    let additional_props_data: serde_json::Value = std::fs::read_to_string(&ap_file)
        .ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!([]));
    let ref_collections_data: serde_json::Value = std::fs::read_to_string(&rc_file)
        .ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!([]));

    let mut data_section = serde_json::Map::new();
    let mut colls: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
    colls.sort();

    for coll in colls {
        let col_dir = state.repo_root.join(coll);
        if !col_dir.is_dir() { continue; }
        let suffix = repo_suffix(coll, &state.main_collection);
        let mut seen: HashMap<String, String> = HashMap::new();
        if let Ok(rd) = std::fs::read_dir(&col_dir) {
            let mut fnames: Vec<String> = rd.filter_map(|e| e.ok())
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .collect();
            fnames.sort();
            for fname in fnames {
                if !fname.ends_with(suffix) { continue; }
                let stem = &fname[..fname.len() - suffix.len()];
                let parts: Vec<&str> = stem.splitn(2, '.').collect();
                if parts.len() == 2 && parts[1].len() == 4 && parts[1].chars().all(|c| c.is_ascii_digit()) {
                    seen.insert(parts[0].to_string(), fname);
                }
            }
        }
        let mut col_data = serde_json::Map::new();
        let mut sorted: Vec<(String, String)> = seen.into_iter().collect();
        sorted.sort_by(|a, b| a.0.cmp(&b.0));
        for (encoded, fname) in sorted {
            let name = decode_name(&encoded).unwrap_or_else(|| encoded.clone());
            let val = if coll == state.main_collection {
                let bytes = std::fs::read(col_dir.join(&fname)).unwrap_or_default();
                gzip_decompress(&bytes).ok()
                    .and_then(|b| serde_json::from_slice(&b).ok())
                    .unwrap_or(serde_json::json!([]))
            } else {
                serde_json::Value::String(std::fs::read_to_string(col_dir.join(&fname)).unwrap_or_default())
            };
            col_data.insert(name, val);
        }
        data_section.insert(coll.to_string(), serde_json::Value::Object(col_data));
    }

    let output = serde_json::json!({
        "config": {
            "repository_ini": repo_ini_text,
            "additional_properties": additional_props_data,
            "reference_collections": ref_collections_data,
        },
        "data": data_section,
    });
    let _ = std::fs::write(&dest_file, serde_json::to_string_pretty(&output).unwrap() + "\n");
    println!("exported: {}", dest_file.display());
}

// ── mkrepo ─────────────────────────────────────────────────────────────────────

pub fn cmd_mkrepo(json_file: &str, destination: &str) {
    let json_path = std::path::Path::new(json_file);
    if !json_path.exists() {
        eprintln!("error: not found: {}", json_path.display());
        return;
    }
    let text = match std::fs::read_to_string(json_path) {
        Ok(t) => t,
        Err(e) => { eprintln!("error: {e}"); return; }
    };
    let full_data: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => { eprintln!("error: could not parse {json_file}: {e}"); return; }
    };

    if !full_data.get("config").is_some() || !full_data.get("data").is_some() {
        eprintln!("error: invalid fullcopy JSON (missing 'config' or 'data')");
        return;
    }

    let dest_base = std::path::Path::new(destination);
    if !dest_base.is_dir() {
        eprintln!("error: not a directory: {}", dest_base.display());
        return;
    }

    let repo_name = json_path.file_stem().unwrap().to_string_lossy();
    let repo_dir = dest_base.join(repo_name.as_ref());
    if repo_dir.exists() {
        eprintln!("error: already exists: {}", repo_dir.display());
        return;
    }

    let config = &full_data["config"];
    let data = &full_data["data"];

    let repo_ini_text = config["repository_ini"].as_str().unwrap_or("");
    let mut ini = configparser::ini::Ini::new();
    ini.read(repo_ini_text.to_string()).ok();
    let main_coll = ini.get("main_collection", "collection_name")
        .unwrap_or_else(|| "systems".into());

    let _ = std::fs::create_dir_all(&repo_dir);
    let _ = std::fs::write(repo_dir.join("repository.ini"), repo_ini_text);
    let _ = std::fs::write(
        repo_dir.join("additional_properties.json"),
        serde_json::to_string_pretty(&config["additional_properties"]).unwrap() + "\n",
    );
    let _ = std::fs::write(
        repo_dir.join("reference_collections.json"),
        serde_json::to_string_pretty(&config["reference_collections"]).unwrap() + "\n",
    );

    if let Some(data_obj) = data.as_object() {
        for (coll_name, entries) in data_obj {
            let col_dir = repo_dir.join(coll_name);
            let _ = std::fs::create_dir_all(&col_dir);
            let is_main = coll_name == &main_coll;
            let suffix = if is_main { ".txt.gz" } else { ".txt" };
            if let Some(entries_obj) = entries.as_object() {
                for (entry_name, entry_data) in entries_obj {
                    let encoded = encode_name(entry_name);
                    let dest_file = col_dir.join(format!("{encoded}.0000{suffix}"));
                    if is_main {
                        let body = serde_json::to_string_pretty(entry_data).unwrap() + "\n";
                        if let Ok(bytes) = gzip_compress(body.as_bytes()) {
                            let _ = std::fs::write(&dest_file, bytes);
                        }
                    } else {
                        let text = entry_data.as_str().unwrap_or("");
                        let _ = std::fs::write(&dest_file, text);
                    }
                }
            }
        }
    }
    println!("created: {}", repo_dir.display());
}

// ── partialcopy ────────────────────────────────────────────────────────────────

pub fn cmd_partialcopy(
    state: &RepoState,
    collection: &str,
    name: &str,
    destination: &str,
    json_mode: bool,
) {
    let dest_base = std::path::Path::new(destination);
    if !dest_base.is_dir() {
        eprintln!("error: not a directory: {}", dest_base.display());
        return;
    }
    let repo_name = state.repo_root.file_name().unwrap().to_string_lossy();
    let encoded_target = encode_name(name);

    if json_mode {
        let dest_file = dest_base.join(format!("{repo_name}.json"));
        if dest_file.exists() {
            eprintln!("error: already exists: {}", dest_file.display());
            return;
        }
        let repo_ini_text = std::fs::read_to_string(state.repo_root.join("repository.ini")).unwrap_or_default();
        let additional_props_data: serde_json::Value = std::fs::read_to_string(state.repo_root.join("additional_properties.json"))
            .ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!([]));
        let ref_collections_data: serde_json::Value = std::fs::read_to_string(state.repo_root.join("reference_collections.json"))
            .ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!([]));

        let mut data_section = serde_json::Map::new();
        let mut colls: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
        colls.sort();

        for col in colls {
            let col_dir = state.repo_root.join(col);
            if !col_dir.is_dir() { continue; }
            let suffix = repo_suffix(col, &state.main_collection);
            let mut seen: HashMap<String, String> = HashMap::new();
            if let Ok(rd) = std::fs::read_dir(&col_dir) {
                let mut fnames: Vec<String> = rd.filter_map(|e| e.ok())
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .collect();
                fnames.sort();
                for fname in fnames {
                    if !fname.ends_with(suffix) { continue; }
                    let stem = &fname[..fname.len() - suffix.len()];
                    let parts: Vec<&str> = stem.splitn(2, '.').collect();
                    if parts.len() == 2 && parts[1].len() == 4 && parts[1].chars().all(|c| c.is_ascii_digit()) {
                        seen.insert(parts[0].to_string(), fname);
                    }
                }
            }
            let mut col_data = serde_json::Map::new();
            let mut sorted: Vec<(String, String)> = seen.into_iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(&b.0));
            for (encoded, fname) in sorted {
                let entry_name = decode_name(&encoded).unwrap_or_else(|| encoded.clone());
                let is_target = col == collection && encoded == encoded_target;
                let val = if is_target {
                    if col == state.main_collection {
                        let bytes = std::fs::read(col_dir.join(&fname)).unwrap_or_default();
                        gzip_decompress(&bytes).ok()
                            .and_then(|b| serde_json::from_slice(&b).ok())
                            .unwrap_or(serde_json::json!([]))
                    } else {
                        serde_json::Value::String(std::fs::read_to_string(col_dir.join(&fname)).unwrap_or_default())
                    }
                } else if col == state.main_collection {
                    serde_json::json!([])
                } else {
                    serde_json::Value::String(String::new())
                };
                col_data.insert(entry_name, val);
            }
            data_section.insert(col.to_string(), serde_json::Value::Object(col_data));
        }

        let output = serde_json::json!({
            "config": {
                "repository_ini": repo_ini_text,
                "additional_properties": additional_props_data,
                "reference_collections": ref_collections_data,
            },
            "data": data_section,
        });
        let _ = std::fs::write(&dest_file, serde_json::to_string_pretty(&output).unwrap() + "\n");
        println!("exported: {}", dest_file.display());
        return;
    }

    let dest_dir = dest_base.join(repo_name.as_ref());
    if dest_dir.exists() {
        eprintln!("error: already exists: {}", dest_dir.display());
        return;
    }
    let _ = std::fs::create_dir_all(&dest_dir);

    // Copy root-level config files
    if let Ok(rd) = std::fs::read_dir(&state.repo_root) {
        for entry in rd.filter_map(|e| e.ok()) {
            if entry.path().is_file() {
                let _ = std::fs::copy(entry.path(), dest_dir.join(entry.file_name()));
            }
        }
    }

    // Recreate collections
    let mut colls: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
    colls.sort();
    for col in colls {
        let col_src = state.repo_root.join(col);
        if !col_src.is_dir() { continue; }
        let col_dst = dest_dir.join(col);
        let _ = std::fs::create_dir_all(&col_dst);
        if let Ok(rd) = std::fs::read_dir(&col_src) {
            for entry in rd.filter_map(|e| e.ok()) {
                let fname = entry.file_name().to_string_lossy().into_owned();
                let dst_file = col_dst.join(&fname);
                if col == collection && fname.starts_with(&format!("{encoded_target}.")) {
                    let _ = std::fs::copy(entry.path(), &dst_file);
                } else if fname.ends_with(".gz") {
                    let _ = std::fs::write(&dst_file, gzip_compress(b"[]").unwrap_or_default());
                } else {
                    let _ = std::fs::write(&dst_file, b"");
                }
            }
        }
    }
    println!("created: {}", dest_dir.display());
}

// ── init ───────────────────────────────────────────────────────────────────────

pub fn cmd_init(destination: &str) {
    use std::io::Write;

    let dest = std::path::PathBuf::from(destination);
    if let Err(e) = std::fs::create_dir_all(&dest) {
        eprintln!("error: could not create directory: {e}");
        return;
    }
    if dest.join("repository.ini").exists() {
        eprintln!("error: already initialized: {}", dest.display());
        return;
    }

    fn readline() -> String {
        let mut s = String::new();
        std::io::stdin().read_line(&mut s).ok();
        s.trim().to_string()
    }

    fn prompt(msg: &str, default: &str) -> String {
        loop {
            if default.is_empty() {
                print!("{msg}: ");
            } else {
                print!("{msg} [{default}]: ");
            }
            std::io::stdout().flush().ok();
            let answer = readline();
            if !answer.is_empty() { return answer; }
            if !default.is_empty() { return default.to_string(); }
            println!("  (required)");
        }
    }

    fn prompt_bool(msg: &str) -> bool {
        loop {
            print!("{msg} (y/n): ");
            std::io::stdout().flush().ok();
            match readline().to_lowercase().as_str() {
                "y" | "yes" => return true,
                "n" | "no" => return false,
                _ => {}
            }
        }
    }

    println!("Initializing new repository.\n");
    let main_collection = prompt("Main collection name", "systems");
    let partitioning_property = prompt("Partitioning property name", "system");

    let mut additional_props: Vec<serde_json::Value> = Vec::new();
    let mut ref_collections: Vec<serde_json::Value> = Vec::new();

    println!();
    let mut first = true;
    loop {
        let label = if first { "Add a column" } else { "Add another column" };
        first = false;
        if !prompt_bool(label) { break; }

        let col_name = prompt("  Column name", "");
        let is_ref = prompt_bool("  References another collection?");

        if is_ref {
            let ref_col = prompt("    Referenced collection name", "");
            println!("    Content type options: note, date, phone_number, email, year");
            let ref_type_raw = prompt("    Content type", "note").to_uppercase();
            let ref_type = match ref_type_raw.as_str() {
                "STRING" | "DATE" | "PHONE_NUMBER" | "EMAIL" | "YEAR" => ref_type_raw.clone(),
                _ => "STRING".to_string(),
            };
            print!("    Whitelist values (comma-separated, or leave empty): ");
            std::io::stdout().flush().ok();
            let wl_raw = readline();
            let whitelist: Vec<serde_json::Value> = wl_raw
                .split(',')
                .map(|v| v.trim())
                .filter(|v| !v.is_empty())
                .map(|v| serde_json::Value::String(v.to_string()))
                .collect();
            let mut entry = serde_json::json!({
                "collection_name": ref_col,
                "property_name": col_name,
                "type": ref_type,
            });
            if !whitelist.is_empty() {
                entry["whitelist"] = serde_json::Value::Array(whitelist);
            }
            ref_collections.push(entry);
        } else {
            let is_multiline = prompt_bool("  Multiline field?");
            println!("  Validation options: none, not_empty, hh:mm, mm/dd, int, yyyy, re:<pattern>");
            let vtype_raw = prompt("  Validation type", "none").to_lowercase();
            let validation_type = if vtype_raw == "none" {
                "NONE".to_string()
            } else if vtype_raw == "not_empty" {
                "NOT_EMPTY".to_string()
            } else if vtype_raw == "hh:mm" {
                "HH:MM".to_string()
            } else if vtype_raw == "mm/dd" {
                "MM/DD".to_string()
            } else if vtype_raw == "int" {
                "INT".to_string()
            } else if vtype_raw == "yyyy" {
                "YYYY".to_string()
            } else if vtype_raw.starts_with("re:") {
                format!("RE:{}", &vtype_raw[3..])
            } else {
                "NONE".to_string()
            };
            let mut prop_entry = serde_json::json!({
                "property_name": col_name,
                "validation_type": validation_type,
            });
            if is_multiline {
                prop_entry["multiline"] = serde_json::Value::Bool(true);
            }
            additional_props.push(prop_entry);
        }
    }

    let all_cols: Vec<String> = additional_props.iter()
        .filter_map(|p| p["property_name"].as_str().map(|s| s.to_string()))
        .chain(ref_collections.iter().filter_map(|r| r["property_name"].as_str().map(|s| s.to_string())))
        .collect();

    let property_order = if all_cols.len() > 1 {
        println!("\nColumn order:");
        for (i, col) in all_cols.iter().enumerate() {
            println!("  {}. {col}", i + 1);
        }
        print!("Enter numbers in desired order (or press Enter to keep current): ");
        std::io::stdout().flush().ok();
        let order_raw = readline();
        if !order_raw.is_empty() {
            let indices: Vec<usize> = order_raw
                .replace(',', " ")
                .split_whitespace()
                .filter_map(|s| s.parse::<usize>().ok())
                .filter(|&i| i >= 1 && i <= all_cols.len())
                .map(|i| i - 1)
                .collect();
            let mut ordered: Vec<String> = indices.iter().map(|&i| all_cols[i].clone()).collect();
            let seen: std::collections::HashSet<String> = ordered.iter().cloned().collect();
            ordered.extend(all_cols.iter().filter(|c| !seen.contains(*c)).cloned());
            ordered.join(", ")
        } else {
            String::new()
        }
    } else {
        String::new()
    };

    println!();
    let intro_message = prompt("Introduction message", &main_collection);

    let mut repo_ini = format!(
        "[main_collection]\ncollection_name = {main_collection}\npartitioning_property = {partitioning_property}\n"
    );
    if !property_order.is_empty() {
        repo_ini.push_str(&format!("property_order = {property_order}\n"));
    }
    repo_ini.push_str(&format!("\n[introduction]\nmessage = {intro_message}\n"));

    let ref_coll_names: Vec<String> = ref_collections.iter()
        .filter_map(|r| r["collection_name"].as_str().map(|s| s.to_string()))
        .collect();

    let _ = std::fs::write(dest.join("repository.ini"), &repo_ini);
    let _ = std::fs::write(
        dest.join("additional_properties.json"),
        serde_json::to_string_pretty(&serde_json::Value::Array(additional_props)).unwrap() + "\n",
    );
    let _ = std::fs::write(
        dest.join("reference_collections.json"),
        serde_json::to_string_pretty(&serde_json::Value::Array(ref_collections)).unwrap() + "\n",
    );
    let _ = std::fs::create_dir_all(dest.join(&main_collection));
    for cname in &ref_coll_names {
        let _ = std::fs::create_dir_all(dest.join(cname));
    }

    println!("\ncreated: {}", dest.display());
}

// ── update ──────────────────────────────────────────────────────────────────────

pub fn cmd_update(destination: &str) {
    use std::io::Write;

    let dest = std::path::PathBuf::from(destination);
    if !dest.is_dir() {
        eprintln!("error: not a directory: {}", dest.display());
        return;
    }
    if !dest.join("repository.ini").exists() {
        eprintln!("error: not an initialized repository (no repository.ini): {}", dest.display());
        return;
    }

    fn readline() -> String {
        let mut s = String::new();
        std::io::stdin().read_line(&mut s).ok();
        s.trim().to_string()
    }

    fn prompt(msg: &str, default: &str) -> String {
        loop {
            if default.is_empty() {
                print!("{msg}: ");
            } else {
                print!("{msg} [{default}]: ");
            }
            std::io::stdout().flush().ok();
            let answer = readline();
            if !answer.is_empty() { return answer; }
            if !default.is_empty() { return default.to_string(); }
            println!("  (required)");
        }
    }

    fn prompt_bool(msg: &str) -> bool {
        loop {
            print!("{msg} (y/n): ");
            std::io::stdout().flush().ok();
            match readline().to_lowercase().as_str() {
                "y" | "yes" => return true,
                "n" | "no" => return false,
                _ => {}
            }
        }
    }

    fn parse_vtype(raw: &str) -> String {
        let low = raw.to_lowercase();
        if low == "none" { "NONE".to_string() }
        else if low == "not_empty" { "NOT_EMPTY".to_string() }
        else if low == "hh:mm" { "HH:MM".to_string() }
        else if low == "mm/dd" { "MM/DD".to_string() }
        else if low == "int" { "INT".to_string() }
        else if low == "yyyy" { "YYYY".to_string() }
        else if low.starts_with("re:") { format!("RE:{}", &raw[3..]) }
        else { "NONE".to_string() }
    }

    // Read existing config
    let repo_ini_text = std::fs::read_to_string(dest.join("repository.ini")).unwrap_or_default();
    let mut ini = configparser::ini::Ini::new();
    ini.read(repo_ini_text).ok();
    let main_collection = ini.get("main_collection", "collection_name").unwrap_or_else(|| "systems".into());
    let partitioning_property = ini.get("main_collection", "partitioning_property").unwrap_or_else(|| "system".into());
    let property_order_raw = ini.get("main_collection", "property_order").unwrap_or_default();
    let existing_order: Vec<String> = property_order_raw
        .split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
    let mut intro_message = ini.get("introduction", "message").unwrap_or_default();

    let mut additional_props: Vec<serde_json::Value> = std::fs::read_to_string(dest.join("additional_properties.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter().filter(|v| v.is_object()).collect();

    let mut ref_collections: Vec<serde_json::Value> = std::fs::read_to_string(dest.join("reference_collections.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter().filter(|v| v.is_object()).collect();

    // Show current state
    println!("Updating repository at {}\n", dest.display());
    println!("  Main collection : {main_collection}  (partitioning property: {partitioning_property})");
    println!("  Intro message   : {:?}", intro_message);
    println!("  Columns:");
    for p in &additional_props {
        let name = p["property_name"].as_str().unwrap_or("");
        let vtype = p["validation_type"].as_str().unwrap_or("NONE");
        let ml = if p.get("multiline").and_then(|v| v.as_bool()).unwrap_or(false) { ", multiline" } else { "" };
        println!("    {name}  [{vtype}{ml}]");
    }
    for r in &ref_collections {
        let pname = r["property_name"].as_str().unwrap_or("");
        let cname = r["collection_name"].as_str().unwrap_or("");
        let rtype = r["type"].as_str().unwrap_or("STRING");
        println!("    {pname} → {cname}  [{rtype}]");
    }
    println!();

    // ── Add columns ──────────────────────────────────────────────────────────
    println!("--- Add columns ---");
    let mut new_props: Vec<serde_json::Value> = Vec::new();
    let mut new_refs: Vec<serde_json::Value> = Vec::new();
    loop {
        if !prompt_bool("Add a column") { break; }
        let col_name = prompt("  Column name", "");
        let is_ref = prompt_bool("  References another collection?");
        if is_ref {
            let ref_col = prompt("    Referenced collection name", "");
            println!("    Content type options: string, date, phone_number, email, year");
            let ref_type_raw = prompt("    Content type", "string").to_uppercase();
            let ref_type = match ref_type_raw.as_str() {
                "STRING" | "DATE" | "PHONE_NUMBER" | "EMAIL" | "YEAR" => ref_type_raw.clone(),
                _ => "STRING".to_string(),
            };
            print!("    Whitelist values (comma-separated, or leave empty): ");
            std::io::stdout().flush().ok();
            let wl_raw = readline();
            let whitelist: Vec<serde_json::Value> = wl_raw
                .split(',').map(|v| v.trim()).filter(|v| !v.is_empty())
                .map(|v| serde_json::Value::String(v.to_string())).collect();
            let mut entry = serde_json::json!({
                "collection_name": ref_col,
                "property_name": col_name,
                "type": ref_type,
            });
            if !whitelist.is_empty() {
                entry["whitelist"] = serde_json::Value::Array(whitelist);
            }
            new_refs.push(entry);
        } else {
            let is_multiline = prompt_bool("  Multiline field?");
            println!("  Validation options: none, not_empty, hh:mm, mm/dd, int, yyyy, re:<pattern>");
            let validation_type = parse_vtype(&prompt("  Validation type", "none"));
            let mut prop_entry = serde_json::json!({
                "property_name": col_name,
                "validation_type": validation_type,
            });
            if is_multiline {
                prop_entry["multiline"] = serde_json::Value::Bool(true);
            }
            new_props.push(prop_entry);
        }
    }
    for r in &new_refs {
        if let Some(cname) = r["collection_name"].as_str() {
            let _ = std::fs::create_dir_all(dest.join(cname));
        }
    }
    additional_props.extend(new_props);
    ref_collections.extend(new_refs);

    // ── Introduction message ─────────────────────────────────────────────────
    println!("\n--- Introduction message (current: {:?}) ---", intro_message);
    if prompt_bool("Update?") {
        let default = if intro_message.is_empty() { main_collection.clone() } else { intro_message.clone() };
        intro_message = prompt("  New message", &default);
    }

    // ── Column validations ───────────────────────────────────────────────────
    if !additional_props.is_empty() {
        println!("\n--- Column validations ---");
        for prop in additional_props.iter_mut() {
            let col_name = prop["property_name"].as_str().unwrap_or("").to_string();
            let current_vtype = prop["validation_type"].as_str().unwrap_or("NONE").to_string();
            let ml_note = if prop.get("multiline").and_then(|v| v.as_bool()).unwrap_or(false) { ", multiline" } else { "" };
            if prompt_bool(&format!("  Change validation for '{col_name}' (currently: {current_vtype}{ml_note})?")) {
                println!("  Validation options: none, not_empty, hh:mm, mm/dd, int, yyyy, re:<pattern>");
                let new_vtype = parse_vtype(&prompt("  New validation type", "none"));
                prop["validation_type"] = serde_json::Value::String(new_vtype);
            }
        }
    }

    // ── Write back ───────────────────────────────────────────────────────────
    let all_col_names: Vec<String> = additional_props.iter()
        .filter_map(|p| p["property_name"].as_str().map(|s| s.to_string()))
        .chain(ref_collections.iter().filter_map(|r| r["property_name"].as_str().map(|s| s.to_string())))
        .collect();

    let property_order_str = if !existing_order.is_empty() {
        let seen: std::collections::HashSet<String> = existing_order.iter().cloned().collect();
        let mut updated = existing_order.clone();
        updated.extend(all_col_names.iter().filter(|c| !seen.contains(*c)).cloned());
        updated.join(", ")
    } else {
        String::new()
    };

    let mut repo_ini = format!(
        "[main_collection]\ncollection_name = {main_collection}\npartitioning_property = {partitioning_property}\n"
    );
    if !property_order_str.is_empty() {
        repo_ini.push_str(&format!("property_order = {property_order_str}\n"));
    }
    repo_ini.push_str(&format!("\n[introduction]\nmessage = {intro_message}\n"));

    let _ = std::fs::write(dest.join("repository.ini"), &repo_ini);
    let _ = std::fs::write(
        dest.join("additional_properties.json"),
        serde_json::to_string_pretty(&serde_json::Value::Array(additional_props)).unwrap() + "\n",
    );
    let _ = std::fs::write(
        dest.join("reference_collections.json"),
        serde_json::to_string_pretty(&serde_json::Value::Array(ref_collections)).unwrap() + "\n",
    );

    println!("\nupdated: {}", dest.display());
}

// ── appenditems / searchitems / removeitems ────────────────────────────────────

// ---- filter ---------------------------------------------------------------

enum FilterToken {
    And,
    Or,
    Cond { col: String, op: FilterOp, val: String },
}

enum FilterOp { Eq, Like }

enum ItemFilter {
    MatchAll,
    Exact { col: String, val: String },
    Like { col: String, re: regex::Regex },
    And(Box<ItemFilter>, Box<ItemFilter>),
    Or(Box<ItemFilter>, Box<ItemFilter>),
}

impl ItemFilter {
    fn matches(&self, sec: &serde_json::Map<String, serde_json::Value>) -> bool {
        match self {
            ItemFilter::MatchAll => true,
            ItemFilter::Exact { col, val } =>
                sec.get(col).and_then(|v| v.as_str()).unwrap_or("").to_lowercase()
                    == val.to_lowercase(),
            ItemFilter::Like { col, re } =>
                re.is_match(sec.get(col).and_then(|v| v.as_str()).unwrap_or("")),
            ItemFilter::And(a, b) => a.matches(sec) && b.matches(sec),
            ItemFilter::Or(a, b)  => a.matches(sec) || b.matches(sec),
        }
    }
    fn matches_value(&self, val: &str) -> bool {
        let mut m = serde_json::Map::new();
        m.insert("values".to_string(), serde_json::Value::String(val.to_string()));
        self.matches(&m)
    }
}

fn like_to_regex(pattern: &str) -> regex::Regex {
    let mut re = "(?is)^".to_string();
    for ch in pattern.chars() {
        match ch {
            '%' => re.push_str(".*"),
            '_' => re.push('.'),
            c   => re.push_str(&regex::escape(&c.to_string())),
        }
    }
    re.push('$');
    regex::Regex::new(&re).unwrap_or_else(|_| regex::Regex::new("(?is)^$").unwrap())
}

fn word_boundary_at(s: &str) -> bool {
    s.is_empty() || s.starts_with(|c: char| c.is_whitespace() || c == '`' || c == '\'' || c == '"')
}

fn tokenize_item_filter(query: &str) -> Vec<FilterToken> {
    let cond_re = regex::Regex::new(
        r#"(?i)^`([^`]+)`\s*(=|like)\s*(?:'([^']*)'|"([^"]*)")"#
    ).unwrap();
    let mut tokens = vec![];
    let mut rest = query;
    loop {
        rest = rest.trim_start();
        if rest.is_empty() { break; }
        let lower4: String = rest.chars().take(4).flat_map(|c| c.to_lowercase()).collect();
        if lower4.starts_with("and") && word_boundary_at(&rest[3..]) {
            tokens.push(FilterToken::And);
            rest = &rest[3..];
            continue;
        }
        if lower4.starts_with("or") && word_boundary_at(&rest[2..]) {
            tokens.push(FilterToken::Or);
            rest = &rest[2..];
            continue;
        }
        if let Some(caps) = cond_re.captures(rest) {
            let col = caps[1].to_lowercase();
            let op_str = caps[2].to_lowercase();
            let val = caps.get(3).or_else(|| caps.get(4))
                .map(|m| m.as_str().to_string()).unwrap_or_default();
            let op = if op_str == "like" { FilterOp::Like } else { FilterOp::Eq };
            tokens.push(FilterToken::Cond { col, op, val });
            rest = &rest[caps[0].len()..];
            continue;
        }
        let mut chars = rest.chars();
        chars.next();
        rest = chars.as_str();
    }
    tokens
}

fn parse_item_factor(tokens: &[FilterToken], pos: &mut usize) -> ItemFilter {
    if *pos >= tokens.len() { return ItemFilter::MatchAll; }
    match &tokens[*pos] {
        FilterToken::Cond { col, op, val } => {
            let (col, val) = (col.clone(), val.clone());
            let f = match op {
                FilterOp::Eq   => ItemFilter::Exact { col, val },
                FilterOp::Like => ItemFilter::Like  { col, re: like_to_regex(&val) },
            };
            *pos += 1;
            f
        }
        _ => { *pos += 1; ItemFilter::MatchAll }
    }
}

fn parse_item_and_expr(tokens: &[FilterToken], pos: &mut usize) -> ItemFilter {
    let mut left = parse_item_factor(tokens, pos);
    while *pos < tokens.len() && matches!(&tokens[*pos], FilterToken::And) {
        *pos += 1;
        let right = parse_item_factor(tokens, pos);
        left = ItemFilter::And(Box::new(left), Box::new(right));
    }
    left
}

fn parse_item_or_expr(tokens: &[FilterToken], pos: &mut usize) -> ItemFilter {
    let mut left = parse_item_and_expr(tokens, pos);
    while *pos < tokens.len() && matches!(&tokens[*pos], FilterToken::Or) {
        *pos += 1;
        let right = parse_item_and_expr(tokens, pos);
        left = ItemFilter::Or(Box::new(left), Box::new(right));
    }
    left
}

fn parse_json_item_filter(obj: &serde_json::Map<String, serde_json::Value>) -> ItemFilter {
    if obj.is_empty() { return ItemFilter::MatchAll; }
    let filters: Vec<ItemFilter> = obj.iter().map(|(col, val)| {
        let col = col.to_lowercase();
        let val_str = val.as_str().unwrap_or("").to_string();
        if val_str.contains('%') || val_str.contains('_') {
            ItemFilter::Like { col, re: like_to_regex(&val_str) }
        } else {
            ItemFilter::Exact { col, val: val_str }
        }
    }).collect();
    filters.into_iter().reduce(|a, b| ItemFilter::And(Box::new(a), Box::new(b)))
        .unwrap_or(ItemFilter::MatchAll)
}

fn strip_comments(text: &str) -> String {
    text.lines()
        .filter(|l| !l.trim_start().starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n")
}

fn resolve_filter(raw: &str, json_mode: bool) -> Result<ItemFilter, String> {
    let text = strip_comments(raw);
    let text = text.trim();
    if json_mode {
        if text.is_empty() || text == "{}" {
            return Ok(ItemFilter::MatchAll);
        }
        match serde_json::from_str::<serde_json::Map<String, serde_json::Value>>(text) {
            Ok(obj) => Ok(parse_json_item_filter(&obj)),
            Err(e)  => Err(format!("invalid JSON: {e}")),
        }
    } else {
        if text.is_empty() {
            return Err("empty query".to_string());
        }
        let tokens = tokenize_item_filter(text);
        if !tokens.iter().any(|t| matches!(t, FilterToken::Cond { .. })) {
            return Err(
                "no valid conditions; expected syntax: `column`='value' or `column` like 'pat%'"
                    .to_string(),
            );
        }
        let mut pos = 0;
        Ok(parse_item_or_expr(&tokens, &mut pos))
    }
}

// ---- helpers --------------------------------------------------------------

fn open_editor_blocking(editor: &str, path: &Path) -> bool {
    match std::process::Command::new(editor).arg(path).status() {
        Ok(_)  => true,
        Err(e) => { eprintln!("error: could not open editor: {e}"); false }
    }
}

fn query_template(field_order: &[String], json_mode: bool, action: &str) -> String {
    let cols = if field_order.is_empty() { "values".to_string() } else { field_order.join(", ") };
    let action_desc = if action == "search" {
        "Matching sections/values will be printed as JSON."
    } else {
        "Matching sections/values will be removed and pushed."
    };
    if json_mode {
        let obj: serde_json::Map<String, serde_json::Value> = field_order.iter().take(2)
            .map(|c| (c.clone(), serde_json::Value::String(String::new())))
            .collect();
        let json_str = if obj.is_empty() {
            "{}".to_string()
        } else {
            serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
        };
        format!(
            "# JSON query: exact match by default; values with % or _ use LIKE.\n\
             # All keys are ANDed. Empty object {{}} matches everything.\n\
             # Columns: {cols}\n\
             # {action_desc}\n\
             # Delete these comment lines, then edit the JSON, save and close:\n\
             {json_str}\n"
        )
    } else {
        format!(
            "# Filter syntax: `column`='value' | `column` like 'pattern%'\n\
             # Combine with AND / OR. Lines starting with # are ignored.\n\
             # Columns: {cols}\n\
             # {action_desc}\n\
             # Write your query below, then save and close:\n"
        )
    }
}

// ---- commands -------------------------------------------------------------

pub fn cmd_appenditems(
    state: &RepoState,
    collection: &str,
    name: &str,
    editor: &str,
    json_mode: bool,
    stdin_content: Option<String>,
) {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return; }
    };
    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
    let encoded = encode_name(name);
    let dl_dir = state.downloads_dir.join(collection);
    let _ = std::fs::create_dir_all(&dl_dir);
    let dl_name_full = filepath.file_name().unwrap().to_string_lossy().into_owned();
    let dl_name = dl_name_full.strip_suffix(".gz").unwrap_or(&dl_name_full).to_string();
    let dest = dl_dir.join(&dl_name);

    if collection == state.main_collection {
        let content = match stdin_content {
            Some(s) => s,
            None => {
                let temp_path = dl_dir.join(format!("_append_{encoded}.txt"));
                let template = if json_mode {
                    format!("# Write new sections as a JSON array, then save and close:\n{}\n",
                            crate::formats::empty_main_collection_json(field_order).trim_end())
                } else {
                    format!("# Write new sections below (👉👈 format), then save and close:\n{}",
                            empty_main_collection_document(field_order))
                };
                let _ = std::fs::write(&temp_path, &template);
                if !open_editor_blocking(editor, &temp_path) { return; }
                std::fs::read_to_string(&temp_path).unwrap_or_default()
            }
        };
        let stripped = strip_comments(&content);

        let new_sections: Vec<serde_json::Value> = if json_mode {
            match serde_json::from_str::<serde_json::Value>(stripped.trim()) {
                Ok(v) => if let Some(arr) = v.as_array() { arr.clone() } else { vec![v] },
                Err(e) => { eprintln!("error: invalid JSON: {e}"); return; }
            }
        } else {
            text_to_sections(&stripped, field_order, &state.multiline_props)
                .into_iter().map(serde_json::Value::Object).collect()
        };
        if new_sections.is_empty() { println!("nothing to append"); return; }

        let bytes = std::fs::read(&filepath).unwrap_or_default();
        let mut existing: Vec<serde_json::Value> = gzip_decompress(&bytes)
            .ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default();
        if is_initial_state(&sections_to_text(&existing, field_order),
                            field_order, &state.multiline_props) {
            existing.clear();
        }
        let n_new = new_sections.len();
        existing.extend(new_sections);
        let _ = std::fs::write(&dest, sections_to_text(&existing, field_order));
        println!("appended {n_new} items");
        cmd_push(state, collection, name, false);
    } else {
        let content = match stdin_content {
            Some(s) => s,
            None => {
                let temp_path = dl_dir.join(format!("_append_{encoded}.txt"));
                let template = if json_mode {
                    "# Write new values as a JSON array, then save and close:\n[]\n".to_string()
                } else {
                    "# Enter new comma-separated values, then save and close:\n".to_string()
                };
                let _ = std::fs::write(&temp_path, &template);
                if !open_editor_blocking(editor, &temp_path) { return; }
                std::fs::read_to_string(&temp_path).unwrap_or_default()
            }
        };
        let stripped = strip_comments(&content);

        let new_values: Vec<String> = if json_mode {
            match serde_json::from_str::<serde_json::Value>(stripped.trim()) {
                Ok(v) => match v.as_array() {
                    Some(arr) => arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect(),
                    None => { eprintln!("error: expected a JSON array"); return; }
                },
                Err(e) => { eprintln!("error: invalid JSON: {e}"); return; }
            }
        } else {
            stripped.split(',').map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).collect()
        };
        if new_values.is_empty() { println!("nothing to append"); return; }

        let existing_raw = std::fs::read_to_string(&filepath).unwrap_or_default();
        let mut combined: Vec<String> = existing_raw.trim().split(',')
            .map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).collect();
        let n_new = new_values.len();
        combined.extend(new_values);
        let _ = std::fs::write(&dest,
            if combined.is_empty() { String::new() } else { combined.join(",") + "\n" });
        println!("appended {n_new} items");
        cmd_push(state, collection, name, false);
    }
}

pub fn cmd_searchitems(
    state: &RepoState,
    collection: &str,
    name: &str,
    editor: &str,
    json_mode: bool,
    stdin_content: Option<String>,
) {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return; }
    };
    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
    let raw = match stdin_content {
        Some(s) => s,
        None => {
            let _ = std::fs::create_dir_all(&state.downloads_dir);
            let query_path = state.downloads_dir
                .join(format!("_searchquery_{}_{}.txt", collection, name));
            let _ = std::fs::write(&query_path, query_template(field_order, json_mode, "search"));
            if !open_editor_blocking(editor, &query_path) { return; }
            std::fs::read_to_string(&query_path).unwrap_or_default()
        }
    };
    let filter = match resolve_filter(&raw, json_mode) {
        Ok(f)  => f,
        Err(e) => { eprintln!("error: {e}"); return; }
    };

    if collection == state.main_collection {
        let bytes = std::fs::read(&filepath).unwrap_or_default();
        let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
            .ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default();
        let matched: Vec<&serde_json::Value> = sections.iter()
            .filter(|s| s.as_object().map_or(false, |o| filter.matches(o)))
            .collect();
        println!("{}", serde_json::to_string_pretty(&matched).unwrap_or_default());
    } else {
        let raw_content = std::fs::read_to_string(&filepath).unwrap_or_default();
        let matched: Vec<&str> = raw_content.trim().split(',')
            .map(|v| v.trim()).filter(|v| !v.is_empty())
            .filter(|v| filter.matches_value(v))
            .collect();
        println!("{}", serde_json::to_string_pretty(&matched).unwrap_or_default());
    }
}

pub fn cmd_removeitems(
    state: &RepoState,
    collection: &str,
    name: &str,
    editor: &str,
    json_mode: bool,
    stdin_content: Option<String>,
) {
    let filepath = match find_latest(&state.repo_root, &state.main_collection, collection, name) {
        Some(p) => p,
        None => { eprintln!("error: not found: {name}"); return; }
    };
    let field_order = state.field_order.as_deref().unwrap_or(&state.additional_props);
    let raw = match stdin_content {
        Some(s) => s,
        None => {
            let _ = std::fs::create_dir_all(&state.downloads_dir);
            let query_path = state.downloads_dir
                .join(format!("_removequery_{}_{}.txt", collection, name));
            let _ = std::fs::write(&query_path, query_template(field_order, json_mode, "remove"));
            if !open_editor_blocking(editor, &query_path) { return; }
            std::fs::read_to_string(&query_path).unwrap_or_default()
        }
    };
    let filter = match resolve_filter(&raw, json_mode) {
        Ok(f)  => f,
        Err(e) => { eprintln!("error: {e}"); return; }
    };

    if collection == state.main_collection {
        let bytes = std::fs::read(&filepath).unwrap_or_default();
        let sections: Vec<serde_json::Value> = gzip_decompress(&bytes)
            .ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default();
        let remaining: Vec<serde_json::Value> = sections.iter()
            .filter(|s| !s.as_object().map_or(false, |o| filter.matches(o)))
            .cloned().collect();
        let n_removed = sections.len() - remaining.len();
        if n_removed == 0 { println!("no matching sections — nothing removed"); return; }

        let dl_dir = state.downloads_dir.join(collection);
        let _ = std::fs::create_dir_all(&dl_dir);
        let dl_name_full = filepath.file_name().unwrap().to_string_lossy().into_owned();
        let dl_name = dl_name_full.strip_suffix(".gz").unwrap_or(&dl_name_full);
        let _ = std::fs::write(dl_dir.join(dl_name), sections_to_text(&remaining, field_order));
        cmd_push(state, collection, name, false);
        println!("removed {n_removed} items");
    } else {
        let raw_content = std::fs::read_to_string(&filepath).unwrap_or_default();
        let values: Vec<String> = raw_content.trim().split(',')
            .map(|v| v.trim().to_string()).filter(|v| !v.is_empty()).collect();
        let remaining: Vec<String> = values.iter()
            .filter(|v| !filter.matches_value(v)).cloned().collect();
        let n_removed = values.len() - remaining.len();
        if n_removed == 0 { println!("no matching values — nothing removed"); return; }

        let dl_dir = state.downloads_dir.join(collection);
        let _ = std::fs::create_dir_all(&dl_dir);
        let dl_name_full = filepath.file_name().unwrap().to_string_lossy().into_owned();
        let _ = std::fs::write(
            dl_dir.join(&dl_name_full),
            if remaining.is_empty() { String::new() } else { remaining.join(",") + "\n" },
        );
        cmd_push(state, collection, name, false);
        println!("removed {n_removed} items");
    }
}

fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            copy_dir_all(&entry.path(), &dst.join(entry.file_name()))?;
        } else {
            std::fs::copy(entry.path(), dst.join(entry.file_name()))?;
        }
    }
    Ok(())
}
