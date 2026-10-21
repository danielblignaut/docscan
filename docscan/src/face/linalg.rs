//! The small linear algebra the face pipeline needs, without a dependency:
//! a symmetric eigensolver (cyclic Jacobi), rigid and similarity fits
//! (Horn's quaternion method, Umeyama in 2-D), and a planar homography fit
//! (normalised DLT) with its residual.

/// Eigen-decomposition of a symmetric `n × n` matrix (row-major). Returns the
/// eigenvalues in ascending order and the eigenvectors as rows, in the same order.
pub fn sym_eigen(a: &[f64], n: usize) -> (Vec<f64>, Vec<Vec<f64>>) {
    let mut m = a.to_vec();
    let mut v = vec![0f64; n * n];
    for i in 0..n {
        v[i * n + i] = 1.0;
    }
    for _sweep in 0..100 {
        let mut off = 0.0;
        for p in 0..n {
            for q in p + 1..n {
                off += m[p * n + q] * m[p * n + q];
            }
        }
        if off < 1e-22 {
            break;
        }
        for p in 0..n {
            for q in p + 1..n {
                let apq = m[p * n + q];
                if apq.abs() < 1e-300 {
                    continue;
                }
                let app = m[p * n + p];
                let aqq = m[q * n + q];
                let theta = (aqq - app) / (2.0 * apq);
                let t = theta.signum() / (theta.abs() + (theta * theta + 1.0).sqrt());
                let t = if theta == 0.0 { 1.0 } else { t };
                let c = 1.0 / (t * t + 1.0).sqrt();
                let s = t * c;
                for k in 0..n {
                    let mkp = m[k * n + p];
                    let mkq = m[k * n + q];
                    m[k * n + p] = c * mkp - s * mkq;
                    m[k * n + q] = s * mkp + c * mkq;
                }
                for k in 0..n {
                    let mpk = m[p * n + k];
                    let mqk = m[q * n + k];
                    m[p * n + k] = c * mpk - s * mqk;
                    m[q * n + k] = s * mpk + c * mqk;
                }
                for k in 0..n {
                    let vkp = v[k * n + p];
                    let vkq = v[k * n + q];
                    v[k * n + p] = c * vkp - s * vkq;
                    v[k * n + q] = s * vkp + c * vkq;
                }
            }
        }
    }
    let mut idx: Vec<usize> = (0..n).collect();
    idx.sort_by(|&i, &j| m[i * n + i].partial_cmp(&m[j * n + j]).unwrap_or(std::cmp::Ordering::Equal));
    let vals = idx.iter().map(|&i| m[i * n + i]).collect();
    let vecs = idx.iter().map(|&i| (0..n).map(|k| v[k * n + i]).collect()).collect();
    (vals, vecs)
}

/// A similarity transform `dst ≈ s·R·src + t` in 3-D, by Horn's quaternion
/// method. Returns (row-major R, s, t).
pub fn similarity_3d(src: &[[f64; 3]], dst: &[[f64; 3]]) -> ([f64; 9], f64, [f64; 3]) {
    let n = src.len().min(dst.len()).max(1) as f64;
    let mean = |p: &[[f64; 3]]| {
        let mut m = [0f64; 3];
        for q in p {
            for k in 0..3 {
                m[k] += q[k] / n;
            }
        }
        m
    };
    let ms = mean(src);
    let md = mean(dst);
    let mut s = [[0f64; 3]; 3];
    let mut var = 0.0;
    for (a, b) in src.iter().zip(dst) {
        let a = [a[0] - ms[0], a[1] - ms[1], a[2] - ms[2]];
        let b = [b[0] - md[0], b[1] - md[1], b[2] - md[2]];
        var += a[0] * a[0] + a[1] * a[1] + a[2] * a[2];
        for i in 0..3 {
            for j in 0..3 {
                s[i][j] += a[i] * b[j];
            }
        }
    }
    let (sxx, sxy, sxz) = (s[0][0], s[0][1], s[0][2]);
    let (syx, syy, syz) = (s[1][0], s[1][1], s[1][2]);
    let (szx, szy, szz) = (s[2][0], s[2][1], s[2][2]);
    #[rustfmt::skip]
    let nmat = [
        sxx + syy + szz, syz - szy, szx - sxz, sxy - syx,
        syz - szy, sxx - syy - szz, sxy + syx, szx + sxz,
        szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy,
        sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz,
    ];
    let (_, vecs) = sym_eigen(&nmat, 4);
    let q = &vecs[3];
    let (w, x, y, z) = (q[0], q[1], q[2], q[3]);
    #[rustfmt::skip]
    let r = [
        w * w + x * x - y * y - z * z, 2.0 * (x * y - w * z), 2.0 * (x * z + w * y),
        2.0 * (x * y + w * z), w * w - x * x + y * y - z * z, 2.0 * (y * z - w * x),
        2.0 * (x * z - w * y), 2.0 * (y * z + w * x), w * w - x * x - y * y + z * z,
    ];
    let mut num = 0.0;
    for (a, b) in src.iter().zip(dst) {
        let a = [a[0] - ms[0], a[1] - ms[1], a[2] - ms[2]];
        let b = [b[0] - md[0], b[1] - md[1], b[2] - md[2]];
        let ra = [r[0] * a[0] + r[1] * a[1] + r[2] * a[2], r[3] * a[0] + r[4] * a[1] + r[5] * a[2], r[6] * a[0] + r[7] * a[1] + r[8] * a[2]];
        num += ra[0] * b[0] + ra[1] * b[1] + ra[2] * b[2];
    }
    let scale = if var > 0.0 { num / var } else { 1.0 };
    let rm = [r[0] * ms[0] + r[1] * ms[1] + r[2] * ms[2], r[3] * ms[0] + r[4] * ms[1] + r[5] * ms[2], r[6] * ms[0] + r[7] * ms[1] + r[8] * ms[2]];
    let t = [md[0] - scale * rm[0], md[1] - scale * rm[1], md[2] - scale * rm[2]];
    (r, scale, t)
}

/// A 2-D similarity `dst ≈ [a -b; b a]·src + t` (Umeyama, least squares),
/// returned as an affine `[a, -b, tx, b, a, ty]` mapping src to dst.
pub fn similarity_2d(src: &[[f32; 2]], dst: &[[f32; 2]]) -> [f32; 6] {
    let n = src.len().min(dst.len()).max(1) as f64;
    let (mut sx, mut sy, mut dx, mut dy) = (0f64, 0f64, 0f64, 0f64);
    for (a, b) in src.iter().zip(dst) {
        sx += a[0] as f64 / n;
        sy += a[1] as f64 / n;
        dx += b[0] as f64 / n;
        dy += b[1] as f64 / n;
    }
    let (mut num_a, mut num_b, mut den) = (0f64, 0f64, 0f64);
    for (a, b) in src.iter().zip(dst) {
        let (ax, ay) = (a[0] as f64 - sx, a[1] as f64 - sy);
        let (bx, by) = (b[0] as f64 - dx, b[1] as f64 - dy);
        num_a += ax * bx + ay * by;
        num_b += ax * by - ay * bx;
        den += ax * ax + ay * ay;
    }
    let den = if den > 0.0 { den } else { 1.0 };
    let a = num_a / den;
    let b = num_b / den;
    let tx = dx - (a * sx - b * sy);
    let ty = dy - (b * sx + a * sy);
    [a as f32, -b as f32, tx as f32, b as f32, a as f32, ty as f32]
}

/// Hartley normalisation: the transform taking the points to zero mean and
/// mean distance √2, as (scale, mean x, mean y).
fn normaliser(p: &[[f64; 2]]) -> (f64, f64, f64) {
    let n = p.len().max(1) as f64;
    let mx = p.iter().map(|q| q[0]).sum::<f64>() / n;
    let my = p.iter().map(|q| q[1]).sum::<f64>() / n;
    let d = p.iter().map(|q| ((q[0] - mx).powi(2) + (q[1] - my).powi(2)).sqrt()).sum::<f64>() / n;
    let s = if d > 1e-12 { std::f64::consts::SQRT_2 / d } else { 1.0 };
    (s, mx, my)
}

/// The homography `H` (row-major, `dst ~ H·src`) fitted to the
/// correspondences by the normalised DLT, or `None` with fewer than 4.
pub fn fit_homography(src: &[[f64; 2]], dst: &[[f64; 2]]) -> Option<[f64; 9]> {
    let n = src.len().min(dst.len());
    if n < 4 {
        return None;
    }
    let (ss, smx, smy) = normaliser(src);
    let (ds, dmx, dmy) = normaliser(dst);
    let mut ata = [0f64; 81];
    for i in 0..n {
        let x = (src[i][0] - smx) * ss;
        let y = (src[i][1] - smy) * ss;
        let u = (dst[i][0] - dmx) * ds;
        let v = (dst[i][1] - dmy) * ds;
        let r1 = [-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u];
        let r2 = [0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v];
        for r in [r1, r2] {
            for a in 0..9 {
                for b in 0..9 {
                    ata[a * 9 + b] += r[a] * r[b];
                }
            }
        }
    }
    let (_, vecs) = sym_eigen(&ata, 9);
    let h = &vecs[0];
    // Denormalise: H = Td⁻¹ · Hn · Ts.
    let ts = [ss, 0.0, -ss * smx, 0.0, ss, -ss * smy, 0.0, 0.0, 1.0];
    let td_inv = [1.0 / ds, 0.0, dmx, 0.0, 1.0 / ds, dmy, 0.0, 0.0, 1.0];
    let hn = [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], h[8]];
    let m = mul3(&td_inv, &mul3(&hn, &ts));
    let k = if m[8].abs() > 1e-12 { m[8] } else { 1.0 };
    Some(m.map(|x| x / k))
}

pub fn mul3(a: &[f64; 9], b: &[f64; 9]) -> [f64; 9] {
    let mut out = [0f64; 9];
    for i in 0..3 {
        for j in 0..3 {
            out[i * 3 + j] = (0..3).map(|k| a[i * 3 + k] * b[k * 3 + j]).sum();
        }
    }
    out
}

pub fn apply_homography(h: &[f64; 9], p: [f64; 2]) -> [f64; 2] {
    let w = h[6] * p[0] + h[7] * p[1] + h[8];
    let w = if w.abs() < 1e-12 { 1e-12 } else { w };
    [(h[0] * p[0] + h[1] * p[1] + h[2]) / w, (h[3] * p[0] + h[4] * p[1] + h[5]) / w]
}

/// RMS distance between `H·src` and `dst`.
pub fn homography_rms(h: &[f64; 9], src: &[[f64; 2]], dst: &[[f64; 2]]) -> f64 {
    let n = src.len().min(dst.len()).max(1) as f64;
    let sum: f64 = src
        .iter()
        .zip(dst)
        .map(|(a, b)| {
            let p = apply_homography(h, *a);
            (p[0] - b[0]).powi(2) + (p[1] - b[1]).powi(2)
        })
        .sum();
    (sum / n).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eigen_of_diagonalisable() {
        let a = [4.0, 1.0, 1.0, 3.0];
        let (vals, vecs) = sym_eigen(&a, 2);
        let l = 3.5 - (1.25f64).sqrt();
        assert!((vals[0] - l).abs() < 1e-9);
        let v = &vecs[0];
        assert!(((4.0 * v[0] + v[1]) - l * v[0]).abs() < 1e-9);
    }

    #[test]
    fn horn_recovers_rotation() {
        let src = [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0], [1.0, 1.0, 1.0], [-1.0, 0.5, 2.0]];
        let (s, c) = 0.4f64.sin_cos();
        let r = [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c];
        let dst: Vec<[f64; 3]> = src
            .iter()
            .map(|p| {
                let q = [r[0] * p[0] + r[1] * p[1] + r[2] * p[2], r[3] * p[0] + r[4] * p[1] + r[5] * p[2], r[6] * p[0] + r[7] * p[1] + r[8] * p[2]];
                [2.0 * q[0] + 1.0, 2.0 * q[1] - 3.0, 2.0 * q[2] + 0.5]
            })
            .collect();
        let (rr, scale, _) = similarity_3d(&src, &dst);
        assert!((scale - 2.0).abs() < 1e-9);
        for k in 0..9 {
            assert!((rr[k] - r[k]).abs() < 1e-9, "{rr:?}");
        }
    }

    #[test]
    fn homography_exact_for_plane_and_not_for_depth() {
        let h = [1.1, 0.1, 5.0, -0.05, 0.9, 2.0, 0.001, 0.0005, 1.0];
        let src: Vec<[f64; 2]> = (0..20).map(|i| [(i % 5) as f64 * 10.0, (i / 5) as f64 * 12.0]).collect();
        let dst: Vec<[f64; 2]> = src.iter().map(|p| apply_homography(&h, *p)).collect();
        let fit = fit_homography(&src, &dst).unwrap();
        assert!(homography_rms(&fit, &src, &dst) < 1e-6);
    }

    #[test]
    fn similarity_2d_exact() {
        let src = [[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [5.0, 7.0]];
        let dst: Vec<[f32; 2]> = src.iter().map(|p| [2.0 * p[0] - 1.0 * p[1] + 3.0, 1.0 * p[0] + 2.0 * p[1] - 4.0]).collect();
        let m = similarity_2d(&src, &dst);
        assert!((m[0] - 2.0).abs() < 1e-4 && (m[3] - 1.0).abs() < 1e-4 && (m[2] - 3.0).abs() < 1e-3);
    }
}
