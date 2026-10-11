//! Gauss-Krüger (transverse Mercator) forward projection on GRS80, using the
//! Krüger n-series to 6th order (the formulation the GSI uses for the Japan Plane
//! Rectangular Coordinate System). Pure Rust, no PROJ.
//!
//! Returns (easting, northing) in metres. Note that the Japanese convention (and
//! the EPSG:6677 axis order) names northing "X" and easting "Y"; we always return
//! (easting, northing) to keep GIS order explicit.

const A_GRS80: f64 = 6_378_137.0;
const F_GRS80: f64 = 1.0 / 298.257_222_101;

/// A plane-rectangular zone: origin latitude/longitude in degrees, scale factor.
#[derive(Clone, Copy, Debug)]
pub struct Zone {
    pub lat0_deg: f64,
    pub lon0_deg: f64,
    pub k0: f64,
}

/// JGD2011 / Japan Plane Rectangular CS IX (EPSG:6677): 36°N, 139°50'E, k0 = 0.9999.
pub const ZONE_IX: Zone = Zone {
    lat0_deg: 36.0,
    lon0_deg: 139.0 + 50.0 / 60.0,
    k0: 0.9999,
};

struct Series {
    a_bar: f64,
    alpha: [f64; 6],
    two_sqrt_n_over: f64,
}

fn series() -> Series {
    let f = F_GRS80;
    let n = f / (2.0 - f);
    let n2 = n * n;
    let n3 = n2 * n;
    let n4 = n3 * n;
    let n5 = n4 * n;
    let n6 = n5 * n;
    let a_bar = A_GRS80 / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0 + n6 / 256.0);
    let alpha = [
        n / 2.0 - 2.0 / 3.0 * n2 + 5.0 / 16.0 * n3 + 41.0 / 180.0 * n4 - 127.0 / 288.0 * n5
            + 7891.0 / 37800.0 * n6,
        13.0 / 48.0 * n2 - 3.0 / 5.0 * n3 + 557.0 / 1440.0 * n4 + 281.0 / 630.0 * n5
            - 1_983_433.0 / 1_935_360.0 * n6,
        61.0 / 240.0 * n3 - 103.0 / 140.0 * n4
            + 15061.0 / 26880.0 * n5
            + 167_603.0 / 181_440.0 * n6,
        49561.0 / 161_280.0 * n4 - 179.0 / 168.0 * n5 + 6_601_661.0 / 7_257_600.0 * n6,
        34729.0 / 80640.0 * n5 - 3_418_889.0 / 1_995_840.0 * n6,
        212_378_941.0 / 319_334_400.0 * n6,
    ];
    Series {
        a_bar,
        alpha,
        two_sqrt_n_over: 2.0 * n.sqrt() / (1.0 + n),
    }
}

/// Unscaled (xi, eta) series sum for a latitude/longitude offset.
fn xi_eta(s: &Series, lat: f64, dlon: f64) -> (f64, f64) {
    let sin_lat = lat.sin();
    let t = (sin_lat.atanh() - s.two_sqrt_n_over * (s.two_sqrt_n_over * sin_lat).atanh()).sinh();
    let xi_p = (t / dlon.cos()).atan();
    let eta_p = (dlon.sin() / (1.0 + t * t).sqrt()).atanh();
    let mut xi = xi_p;
    let mut eta = eta_p;
    for (j, a) in s.alpha.iter().enumerate() {
        let k = 2.0 * (j as f64 + 1.0);
        xi += a * (k * xi_p).sin() * (k * eta_p).cosh();
        eta += a * (k * xi_p).cos() * (k * eta_p).sinh();
    }
    (xi, eta)
}

/// Forward projection: geodetic (lat, lon) in degrees -> (easting, northing) metres.
pub fn forward(zone: Zone, lat_deg: f64, lon_deg: f64) -> (f64, f64) {
    let s = series();
    let lat = lat_deg.to_radians();
    let dlon = (lon_deg - zone.lon0_deg).to_radians();
    let (xi, eta) = xi_eta(&s, lat, dlon);
    let (xi0, _) = xi_eta(&s, zone.lat0_deg.to_radians(), 0.0);
    let northing = zone.k0 * s.a_bar * (xi - xi0);
    let easting = zone.k0 * s.a_bar * eta;
    (easting, northing)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn origin_maps_to_zero() {
        let (e, n) = forward(ZONE_IX, 36.0, 139.0 + 50.0 / 60.0);
        assert!(e.abs() < 1e-6 && n.abs() < 1e-6);
    }
}
