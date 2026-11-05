//VERSION=3
// Statistical API evalscript for Landsat 8-9 OLI-TIRS L1 (top of atmosphere).
// Same valid-only trick as s2_stats.js:
//   "valid"   B0 = 1 where the QA band flags no fill, dilated cloud, cirrus, cloud
//             or cloud shadow, else 0
//   "surface" B0=B03 (green), B1=B04 (red), B2=B06 (SWIR 1.6 um),
//             B3=B10 (thermal brightness temperature, kelvin), each x that flag
function setup() {
  return {
    input: [{ bands: ["B03", "B04", "B06", "B10", "BQA", "dataMask"] }],
    output: [
      { id: "surface", bands: 4, sampleType: "FLOAT32" },
      { id: "valid", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}

// QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow
var BAD_BITS = 1 | 2 | 4 | 8 | 16;

function evaluatePixel(s) {
  var ok = (s.BQA & BAD_BITS) === 0 ? 1 : 0;
  return {
    surface: [s.B03 * ok, s.B04 * ok, s.B06 * ok, s.B10 * ok],
    valid: [ok],
    dataMask: [s.dataMask]
  };
}
