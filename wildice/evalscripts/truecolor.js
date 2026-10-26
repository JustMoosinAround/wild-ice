//VERSION=3
// Process API evalscript: Sentinel-2 true-color thumbnail (8-bit PNG).
function setup() {
  return {
    input: [{ bands: ["B04", "B03", "B02", "dataMask"] }],
    output: { bands: 4 }
  };
}

function evaluatePixel(s) {
  var g = 2.5;
  return [g * s.B04, g * s.B03, g * s.B02, s.dataMask];
}
