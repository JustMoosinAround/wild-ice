//VERSION=3
// Statistical API evalscript for Sentinel-1 GRD: VV backscatter, linear power.
// Output "vv" B0; the client converts the mean to dB (10*log10).
function setup() {
  return {
    input: [{ bands: ["VV", "dataMask"] }],
    output: [
      { id: "vv", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}

function evaluatePixel(s) {
  return { vv: [s.VV], dataMask: [s.dataMask] };
}
