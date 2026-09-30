"""Optional open-data sources layered on top of OpenStreetMap.

Each module fetches one dataset, caches it under data_cache/, and is applied to a
region only where it has coverage (US, Texas, Austin...). All are keyless and open.

- usgs_3dep.py: bare-earth lidar elevation (US)
- austin.py: crashes, city bike-comfort ratings, counters, work zones (City of Austin)
- txdot_aadt.py: measured motor-traffic volumes (Texas)
- canopy.py: 1 m tree canopy height (Meta/WRI, global)
- noise.py: road/aviation noise (US DOT)
- overture.py: cafés and other stops (Overture Maps)
- apply.py: joins all of the above onto a region graph
"""
