use std::collections::{HashMap, HashSet};

use crate::formats::{is_prop_label, SEPARATOR};

pub fn validate_main_collection(
    content: &str,
    field_order: &[String],
    mandatory_prop_names: &HashSet<String>,
    prop_validation_types: &HashMap<String, String>,
    multiline_props: &HashSet<String>,
) -> Result<(), String> {
    let lines: Vec<&str> = content.lines().collect();
    let n = lines.len();
    let mut i = 0;
    let mut section_count = 0;

    while i < n {
        if lines[i] != SEPARATOR {
            return Err(format!("line {}: expected separator", i + 1));
        }
        i += 1;

        for key in field_order {
            let label = format!("👉{key}👈");
            if i >= n || lines[i] != label {
                return Err(format!("line {}: expected {label:?}", i + 1));
            }
            i += 1;
            if multiline_props.contains(key) {
                while i < n && lines[i] != SEPARATOR && !is_prop_label(lines[i]) {
                    i += 1;
                }
            } else {
                if i >= n {
                    return Err(format!("line {}: missing value for {key:?}", i + 1));
                }
                let val = lines[i];
                if mandatory_prop_names.contains(key) {
                    if val.trim().is_empty() {
                        return Err(format!("line {}: value for {key:?} is required", i + 1));
                    }
                } else if let Some(vtype) = prop_validation_types.get(key) {
                    check_value_type(val, vtype, key, i + 1)?;
                }
                i += 1;
            }
        }
        section_count += 1;
    }

    if section_count == 0 {
        return Err("no sections found".into());
    }
    Ok(())
}

fn check_value_type(val: &str, vtype: &str, key: &str, line_no: usize) -> Result<(), String> {
    match vtype {
        "NOT_EMPTY" => {
            if val.trim().is_empty() {
                return Err(format!("line {line_no}: value for {key:?} is required"));
            }
        }
        "HH:MM" => {
            if !regex::Regex::new(r"^\d{2}:\d{2}$").unwrap().is_match(val) {
                return Err(format!("line {line_no}: value for {key:?} must be HH:MM (got {val:?})"));
            }
        }
        "MM/DD" => {
            if !regex::Regex::new(r"^\d{2}/\d{2}$").unwrap().is_match(val) {
                return Err(format!("line {line_no}: value for {key:?} must be MM/DD (got {val:?})"));
            }
        }
        "INT" => {
            if !regex::Regex::new(r"^[0-9]+$").unwrap().is_match(val) {
                return Err(format!("line {line_no}: value for {key:?} must be an integer (got {val:?})"));
            }
        }
        "YYYY" => {
            if !regex::Regex::new(r"^\d{4}$").unwrap().is_match(val) {
                return Err(format!("line {line_no}: value for {key:?} must be YYYY (got {val:?})"));
            }
        }
        vt if vt.starts_with("RE:") => {
            let pattern = &vt[3..];
            let re = regex::Regex::new(&format!("^(?:{pattern})$"))
                .map_err(|e| format!("invalid regex {pattern:?}: {e}"))?;
            if !re.is_match(val) {
                return Err(format!(
                    "line {line_no}: value for {key:?} must match /{pattern}/ (got {val:?})"
                ));
            }
        }
        _ => {}
    }
    Ok(())
}

pub fn validate_dates(content: &str) -> Result<(), String> {
    let re = regex::Regex::new(r"^\d{4}/\d{2}/\d{2}(,\d{4}/\d{2}/\d{2})*\n?$").unwrap();
    if re.is_match(content) { Ok(()) }
    else { Err("expected: yyyy/mm/dd,yyyy/mm/dd,... (one line)".into()) }
}

pub fn validate_phone_numbers(content: &str) -> Result<(), String> {
    let re = regex::Regex::new(r"^[0-9\-\+]+(,[0-9\-\+]+)*\n?$").unwrap();
    if re.is_match(content) { Ok(()) }
    else { Err("expected: digits/dashes/plus signs separated by commas (one line)".into()) }
}

pub fn validate_email(content: &str) -> Result<(), String> {
    let seg = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}";
    let re = regex::Regex::new(&format!("^{seg}(,{seg})*\n?$")).unwrap();
    if re.is_match(content) { Ok(()) }
    else { Err("expected: email@domain.tld,email2@domain.tld,... (one line)".into()) }
}

pub fn validate_years(content: &str) -> Result<(), String> {
    let re = regex::Regex::new(r"^\d{4}(,\d{4})*\n?$").unwrap();
    if re.is_match(content) { Ok(()) }
    else { Err("expected: yyyy,yyyy,... (one line)".into()) }
}

pub fn validate_ref_collection(collection_type: &str, content: &str) -> Result<(), String> {
    match collection_type {
        "DATE" => validate_dates(content),
        "PHONE_NUMBER" => validate_phone_numbers(content),
        "EMAIL" => validate_email(content),
        "YEAR" => validate_years(content),
        _ => Ok(()),
    }
}
