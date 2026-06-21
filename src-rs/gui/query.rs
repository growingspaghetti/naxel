use regex::Regex;
use std::collections::HashMap;

pub type Row = Vec<String>;
pub type FilterFn = Box<dyn Fn(&Row, &Row) -> bool + Send + Sync>;

pub enum QueryResult {
    Filter { func: FilterFn, count_only: bool },
    Lookup { prop: String, entry: String, values: Vec<String> },
}

fn like_to_regex(pattern: &str) -> Regex {
    let mut re = String::from("(?i)^");
    for ch in pattern.chars() {
        match ch {
            '%' => re.push_str(".*"),
            '_' => re.push('.'),
            c => re.push_str(&regex::escape(&c.to_string())),
        }
    }
    re.push('$');
    Regex::new(&re).unwrap_or_else(|_| Regex::new("^$").unwrap())
}

#[derive(Debug, Clone)]
enum Op { Eq, Like, In }

#[derive(Debug, Clone)]
enum Token {
    And,
    Or,
    Cond { col: String, op: Op, val: String, is_contents: bool },
}

fn tokenize(clause: &str) -> Vec<Token> {
    let mut tokens = vec![];
    let mut rest = clause.trim();

    while !rest.is_empty() {
        rest = rest.trim_start();
        if rest.is_empty() { break; }

        // AND / OR
        if let Some(m) = Regex::new(r"(?i)^(and|or)(?:\s|$)").unwrap().find(rest) {
            let kw = &rest[..m.end()].trim().to_uppercase();
            if kw == "AND" { tokens.push(Token::And); }
            else { tokens.push(Token::Or); }
            rest = &rest[m.end()..];
            continue;
        }

        // 'val' in col[.contents]
        let in_re = Regex::new(r#"(?i)^(?:'([^']*)'|"([^"]*)")\s+in\s+(\w+)(?:\.(contents))?"#).unwrap();
        if let Some(cap) = in_re.captures(rest) {
            let val = cap.get(1).or(cap.get(2)).map(|m| m.as_str()).unwrap_or("").to_string();
            let col = cap[3].to_string();
            let is_contents = cap.get(4).is_some();
            tokens.push(Token::Cond { col, op: Op::In, val, is_contents });
            rest = &rest[cap.get(0).unwrap().end()..];
            continue;
        }

        // col[.contents] (= | like) 'val'
        let cond_re = Regex::new(r#"(?i)^(\w+)(?:\.(contents))?\s*(=|like)\s*(?:'([^']*)'|"([^"]*)")"#).unwrap();
        if let Some(cap) = cond_re.captures(rest) {
            let col = cap[1].to_string();
            let is_contents = cap.get(2).is_some();
            let op_str = &cap[3].to_lowercase();
            let op = if op_str == "like" { Op::Like } else { Op::Eq };
            let val = cap.get(4).or(cap.get(5)).map(|m| m.as_str()).unwrap_or("").to_string();
            tokens.push(Token::Cond { col, op, val, is_contents });
            rest = &rest[cap.get(0).unwrap().end()..];
            continue;
        }

        // Skip unknown chars
        let mut chars = rest.chars();
        chars.next();
        rest = chars.as_str();
    }
    tokens
}

fn build_filter(
    tokens: &[Token],
    columns: &[String],
    ref_data: &HashMap<String, HashMap<String, String>>,
) -> FilterFn {
    parse_or(tokens, 0, columns, ref_data).0
}

fn col_index(col: &str, columns: &[String]) -> Option<usize> {
    columns.iter().position(|c| c.eq_ignore_ascii_case(col))
}

fn make_false_fn() -> FilterFn {
    Box::new(|_, _| false)
}

fn parse_or(
    tokens: &[Token],
    mut pos: usize,
    columns: &[String],
    ref_data: &HashMap<String, HashMap<String, String>>,
) -> (FilterFn, usize) {
    let (mut fn_left, new_pos) = parse_and(tokens, pos, columns, ref_data);
    pos = new_pos;
    while pos < tokens.len() {
        if !matches!(tokens[pos], Token::Or) { break; }
        pos += 1;
        let (fn_right, new_pos) = parse_and(tokens, pos, columns, ref_data);
        pos = new_pos;
        fn_left = Box::new(move |orig: &Row, exp: &Row| fn_left(orig, exp) || fn_right(orig, exp));
    }
    (fn_left, pos)
}

fn parse_and(
    tokens: &[Token],
    mut pos: usize,
    columns: &[String],
    ref_data: &HashMap<String, HashMap<String, String>>,
) -> (FilterFn, usize) {
    let (mut fn_left, new_pos) = parse_factor(tokens, pos, columns, ref_data);
    pos = new_pos;
    while pos < tokens.len() {
        if !matches!(tokens[pos], Token::And) { break; }
        pos += 1;
        let (fn_right, new_pos) = parse_factor(tokens, pos, columns, ref_data);
        pos = new_pos;
        fn_left = Box::new(move |orig: &Row, exp: &Row| fn_left(orig, exp) && fn_right(orig, exp));
    }
    (fn_left, pos)
}

fn parse_factor(
    tokens: &[Token],
    pos: usize,
    columns: &[String],
    ref_data: &HashMap<String, HashMap<String, String>>,
) -> (FilterFn, usize) {
    if pos >= tokens.len() { return (make_false_fn(), pos); }
    let Token::Cond { col, op, val, is_contents } = &tokens[pos] else {
        return (make_false_fn(), pos + 1);
    };
    let idx = match col_index(col, columns) {
        Some(i) => i,
        None => return (make_false_fn(), pos + 1),
    };
    let col_lower = col.to_lowercase();
    let val = val.clone();

    let rd: HashMap<String, HashMap<String, String>> = ref_data.clone();

    let f: FilterFn = match (op, is_contents) {
        (Op::Eq, false) => {
            let v = val.clone();
            Box::new(move |orig: &Row, _exp: &Row| {
                orig.get(idx).map(|c| c.eq_ignore_ascii_case(&v)).unwrap_or(false)
            })
        }
        (Op::Eq, true) => {
            let v = val.clone();
            let col_l = col_lower.clone();
            let r = rd.clone();
            Box::new(move |orig: &Row, _: &Row| {
                let entry = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                let content = r.get(&col_l).and_then(|m| m.get(entry)).map(|s| s.as_str()).unwrap_or("");
                content.eq_ignore_ascii_case(&v)
            })
        }
        (Op::Like, false) => {
            let pat = like_to_regex(&val);
            Box::new(move |_orig: &Row, exp: &Row| {
                exp.get(idx).map(|c| pat.is_match(c)).unwrap_or(false)
            })
        }
        (Op::Like, true) => {
            let pat = like_to_regex(&val);
            let col_l = col_lower.clone();
            let r = rd.clone();
            Box::new(move |orig: &Row, _: &Row| {
                let entry = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                let content = r.get(&col_l).and_then(|m| m.get(entry)).map(|s| s.as_str()).unwrap_or("");
                pat.is_match(content)
            })
        }
        (Op::In, false) => {
            let v = val.clone();
            if v.contains('%') || v.contains('_') {
                let pat = like_to_regex(&v);
                Box::new(move |orig: &Row, _: &Row| {
                    let cell = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                    cell.split(',').any(|t| pat.is_match(t.trim()))
                })
            } else {
                Box::new(move |orig: &Row, _: &Row| {
                    let cell = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                    cell.split(',').any(|t| t.trim().eq_ignore_ascii_case(&v))
                })
            }
        }
        (Op::In, true) => {
            let v = val.clone();
            let col_l = col_lower.clone();
            let r = rd.clone();
            if v.contains('%') || v.contains('_') {
                let pat = like_to_regex(&v);
                Box::new(move |orig: &Row, _: &Row| {
                    let entry = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                    let content = r.get(&col_l).and_then(|m| m.get(entry)).map(|s| s.as_str()).unwrap_or("");
                    content.split(',').any(|t| pat.is_match(t.trim()))
                })
            } else {
                Box::new(move |orig: &Row, _: &Row| {
                    let entry = orig.get(idx).map(|s| s.as_str()).unwrap_or("");
                    let content = r.get(&col_l).and_then(|m| m.get(entry)).map(|s| s.as_str()).unwrap_or("");
                    content.split(',').any(|t| t.trim().eq_ignore_ascii_case(&v))
                })
            }
        }
    };
    (f, pos + 1)
}

static WHERE_RE: std::sync::LazyLock<Regex> = std::sync::LazyLock::new(|| {
    Regex::new(r"(?i)^(?:select\s+(\*|count)\s+)?where\s+").unwrap()
});

static LOOKUP_RE: std::sync::LazyLock<Regex> = std::sync::LazyLock::new(|| {
    Regex::new(r"(?i)^select\s+(\w+)\.([^\s.]+)\.contents\s*$").unwrap()
});

pub fn parse_query(
    query: &str,
    columns: &[String],
    ref_data: &HashMap<String, HashMap<String, String>>,
) -> QueryResult {
    let q = query.trim();
    if q.is_empty() {
        return QueryResult::Filter {
            func: Box::new(|_, _| true),
            count_only: false,
        };
    }

    if let Some(cap) = LOOKUP_RE.captures(q) {
        let prop = cap[1].to_string();
        let entry = cap[2].to_string();
        let raw = ref_data.get(&prop).and_then(|m| m.get(&entry)).map(|s| s.as_str()).unwrap_or("");
        let values: Vec<String> = if raw.is_empty() {
            vec![]
        } else {
            raw.split(',').filter_map(|v| {
                let v = v.trim();
                if v.is_empty() { None } else { Some(v.to_string()) }
            }).collect()
        };
        return QueryResult::Lookup { prop, entry, values };
    }

    if let Some(m) = WHERE_RE.find(q) {
        let count_only = WHERE_RE.captures(q)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().eq_ignore_ascii_case("count"))
            .unwrap_or(false);
        let clause = &q[m.end()..];
        let tokens = tokenize(clause);
        let func = build_filter(&tokens, columns, ref_data);
        return QueryResult::Filter { func, count_only };
    }

    // Plain text substring
    let lower = q.to_lowercase();
    QueryResult::Filter {
        func: Box::new(move |_orig: &Row, exp: &Row| {
            exp.iter().any(|cell| cell.to_lowercase().contains(&lower))
        }),
        count_only: false,
    }
}
