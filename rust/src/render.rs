//! minijinja environment over web/templates/ — the single template source
//! for every page (the Flask renderer is gone). Jinja2-compatible syntax:
//! extends/blocks, filters, tests. Two Flask-isms are bridged here so the
//! templates stay portable:
//!   url_for(endpoint)  -> global function mapping endpoint names to paths
//!   tojson(indent=N)   -> filter with Flask's HTML-safe escaping

use std::path::Path;

use minijinja::{value::Value, Environment, Error, ErrorKind};

/// Flask's tojson escapes these so JSON embedded in HTML cannot break out.
fn htmlsafe_json(s: &str) -> String {
    s.replace('<', "\\u003c")
        .replace('>', "\\u003e")
        .replace('&', "\\u0026")
        .replace('\'', "\\u0027")
}

fn tojson(value: Value, indent: Option<usize>) -> Result<String, Error> {
    let json: serde_json::Value = serde_json::to_value(&value)
        .map_err(|e| Error::new(ErrorKind::BadSerialization, "tojson failed").with_source(e))?;
    let out = match indent.filter(|n| *n > 0) {
        Some(n) => {
            let mut buf = Vec::new();
            let indent_bytes = vec![b' '; n];
            let fmt = serde_json::ser::PrettyFormatter::with_indent(&indent_bytes);
            let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
            use serde::Serialize;
            json.serialize(&mut ser).map_err(|e| {
                Error::new(ErrorKind::BadSerialization, "tojson failed").with_source(e)
            })?;
            String::from_utf8(buf).expect("json is utf-8")
        }
        None => serde_json::to_string(&json)
            .map_err(|e| Error::new(ErrorKind::BadSerialization, "tojson failed").with_source(e))?,
    };
    Ok(htmlsafe_json(&out))
}

fn url_for(endpoint: &str) -> &'static str {
    match endpoint {
        "my_team" => "/team",
        "pin_toggle" => "/team/pin",
        "league" => "/league",
        "league_team" => "/league/team/",
        "league_matchup" => "/league/matchup",
        "cron_status" => "/cron",
        "dashboard" => "/dashboard",
        "players" => "/players",
        "player_detail" => "/player/",
        "predictions" => "/predictions",
        "sos" => "/sos",
        "ratings" => "/ratings",
        "strategy" => "/strategy",
        "api_predictions" => "/api/predictions",
        "api_modelcard" => "/api/modelcard",
        _ => "/",
    }
}

pub fn environment(root: &Path) -> Environment<'static> {
    let mut env = Environment::new();
    let templates = root.join("web").join("templates");
    env.set_loader(move |name| {
        // template names come from our own extends/include tags; still,
        // never let a name escape the templates directory.
        if name.contains("..") || name.starts_with('/') {
            return Ok(None);
        }
        match std::fs::read_to_string(templates.join(name)) {
            Ok(src) => Ok(Some(src)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(
                Error::new(ErrorKind::TemplateNotFound, format!("cannot read {name}"))
                    .with_source(e),
            ),
        }
    });
    env.add_global("url_for", Value::from_function(url_for));
    env.add_filter("tojson", tojson);
    env
}
