//! `docscan/src/exposure.rs`, unchanged, behind a minimal raw ABI so Node can
//! drive the wasm32 build without wasm-bindgen: `alloc`, then `run` on RGB or
//! RGBA bytes, then read the result through the accessors. One call at a time.

#[allow(dead_code)]
#[path = "../../../../docscan/src/exposure.rs"]
mod exposure;

static mut OUT: Vec<u8> = Vec::new();
static mut P90: f64 = 0.0;
static mut GAIN: f64 = 0.0;

#[unsafe(no_mangle)]
pub extern "C" fn alloc(len: usize) -> *mut u8 {
    let mut v = vec![0u8; len];
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

#[unsafe(no_mangle)]
pub extern "C" fn free(ptr: *mut u8, len: usize) {
    unsafe { drop(Vec::from_raw_parts(ptr, len, len)) }
}

/// -1 on error, 0 when the gate stayed shut, 1 when applied, 2 when applied
/// and changed.
#[unsafe(no_mangle)]
pub extern "C" fn run(ptr: *const u8, len: usize, width: usize, height: usize, rgba: u32) -> i32 {
    let pixels = unsafe { std::slice::from_raw_parts(ptr, len) };
    let layout = if rgba == 1 { exposure::Layout::Rgba } else { exposure::Layout::Rgb };
    match exposure::correct(pixels, width, height, layout) {
        Err(_) => -1,
        Ok(c) => unsafe {
            P90 = c.diagnostics.background_p90;
            GAIN = c.diagnostics.gain;
            OUT = c.pixels.unwrap_or_default();
            if !c.diagnostics.applied { 0 } else if c.changed { 2 } else { 1 }
        },
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn out_ptr() -> *const u8 {
    unsafe { (*std::ptr::addr_of!(OUT)).as_ptr() }
}

#[unsafe(no_mangle)]
pub extern "C" fn out_len() -> usize {
    unsafe { (*std::ptr::addr_of!(OUT)).len() }
}

#[unsafe(no_mangle)]
pub extern "C" fn p90() -> f64 {
    unsafe { P90 }
}

#[unsafe(no_mangle)]
pub extern "C" fn gain() -> f64 {
    unsafe { GAIN }
}
