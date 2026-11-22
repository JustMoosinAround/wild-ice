// Glossary page content: what the app's colours, badges, warnings and graph mean.
// Plain data so a test can check every chip and badge has an entry.

export const GLOSSARY = [
  {
    title: "Lake colours",
    items: [
      { term: "Likely black ice", text: "Thick enough to skate (2+ in, estimated), little or no snow since the surface last cleared, and a clear satellite image since freeze-up shows bare ice." },
      { term: "Skateable, rough", text: "Someone skated it recently but graded the ice D or worse." },
      { term: "Freezing", text: "Ice is forming but the estimate is still under 2 in." },
      { term: "Unknown", text: "Probably thick enough, but no clear satellite image since freeze-up, or the evidence disagrees." },
      { term: "Snow covered", text: "Snow on the ice: from a station, the weather model, a report or a white satellite image." },
      { term: "Open water", text: "No ice yet, or a report or warm satellite reading says it's open." },
    ],
  },
  {
    title: "Badges",
    items: [
      { term: "Just in", text: "The lake came in within the last 3 days and nobody has reported skating it since: a chance at first tracks." },
      { term: "Last grade", text: "The most recent ice grade from a skater, A+ (best) to F- (skateable but awful)." },
      { term: "New to you", text: "You haven't skated this lake: no report or uploaded track of yours on it." },
      { term: "Approach", text: "Distance from the nearest road, in a straight line, for lakes reached by trail. The real route is longer." },
    ],
  },
  {
    title: "Warnings",
    items: [
      { term: "New ice", text: "Froze in the last week. New sheets often have thin spots and skinned-over holes that stay open for days." },
      { term: "Thaw-weakened", text: "Enough above-freezing weather since the last few cold days to leave holes and soft spots. The ice is weaker than its thickness suggests until it's had about 3 cold days." },
      { term: "Rotten ice risk", text: "A long thaw: ice this thawed (candled) can fail at almost any thickness." },
      { term: "Slush", text: "Snow deeper than about half the ice thickness can push the ice under water, flooding it into slush under the snow." },
      { term: "Big ice", text: "Lakes over about 3 miles: wind and currents make leads and open areas, and sheets can move. Want about 2 in more ice than on a small pond." },
      { term: "Lead risk", text: "Strong wind on a big, thin or thaw-weakened sheet can split it, opening water between you and shore in minutes." },
      { term: "Pressure ridges", text: "A warm-up after a cold spell makes big sheets expand and buckle, usually off points and across bay mouths. Ridges can be open water in a windy thaw." },
    ],
  },
  {
    title: "The graph",
    items: [
      { term: "Air and water", text: "Daily mean air temperature with the low–high band, and the model's estimate of the lake's water temperature." },
      { term: "Ice and snowfall", text: "The model's ice thickness estimate and daily new snow (measured at a nearby station when there is one)." },
      { term: "Markers", text: "Dots along the top of the ice panel: clear satellite images (cracks, dark, snow, grey, open water), skater reports, and freeze-ups. Tap a day to read them." },
    ],
  },
  {
    title: "Terms",
    items: [
      { term: "Crack network", text: "Thin white lines across the ice (cracks and pressure ridges) on a clear satellite image. Open water and snow cover can't show them, so they mean bare ice, even on turquoise glacial lakes." },
      { term: "Freeze-up", text: "The day the model's ice first reaches about 2 cm. Satellite images from before it show open water, so they don't count as ice." },
      { term: "Thaw degree-day", text: "One degree (C) above freezing for one day. Ice melts roughly 0.4–1.1 cm per thaw degree-day, faster in warm wind or sun." },
      { term: "Estimates", text: "Ice thickness, water temperature and labels come from weather, satellites and skaters' reports. They can be wrong or out of date: check the ice yourself." },
    ],
  },
];
