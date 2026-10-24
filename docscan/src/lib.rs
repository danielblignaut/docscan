//! In-browser identity document and barcode scanning.
//!
//! One [`Scanner`] holds the OCR models. The page feeds it RGBA frames from
//! the camera (cropped to the on-screen guide) and gets back JSON:
//!
//! - [`Scanner::barcodes`]: every barcode in the frame, any symbology.
//! - [`Scanner::document`]: quality, the identity barcodes, OCR, the MRZ,
//!   and which document it is, with its fields.
//! - [`Scanner::quality`]: sharpness, glare and exposure only, for every frame.

pub mod barcode;
pub mod document_evidence;
pub mod face;
pub mod geometry;
pub mod idback;
pub mod idocr;
pub mod labels;
pub mod mrz;
pub mod mrz_decode;
pub mod page;
pub mod poa;
pub mod quad;
pub mod quality;
pub mod text;
pub mod text_v6;
pub mod za;

use ocrs::{ImageSource, OcrEngine, OcrEngineParams, TextItem};
use rten_tensor::prelude::*;
use serde::Serialize;
use wasm_bindgen::prelude::*;

/// `initThreadPool(n)` in the `threads` build: starts `n` Web Workers that
/// rayon (and so rten's OCR) runs on. Await it once before scanning.
#[cfg(feature = "threads")]
pub use wasm_bindgen_rayon::init_thread_pool;

pub const MRZ_CHARS: &str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<";

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DocumentKind {
    ZaSmartIdFront,
    ZaSmartIdBack,
    ZaGreenBook,
    ZaPassport,
    GbPassport,
    /// A passport from any other state: the MRZ is read, but the layout is
    /// not one this scanner was built for.
    OtherPassport,
    /// An ICAO TD1 card MRZ from any state.
    OtherIdCard,
    Unknown,
}

/// What the page has asked the holder to show. It narrows the orientation
/// search (a card or passport page is landscape, a green book page portrait)
/// and settles what a lone ID-number barcode belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Expected {
    #[default]
    Any,
    SmartIdFront,
    SmartIdBack,
    GreenBook,
    Passport,
}

impl Expected {
    pub fn parse(s: &str) -> Expected {
        match s {
            "smart_id_front" => Expected::SmartIdFront,
            "smart_id_back" => Expected::SmartIdBack,
            "green_book" => Expected::GreenBook,
            "passport" => Expected::Passport,
            _ => Expected::Any,
        }
    }

    /// Whether the document is wider than tall when upright, if known.
    fn landscape(self) -> Option<bool> {
        match self {
            Expected::SmartIdFront | Expected::SmartIdBack | Expected::Passport => Some(true),
            Expected::GreenBook => Some(false),
            Expected::Any => None,
        }
    }
}

/// ID-1 cards are 85.6 × 54 mm. A green book page is about 1.42 : 1.
const CARD_ASPECT: f32 = 85.6 / 54.0;

/// Whether a flattened outline has a card's proportions, either way up.
fn card_shaped(width: usize, height: usize) -> bool {
    let a = width.max(height) as f32 / width.min(height).max(1) as f32;
    (a - CARD_ASPECT).abs() <= 0.09
}

#[derive(Debug, Clone, Serialize)]
pub struct DocumentResult {
    pub kind: DocumentKind,
    /// Whether the reading is complete and self-consistent enough to accept:
    /// the MRZ check digits pass, the barcode parsed, or the printed ID
    /// number passes Luhn with the anchors found.
    pub accepted: bool,
    /// Physical originality is separate from readable/self-consistent fields.
    /// Unknown is serialized as null, never treated as an original document.
    pub copy_assessment: document_evidence::CopyAssessment,
    pub reasons: Vec<String>,
    pub quality: quality::Quality,
    pub barcodes: Vec<barcode::Barcode>,
    pub mrz: Option<mrz::Mrz>,
    pub smart_id_barcode: Option<za::SmartIdBarcode>,
    /// An identity number read from a linear barcode (Code 39 or Code 128):
    /// the green book carries one, and so does the smart ID card's back.
    pub id_barcode: Option<za::IdNumber>,
    pub printed: Option<za::PrintedFields>,
    pub lines: Vec<za::Line>,
    /// The raw MRZ lines as recognised, before correction.
    pub mrz_lines: Vec<String>,
    /// The skew the OCR pass levelled, in degrees.
    pub skew: f32,
    /// The quarter turns (clockwise) the OCR read the page at.
    pub quarter_turns: u8,
    /// How many OCR passes the orientation search spent.
    pub ocr_passes: u8,
    /// The document's outline in the input frame, when found. Line and
    /// barcode positions are then in the flattened image's coordinates.
    pub document: Option<quad::Quad>,
    pub analysed_size: [u32; 2],
    pub timings_ms: Timings,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct OcrOutput {
    pub lines: Vec<za::Line>,
    /// The words the lines were built from, in the levelled image.
    #[serde(skip)]
    pub words: Vec<za::Line>,
    pub mrz: Vec<String>,
    pub skew: f32,
}

/// A page levelled for OCR, with the words found on it upright (turn 0).
struct LevelledPage {
    ink: Vec<u8>,
    luma: Vec<u8>,
    w: usize,
    h: usize,
    skew: f32,
    words: Vec<rten_imageproc::RotatedRect>,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct Timings {
    /// Outline, flattening and quality.
    pub quality: f64,
    pub barcodes: f64,
    pub ocr: f64,
    pub total: f64,
}

#[wasm_bindgen]
extern "C" {
    #[wasm_bindgen(js_namespace = performance, js_name = now)]
    fn perf_now() -> f64;
}

pub(crate) fn now() -> f64 {
    #[cfg(target_arch = "wasm32")]
    {
        perf_now()
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() * 1000.0
    }
}

#[wasm_bindgen]
#[derive(Default)]
pub struct Scanner {
    ocr: Option<OcrEngine>,
    /// The recognition model, run directly for MRZ lines ([`mrz_decode`]).
    rec_model: Option<rten::Model>,
    /// The quarter turn that last read as a document: the holder tends to
    /// keep the book the same way round, so it is tried first next time.
    last_turn: std::cell::Cell<Option<u8>>,
    /// The proof-of-address field tagger, when loaded.
    tagger: Option<poa::tagger::Tagger>,
    /// Proof of address: leave the city, suburb and postal code as read,
    /// without the gazetteer's correction.
    no_gazetteer: bool,
    /// Proof of address: the frames of the capture in progress, as read.
    capture: std::cell::RefCell<Vec<(poa::AddressResult, Vec<poa::features::Word>)>>,
    /// The detection model with a free input size, for pages
    /// ([`Scanner::detect_page`]): ocrs runs its own only at 800 × 600.
    det: Option<rten::Model>,
}

#[wasm_bindgen]
impl Scanner {
    #[wasm_bindgen(constructor)]
    pub fn new() -> Scanner {
        // A panic otherwise surfaces as a bare "unreachable" trap.
        console_error_panic_hook::set_once();
        Scanner::default()
    }

    /// Loads the ocrs detection and recognition models (`.rten` files).
    /// Barcode reading works without them.
    pub fn load_ocr(&mut self, detection: Vec<u8>, recognition: Vec<u8>) -> Result<(), JsError> {
        self.load_ocr_models(detection, recognition)
            .map_err(|e| JsError::new(&e.to_string()))
    }

    pub fn has_ocr(&self) -> bool {
        self.ocr.is_some()
    }

    pub fn quality(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let luma = quality::rgba_to_luma(rgba);
        to_js(&quality::measure(&luma, width as usize, height as usize))
    }

    /// Every barcode in the frame. `formats` narrows the symbologies
    /// (`"qrcode"`, `"pdf417"`, `"code128"`, …); empty means all.
    pub fn barcodes(
        &self,
        rgba: &[u8],
        width: u32,
        height: u32,
        formats: Vec<String>,
    ) -> Result<JsValue, JsError> {
        let luma = quality::rgba_to_luma(rgba);
        let formats = (!formats.is_empty()).then_some(formats.as_slice());
        to_js(&barcode::read_all(&luma, width, height, formats))
    }

    /// Opt-in matrix fallback: after an empty baseline, try one half-scale
    /// QR/Data Matrix/Aztec/PDF417 read, restricted to the requested formats.
    /// Coordinates refer to the original frame. This bounds passes, not time.
    /// The default reader and identity/labelled acceptance paths are unchanged.
    pub fn barcodes_with_empty_matrix_retry(
        &self,
        rgba: &[u8],
        width: u32,
        height: u32,
        formats: Vec<String>,
    ) -> Result<JsValue, JsError> {
        let luma = quality::rgba_to_luma(rgba);
        let formats = (!formats.is_empty()).then_some(formats.as_slice());
        to_js(&barcode::read_all_with_empty_matrix_retry(&luma, width, height, formats))
    }

    /// Reads an identity document. `run_ocr` false reads only barcodes and
    /// quality, which is enough for the smart ID back and fast enough for
    /// every frame. `expected` is what the page asked for (`"smart_id_front"`,
    /// `"smart_id_back"`, `"green_book"`, `"passport"`, or `""` for any).
    pub fn document(
        &self,
        rgba: &[u8],
        width: u32,
        height: u32,
        run_ocr: bool,
        expected: &str,
    ) -> Result<JsValue, JsError> {
        let result = self
            .analyse(rgba, width, height, run_ocr, Expected::parse(expected))
            .map_err(|e| JsError::new(&e.to_string()))?;
        to_js(&result)
    }

    /// The document's outline (`{corners, support}`), or `null`.
    pub fn find_document(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        to_js(&quad::find_document(rgba, width as usize, height as usize))
    }

    /// Flattens the quadrilateral `corners` (`[x0, y0, … x3, y3]`, clockwise
    /// from top-left) of an RGBA image into an `out_width × out_height` RGBA
    /// image: the captured document, cropped and squared up.
    pub fn flatten(
        &self,
        rgba: &[u8],
        width: u32,
        height: u32,
        corners: Vec<f32>,
        out_width: u32,
        out_height: u32,
    ) -> Result<Vec<u8>, JsError> {
        if corners.len() != 8 {
            return Err(JsError::new("corners must hold 8 numbers"));
        }
        let c = [[corners[0], corners[1]], [corners[2], corners[3]], [corners[4], corners[5]], [corners[6], corners[7]]];
        quad::warp(rgba, width as usize, height as usize, 4, &c, out_width as usize, out_height as usize)
            .ok_or_else(|| JsError::new("degenerate corners"))
    }

    /// Every barcode with the printed text around it, as named fields
    /// (`IMEI1`, `SN`, an EAN-13 confirmed by its printed digits), each with
    /// its check digit verified. Needs the OCR models.
    pub fn labelled(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let out = self.labelled_native(rgba, width, height).map_err(|e| JsError::new(&e.to_string()))?;
        to_js(&out)
    }

    /// Loads the proof-of-address field tagger (`poa-tagger.onnx` or `.rten`).
    pub fn load_tagger(&mut self, model: Vec<u8>) -> Result<(), JsError> {
        self.tagger = Some(poa::tagger::Tagger::load(model).map_err(|e| JsError::new(&e.to_string()))?);
        Ok(())
    }

    /// Loads the page detector (`text-detection-page.onnx`: ocrs's text
    /// detection model with its input size freed, scripts/make-page-detector.py).
    /// Optional: proof-of-address pages are then detected in strips the width
    /// of the page rather than nine overlapping tiles.
    pub fn load_page_detector(&mut self, model: Vec<u8>) -> Result<(), JsError> {
        self.load_page_detector_native(model).map_err(|e| JsError::new(&e.to_string()))
    }

    pub fn has_tagger(&self) -> bool {
        self.tagger.is_some()
    }

    /// One frame's page analysis for the proof-of-address flow: the outline,
    /// its shape, whether it is wholly in view, sharpness and glare.
    pub fn page(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        to_js(&page::analyse(rgba, width as usize, height as usize))
    }

    /// The flattened page as OCR sees it (greyscale RGBA, possibly a little
    /// larger when levelled): `{width, height, data}`.
    pub fn enhance_page(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let (img, w, h) = prepare_page(rgba, width as usize, height as usize);
        let out = js_sys_object(w, h, page::grey_to_rgba(&img));
        Ok(out)
    }

    /// Reads a captured, flattened page (RGBA): OCR, then the fields by the
    /// tagger (`method` "tagger", or "" when it is loaded) or by rules
    /// ("rules"), then the checks, with `today` (`YYYY-MM-DD`, the device's
    /// date) for the document's age.
    pub fn address(&self, rgba: &[u8], width: u32, height: u32, today: &str, method: &str) -> Result<JsValue, JsError> {
        let today = poa::verify::Date::parse_iso(today).ok_or_else(|| JsError::new("today must be YYYY-MM-DD"))?;
        let method = match method {
            "rules" => Some(poa::Method::Rules),
            "tagger" => Some(poa::Method::Tagger),
            _ => None,
        };
        let r = self
            .address_native(rgba, width as usize, height as usize, today, method)
            .map_err(|e| JsError::new(&e.to_string()))?;
        to_js(&r.0)
    }

    /// Reads a captured page and checks it against a known customer
    /// (`{name, surname?, address: {street, suburb, city, province,
    /// postal_code}}`): `{result, customer}`, where `customer` holds the
    /// decision (`accepted`, `reasons`) and its evidence (the name and
    /// address matches with their scores and printed lines, the date's age).
    pub fn verify_address(&self, rgba: &[u8], width: u32, height: u32, today: &str, customer: JsValue) -> Result<JsValue, JsError> {
        let today = poa::verify::Date::parse_iso(today).ok_or_else(|| JsError::new("today must be YYYY-MM-DD"))?;
        let customer: poa::customer::Customer = serde_wasm_bindgen::from_value(customer).map_err(|e| JsError::new(&e.to_string()))?;
        let (r, words) = self.address_native(rgba, width as usize, height as usize, today, None).map_err(|e| JsError::new(&e.to_string()))?;
        let check = poa::customer::check(&words, &r.spans, &customer, poa::capture::doc_date(&r.fields), today);
        #[derive(Serialize)]
        struct Out<'a> {
            result: &'a poa::AddressResult,
            customer: poa::customer::CustomerCheck,
        }
        to_js(&Out { result: &r, customer: check })
    }

    /// Starts a new multi-frame capture (forgets the frames read so far).
    pub fn capture_reset(&self) {
        self.capture.borrow_mut().clear();
    }

    /// Reads one more frame's flattened page into the capture in progress
    /// and returns its own reading (as [`Scanner::address`]).
    pub fn capture_add(&self, rgba: &[u8], width: u32, height: u32, today: &str) -> Result<JsValue, JsError> {
        let today = poa::verify::Date::parse_iso(today).ok_or_else(|| JsError::new("today must be YYYY-MM-DD"))?;
        let (r, words) = self.address_native(rgba, width as usize, height as usize, today, None).map_err(|e| JsError::new(&e.to_string()))?;
        let out = to_js(&r);
        self.capture.borrow_mut().push((r, words));
        out
    }

    /// The capture so far: fields voted across its frames, the decision about
    /// the customer when one is given (`null` for none), and `more`: whether
    /// another frame should be read (the frames disagree on a key field and
    /// fewer than three have been read). `{result, more}`.
    pub fn capture_result(&self, today: &str, customer: JsValue) -> Result<JsValue, JsError> {
        let today = poa::verify::Date::parse_iso(today).ok_or_else(|| JsError::new("today must be YYYY-MM-DD"))?;
        let customer: Option<poa::customer::Customer> =
            if customer.is_null() || customer.is_undefined() { None } else { Some(serde_wasm_bindgen::from_value(customer).map_err(|e| JsError::new(&e.to_string()))?) };
        let frames = self.capture.borrow();
        let rs: Vec<&poa::AddressResult> = frames.iter().map(|f| &f.0).collect();
        let ws: Vec<&[poa::features::Word]> = frames.iter().map(|f| f.1.as_slice()).collect();
        let r = poa::capture::combine(&rs, &ws, customer.as_ref(), today);
        #[derive(Serialize)]
        struct Out {
            result: poa::capture::CaptureResult,
            more: bool,
        }
        let more = poa::capture::next_frame_needed(&r);
        to_js(&Out { result: r, more })
    }

    /// General page OCR with enhancement, small-print detection and word boxes.
    /// Input must be upright and flattened; boxes refer to the returned page_size.
    pub fn text_page(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let result = self.text_page_native(rgba, width, height).map_err(|e| JsError::new(&e.to_string()))?;
        to_js(&result)
    }

    /// Recognised text lines only, for general OCR use.
    pub fn text(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let lines = self
            .ocr_lines(rgba, width, height)
            .map_err(|e| JsError::new(&e.to_string()))?;
        to_js(&lines)
    }
}

/// `{width, height, data}` for an image handed back to JavaScript.
fn js_sys_object(width: usize, height: usize, data: Vec<u8>) -> JsValue {
    #[derive(Serialize)]
    struct Img {
        width: usize,
        height: usize,
        #[serde(with = "serde_bytes_compat")]
        data: Vec<u8>,
    }
    let img = Img { width, height, data };
    img.serialize(&serde_wasm_bindgen::Serializer::new()).unwrap_or(JsValue::NULL)
}

/// Serialises bytes as a byte array (a `Uint8Array` through serde-wasm-bindgen).
mod serde_bytes_compat {
    pub fn serialize<S: serde::Serializer>(v: &[u8], s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(v)
    }
}

/// The longest side a page is read at: A4 at 150 dpi. Captures are scaled to
/// it, down or (a phone's ~1000 px wide page) up: at 120 dpi ocrs already
/// runs words together and reads commas as full stops.
pub const PAGE_LONG: usize = 1754;

/// Scales a flattened colour page to [`PAGE_LONG`] and enhances it.
pub fn prepare_page(rgba: &[u8], w: usize, h: usize) -> (Vec<u8>, usize, usize) {
    let k = (PAGE_LONG as f32 / w.max(h) as f32).min(2.0);
    if (k - 1.0).abs() > 0.02 {
        let (scaled, sw, sh) = quality::scale_rgba(rgba, w, h, k);
        page::enhance(&scaled, sw, sh, page::Plane::Luma)
    } else {
        page::enhance(rgba, w, h, page::Plane::Luma)
    }
}

fn to_js<T: Serialize>(value: &T) -> Result<JsValue, JsError> {
    value
        .serialize(&serde_wasm_bindgen::Serializer::json_compatible().serialize_missing_as_null(true))
        .map_err(|e| JsError::new(&e.to_string()))
}

impl Scanner {
    pub fn load_ocr_models(&mut self, detection: Vec<u8>, recognition: Vec<u8>) -> anyhow::Result<()> {
        // MRZ lines are re-read with the recognition model run directly, so
        // the MRZ's layout can steer the decoding (mrz_decode.rs).
        self.rec_model = Some(rten::Model::load(recognition.clone())?);
        let ocr = OcrEngine::new(OcrEngineParams {
            detection_model: Some(rten::Model::load(detection)?),
            recognition_model: Some(rten::Model::load(recognition)?),
            ..Default::default()
        })?;
        self.ocr = Some(ocr);
        Ok(())
    }

    /// Text lines of a frame, read from a copy levelled by the estimated
    /// skew. ocrs crops each line as an upright box, so on a tilted page two
    /// lines (the MRZ especially) bleed into one; levelling first avoids it.
    ///
    /// Layout lines are rebuilt from words by position, because ocrs can
    /// attach a value word to the label line above it. Lines that look like
    /// an MRZ are re-read with the MRZ alphabet.
    pub fn ocr_lines(&self, rgba: &[u8], width: u32, height: u32) -> anyhow::Result<OcrOutput> {
        let (w, h) = (width as usize, height as usize);
        self.ocr_planes(&quality::rgba_to_ink(rgba), &quality::rgba_to_luma(rgba), w, h)
    }

    /// OCR of one page orientation. Words are found and read on the ink
    /// plane ([`quality::rgba_to_ink`]), where coloured security print fades;
    /// MRZ lines are re-read on the luma plane, which suits the black OCR-B
    /// on white of the machine-readable zone.
    pub fn ocr_planes(&self, ink: &[u8], luma: &[u8], w: usize, h: usize) -> anyhow::Result<OcrOutput> {
        let page = self.level_page(ink, luma, w, h)?;
        self.read_turned(&page, 0)
    }

    /// The page levelled by its estimated skew, with its words detected
    /// once: ocrs reads only upright text, but its word boxes are found in
    /// any orientation, so the other quarter turns reuse them.
    fn level_page(&self, ink: &[u8], luma: &[u8], w: usize, h: usize) -> anyhow::Result<LevelledPage> {
        let ocr = self.ocr.as_ref().ok_or_else(|| anyhow::anyhow!("OCR models not loaded"))?;
        let skew = geometry::estimate_skew(luma, w, h);
        let level = |img: &[u8]| if skew.abs() >= 1.0 { geometry::rotate(img, w, h, skew) } else { (img.to_vec(), w, h) };
        let (ink, lw, lh) = level(ink);
        let (luma, _, _) = level(luma);
        // The detector's input is portrait (600 x 800), and ocrs squashes any
        // page to fit it: a landscape card would lose half its width and be
        // stretched in height. It is detected turned a quarter instead (the
        // detector finds words in any orientation) and the boxes turned back.
        let words = if lw > lh {
            let (t, tw, th) = geometry::rotate_quarters(&ink, lw, lh, 1);
            let found = ocr.detect_words(&ocr.prepare_input(ImageSource::from_bytes(&t, (tw as u32, th as u32))?)?)?;
            found.iter().map(|r| idocr::turn_rect(r, tw, th, 3)).collect()
        } else {
            ocr.detect_words(&ocr.prepare_input(ImageSource::from_bytes(&ink, (lw as u32, lh as u32))?)?)?
        };
        Ok(LevelledPage { ink, luma, w: lw, h: lh, skew, words })
    }

    /// Reads a levelled page turned by `quarters` (clockwise), with the
    /// words found upright turned with it.
    fn read_turned(&self, page: &LevelledPage, quarters: u8) -> anyhow::Result<OcrOutput> {
        let ocr = self.ocr.as_ref().ok_or_else(|| anyhow::anyhow!("OCR models not loaded"))?;
        let (img, lw, lh) = geometry::rotate_quarters(&page.ink, page.w, page.h, quarters);
        let input = ocr.prepare_input(ImageSource::from_bytes(&img, (lw as u32, lh as u32))?)?;
        let words: Vec<_> = page.words.iter().map(|r| idocr::turn_rect(r, page.w, page.h, quarters)).collect();
        let line_rects = ocr.find_text_lines(&input, &words);
        // MRZ lines are read on the luma plane, which suits black OCR-B on
        // white, by the recognition model run directly so the MRZ's layout
        // can steer the decoding (mrz_decode.rs). Lines shaped like one (long
        // and thin, across much of the page) go there first, and only those
        // that do not read as an MRZ are then recognised as ordinary text:
        // each line is recognised once.
        let mut decoded: Vec<(usize, mrz_decode::Decoded)> = Vec::new();
        let mut ordinary: Vec<usize> = Vec::new();
        let luma_input = match self.rec_model.as_ref() {
            Some(_) => {
                let (img, lw, lh) = geometry::rotate_quarters(&page.luma, page.w, page.h, quarters);
                Some(ocr.prepare_input(ImageSource::from_bytes(&img, (lw as u32, lh as u32))?)?)
            }
            None => None,
        };
        // The line read on the luma plane by the model run directly: its
        // greedy text, and its MRZ decoding.
        let read_mrz = |line: &[rten_imageproc::RotatedRect]| -> anyhow::Result<Option<(String, Option<mrz_decode::Decoded>)>> {
            let (Some(rec), Some(luma_input)) = (self.rec_model.as_ref(), luma_input.as_ref()) else { return Ok(None) };
            let img = ocr.prepare_recognition_input(luma_input, line)?;
            let [ih, iw] = img.shape();
            let out: rten_tensor::NdTensor<f32, 3> = rec.run_one(img.into_shape([1, 1, ih, iw]).view().into(), None)?.try_into()?;
            // [seq, batch, classes]
            let lp = out.slice((.., 0, ..));
            Ok(Some((mrz_decode::greedy(lp), mrz_decode::read_line(lp))))
        };
        for (i, line) in line_rects.iter().enumerate() {
            if !mrz_shaped(line, lw) {
                ordinary.push(i);
                continue;
            }
            match read_mrz(line)? {
                Some((text, Some(d))) if mrz::looks_like_mrz(&text) => decoded.push((i, d)),
                _ => ordinary.push(i),
            }
        }
        let rects: Vec<Vec<rten_imageproc::RotatedRect>> = ordinary.iter().map(|&i| line_rects[i].clone()).collect();
        let texts = ocr.recognize_text(&input, &rects)?;

        let mut placed = Vec::new();
        let mut stray_mrz = Vec::new();
        for (k, text) in texts.iter().enumerate() {
            let Some(text) = text else { continue };
            let s = text.to_string();
            if mrz::looks_like_mrz(&s) {
                // An MRZ line not shaped like one (a poor outline, a tilt):
                // decoded as the others are when the direct model can.
                match read_mrz(&line_rects[ordinary[k]])? {
                    Some((_, Some(d))) => decoded.push((ordinary[k], d)),
                    _ => stray_mrz.push((ordinary[k], s)),
                }
                continue;
            }
            for word in text.words() {
                let r = word.bounding_rect();
                let mut word_text = word.to_string();
                // `?` is the recogniser's "unsure": in a word of capitals (a
                // name, often crossed by a coloured overprint) read the word
                // again with the alphabet restricted to capitals.
                if word_text.contains('?')
                    && word_text.chars().filter(|c| c.is_ascii_uppercase()).count() * 2 >= word_text.chars().count()
                    && let Some(rec) = self.rec_model.as_ref()
                {
                    let pad = 2.0;
                    let rect = rten_imageproc::RotatedRect::from_rect(rten_imageproc::RectF::from_tlbr(
                        r.top() as f32 - pad,
                        r.left() as f32 - pad,
                        r.bottom() as f32 + pad,
                        r.right() as f32 + pad,
                    ));
                    let img = ocr.prepare_recognition_input(&input, &[rect])?;
                    let [ih, iw] = img.shape();
                    let out: rten_tensor::NdTensor<f32, 3> = rec.run_one(img.into_shape([1, 1, ih, iw]).view().into(), None)?.try_into()?;
                    let again = mrz_decode::greedy_restricted(out.slice((.., 0, ..)), "ABCDEFGHIJKLMNOPQRSTUVWXYZ-'");
                    if !again.is_empty() {
                        word_text = again;
                    }
                }
                placed.push(za::Line {
                    text: word_text,
                    x: r.left() as f32,
                    y: r.top() as f32,
                    w: r.width() as f32,
                    h: r.height() as f32,
                });
            }
        }
        let vocab = za::words(&placed);
        // In reading order: the MRZ's lines are paired by position.
        decoded.sort_by_key(|(i, _)| *i);
        let mut ds: Vec<mrz_decode::Decoded> = decoded.iter().map(|(_, d)| d.clone()).collect();
        mrz_decode::finish_lines(&mut ds, &vocab);
        let mut lines_in_order: Vec<(usize, String)> = decoded.iter().map(|(i, _)| *i).zip(ds.into_iter().map(|d| d.text)).collect();
        lines_in_order.extend(stray_mrz);
        lines_in_order.sort_by_key(|(i, _)| *i);
        let mrz_texts: Vec<String> = lines_in_order.into_iter().map(|(_, s)| s).collect();
        Ok(OcrOutput { lines: za::rows_from_words(placed.clone()), words: placed, mrz: mrz_texts, skew: page.skew })
    }

    /// Proof of address: whether to correct place names and postal codes with the gazetteer (on by default).
    pub fn set_gazetteer(&mut self, on: bool) {
        self.no_gazetteer = !on;
    }

    pub fn load_page_detector_native(&mut self, model: Vec<u8>) -> anyhow::Result<()> {
        self.det = Some(rten::Model::load(model)?);
        Ok(())
    }

    pub fn load_tagger_native(&mut self, model: Vec<u8>) -> anyhow::Result<()> {
        self.tagger = Some(poa::tagger::Tagger::load(model)?);
        Ok(())
    }

    /// OCR words of an enhanced (greyscale) page, in reading order.
    pub fn page_words(&self, grey: &[u8], w: usize, h: usize) -> anyhow::Result<Vec<poa::features::Word>> {
        // DOCSCAN_PAGE_OCR=tiles: the older per-tile recognition, for comparison.
        let tiles = cfg!(not(target_arch = "wasm32")) && std::env::var("DOCSCAN_PAGE_OCR").is_ok_and(|v| v == "tiles");
        let words = if tiles { self.ocr_tiled_words(&page::grey_to_rgba(grey), w, h)? } else { self.ocr_page(grey, w, h)? };
        Ok(poa::features::reading_order(&words))
    }

    /// Words detected on a page with a detection model whose input size is
    /// free (ocrs's own runs only at its declared 800 × 600): the model is
    /// fully convolutional, so it runs on strips the width of the page, and
    /// the stitched probability map is thresholded and its connected
    /// components turned into word rectangles exactly as ocrs does (threshold
    /// 0.2, contours simplified, the minimum-area rectangle grown by 3 px, at
    /// least 100 px²). The 3 × 3 overlapping 600 × 800 tiles covered a page
    /// about twice over, and a word cut by a tile edge had to be de-duplicated.
    fn detect_page(&self, grey: &[u8], w: usize, h: usize) -> anyhow::Result<Vec<rten_imageproc::RotatedRect>> {
        use rten_imageproc::{RetrievalMode, find_contours, min_area_rect, simplify_polygon};
        use rten_tensor::prelude::*;
        use rten_tensor::NdTensor;
        let det = self.det.as_ref().ok_or_else(|| anyhow::anyhow!("OCR models not loaded"))?;
        // The page in strips the full width of the page and STRIP rows tall,
        // overlapping by OVERLAP rows; each pixel's probability is taken from
        // the strip it sits deeper in.
        // 384 rows: the activations of a 1248 × 384 strip are about those of
        // a 600 × 800 tile, so peak memory stays where it was (196 MB against
        // 192 MB natively; a whole page in one pass peaks at 700 MB).
        const STRIP: usize = 384;
        const OVERLAP: usize = 64;
        let pw = w.next_multiple_of(32);
        let sh = STRIP.min(h.next_multiple_of(32));
        let mut starts = vec![0usize];
        while starts.last().unwrap() + sh < h {
            starts.push((starts.last().unwrap() + sh - OVERLAP).min(h.saturating_sub(sh)));
        }
        let mut prob = vec![0f32; w * h];
        for (k, &y0) in starts.iter().enumerate() {
            let mut input = NdTensor::full([1, 1, sh, pw], -0.5f32);
            for y in 0..sh.min(h - y0) {
                for x in 0..w {
                    input[[0, 0, y, x]] = grey[(y0 + y) * w + x] as f32 / 255.0 - 0.5;
                }
            }
            let out: NdTensor<f32, 4> = det.run_one(input.view().as_dyn().into(), None)?.try_into()?;
            // Rows this strip owns: from the middle of the overlap above to the middle of the one below.
            let top = if k == 0 { 0 } else { (starts[k - 1] + sh).saturating_sub(y0) / 2 };
            let bottom = if k + 1 == starts.len() { sh.min(h - y0) } else { (y0 + sh - starts[k + 1]) / 2 + (starts[k + 1] - y0) };
            for y in top..bottom.min(h - y0) {
                for x in 0..w {
                    prob[(y0 + y) * w + x] = out[[0, 0, y, x]];
                }
            }
        }
        let mask = NdTensor::from_fn([h, w], |[y, x]| prob[y * w + x] > 0.2);
        Ok(find_contours(mask.view(), RetrievalMode::External)
            .iter()
            .filter_map(|poly| {
                let pts: Vec<_> = poly.iter().map(|p| p.to_f32()).collect();
                min_area_rect(&simplify_polygon(&pts, 2.0)).map(|mut r| {
                    r.resize(r.width() + 6.0, r.height() + 6.0);
                    r
                })
            })
            .filter(|r| r.area() >= 100.0)
            .collect())
    }

    /// OCR of a whole page, word by word: words are detected tile by tile at
    /// the detection model's native input size (as [`Scanner::ocr_tiled`]
    /// does, so small print keeps its detail), the detections from
    /// overlapping tiles merged, and then every line recognised once, on the
    /// whole page. Recognising per tile reads the overlaps two to four times
    /// over, and recognition is most of OCR's cost. The page is expected to
    /// be level already ([`page::enhance`] deskews it).
    pub fn ocr_page(&self, grey: &[u8], w: usize, h: usize) -> anyhow::Result<Vec<za::Line>> {
        use rten_imageproc::{BoundingRect, Point, RotatedRect};
        let ocr = self.ocr.as_ref().ok_or_else(|| anyhow::anyhow!("OCR models not loaded"))?;
        let profile = cfg!(not(target_arch = "wasm32")) && std::env::var("DOCSCAN_PROFILE").is_ok();
        let t0 = now();
        const TILE_W: usize = 600;
        const TILE_H: usize = 800;
        let starts = |len: usize, tile: usize| -> Vec<usize> {
            if len <= tile {
                return vec![0];
            }
            let n = (len - tile).div_ceil(tile * 3 / 4) + 1;
            let step = (len - tile) as f32 / (n - 1) as f32;
            (0..n).map(|i| (i as f32 * step).round() as usize).collect()
        };
        let words = if self.det.is_some() {
            self.detect_page(grey, w, h)?
        } else {
            let (tw, th) = (TILE_W.min(w), TILE_H.min(h));
            let mut found: Vec<RotatedRect> = Vec::new();
            for &y0 in &starts(h, th) {
                for &x0 in &starts(w, tw) {
                    let mut tile = Vec::with_capacity(tw * th);
                    for y in y0..y0 + th {
                        tile.extend_from_slice(&grey[y * w + x0..y * w + x0 + tw]);
                    }
                    let input = ocr.prepare_input(ImageSource::from_bytes(&tile, (tw as u32, th as u32))?)?;
                    for r in ocr.detect_words(&input)? {
                        let c = r.center();
                        found.push(RotatedRect::new(Point::from_yx(c.y + y0 as f32, c.x + x0 as f32), r.up_axis(), r.width(), r.height()));
                    }
                }
            }
            // A word seen in two tiles: keep the larger detection (the other is
            // usually cut by a tile edge).
            let area = |r: &RotatedRect| r.width() * r.height();
            found.sort_by(|a, b| area(b).total_cmp(&area(a)));
            let mut words: Vec<RotatedRect> = Vec::new();
            for r in found {
                let b = r.bounding_rect();
                let dup = words.iter().any(|k| {
                    let kb = k.bounding_rect();
                    let ow = kb.right().min(b.right()) - kb.left().max(b.left());
                    let oh = kb.bottom().min(b.bottom()) - kb.top().max(b.top());
                    ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (b.width() * b.height()).min(kb.width() * kb.height())
                });
                if !dup {
                    words.push(r);
                }
            }
            words
        };
        let t1 = now();
        let input = ocr.prepare_input(ImageSource::from_bytes(grey, (w as u32, h as u32))?)?;
        let lines = ocr.find_text_lines(&input, &words);
        // A "line" of word boxes far apart (two stray words found again in a
        // line that already has them) is recognised as one crop spanning the
        // gap, which reads every word in between a second time: split lines
        // at wide gaps.
        let mut split: Vec<Vec<RotatedRect>> = Vec::new();
        for line in lines {
            let mut cur: Vec<RotatedRect> = Vec::new();
            for r in line {
                if let Some(prev) = cur.last() {
                    let (pb, b) = (prev.bounding_rect(), r.bounding_rect());
                    let h = pb.height().max(b.height()).max(1.0);
                    if b.left() - pb.right() > 3.0 * h {
                        split.push(std::mem::take(&mut cur));
                    }
                }
                cur.push(r);
            }
            if !cur.is_empty() {
                split.push(cur);
            }
        }
        // In batches: recognising a page's hundred-odd lines at once holds
        // every line image (and the model's activations for all of them) in
        // memory together, which in wasm grows the heap for good.
        // ocrs pads every line of a batch to the batch's widest (in steps of
        // 50 px at the recogniser's height) and runs each width group
        // separately, so 16 lines in reading order make many small groups:
        // batch lines of similar width together (by their width at that
        // height), and put the readings back in order.
        let aspect = |line: &[RotatedRect]| {
            let (x0, x1) = line.iter().map(|r| r.bounding_rect()).fold((f32::MAX, f32::MIN), |(a, b), r| (a.min(r.left()), b.max(r.right())));
            let h = line.iter().map(|r| r.bounding_rect().height()).fold(1.0f32, f32::max);
            (x1 - x0) / h
        };
        let mut order: Vec<usize> = (0..split.len()).collect();
        order.sort_by(|&a, &b| aspect(&split[a]).total_cmp(&aspect(&split[b])));
        let mut texts: Vec<Option<ocrs::TextLine>> = vec![None; split.len()];
        for batch in order.chunks(16) {
            let lines: Vec<Vec<RotatedRect>> = batch.iter().map(|&i| split[i].clone()).collect();
            for (&i, t) in batch.iter().zip(ocr.recognize_text(&input, &lines)?) {
                texts[i] = t;
            }
        }
        if profile {
            let words: usize = split.iter().map(|l| l.len()).sum();
            eprintln!("ocr_page: detect {:.0} ms, recognise {:.0} ms ({} lines, {} words)", t1 - t0, now() - t1, split.len(), words);
        }
        // Words read twice (by two overlapping line crops): keep the reading
        // from the line with more words, whose crop fits the text best.
        let mut read: Vec<(usize, za::Line)> = Vec::new();
        for (li, text) in texts.into_iter().enumerate() {
            let Some(text) = text else { continue };
            for word in text.words() {
                let r = word.bounding_rect();
                read.push((split[li].len(), za::Line { text: word.to_string(), x: r.left() as f32, y: r.top() as f32, w: r.width() as f32, h: r.height() as f32 }));
            }
        }
        read.sort_by(|a, b| b.0.cmp(&a.0));
        let mut out: Vec<za::Line> = Vec::new();
        for (_, l) in read {
            let dup = out.iter().any(|k| {
                let ow = (k.x + k.w).min(l.x + l.w) - k.x.max(l.x);
                let oh = (k.y + k.h).min(l.y + l.h) - k.y.max(l.y);
                ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (l.w * l.h).min(k.w * k.h)
            });
            if !dup {
                out.push(l);
            }
        }
        Ok(out)
    }

    /// [`Scanner::address`]: also returns the page's words.
    pub fn address_native(
        &self,
        rgba: &[u8],
        w: usize,
        h: usize,
        today: poa::verify::Date,
        method: Option<poa::Method>,
    ) -> anyhow::Result<(poa::AddressResult, Vec<poa::features::Word>)> {
        let t0 = now();
        let (grey, pw, ph) = prepare_page(rgba, w, h);
        let t1 = now();
        let words = self.page_words(&grey, pw, ph)?;
        let t2 = now();
        let r = self.address_from_words(&words, pw, ph, today, method)?;
        let t3 = now();
        let mut r = r;
        r.timings_ms = poa::AddressTimings { enhance: t1 - t0, ocr: t2 - t1, extract: t3 - t2, total: t3 - t0 };
        Ok((r, words))
    }

    /// The fields from a page's OCR words, by the tagger or by rules.
    pub fn address_from_words(
        &self,
        words: &[poa::features::Word],
        pw: usize,
        ph: usize,
        today: poa::verify::Date,
        method: Option<poa::Method>,
    ) -> anyhow::Result<poa::AddressResult> {
        let text = poa::page_text(words);
        let method = method.unwrap_or(if self.tagger.is_some() { poa::Method::Tagger } else { poa::Method::Rules });
        let (fields, confidence, spans) = match method {
            poa::Method::Tagger => {
                let tagger = self.tagger.as_ref().ok_or_else(|| anyhow::anyhow!("the tagger is not loaded"))?;
                let probs = tagger.probabilities(words, pw as f32, ph as f32)?;
                let spans = poa::tagger::spans(words, &probs);
                let (mut f, mut c) = poa::fields_from_spans(words, &spans, &text);
                // A key field the tagger found nothing for: the rules' reading, if any.
                let a = &f.address;
                if (f.document_date.is_none() && f.statement_period.is_none())
                    || f.holder_name.is_none()
                    || a.street.is_none()
                    || a.city.is_none()
                    || a.postal_code.is_none()
                {
                    let (rf, _) = poa::rules::extract(words, ph as f32, &text, today);
                    if f.document_date.is_none() && f.statement_period.is_none()
                        && let Some(d) = rf.document_date
                    {
                        f.document_date = Some(d);
                        c.push(("document_date", 0.3));
                    }
                    if poa::RULES_FILL {
                        for (field, mine, theirs) in [
                            ("holder_name", &mut f.holder_name, rf.holder_name),
                            ("street", &mut f.address.street, rf.address.street),
                            ("city", &mut f.address.city, rf.address.city),
                            ("postal_code", &mut f.address.postal_code, rf.address.postal_code),
                        ] {
                            if mine.is_none() && theirs.is_some() {
                                *mine = theirs;
                                c.push((field, poa::capture::RULES_FILL_CONFIDENCE));
                            }
                        }
                    }
                }
                (f, c, spans)
            }
            poa::Method::Rules => {
                let (f, c) = poa::rules::extract(words, ph as f32, &text, today);
                (f, c, Vec::new())
            }
        };
        let mut fields = fields;
        if !self.no_gazetteer {
            poa::gazetteer::correct(&mut fields);
            poa::infer_province(&mut fields);
        }
        let verification = poa::verify_fields(&fields, &text, &confidence, today);
        Ok(poa::AddressResult {
            method,
            fields,
            verification,
            text,
            words: words.len(),
            spans,
            page_size: [pw as u32, ph as u32],
            timings_ms: Default::default(),
        })
    }

    /// The widest image [`Scanner::labelled_native`] reads print from.
    pub const LABEL_OCR_WIDTH_PX: u32 = 1280;

    pub fn labelled_native(&self, rgba: &[u8], width: u32, height: u32) -> anyhow::Result<labels::Labelled> {
        let luma = quality::rgba_to_luma(rgba);
        let barcodes = barcode::read_all(&luma, width, height, None);
        // Bar patches, read or not: they give decoded codes their extent and
        // let unreadable bars claim the value printed beside them.
        let regions: Vec<[f32; 4]> = barcode::oriented_regions(&luma, width as usize, height as usize).iter().map(|r| r.bounds()).collect();
        // Print is read at most LABEL_OCR_WIDTH_PX wide, the size the browser
        // analyses: device-label print is large enough there, and a larger
        // frame only costs tiles (a 1920-wide frame takes ten rather than
        // three, and reads no better).
        let k = (Self::LABEL_OCR_WIDTH_PX as f32 / width as f32).min(1.0);
        let lines = if k < 1.0 {
            let (small, sw, sh) = quality::scale_rgba(rgba, width as usize, height as usize, k);
            let mut lines = self.ocr_tiled(&small, sw, sh)?;
            for l in &mut lines {
                (l.x, l.y, l.w, l.h) = (l.x / k, l.y / k, l.w / k, l.h / k);
            }
            lines
        } else {
            self.ocr_tiled(rgba, width as usize, height as usize)?
        };
        Ok(labels::associate(&barcodes, &regions, &lines))
    }

    /// OCR of a whole frame in overlapping tiles about the detection model's
    /// input size (600 × 800). The model squashes a larger image to fit, which
    /// costs small print (a device label's digits) the detail it needs; tiles
    /// keep every pixel, and are scaled up when the frame is small. Lines come
    /// back in frame pixels, with duplicates from the overlaps removed.
    pub fn ocr_tiled(&self, rgba: &[u8], w: usize, h: usize) -> anyhow::Result<Vec<za::Line>> {
        self.tiled(rgba, w, h, false, |o| o.lines)
    }

    /// [`Scanner::ocr_tiled`], word by word rather than line by line.
    pub fn ocr_tiled_words(&self, rgba: &[u8], w: usize, h: usize) -> anyhow::Result<Vec<za::Line>> {
        self.tiled(rgba, w, h, true, |o| o.words)
    }

    /// `sparse`: overlap neighbouring tiles by at least a quarter rather than
    /// spacing them a quarter apart, which saves a row or column of tiles on
    /// a page whose lines of print are short against the tile.
    fn tiled(&self, rgba: &[u8], w: usize, h: usize, sparse: bool, pick: impl Fn(OcrOutput) -> Vec<za::Line>) -> anyhow::Result<Vec<za::Line>> {
        const TILE_W: usize = 600;
        const TILE_H: usize = 800;
        // Small frames: one tile, enlarged to the model's size.
        let tiles = |len: usize, tile: usize| -> Vec<usize> {
            if len <= tile {
                return vec![0];
            }
            let n = if sparse { (len - tile).div_ceil(tile * 3 / 4) + 1 } else { len.div_ceil(tile * 3 / 4) };
            let step = (len - tile) as f32 / (n - 1).max(1) as f32;
            (0..n).map(|i| (i as f32 * step).round() as usize).collect()
        };
        let (tw, th) = (TILE_W.min(w), TILE_H.min(h));
        let mut all: Vec<za::Line> = Vec::new();
        for &y0 in &tiles(h, th) {
            for &x0 in &tiles(w, tw) {
                let mut tile = Vec::with_capacity(tw * th * 4);
                for y in y0..y0 + th {
                    tile.extend_from_slice(&rgba[(y * w + x0) * 4..(y * w + x0 + tw) * 4]);
                }
                // Enlarge to fill the model's input, up to 2×.
                let k = ((TILE_W as f32 / tw as f32).min(TILE_H as f32 / th as f32)).clamp(1.0, 2.0);
                let (tile, sw, sh) = if k > 1.05 { quality::scale_rgba(&tile, tw, th, k) } else { (tile, tw, th) };
                let ocr = self.ocr_lines(&tile, sw as u32, sh as u32)?;
                let skew = ocr.skew;
                for mut l in pick(ocr) {
                    if skew.abs() >= 1.0 {
                        let c = [[l.x, l.y], [l.x + l.w, l.y], [l.x, l.y + l.h], [l.x + l.w, l.y + l.h]]
                            .map(|p| geometry::rotated_to_source(p, sw, sh, skew));
                        let (x0, x1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
                        let (y0, y1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
                        (l.x, l.y, l.w, l.h) = (x0, y0, x1 - x0, y1 - y0);
                    }
                    (l.x, l.y, l.w, l.h) = (l.x / k + x0 as f32, l.y / k + y0 as f32, l.w / k, l.h / k);
                    all.push(l);
                }
            }
        }
        // A line read in two overlapping tiles: keep the longer reading (the
        // other is usually cut by a tile edge).
        all.sort_by(|a, b| b.text.chars().count().cmp(&a.text.chars().count()));
        let mut kept: Vec<za::Line> = Vec::new();
        for l in all {
            let dup = kept.iter().any(|k| {
                let ow = (k.x + k.w).min(l.x + l.w) - k.x.max(l.x);
                let oh = (k.y + k.h).min(l.y + l.h) - k.y.max(l.y);
                ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (l.w * l.h).min(k.w * k.h)
            });
            if !dup {
                kept.push(l);
            }
        }
        kept.sort_by(|a, b| a.y.total_cmp(&b.y).then(a.x.total_cmp(&b.x)));
        Ok(kept)
    }

    pub fn analyse(
        &self,
        rgba: &[u8],
        width: u32,
        height: u32,
        run_ocr: bool,
        expected: Expected,
    ) -> anyhow::Result<DocumentResult> {
        let t0 = now();
        let luma = quality::rgba_to_luma(rgba);
        let (w, h) = (width as usize, height as usize);
        // Flatten the document when its outline is found; tilt and
        // perspective defeat both the PDF417 reader and line OCR.
        let document = quad::find_document(rgba, w, h);
        let flat = document.and_then(|q| {
            let (ow, oh) = quad::output_size(&q, 1600);
            quad::warp(&luma, w, h, 1, &q.corners, ow, oh).map(|img| (img, ow, oh))
        });
        let (work, ww, wh) = match &flat {
            Some((img, ow, oh)) => (img.as_slice(), *ow, *oh),
            None => (luma.as_slice(), w, h),
        };
        let q = quality::measure(work, ww, wh);
        // OCR reads the ink plane, flattened the same way.
        let ink = || {
            let plane = quality::rgba_to_ink(rgba);
            match &document {
                Some(quad) => quad::warp(&plane, w, h, 1, &quad.corners, ww, wh).unwrap_or(plane),
                None => plane,
            }
        };
        let t1 = now();

        let formats: Vec<String> = barcode::ID_FORMATS.iter().map(|s| s.to_string()).collect();
        let mut barcodes = barcode::read_all(work, ww as u32, wh as u32, Some(&formats));
        if flat.is_some() && !barcodes.iter().any(|b| b.format == "pdf417") && idback::frame_has_wide_bars(&luma, w, h) {
            // A wrong outline must not cost a barcode the raw frame would give.
            // (Only when the frame shows a patch of bars that could be one:
            // reading the whole frame again costs as much as the first read,
            // on every frame of a card front or a passport.)
            let raw = barcode::read_all(&luma, width, height, Some(&formats));
            if raw.iter().any(|b| b.format == "pdf417") {
                barcodes = raw;
            }
        }
        if let (Some(quad), Some((_, ow, oh))) = (&document, &flat)
            && !barcodes.iter().any(|b| b.format == "pdf417")
            && idback::roughly_card_shaped(*ow, *oh)
            && idback::has_wide_bars(work, ww, wh)
        {
            barcodes.extend(idback::rescue_pdf417(&luma, w, h, quad, *ow, *oh));
        }
        let smart_id_barcode = barcodes
            .iter()
            .filter(|b| b.format == "pdf417")
            .find_map(|b| za::parse_smart_id_barcode(&b.text));
        let t2 = now();

        // The outline's proportions, when there is one: the frame's own are
        // the guide's, and say nothing about the document.
        let shape = flat.as_ref().map(|(_, ow, oh)| (*ow, *oh));
        let mut result = if run_ocr && self.ocr.is_some() && smart_id_barcode.is_none() {
            // ocrs reads only upright text, and a page may be sideways (an ID
            // book photographed in landscape) or upside down. Try the turns
            // the page's shape allows, most likely first, and keep the first
            // that reads as a document. An OCR pass costs over a second in the
            // browser, so the search is kept as short as the shape allows.
            // A small document is read enlarged: the detector pads anything
            // smaller than its 600 x 800 input rather than scaling it up, so
            // small print stays small to it.
            let k = (OCR_MIN_LONG / ww.max(wh) as f32).clamp(1.0, 2.5);
            let (page, k) = if k > 1.05 {
                let (sw, sh) = ((ww as f32 * k).round() as usize, (wh as f32 * k).round() as usize);
                let corners = match &document {
                    Some(quad) => quad.corners,
                    None => [[0.0, 0.0], [w as f32, 0.0], [w as f32, h as f32], [0.0, h as f32]],
                };
                let ink_big = quad::warp(&quality::rgba_to_ink(rgba), w, h, 1, &corners, sw, sh);
                let luma_big = quad::warp(&luma, w, h, 1, &corners, sw, sh);
                match (ink_big, luma_big) {
                    (Some(i), Some(l)) => (self.level_page(&i, &l, sw, sh)?, sw as f32 / ww as f32),
                    _ => (self.level_page(&ink(), work, ww, wh)?, 1.0),
                }
            } else {
                (self.level_page(&ink(), work, ww, wh)?, 1.0)
            };
            let mut attempt: Option<DocumentResult> = None;
            let mut order = first_turns(expected, shape, self.last_turn.get());
            // The word boxes' shape says whether the text runs across or
            // down the page: when it is clear, only turns that make the
            // text run across are read.
            let across = idocr::text_runs_across(&page.words);
            if let Some(across) = across {
                let ok = |t: &u8| (t % 2 == 0) == across;
                order.retain(ok);
                if order.is_empty() {
                    let last = self.last_turn.get().filter(ok);
                    order.push(last.unwrap_or(if across { 0 } else { 1 }));
                }
            }
            let mut passes = 0u8;
            let mut i = 0;
            while i < order.len() {
                let quarters = order[i];
                i += 1;
                let mut ocr = self.read_turned(&page, quarters)?;
                if k > 1.0 {
                    // Positions in the flattened document's pixels.
                    for l in ocr.lines.iter_mut().chain(ocr.words.iter_mut()) {
                        (l.x, l.y, l.w, l.h) = (l.x / k, l.y / k, l.w / k, l.h / k);
                    }
                }
                passes += 1;
                let readable = readable_lines(&ocr.lines);
                let mut r = classify(q.clone(), barcodes.clone(), smart_id_barcode.clone(), ocr, expected, shape);
                r.quarter_turns = quarters;
                let found = r.kind != DocumentKind::Unknown && !r.lines.is_empty();
                // If no turn identifies the document, retain the reading with
                // the most readable lines. The last turn is often upside-down
                // noise; it must not overwrite useful upright text. Identified
                // documents still win and stop the search exactly as before.
                if prefer_orientation(&r, attempt.as_ref()) {
                    attempt = Some(r);
                }
                if found {
                    self.last_turn.set(Some(quarters));
                    break;
                }
                if i == order.len() {
                    // Plenty of text that is no known document is probably
                    // upside down; too little means the page is sideways.
                    // When the page asked for a particular document, a frame
                    // without an outline is not searched further: it cannot
                    // be captured, and the next frame will have one.
                    let any = expected == Expected::Any;
                    let next: &[u8] = match quarters {
                        0 if readable >= 8 => &[2],
                        0 if any => &[1, 3],
                        1 if any => &[3, 0],
                        3 if any => &[1, 0],
                        1 => &[3],
                        3 => &[1],
                        // Upside down was tried first only because the last
                        // document read that way: try it upright.
                        2 => &[0],
                        _ => &[],
                    };
                    let next: Vec<u8> = match across {
                        // Text across the page: upright or upside down; down it: one of the sideways turns.
                        Some(true) => vec![(quarters + 2) % 4],
                        Some(false) => vec![if quarters == 1 { 3 } else { 1 }],
                        None => next.to_vec(),
                    };
                    order.extend(next.iter().filter(|t| !order.contains(t)).copied().collect::<Vec<_>>());
                    // Three passes at most: over three seconds in the browser.
                    order.truncate(3);
                }
            }
            let mut r = attempt.unwrap();
            r.ocr_passes = passes;
            r
        } else {
            classify(q, barcodes, smart_id_barcode, OcrOutput::default(), expected, shape)
        };
        result.copy_assessment = document_evidence::assess_pixels(rgba, w, h);
        let t3 = now();

        result.timings_ms = Timings { quality: t1 - t0, barcodes: t2 - t1, ocr: t3 - t2, total: t3 - t0 };
        result.document = document;
        result.analysed_size = [ww as u32, wh as u32];
        Ok(result)
    }
}

/// Rank only unknown readings, retaining their orientation and geometry.
/// Ties keep the earlier unknown attempt. A classified result (even an MRZ
/// with no ordinary text) preserves the old last-attempt rule; readable text
/// must not change which classified reading or acceptance decision is returned.
fn prefer_orientation(candidate: &DocumentResult, best: Option<&DocumentResult>) -> bool {
    best.is_none_or(|best| {
        candidate.kind != DocumentKind::Unknown
            || best.kind != DocumentKind::Unknown
            || readable_lines(&candidate.lines) > readable_lines(&best.lines)
    })
}

/// The same coarse evidence used to decide which orientation to try next.
fn readable_lines(lines: &[za::Line]) -> usize {
    lines.iter().filter(|line| line.text.chars().filter(|c| c.is_alphanumeric()).count() >= 4).count()
}

/// The quarter turns to try first. A document whose upright shape is known
/// (a card or passport page is landscape, a green book page portrait) is
/// upright or upside down when the outline has that shape, and sideways when
/// it does not; the turn that read last time goes first.
fn first_turns(expected: Expected, shape: Option<(usize, usize)>, last: Option<u8>) -> Vec<u8> {
    let sideways = match (expected.landscape(), shape) {
        (Some(landscape), Some((w, h))) => Some((w >= h) != landscape),
        _ => None,
    };
    match sideways {
        Some(true) => match last {
            Some(3) => vec![3],
            _ => vec![1],
        },
        Some(false) => vec![if last == Some(2) { 2 } else { 0 }],
        // No outline (or any document): start from the turn that read last.
        None => vec![last.unwrap_or(0)],
    }
}

/// The long side, in pixels, a document is enlarged to (from the frame,
/// at most 2.5x) before OCR when it is smaller. On DEV's small and 640-wide
/// frames this read more fields than reading them as they are (1 300 did
/// no better than 1 000).
const OCR_MIN_LONG: f32 = 1000.0;

/// The current year, from the device's clock.
fn this_year() -> u32 {
    // Days since 1970 to a year is close enough for a century cut-off.
    1970 + (now() / 1000.0 / 86_400.0 / 365.2425) as u32
}

/// Whether a text line has the shape of an MRZ line: at least 28
/// characters of fixed-pitch OCR-B make it long and thin (width over 12
/// times its height) and it spans much of the page (over 45% of its width).
fn mrz_shaped(line: &[rten_imageproc::RotatedRect], page_width: usize) -> bool {
    let Some(b) = rten_imageproc::bounding_rect(line.iter()) else { return false };
    b.width() > 12.0 * b.height() && b.width() > 0.45 * page_width as f32
}

/// Words printed on the smart ID card's back (the conditions panel).
const SMART_ID_BACK_ANCHORS: &[&str] = &["Home Affairs", "Identification Act", "Conditions"];

fn classify(
    quality: quality::Quality,
    barcodes: Vec<barcode::Barcode>,
    smart_id_barcode: Option<za::SmartIdBarcode>,
    ocr: OcrOutput,
    expected: Expected,
    shape: Option<(usize, usize)>,
) -> DocumentResult {
    let mut reasons = Vec::new();
    let lines = ocr.lines;
    let mrz = mrz::find_mrz(&ocr.mrz).map(|mut m| {
        // Check digits do not cover the names, and the recogniser often reads
        // a lone `<` between names as a letter; the printed names repair it.
        let vocab = za::words(&lines);
        mrz::repair_names(&mut m, &vocab);
        let printed: Vec<String> = lines.iter().map(|l| l.text.clone()).collect();
        mrz::split_names_by_print(&mut m, &printed);
        m
    });
    // An identity number in a linear barcode. Both the green book and the
    // smart ID back carry one, so on its own it does not say which.
    let id_barcode = barcodes.iter().find_map(|b| {
        (b.format != "pdf417")
            .then(|| za::parse_id_number(b.text.trim()))
            .flatten()
            .filter(|id| id.luhn_valid && id.date_valid)
    });

    let mut out = DocumentResult {
        kind: DocumentKind::Unknown,
        accepted: false,
        copy_assessment: document_evidence::CopyAssessment::default(),
        reasons: Vec::new(),
        quality,
        barcodes,
        mrz: None,
        smart_id_barcode: None,
        id_barcode: id_barcode.clone(),
        printed: None,
        lines,
        mrz_lines: ocr.mrz,
        skew: ocr.skew,
        quarter_turns: 0,
        ocr_passes: 0,
        document: None,
        analysed_size: [0, 0],
        timings_ms: Timings::default(),
    };

    if let Some(b) = smart_id_barcode {
        out.kind = DocumentKind::ZaSmartIdBack;
        // The card's Code 39 repeats the identity number: when both are read
        // they must agree.
        let agree = id_barcode.as_ref().is_none_or(|id| id.value == b.id_number.value);
        out.accepted = b.id_number.luhn_valid && agree;
        reasons.push("smart ID PDF417 parsed".into());
        if !agree {
            reasons.push("the PDF417 and Code 39 identity numbers differ".into());
        }
        out.smart_id_barcode = Some(b);
        out.reasons = reasons;
        return out;
    }

    if let Some(m) = mrz {
        out.kind = match (m.format, m.issuing_state.as_str()) {
            ("TD3", "ZAF") => DocumentKind::ZaPassport,
            ("TD3", "GBR") => DocumentKind::GbPassport,
            ("TD3", _) => DocumentKind::OtherPassport,
            _ => DocumentKind::OtherIdCard,
        };
        // Check digits do not cover the state codes: a code no state uses
        // means letters were misread (a defocused page whose digits happen
        // to check out).
        let states_ok = mrz::valid_state(&m.issuing_state) && mrz::valid_state(&m.nationality);
        out.accepted = m.checks.all() && states_ok;
        reasons.push(format!("{} MRZ, check digits {}", m.format, if m.checks.all() { "pass" } else { "fail" }));
        if !states_ok {
            reasons.push(format!("unknown state code ({} / {})", m.issuing_state, m.nationality));
        }
        out.mrz = Some(m);
        out.reasons = reasons;
        return out;
    }

    let lines = &out.lines;
    let is_book = za::has_any(lines, za::GREEN_BOOK_ANCHORS);
    let is_passport = za::has_any(lines, za::PASSPORT_ANCHORS);
    let is_card_front = !is_passport && za::has_any(lines, za::SMART_ID_FRONT_ANCHORS);
    let is_card_back = za::has_any(lines, SMART_ID_BACK_ANCHORS);

    if is_book && !is_card_back {
        out.kind = DocumentKind::ZaGreenBook;
        let mut printed = za::green_book_fields(lines);
        if printed.id_number.is_none() {
            printed.id_number = id_barcode.clone();
        }
        let id_ok = printed.id_number.as_ref().is_some_and(|id| id.luhn_valid && id.date_valid);
        let agree = match (&id_barcode, &printed.id_number) {
            (Some(b), Some(p)) => b.value == p.value,
            _ => true,
        };
        // As on the card front, the holder's name must be read too: an ID
        // number alone (the barcode) does not make a complete reading.
        out.accepted = id_ok && agree && printed.surname.is_some();
        reasons.push(format!(
            "green book: barcode {}, printed ID {}, surname {}",
            id_barcode.is_some(),
            id_ok,
            printed.surname.is_some()
        ));
        if !agree {
            reasons.push("printed and barcoded ID numbers differ".into());
        }
        out.printed = Some(printed);
    } else if is_card_front {
        out.kind = DocumentKind::ZaSmartIdFront;
        let mut printed = za::smart_id_front_fields(lines);
        za::complete_from_id(&mut printed, this_year());
        let id_ok = printed.id_number.as_ref().is_some_and(|id| id.luhn_valid && id.date_valid);
        out.accepted = id_ok && printed.surname.is_some();
        reasons.push(format!("smart ID front: printed ID {id_ok}, surname {}", printed.surname.is_some()));
        out.printed = Some(printed);
    } else if is_card_back || (id_barcode.is_some()
        && (expected == Expected::SmartIdBack
            || (expected != Expected::GreenBook && shape.is_some_and(|(w, h)| card_shaped(w, h)))))
    {
        // The back of a smart ID card whose PDF417 was not read: the Code 39
        // gives the identity number and nothing else. Never accepted on its
        // own; the page may settle for it when the PDF417 will not read.
        out.kind = DocumentKind::ZaSmartIdBack;
        reasons.push(match &id_barcode {
            Some(_) => "smart ID back: Code 39 identity number only, the PDF417 was not read".into(),
            None => "smart ID back: neither barcode was read".into(),
        });
    } else if id_barcode.is_some() {
        reasons.push("an identity number barcode, but nothing printed says which document it is on".into());
    } else if is_passport {
        reasons.push("a passport page, but the MRZ was not read".into());
    } else if !lines.is_empty() {
        reasons.push("no MRZ, barcode or known anchors".into());
    }
    out.reasons = reasons;
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn quality() -> quality::Quality {
        quality::Quality { sharpness: 100.0, glare: 0.0, brightness: 128.0, edge_density: 0.1 }
    }

    fn code39(text: &str) -> barcode::Barcode {
        barcode::Barcode { format: "code39".into(), text: text.into(), bytes: vec![], points: vec![] }
    }

    fn line(text: &str, y: f32) -> za::Line {
        za::Line { text: text.into(), x: 10.0, y, w: 300.0, h: 20.0 }
    }

    /// A Code 39 identity number alone is on both the green book and the
    /// smart ID back; it must not make a card back into a green book.
    #[test]
    fn lone_id_barcode_is_not_a_green_book() {
        let ocr = || OcrOutput::default();
        let id = "9003141234083";
        let card = classify(quality(), vec![code39(id)], None, ocr(), Expected::Any, Some((1270, 800)));
        assert_eq!(card.kind, DocumentKind::ZaSmartIdBack);
        assert!(!card.accepted);
        assert_eq!(card.id_barcode.as_ref().map(|i| i.value.as_str()), Some(id));

        let unshaped = classify(quality(), vec![code39(id)], None, ocr(), Expected::Any, None);
        assert_eq!(unshaped.kind, DocumentKind::Unknown);

        let asked = classify(quality(), vec![code39(id)], None, ocr(), Expected::SmartIdBack, None);
        assert_eq!(asked.kind, DocumentKind::ZaSmartIdBack);

        // With the book's printed anchors it is a green book.
        let book_ocr = OcrOutput {
            lines: vec![line("VAN/SURNAME", 10.0), line("VAN DER SPECIMEN", 35.0), line("I.D. No. 9003141234083", 80.0)],
            ..Default::default()
        };
        let book = classify(quality(), vec![code39(id)], None, book_ocr, Expected::Any, Some((1000, 1420)));
        assert_eq!(book.kind, DocumentKind::ZaGreenBook);
        assert!(book.accepted);
    }

    /// The smart ID back's PDF417 and Code 39 carry the same number.
    #[test]
    fn smart_id_back_barcodes_must_agree() {
        let pdf = "TESTERSON|ZANELE|F|RSA|9003141234083|14 MAR 1990|RSA|CITIZEN";
        let parsed = za::parse_smart_id_barcode(pdf);
        let ok = classify(quality(), vec![code39("9003141234083")], parsed.clone(), OcrOutput::default(), Expected::Any, None);
        assert!(ok.accepted);
        let bad = classify(quality(), vec![code39("8001015009087")], parsed, OcrOutput::default(), Expected::Any, None);
        assert_eq!(bad.kind, DocumentKind::ZaSmartIdBack);
        assert!(!bad.accepted);
    }

    fn unknown_reading(texts: &[&str], quarters: u8) -> DocumentResult {
        let mut r = classify(
            quality(), vec![], None,
            OcrOutput { lines: texts.iter().enumerate().map(|(i, t)| line(t, i as f32 * 20.0)).collect(), ..Default::default() },
            Expected::Any, None,
        );
        assert_eq!(r.kind, DocumentKind::Unknown);
        assert!(!r.accepted);
        r.quarter_turns = quarters;
        r
    }

    #[test]
    fn unknown_orientation_keeps_readable_text_in_either_search_order() {
        let upright = unknown_reading(&["MEMBERSHIP CERTIFICATE", "ALÉX EXAMPLE", "VALID UNTIL"], 0);
        let inverted = unknown_reading(&["<>??", "i1", "s", "0", "??"], 2);
        assert!(prefer_orientation(&upright, None));
        assert!(prefer_orientation(&upright, Some(&inverted)));
        assert!(!prefer_orientation(&inverted, Some(&upright)));
        let mut best = None;
        for r in [inverted.clone(), upright, inverted] {
            if prefer_orientation(&r, best.as_ref()) {
                best = Some(r);
            }
        }
        let best = best.unwrap();
        assert_eq!(best.quarter_turns, 0);
        assert_eq!(best.lines[1].text, "ALÉX EXAMPLE");
        assert_eq!(best.lines[1].y, 20.0);
        assert!(!best.accepted);
    }

    #[test]
    fn unknown_orientation_ties_keep_the_first_attempt() {
        let first = unknown_reading(&["EXAMPLE"], 1);
        let later = unknown_reading(&["SAMPLE"], 3);
        assert!(!prefer_orientation(&later, Some(&first)));
        let empty = unknown_reading(&[], 0);
        assert!(prefer_orientation(&empty, None));
        assert!(!prefer_orientation(&empty, Some(&empty)));
        assert_eq!(readable_lines(&[line("ÄBCD", 0.0), line("!!!", 20.0), line("ABC", 40.0)]), 1);
    }

    #[test]
    fn identified_orientation_wins_even_when_it_is_not_accepted() {
        let unknown = unknown_reading(&["MEMBERSHIP CERTIFICATE", "ALÉX EXAMPLE", "VALID UNTIL"], 0);
        let identified = classify(
            quality(), vec![], None,
            OcrOutput { lines: vec![line("VAN/SURNAME", 0.0)], ..Default::default() },
            Expected::Any, None,
        );
        assert_eq!(identified.kind, DocumentKind::ZaGreenBook);
        assert!(!identified.accepted);
        assert!(prefer_orientation(&identified, Some(&unknown)));
    }

    #[test]
    fn mrz_without_ordinary_text_keeps_the_existing_last_attempt_rule() {
        let mrz_only = classify(
            quality(), vec![], None,
            OcrOutput {
                mrz: vec![
                    "P<GBRUK<SPECIMEN<<ANGELA<ZOE<<<<<<<<<<<<<<<<".into(),
                    "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06".into(),
                ],
                ..Default::default()
            },
            Expected::Any, None,
        );
        assert_eq!(mrz_only.kind, DocumentKind::GbPassport);
        assert!(mrz_only.accepted && mrz_only.lines.is_empty());
        let readable = unknown_reading(&["MEMBERSHIP CERTIFICATE", "ALÉX EXAMPLE"], 0);
        let empty = unknown_reading(&[], 2);
        assert!(prefer_orientation(&mrz_only, Some(&readable)));
        assert!(prefer_orientation(&empty, Some(&mrz_only)));
    }

    #[test]
    fn turns_follow_the_outline() {
        // A card seen in portrait is sideways; a book page seen landscape too.
        assert_eq!(first_turns(Expected::SmartIdFront, Some((600, 950)), None), vec![1]);
        assert_eq!(first_turns(Expected::SmartIdFront, Some((950, 600)), None), vec![0]);
        assert_eq!(first_turns(Expected::GreenBook, Some((1000, 700)), Some(3)), vec![3]);
        assert_eq!(first_turns(Expected::GreenBook, Some((700, 1000)), None), vec![0]);
        assert_eq!(first_turns(Expected::Any, Some((1000, 700)), None), vec![0]);
    }
}
