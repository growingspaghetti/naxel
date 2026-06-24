use crate::table_spec::{NxInfo, PushInfo, TableData};
use std::sync::Mutex;

pub struct AppState {
    data: Mutex<Option<TableData>>,
}

#[tauri::command]
fn get_table_data(state: tauri::State<AppState>) -> Option<TableData> {
    state.data.lock().unwrap().clone()
}

#[tauri::command]
fn read_file(path: String) -> Result<String, String> {
    std::fs::read_to_string(&path).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_file(path: String, content: String) -> Result<(), String> {
    std::fs::write(&path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn submit_text_edit(state: tauri::State<AppState>, path: String, content: String) -> Result<String, String> {
    std::fs::write(&path, &content).map_err(|e| e.to_string())?;
    let context = {
        let data = state.data.lock().unwrap();
        match data.as_ref() {
            Some(TableData::TextEdit { context, .. }) => context.clone(),
            _ => return Err("invalid state".to_string()),
        }
    };
    let result = crate::commands::process_text_edit_submit(&context, &content);
    match &result {
        Ok(msg)  => println!("{msg}"),
        Err(msg) => eprintln!("{msg}"),
    }
    result
}

#[tauri::command]
fn cancel_text_edit(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn save_and_push(state: tauri::State<AppState>, path: String, content: String) -> Result<(), String> {
    std::fs::write(&path, &content).map_err(|e| e.to_string())?;
    let push_info = {
        let data = state.data.lock().unwrap();
        match data.as_ref() {
            Some(TableData::MainText { push_info, .. }) => push_info.clone(),
            Some(TableData::Ref { push_info, .. }) => push_info.clone(),
            _ => None,
        }
    };
    if let Some(info) = push_info {
        do_push(&info);
    }
    Ok(())
}

#[tauri::command]
fn get_nx_names(state: tauri::State<AppState>, collection: String) -> Result<Vec<String>, String> {
    let nx_info = {
        let data = state.data.lock().unwrap();
        match data.as_ref() {
            Some(TableData::Nx { nx_info, .. }) => nx_info.clone(),
            _ => return Err("not in nx mode".to_string()),
        }
    };
    Ok(crate::commands::ls_names(&nx_info.repo_root, &nx_info.main_collection, &collection))
}

#[tauri::command]
fn run_nx_cmd(
    state: tauri::State<AppState>,
    cmd: String,
    collection: String,
    name: String,
    jtable: bool,
) -> Result<(), String> {
    let nx_info = {
        let data = state.data.lock().unwrap();
        match data.as_ref() {
            Some(TableData::Nx { nx_info, .. }) => nx_info.clone(),
            _ => return Err("not in nx mode".to_string()),
        }
    };

    let repo_name = nx_info.repo_root.file_name().unwrap_or_default().to_string_lossy();
    let cmd_str = if jtable {
        format!("{cmd} {collection} {name} --jtable")
    } else {
        format!("{cmd} {collection} {name}")
    };
    println!("\r{repo_name} > {cmd_str}");

    let mini_state = nx_info_to_state(&nx_info, &collection);

    let td = match cmd.as_str() {
        "cat" => crate::commands::cmd_cat(&mini_state, &collection, &name, jtable, false, None),
        "get" => crate::commands::cmd_get(&mini_state, &collection, &name, &nx_info.editor, jtable, None),
        "diff" => crate::commands::cmd_diff(&mini_state, &collection, &name, jtable),
        _ => return Err(format!("unknown nx sub-command: {cmd}")),
    };

    if let Some(td) = td {
        spawn_nx_table(td);
    }
    Ok(())
}

fn spawn_nx_table(td: TableData) {
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
    std::thread::spawn(move || { let _ = child.wait(); });
}

fn nx_info_to_state(nx_info: &NxInfo, collection: &str) -> crate::repo::RepoState {
    use crate::repo::{MandatoryRefProp, RepoState};
    use std::collections::HashSet;
    let mut collections = HashSet::new();
    for k in nx_info.collection_type.keys() {
        collections.insert(k.clone());
    }
    collections.insert(nx_info.main_collection.clone());
    collections.insert(collection.to_string());
    RepoState {
        repo_root: nx_info.repo_root.clone(),
        downloads_dir: nx_info.downloads_dir.clone(),
        cache_dir: nx_info.cache_dir.clone(),
        main_collection: nx_info.main_collection.clone(),
        partitioning_property: String::new(),
        collections,
        collection_type: nx_info.collection_type.clone(),
        additional_props: nx_info.additional_props.clone(),
        mandatory_ref_props: nx_info.mandatory_ref_props.iter().map(|m| MandatoryRefProp {
            property_name: m.property_name.clone(),
            collection_name: m.collection_name.clone(),
            whitelist: m.whitelist.iter().cloned().collect(),
        }).collect(),
        field_order: nx_info.field_order.clone(),
        prop_validation_types: nx_info.prop_validation_types.clone(),
        multiline_props: nx_info.multiline_props.iter().cloned().collect(),
        intro_message: String::new(),
    }
}

fn do_push(info: &PushInfo) {
    use crate::repo::{MandatoryRefProp, RepoState};
    use std::collections::HashSet;
    let mini_state = RepoState {
        repo_root: info.repo_root.clone(),
        downloads_dir: info.downloads_dir.clone(),
        cache_dir: std::path::PathBuf::new(),
        main_collection: info.main_collection.clone(),
        partitioning_property: String::new(),
        collections: HashSet::new(),
        collection_type: info.collection_type.clone(),
        additional_props: info.additional_props.clone(),
        mandatory_ref_props: info.mandatory_ref_props.iter().map(|m| MandatoryRefProp {
            property_name: m.property_name.clone(),
            collection_name: m.collection_name.clone(),
            whitelist: m.whitelist.iter().cloned().collect(),
        }).collect(),
        field_order: info.field_order.clone(),
        prop_validation_types: info.prop_validation_types.clone(),
        multiline_props: info.multiline_props.iter().cloned().collect(),
        intro_message: String::new(),
    };
    crate::commands::cmd_push(&mini_state, &info.collection, &info.name, false);
}

pub fn show_table(data: TableData) {
    let title = match &data {
        TableData::Nx { .. }              => "nx".to_string(),
        TableData::Csv { title, .. }      => title.clone(),
        TableData::MainText { title, .. } => title.clone(),
        TableData::Ref { title, .. }      => title.clone(),
        TableData::Diff { title, .. }     => title.clone(),
        TableData::TextEdit { title, .. } => title.clone(),
    };
    let (width, height) = match &data {
        TableData::Nx { .. }       => (360.0_f64, 480.0_f64),
        TableData::TextEdit { .. } => (700.0_f64, 500.0_f64),
        _                          => (960.0_f64, 540.0_f64),
    };

    tauri::Builder::default()
        .manage(AppState { data: Mutex::new(Some(data)) })
        .invoke_handler(tauri::generate_handler![
            get_table_data, read_file, save_file, save_and_push,
            submit_text_edit, cancel_text_edit,
            get_nx_names, run_nx_cmd
        ])
        .setup(move |app| {
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title(title.as_str())
            .inner_size(width, height)
            .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run tauri");
}
