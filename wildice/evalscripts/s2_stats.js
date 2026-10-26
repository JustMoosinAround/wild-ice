//VERSION=3
// Statistical API evalscript for Sentinel-2 L2A.
// The Statistical API has one dataMask per request, not per output, so valid-only
// means are built from two outputs over every pixel that has data:
//   "valid"      B0 = 1 where SCL is not no-data/saturated/shadow/cloud/cirrus, else 0
//   "reflectance" B0=B03, B1=B04, B2=B11, each multiplied by that 0/1 flag
// The client computes valid_fraction = mean(valid) and the valid-only band mean
// = mean(reflectance band) / mean(valid).
function setup() {
  return {
    input: [{ bands: ["B03", "B04", "B11", "SCL", "dataMask"] }],
    output: [
      { id: "reflectance", bands: 3, sampleType: "FLOAT32" },
      { id: "valid", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}

// SCL classes: 0 no data, 1 saturated, 3 cloud shadow, 8/9 cloud, 10 cirrus
var BAD = [0, 1, 3, 8, 9, 10];

function evaluatePixel(s) {
  var ok = BAD.indexOf(s.SCL) === -1 ? 1 : 0;
  return {
    reflectance: [s.B03 * ok, s.B04 * ok, s.B11 * ok],
    valid: [ok],
    dataMask: [s.dataMask]
  };
}
