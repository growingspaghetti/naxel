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
            let name_col = format!("{}_name", state.partitioning_property);
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
        let name_col = format!("{}_name", state.partitioning_property);
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
