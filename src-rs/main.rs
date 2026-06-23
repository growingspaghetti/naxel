mod config;
mod encoding;
mod formats;
mod repo;
mod validation;
mod commands;
mod table_spec;
mod gui;

use std::path::Path;

use config::load_app_config;
use repo::{initialize_repo, sync_cache, RepoState};
use commands::*;
use table_spec::TableData;

fn usage(state: &RepoState) {
    let mut colls: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
    colls.sort();
    println!(
        "commands:\n  cd <path>\n  ls <collection>\n  add <collection> <name>\n  del <collection> <name>\n  cat <collection> <name> [--version=N] [--jtable] [--json]\n  get <collection> <name> [--jtable] [-]\n  clear <collection> <name> [--jtable]\n  len <collection> <name>\n  push <collection> <name>\n  export <collection> <file.csv|file.json> [--jtable]\n  diff <collection> <name> [--jtable]\n  appenditems <collection> <name> [-] [--json]\n  searchitems <collection> <name> [-] [--json]\n  removeitems <collection> <name> [-] [--json]\n  fullcopy <destination-directory> [--json]\n  mkrepo <json-file> <destination-directory>\n  partialcopy <collection> <name> <destination-directory> [--json]\n  nx\n  exit\ncollections: {}",
        colls.join(", ")
    );
}

fn do_cd(
    path_str: &str,
    downloads_base: &Path,
    cache_base: &Path,
    require_repo_ini: bool,
) -> Option<RepoState> {
    let new_path = match std::fs::canonicalize(path_str) {
        Ok(p) => p,
        Err(_) => { eprintln!("error: not a directory: {path_str}"); return None; }
    };
    if !new_path.is_dir() {
        eprintln!("error: not a directory: {}", new_path.display());
        return None;
    }
    if require_repo_ini && !new_path.join("repository.ini").exists() {
        eprintln!("error: not a repository (no repository.ini): {}", new_path.display());
        return None;
    }
    let state = initialize_repo(&new_path, downloads_base, cache_base);
    sync_cache(&state);
    if !state.intro_message.is_empty() {
        println!("{}", state.intro_message);
    }
    println!("switched to: {}", state.repo_root.display());
    Some(state)
}

fn spawn_table(td: TableData) {
    let exe = std::env::current_exe()
        .unwrap_or_else(|_| std::path::PathBuf::from("naxel"));
    let json = match serde_json::to_string(&td) {
        Ok(j) => j,
        Err(e) => { eprintln!("error: failed to serialize table data: {e}"); return; }
    };
    use std::io::Write;
    use std::process::{Command, Stdio};
    let mut child = match Command::new(&exe)
        .arg("--table")
        .stdin(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => { eprintln!("error: failed to spawn table window: {e}"); return; }
    };
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(json.as_bytes());
    }
    // Fire-and-forget: reap in background thread to avoid zombies
    std::thread::spawn(move || { let _ = child.wait(); });
}

fn dispatch(parts: &[&str], state: &RepoState, editor: &str) -> Option<Option<TableData>> {
    let cmd = parts[0];

    if cmd == "exit" { return None; }

    let needs_collection = matches!(
        cmd,
        "ls" | "add" | "del" | "cat" | "get" | "clear" | "len" | "push" | "export" | "diff"
        | "partialcopy" | "appenditems" | "searchitems" | "removeitems"
    );

    let collection = if needs_collection {
        if parts.len() < 2 {
            eprintln!("error: missing collection");
            return Some(None);
        }
        let coll = parts[1];
        if !state.collections.contains(coll) {
            let mut choices: Vec<&str> = state.collections.iter().map(|s| s.as_str()).collect();
            choices.sort();
            eprintln!("error: unknown collection '{coll}' (choices: {})", choices.join(", "));
            return Some(None);
        }
        coll
    } else {
        ""
    };

    let field_order: &[String] = state.field_order.as_deref()
        .unwrap_or(&state.additional_props);

    let table_data: Option<TableData> = match cmd {
        "ls" => {
            if parts.len() != 2 { eprintln!("usage: ls <collection>"); }
            else { cmd_ls(&state.repo_root, &state.main_collection, collection); }
            None
        }
        "add" => {
            if parts.len() != 3 { eprintln!("usage: add <collection> <name>"); }
            else { cmd_add(&state.repo_root, &state.main_collection, collection, parts[2], field_order); }
            None
        }
        "del" => {
            if parts.len() != 3 { eprintln!("usage: del <collection> <name>"); }
            else { cmd_del(&state.repo_root, &state.main_collection, collection, parts[2], &state.cache_dir); }
            None
        }
        "cat" => {
            let jtable = parts.contains(&"--jtable");
            let as_json = parts.contains(&"--json");
            let version_flag = parts.iter().find(|p| p.starts_with("--version=")).copied();
            let version: Option<String> = version_flag.map(|p| {
                let raw = &p["--version=".len()..];
                raw.parse::<u32>().map(|n| format!("{n:04}")).unwrap_or_else(|_| raw.to_string())
            });
            let real_parts: Vec<&str> = parts.iter()
                .filter(|&&p| p != "--jtable" && p != "--json" && !p.starts_with("--version="))
                .copied().collect();
            if real_parts.len() != 3 { eprintln!("usage: cat <collection> <name> [--version=N] [--jtable] [--json]"); None }
            else if jtable && as_json { eprintln!("error: --jtable and --json are mutually exclusive"); None }
            else { cmd_cat(state, collection, real_parts[2], jtable, as_json, version.as_deref()) }
        }
        "get" => {
            let jtable = parts.contains(&"--jtable");
            let stdin_flag = parts.contains(&"-");
            let real_parts: Vec<&str> = parts.iter()
                .filter(|&&p| p != "--jtable" && p != "-")
                .copied()
                .collect();
            if real_parts.len() != 3 { eprintln!("usage: get <collection> <name> [--jtable] [-]"); None }
            else {
                let stdin_content = if stdin_flag {
                    use std::io::Read;
                    let mut s = String::new();
                    std::io::stdin().read_to_string(&mut s).ok();
                    Some(s)
                } else {
                    None
                };
                cmd_get(state, collection, real_parts[2], editor, jtable, stdin_content)
            }
        }
        "clear" => {
            let jtable = parts.contains(&"--jtable");
            let real_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--jtable").copied().collect();
            if real_parts.len() != 3 { eprintln!("usage: clear <collection> <name> [--jtable]"); None }
            else { cmd_clear(state, collection, real_parts[2], editor, jtable) }
        }
        "len" => {
            if parts.len() != 3 { eprintln!("usage: len <collection> <name>"); }
            else { cmd_len(&state.repo_root, &state.main_collection, collection, parts[2]); }
            None
        }
        "push" => {
            let as_json = parts.contains(&"--json");
            let push_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--json").copied().collect();
            if push_parts.len() != 3 { eprintln!("usage: push <collection> <name> [--json]"); }
            else { cmd_push(state, collection, push_parts[2], as_json); }
            None
        }
        "export" => {
            let jtable = parts.contains(&"--jtable");
            let real_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--jtable").copied().collect();
            if real_parts.len() != 3 {
                eprintln!("usage: export <collection> <file.csv|file.json> [--jtable]");
                None
            } else {
                cmd_export(state, collection, real_parts[2], editor, jtable)
            }
        }
        "diff" => {
            let jtable = parts.contains(&"--jtable");
            let real_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--jtable").copied().collect();
            if real_parts.len() != 3 { eprintln!("usage: diff <collection> <name> [--jtable]"); None }
            else { cmd_diff(state, collection, real_parts[2], jtable) }
        }
        "appenditems" => {
            let json_mode = parts.contains(&"--json");
            let stdin_flag = parts.contains(&"-");
            let real_parts: Vec<&str> = parts.iter()
                .filter(|&&p| p != "--json" && p != "-").copied().collect();
            if real_parts.len() != 3 {
                eprintln!("usage: appenditems <collection> <name> [-] [--json]");
            } else {
                let stdin_content = if stdin_flag {
                    use std::io::Read;
                    let mut s = String::new();
                    std::io::stdin().read_to_string(&mut s).ok();
                    Some(s)
                } else { None };
                cmd_appenditems(state, collection, real_parts[2], json_mode, stdin_content);
            }
            None
        }
        "searchitems" => {
            let json_mode = parts.contains(&"--json");
            let stdin_flag = parts.contains(&"-");
            let real_parts: Vec<&str> = parts.iter()
                .filter(|&&p| p != "--json" && p != "-").copied().collect();
            if real_parts.len() != 3 {
                eprintln!("usage: searchitems <collection> <name> [-] [--json]");
            } else {
                let stdin_content = if stdin_flag {
                    use std::io::Read;
                    let mut s = String::new();
                    std::io::stdin().read_to_string(&mut s).ok();
                    Some(s)
                } else { None };
                cmd_searchitems(state, collection, real_parts[2], json_mode, stdin_content);
            }
            None
        }
        "removeitems" => {
            let json_mode = parts.contains(&"--json");
            let stdin_flag = parts.contains(&"-");
            let real_parts: Vec<&str> = parts.iter()
                .filter(|&&p| p != "--json" && p != "-").copied().collect();
            if real_parts.len() != 3 {
                eprintln!("usage: removeitems <collection> <name> [-] [--json]");
            } else {
                let stdin_content = if stdin_flag {
                    use std::io::Read;
                    let mut s = String::new();
                    std::io::stdin().read_to_string(&mut s).ok();
                    Some(s)
                } else { None };
                cmd_removeitems(state, collection, real_parts[2], json_mode, stdin_content);
            }
            None
        }
        "fullcopy" => {
            let json_mode = parts.contains(&"--json");
            let real_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--json").copied().collect();
            if real_parts.len() != 2 { eprintln!("usage: fullcopy <destination-directory> [--json]"); }
            else { cmd_fullcopy(state, real_parts[1], json_mode); }
            None
        }
        "mkrepo" => {
            if parts.len() != 3 { eprintln!("usage: mkrepo <json-file> <destination-directory>"); }
            else { cmd_mkrepo(parts[1], parts[2]); }
            None
        }
        "partialcopy" => {
            let json_mode = parts.contains(&"--json");
            let real_parts: Vec<&str> = parts.iter().filter(|&&p| p != "--json").copied().collect();
            if real_parts.len() != 4 {
                eprintln!("usage: partialcopy <collection> <name> <destination-directory> [--json]");
            } else {
                cmd_partialcopy(state, collection, real_parts[2], real_parts[3], json_mode);
            }
            None
        }
        "nx" => {
            if parts.len() != 1 { eprintln!("usage: nx"); None }
            else { cmd_nx(state, editor) }
        }
        _ => {
            eprintln!("unknown command: {cmd:?}");
            None
        }
    };

    Some(table_data)
}

fn main() {
    // Table-window mode: re-spawned by the REPL with --table, reads TableData JSON from stdin.
    let raw_args: Vec<String> = std::env::args().skip(1).collect();
    if raw_args.first().map(|s| s == "--table").unwrap_or(false) {
        use std::io::Read;
        let mut json = String::new();
        std::io::stdin().read_to_string(&mut json).expect("read stdin");
        let data: table_spec::TableData = match serde_json::from_str(&json) {
            Ok(d) => d,
            Err(e) => { eprintln!("error: invalid table data: {e}"); std::process::exit(1); }
        };
        gui::show_table(data);
        return;
    }

    if raw_args.first().map(|s| s == "init").unwrap_or(false) {
        if raw_args.len() != 2 {
            eprintln!("usage: naxel init <destination-directory>");
            std::process::exit(1);
        }
        cmd_init(&raw_args[1]);
        return;
    }

    if raw_args.first().map(|s| s == "update").unwrap_or(false) {
        if raw_args.len() != 2 {
            eprintln!("usage: naxel update <destination-directory>");
            std::process::exit(1);
        }
        cmd_update(&raw_args[1]);
        return;
    }

    let script_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));

    // Find the project root (parent of src-rs/target)
    let project_dir = {
        // walk up until we find settings.ini or Cargo.toml
        let mut d = script_dir.clone();
        loop {
            if d.join("settings.ini").exists() || d.join("Cargo.toml").exists() {
                break;
            }
            match d.parent() {
                Some(p) => d = p.to_path_buf(),
                None => { d = std::env::current_dir().unwrap_or_default(); break; }
            }
        }
        d
    };

    let cfg = load_app_config(&project_dir);
    let downloads_base = project_dir.join("downloads");
    let cache_base = project_dir.join("cache");
    let editor = cfg.editor.clone();

    let mut state = initialize_repo(&cfg.repo_root, &downloads_base, &cache_base);

    let args = raw_args;
    if args.first().map(|s| s == "-c").unwrap_or(false) {
        if args.len() < 2 {
            eprintln!("error: -c requires a command string");
            std::process::exit(1);
        }
        sync_cache(&state);
        for raw in args[1].split("&&") {
            let raw = raw.trim();
            if raw.is_empty() { continue; }
            let parts: Vec<&str> = raw.split_whitespace().collect();
            if parts.is_empty() { continue; }
            if parts[0] == "cd" {
                if parts.len() != 2 { eprintln!("error: cd requires a path"); continue; }
                if let Some(s) = do_cd(parts[1], &downloads_base, &cache_base, false) {
                    state = s;
                }
                continue;
            }
            match dispatch(&parts, &state, &editor) {
                None => break,
                Some(Some(td)) => spawn_table(td),
                Some(None) => {}
            }
        }
        return;
    }

    println!("naxel  repository={}", state.repo_root.display());
    sync_cache(&state);
    if !state.intro_message.is_empty() {
        println!("{}", state.intro_message);
    }
    println!("Type 'help' for usage or 'exit' to quit.\n");

    let mut rl = rustyline::DefaultEditor::new().expect("readline init");

    loop {
        let prompt = format!("{} > ", state.repo_root.file_name().unwrap_or_default().to_string_lossy());
        let line = match rl.readline(&prompt) {
            Ok(l) => l,
            Err(rustyline::error::ReadlineError::Interrupted)
            | Err(rustyline::error::ReadlineError::Eof) => {
                println!();
                break;
            }
            Err(e) => { eprintln!("error: {e}"); break; }
        };
        let line = line.trim();
        if line.is_empty() { continue; }
        let _ = rl.add_history_entry(line);

        if line == "help" { usage(&state); continue; }

        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() { continue; }

        if parts[0] == "cd" {
            if parts.len() != 2 { eprintln!("usage: cd <path>"); }
            else if let Some(s) = do_cd(parts[1], &downloads_base, &cache_base, true) {
                state = s;
            }
            continue;
        }

        match dispatch(&parts, &state, &editor) {
            None => break,
            Some(Some(td)) => spawn_table(td),
            Some(None) => {}
        }
    }
}
