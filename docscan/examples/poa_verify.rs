//! Runs the proof-of-address checks on fields from elsewhere (a VLM, in
//! `eval/poa_eval.py`): one JSON line in per page, `{"text", "fields",
//! "today"}`, one `Verification` line out. `fields` has the shape of
//! `docscan::poa::Fields` (unknown keys are ignored; missing ones are null).
use std::io::BufRead;

use docscan::poa::{self, Fields, verify::Date};

fn main() -> anyhow::Result<()> {
    for line in std::io::stdin().lock().lines() {
        let v: serde_json::Value = serde_json::from_str(&line?)?;
        let today = Date::parse_iso(v["today"].as_str().unwrap_or("2026-10-15")).unwrap();
        let text = v["text"].as_str().unwrap_or("");
        let mut fields: Fields = serde_json::from_value(v["fields"].clone()).unwrap_or_default();
        // A province the model named is checked against the canonical names.
        fields.address.province = fields.address.province.as_deref().and_then(poa::verify::province).map(String::from);
        let out = poa::verify_fields(&fields, text, &[], today);
        println!("{}", serde_json::to_string(&out)?);
    }
    Ok(())
}
