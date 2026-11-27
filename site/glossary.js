// Glossary page content: what the app's colours, badges, warnings and graph mean.
// Plain data so a test can check every chip and badge has an entry.

export const GLOSSARY = [
  {
    title: "Lake colours",
    items: [
      { term: "Likely skateable", text: "2+ in of ice, little snow, and something confirms bare ice." },
      { term: "Skateable, rough", text: "Skated recently, graded D or worse." },
      { term: "Freezing", text: "Ice forming, under 2 in." },
      { term: "Unknown", text: "Probably thick enough, but nothing confirms it." },
      { term: "Snow covered", text: "Snow on the ice." },
      { term: "Open water", text: "No ice yet." },
    ],
  },
  {
    title: "Badges",
    items: [
      { term: "Just in", text: "Came in within 3 days. First tracks may be open." },
      { term: "Grade", text: "Latest skater grade, A+ to F-." },
      { term: "New to you", text: "You haven't skated it." },
      { term: "Approach", text: "Straight-line distance from the road." },
    ],
  },
  {
    title: "Warnings",
    items: [
      { term: "New ice", text: "Froze this week. Expect thin spots." },
      { term: "Thaw-weakened", text: "Recent warm days. Weaker than it looks." },
      { term: "Rotten ice risk", text: "Long thaw. Can fail at any thickness." },
      { term: "Slush", text: "Heavy snow may have flooded the ice." },
      { term: "Big ice", text: "Over 3 miles: leads and open areas." },
      { term: "Lead risk", text: "Strong wind can open water fast." },
      { term: "Pressure ridges", text: "Warm-up after cold: ridges, maybe open." },
    ],
  },
  {
    title: "The graph",
    items: [
      { term: "Air and water", text: "Daily air temperature and estimated water temperature." },
      { term: "Ice and snowfall", text: "Estimated ice thickness and new snow." },
      { term: "Markers", text: "Satellite images, reports and freeze-ups. Tap a day." },
    ],
  },
  {
    title: "Terms",
    items: [
      { term: "Dark image", text: "Black ice or open water. Can't tell alone." },
      { term: "Crack network", text: "White lines on the ice. Means bare ice." },
      { term: "Freeze-up", text: "The day ice first formed." },
      { term: "Estimates", text: "Ice data can be wrong. Check it yourself." },
    ],
  },
];
