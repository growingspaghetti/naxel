pub mod query;
pub mod table;

pub use crate::table_spec::TableData;

/// Open a table window synchronously (blocks until closed).
pub fn show_table(data: TableData) {
    if let Err(e) = table::run(data) {
        eprintln!("gui error: {e}");
    }
}
