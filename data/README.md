# Data

## hydrolakes_southcentral.csv

Mean lake depths for Southcentral Alaska (the `region.bbox` in `config.yaml`), cut
from HydroLAKES v1.0 (points version): Hylak_id, Lake_name, Lake_area (km²),
Depth_avg (m) and the outlet ("pour point") longitude/latitude. Depths in this
region are modeled estimates (Vol_src 3), not surveys.

Source: Messager, M.L., Lehner, B., Grill, G., Nedeva, I., Schmitt, O. (2016).
Estimating the volume and age of water stored in global lakes using a
geo-statistical approach. *Nature Communications* 7: 13603.
https://www.hydrosheds.org/products/hydrolakes — licensed CC BY 4.0.

Modification: rows outside the bounding box and all other columns were dropped.
`wildice/depths.py` matches each outlet point to a catalog lake (within 300 m of
the outline, area within a factor of 3) and the ice model turns mean depth into how
long the water takes to cool (`icemodel.water_lag_days`).
