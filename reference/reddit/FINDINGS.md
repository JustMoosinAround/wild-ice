# r/nordicskating vs. satellite and model (walled off)

Second run, 2026-11-22, 18 reports (saved search page + Arctic Shift archive of posts
and comments): https://github.com/JustMoosinAround/wild-ice/actions/runs/45049839992
Nothing here changes the daily labels.

Model replay: 2 of 17 matched (Portage 2024-01-18, Skilak 2025-02-15), 15 misses,
0 false alerts, 1 Copernicus timeout (Byers 2025-11-14; satellite: dark Nov 9 and 12).

## Patterns in the misses

1. **Low-sun window throws away real dark ice (5 misses).** Between Nov 25 and
   Jan 15 a dark image doesn't count as a reset (low sun can make snow look dark).
   But skaters were on these lakes on dark-image days:
   - Eklutna: Landsat dark Jan 2 + 3 2025 (brightness 0.10); skated Jan 1 and Jan 4;
     model: snow covered / unknown ("dark on Jan 3 Landsat image" in its own reason).
   - Jean Lake: Landsat dark Dec 13, 20, 21 2025 (0.095); skated Dec 14; model unknown.
   - Grant Lake: Landsat dark Dec 13, 14, 20-22 2025 (0.10); skated Dec 16 and 19.
   Landsat reads ~0.10 on these days while Sentinel-2 reads "grey" (0.17-0.26) on
   the same lakes, so the two sensors disagree in low sun.
2. **The snow counter never settles.** Jerome Lake shows "324 cm snow since Oct 23";
   Arc 31 cm, Eklutna 29 cm, Grant 20 cm, all on days people skated. Wind, settling
   and sublimation aren't modelled, so any lake without a recent confirmed reset
   reads as buried.
3. **"Grey" on skated lakes.** Lower Trail (0.26-0.28), Arc (0.23-0.36), Westchester
   (0.23-0.26), Jerome (Landsat 0.18): skated or reported skateable while grey.
   Could be thin snow, hoar frost, or rough/white ice that still skates.
4. **Undated posts are noise.** Kashwitna (white all week) and Kenai Lake ("mostly
   snow-covered") were labelled snow covered, which is probably right on the post date.

## Proposals (reset rules: owner decides)

- In low sun, let a very dark **Landsat** look (brightness <= ~0.12) count as dark ice,
  or require two dark looks in a row.
- Decay the snow counter (settle/blow off) instead of summing all season.
- Look at the grey band: maybe "grey after a dark look, no new snow" = likely ice.
