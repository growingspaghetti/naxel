mod formats;
mod gui;
mod table_spec;

fn main() {
    use std::io::Read;
    let mut json = String::new();
    std::io::stdin().read_to_string(&mut json).expect("read stdin");
    let data: table_spec::TableData = match serde_json::from_str(&json) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("error: invalid table data: {e}");
            std::process::exit(1);
        }
    };
    gui::show_table(data);
}
