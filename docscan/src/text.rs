//! General page OCR: enhancement and small-print detection, with geometry.
//!
//! Coordinates refer to the enhanced, deskewed `page_size`, not the original
//! photo. Text is ordered by rows and split at wide column gaps; this is not
//! semantic table reconstruction or multi-column paragraph ordering.
use crate::{
    Scanner, now,
    poa::features::{Word, reading_order},
    prepare_page,
    za::Line,
};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct PageText {
    pub text: String,
    pub lines: Vec<Line>,
    pub words: Vec<Word>,
    pub page_size: [u32; 2],
    pub timings_ms: TextTimings,
}

#[derive(Debug, Serialize)]
pub struct TextTimings {
    pub enhance: f64,
    pub ocr: f64,
}

impl Scanner {
    /// Read an upright, flattened page without applying identity or address
    /// rules. Uses full-page strips (or overlapping tiles without the optional
    /// detector), so small print is not squashed into the ID detector's input.
    pub fn text_page_native(&self, rgba: &[u8], width: u32, height: u32) -> anyhow::Result<PageText> {
        let (w, h) = (width as usize, height as usize);
        anyhow::ensure!(
            w > 0 && h > 0 && w.checked_mul(h).and_then(|n| n.checked_mul(4)) == Some(rgba.len()),
            "invalid RGBA image dimensions"
        );
        let t0 = now();
        let (grey, pw, ph) = prepare_page(rgba, w, h);
        let t1 = now();
        let words = reading_order(&self.ocr_page(&grey, pw, ph)?);
        let lines = lines_from_words(&words);
        Ok(PageText {
            text: lines.iter().map(|l| l.text.as_str()).collect::<Vec<_>>().join("\n"),
            lines,
            words,
            page_size: [pw as u32, ph as u32],
            timings_ms: TextTimings {
                enhance: t1 - t0,
                ocr: now() - t1,
            },
        })
    }
}

fn lines_from_words(words: &[Word]) -> Vec<Line> {
    let mut lines: Vec<Line> = Vec::new();
    let mut previous = None;
    for word in words {
        if previous == Some(word.line) {
            let line = lines.last_mut().unwrap();
            let right = (line.x + line.w).max(word.x + word.w);
            let bottom = (line.y + line.h).max(word.y + word.h);
            line.x = line.x.min(word.x);
            line.y = line.y.min(word.y);
            line.w = right - line.x;
            line.h = bottom - line.y;
            line.text.push(' ');
            line.text.push_str(&word.text);
        } else {
            lines.push(Line {
                text: word.text.clone(),
                x: word.x,
                y: word.y,
                w: word.w,
                h: word.h,
            });
        }
        previous = Some(word.line);
    }
    lines
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_text_keeps_lines_columns_and_their_geometry() {
        let word = |text: &str, x, y| Line {
            text: text.into(),
            x,
            y,
            w: 20.0,
            h: 10.0,
        };
        let words = reading_order(&[word("next", 10.0, 30.0), word("column", 200.0, 10.0), word("world", 35.0, 10.0), word("Hello", 10.0, 10.0)]);
        let lines = lines_from_words(&words);
        assert_eq!(lines.iter().map(|l| l.text.as_str()).collect::<Vec<_>>(), ["Hello world", "column", "next"]);
        assert_eq!((lines[0].x, lines[0].y, lines[0].w, lines[0].h), (10.0, 10.0, 45.0, 10.0));
        assert_eq!(words.iter().map(|w| w.line).collect::<Vec<_>>(), [0, 0, 1, 2]);
        assert!(lines_from_words(&[]).is_empty());
    }

    #[test]
    fn invalid_image_is_an_error_before_preprocessing() {
        let scanner = Scanner::new();
        for (bytes, w, h) in [(&[][..], 0, 10), (&[0; 4][..], 2, 2), (&[][..], u32::MAX, u32::MAX)] {
            assert!(scanner.text_page_native(bytes, w, h).is_err());
        }
    }
}
