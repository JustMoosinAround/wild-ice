# lakeice.org in the model

What Wild Ice takes from lakeice.org (Bob Dill's site). Numbers in °F are converted to °C.

## In the model

| Page | Rule | Where |
|---|---|---|
| Ice growth, More on Ice Growth | Ashton (1989) thin-ice growth from freezing degree-days | `icemodel.ashton_thickness_cm` |
| Thawed Ice | Ice melts at Ashton/Bilello decay rates: 0.69 cm per thaw degree-day on average, 1.14 in warm wind or in a shallow pond in the sun, 0.37 in low sun | `icemodel.thaw_loss_cm`, `config.yaml: thaw` |
| Thawed Ice, Key Points | Thaw note: 8+ thaw degree-days since the last 3 cold days in a row give "thaw-weakened" (holes, soft spots, thickness overstates strength); 57+ give "rotten ice risk" (candled ice) | `hazards.thaw_note` |
| Small Ponds, End of Season | Shallow ponds (under 2 m mean depth) melt faster, edges first | `thaw_loss_cm`, `thaw_note` |
| New-ice Holes, Breakthrough Thickness | In the first week after freeze-up: thin spots and skinned-over holes | `hazards.new_ice_note` |
| Small Ponds, Feature Summary | Snow deeper than about half the ice thickness floods it into slush | `hazards.slush_note` |
| Pressure Ridges (+ More) | Ridge warnings after a warm-up on lakes about a mile or more across; ridges open in windy thaws | `hazards.ridge_note` |
| Contraction / Stress Cracks | Patchy ice texture caps confidence | `patches.py` |
| Ice Sheet Edges, Polynyas | Patch history, open-water patches | `patches.py` |
| Big Ice, Thickness | Lakes over 3 mi: leads, open areas, moving sheets; want 5 cm more ice | `hazards.big_ice_note` |
| Leads, Upwind of Open Water | Lead risk in strong wind on thin or thawed sheets | `hazards.lead_note` |
| Satellite View | Clear-sky imagery; skip cloudy scenes | `imagery`, `scenes` |
| Weather History | Per-lake weather chart and the last week's notes | map panel |

## Not modelled (no data to drive them)

- Spring, gas, reef, drain, puddle and weed holes; under-ice streams; swamps; dock bubblers. These are local features. Ice Log reports and photos are the way to record them.
- Rivers and river-fed lakes: our HydroLAKES extract has no residence time yet.
- Ice types (S1/S2, snow ice, corn, cobblestone, shell ice), ice colour, slush balls.

## Open proposals: reset rules (owner is reworking these)

- **Thaw size.** A thaw resets the surface only when it's big enough. lakeice.org's numbers: 15 °F thaw degree-days (8 °C) with wind fill a sheet with holes and hide old ridges. Heavy rain for 24 h takes about 1" (2.5 cm), mostly from the warm air. Today a reset needs `reset.thaw_days` warm days in a row or `reset.rain_mm` of rain.
- **Puddles that refreeze.** Shell ice and refrozen puddles give a rough, often white surface, not fresh black ice.
- **Snow insulation.** Even a thin snow cover "dramatically" slows growth, so ice under snow should grow more slowly. It isn't modelled yet because the snow counter doesn't settle or blow off.
- **Spring sun.** After the equinox, rotten ice can come well before the degree-day threshold. This is the deferred spring rule.
