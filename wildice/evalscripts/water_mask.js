//VERSION=3
// Process API evalscript: open water (NDWI > 0.1) as 255, everything else 0.
// Used on a July-August mosaic to trace each lake's shoreline.
function setup() {
  return { input: [{ bands: ["B03", "B08", "dataMask"] }], output: { bands: 1, sampleType: "UINT8" } };
}

function evaluatePixel(s) {
  if (s.dataMask === 0) return [0];
  var ndwi = (s.B03 - s.B08) / (s.B03 + s.B08 + 1e-6);
  return [ndwi > 0.1 ? 255 : 0];
}
