use std::collections::HashSet;

pub const SEPARATOR: &str = "🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔";

pub fn is_prop_label(line: &str) -> bool {
    line.starts_with('👉') && line.ends_with('👈') && line != SEPARATOR
}

pub fn label_name(line: &str) -> &str {
    // strip leading 👉 (4 bytes) and trailing 👈 (4 bytes)
    &line[4..line.len() - 4]
}

pub fn empty_main_collection_document(field_order: &[String]) -> String {
    let mut lines = vec![SEPARATOR.to_string()];
    for key in field_order {
        lines.push(format!("👉{key}👈"));
        lines.push(String::new());
    }
    lines.join("\n") + "\n"
}

pub fn empty_main_collection_json(field_order: &[String]) -> String {
    let section: serde_json::Map<String, serde_json::Value> = field_order.iter()
        .map(|k| (k.clone(), serde_json::Value::String(String::new())))
        .collect();
    serde_json::to_string_pretty(&serde_json::json!([section])).unwrap() + "\n"
}

pub fn sections_to_text(sections: &[serde_json::Value], field_order: &[String]) -> String {
    let mut lines: Vec<String> = vec![];
    for sec in sections {
        lines.push(SEPARATOR.to_string());
        for key in field_order {
            lines.push(format!("👉{key}👈"));
            let val = sec.get(key).and_then(|v| v.as_str()).unwrap_or("");
            lines.push(val.to_string());
        }
    }
    lines.join("\n") + "\n"
}

pub fn text_to_sections(
    content: &str,
    field_order: &[String],
    multiline_props: &HashSet<String>,
) -> Vec<serde_json::Map<String, serde_json::Value>> {
    let lines: Vec<&str> = content.lines().collect();
    let n = lines.len();
    let mut i = 0;
    let mut sections = vec![];

    while i < n {
        if lines[i] != SEPARATOR {
            i += 1;
            continue;
        }
        i += 1;
        let mut section = serde_json::Map::new();
        let mut ok = true;

        for key in field_order {
            let label = format!("👉{key}👈");
            if i >= n || lines[i] != label {
                ok = false;
                break;
            }
            i += 1;
            if multiline_props.contains(key) {
                let mut ml = vec![];
                while i < n && lines[i] != SEPARATOR && !is_prop_label(lines[i]) {
                    ml.push(lines[i]);
                    i += 1;
                }
                section.insert(key.clone(), serde_json::Value::String(ml.join("\n")));
            } else {
                let val = if i < n { lines[i].to_string() } else { String::new() };
                section.insert(key.clone(), serde_json::Value::String(val));
                if i < n { i += 1; }
            }
        }
        if ok {
            sections.push(section);
        }
    }
    sections
}

pub fn parse_sections_lenient(
    content: &str,
    field_order: &[String],
    multiline_props: &HashSet<String>,
) -> Vec<serde_json::Map<String, serde_json::Value>> {
    let lines: Vec<&str> = content.lines().collect();
    let n = lines.len();
    let mut i = 0;
    let mut sections = vec![];

    while i < n {
        if lines[i] != SEPARATOR {
            i += 1;
            continue;
        }
        i += 1;
        let mut found: std::collections::HashMap<String, String> = std::collections::HashMap::new();

        while i < n && lines[i] != SEPARATOR {
            if is_prop_label(lines[i]) {
                let prop = label_name(lines[i]).to_string();
                i += 1;
                if multiline_props.contains(&prop) {
                    let mut ml = vec![];
                    while i < n && lines[i] != SEPARATOR && !is_prop_label(lines[i]) {
                        ml.push(lines[i]);
                        i += 1;
                    }
                    found.insert(prop, ml.join(" ").trim().to_string());
                } else {
                    let val = if i < n { lines[i].trim().to_string() } else { String::new() };
                    found.insert(prop, val);
                    if i < n { i += 1; }
                }
            } else {
                i += 1;
            }
        }

        let section: serde_json::Map<String, serde_json::Value> = field_order.iter()
            .map(|k| {
                let v = found.get(k).cloned().unwrap_or_default();
                (k.clone(), serde_json::Value::String(v))
            })
            .collect();
        sections.push(section);
    }
    sections
}

pub fn is_initial_state(
    content: &str,
    field_order: &[String],
    multiline_props: &HashSet<String>,
) -> bool {
    if content.trim().is_empty() {
        return true;
    }
    let sections = parse_sections_lenient(content, field_order, multiline_props);
    !sections.is_empty()
        && sections.iter().all(|s| {
            field_order.iter().all(|k| {
                s.get(k).and_then(|v| v.as_str()).unwrap_or("").is_empty()
            })
        })
}

pub fn gzip_decompress(bytes: &[u8]) -> anyhow::Result<Vec<u8>> {
    use flate2::read::GzDecoder;
    use std::io::Read;
    let mut d = GzDecoder::new(bytes);
    let mut out = vec![];
    d.read_to_end(&mut out)?;
    Ok(out)
}

pub fn gzip_compress(data: &[u8]) -> anyhow::Result<Vec<u8>> {
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::Write;
    let mut e = GzEncoder::new(vec![], Compression::default());
    e.write_all(data)?;
    Ok(e.finish()?)
}

pub fn csv_field(s: &str) -> String {
    if s.contains(',') || s.contains('"') || s.contains('\n') {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

pub fn csv_row(fields: &[&str]) -> String {
    fields.iter().map(|f| csv_field(f)).collect::<Vec<_>>().join(", ")
}

pub fn sections_all_blank(sections: &[serde_json::Value]) -> bool {
    sections.iter().all(|s| {
        s.as_object().map(|o| o.values().all(|v| {
            v.as_str().map(|s| s.is_empty()).unwrap_or(true)
        })).unwrap_or(true)
    })
}
