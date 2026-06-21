use crate::table_spec::{PushInfo, TableData};
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
        TableData::Csv { title, .. }      => title.clone(),
        TableData::MainText { title, .. } => title.clone(),
        TableData::Ref { title, .. }      => title.clone(),
        TableData::Diff { title, .. }     => title.clone(),
    };

    tauri::Builder::default()
        .manage(AppState { data: Mutex::new(Some(data)) })
        .invoke_handler(tauri::generate_handler![get_table_data, read_file, save_file, save_and_push])
        .setup(move |app| {
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title(title.as_str())
            .inner_size(960.0, 540.0)
            .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run tauri");
}
