//! Word boxes of an identity document's page, reused across the
//! orientation search: ocrs finds words in any orientation but reads only
//! upright text, so the page's words are detected once and turned with the
//! page rather than detected again for every quarter turn.

use rten_imageproc::{BoundingRect, PointF, RotatedRect, min_area_rect};

/// A word box in a `w × h` image, as it lies once the image is turned by
/// `quarters` clockwise ([`crate::geometry::rotate_quarters`]).
pub fn turn_rect(r: &RotatedRect, w: usize, h: usize, quarters: u8) -> RotatedRect {
    let turn = |p: PointF| -> PointF {
        let (x, y) = (p.x, p.y);
        let (w, h) = (w as f32, h as f32);
        match quarters % 4 {
            0 => PointF::from_yx(y, x),
            1 => PointF::from_yx(x, h - 1.0 - y),
            2 => PointF::from_yx(h - 1.0 - y, w - 1.0 - x),
            _ => PointF::from_yx(w - 1.0 - x, y),
        }
    };
    if quarters % 4 == 0 {
        return *r;
    }
    let corners: Vec<PointF> = r.corners().into_iter().map(turn).collect();
    // The same box, in the convention min_area_rect gives detected words.
    min_area_rect(&corners).unwrap_or(*r)
}

/// Whether the words' boxes run across the page (`Some(true)`), down it
/// (`Some(false)`: the page is sideways), or it is unclear: the share of the
/// boxes' area in boxes clearly longer one way than the other.
pub fn text_runs_across(words: &[RotatedRect]) -> Option<bool> {
    let (mut across, mut down) = (0f32, 0f32);
    for r in words {
        let b = r.bounding_rect();
        let (bw, bh) = (b.width(), b.height());
        if bw > 1.5 * bh {
            across += bw * bh;
        } else if bh > 1.5 * bw {
            down += bw * bh;
        }
    }
    let total = across + down;
    if total <= 0.0 || words.len() < 6 {
        return None;
    }
    if across >= 0.75 * total {
        Some(true)
    } else if down >= 0.75 * total {
        Some(false)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rten_imageproc::Point;

    fn word(cx: f32, cy: f32, w: f32, h: f32) -> RotatedRect {
        RotatedRect::new(Point::from_yx(cy, cx), rten_imageproc::Vec2::from_yx(-1.0, 0.0), w, h)
    }

    #[test]
    fn a_turned_box_lands_where_the_turned_image_has_it() {
        // A wide word near the top-left of a 200 x 100 page, turned clockwise:
        // it becomes tall, near the top-right of the 100 x 200 result.
        let r = turn_rect(&word(30.0, 10.0, 40.0, 10.0), 200, 100, 1);
        let b = r.bounding_rect();
        assert!((b.width() - 10.0).abs() < 0.5 && (b.height() - 40.0).abs() < 0.5, "{b:?}");
        let c = r.center();
        assert!((c.x - 89.0).abs() < 0.6 && (c.y - 30.0).abs() < 0.6, "{c:?}");
    }

    #[test]
    fn word_shapes_say_which_way_text_runs() {
        let across: Vec<RotatedRect> = (0..8).map(|i| word(50.0, 10.0 + 20.0 * i as f32, 60.0, 12.0)).collect();
        assert_eq!(text_runs_across(&across), Some(true));
        let down: Vec<RotatedRect> = across.iter().map(|r| turn_rect(r, 200, 200, 1)).collect();
        assert_eq!(text_runs_across(&down), Some(false));
        assert_eq!(text_runs_across(&across[..3]), None);
    }
}
