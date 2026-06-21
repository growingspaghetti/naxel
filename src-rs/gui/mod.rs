use crate::table_spec::TableData;
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

pub fn show_table(data: TableData) {
    let title = match &data {
        TableData::Csv { title, .. }      => title.clone(),
        TableData::MainText { title, .. } => title.clone(),
        TableData::Ref { title, .. }      => title.clone(),
        TableData::Diff { title, .. }     => title.clone(),
    };

    tauri::Builder::default()
        .manage(AppState { data: Mutex::new(Some(data)) })
        .invoke_handler(tauri::generate_handler![get_table_data, read_file, save_file])
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
