"""Geographic utility functions for location-based impact estimation."""

from typing import List, Any, Tuple, Optional


# Rough population density zones by absolute latitude band
LAT_BAND_ZONES = {
    (0, 15): "tropical_dense",       # Sub-Saharan Africa, SE Asia, Amazon
    (15, 35): "subtropical_high",    # India, China, Middle East, Mexico, N Africa
    (35, 55): "temperate_high",      # Europe, Eastern US, China, Japan
    (55, 70): "northern_moderate",   # Canada, Russia, Scandinavia, Alaska
    (70, 90): "polar_low",           # Arctic, Antarctic regions
}


def get_population_zone(lat: float) -> str:
    """Classify a latitude into a rough population density zone."""
    abs_lat = abs(lat)
    for (lo, hi), zone in LAT_BAND_ZONES.items():
        if lo <= abs_lat < hi:
            return zone
    return "polar_low"


def estimate_impact_description(lat: float, lon: float, area_proxy: float, risk_level: str) -> str:
    """Generate a human-readable impact estimate based on location and risk."""
    zone = get_population_zone(lat)
    high_density = zone in ("subtropical_high", "temperate_high", "tropical_dense")

    impact_map = {
        "CRITICAL": (
            "National/Regional (>1M potentially affected)" if high_density
            else "Regional (100k–500k potentially affected)"
        ),
        "HIGH": (
            "Regional (50k–500k potentially affected)" if high_density
            else "Local (5k–50k potentially affected)"
        ),
        "MEDIUM": "Local (1k–50k potentially affected)",
        "LOW": "Localized (<1k potentially affected)",
    }
    return impact_map.get(risk_level, "Impact unknown")


def extract_centroid(geometries: List[Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract the centroid (avg lat, avg lon) from a list of EONET geometry dicts.
    EONET coordinates are [longitude, latitude].
    """
    lats: List[float] = []
    lons: List[float] = []

    for geom in geometries:
        if isinstance(geom, dict):
            coords = geom.get("coordinates")
        else:
            coords = getattr(geom, "coordinates", None)

        if coords is None:
            continue
        try:
            # Point geometry: [lon, lat]
            if isinstance(coords, (list, tuple)) and len(coords) == 2:
                if isinstance(coords[0], (int, float)):
                    lons.append(float(coords[0]))
                    lats.append(float(coords[1]))
        except Exception:
            continue

    if lats and lons:
        return round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)
    return None, None


def compute_area_proxy(geometries: List[Any]) -> float:
    """
    Compute a rough geographic spread proxy from geometry point spread.
    Returns lat-range × lon-range (in degrees²).
    """
    lats: List[float] = []
    lons: List[float] = []

    for geom in geometries:
        if isinstance(geom, dict):
            coords = geom.get("coordinates")
        else:
            coords = getattr(geom, "coordinates", None)

        if coords is None:
            continue
        try:
            if isinstance(coords, (list, tuple)) and len(coords) == 2:
                if isinstance(coords[0], (int, float)):
                    lons.append(float(coords[0]))
                    lats.append(float(coords[1]))
        except Exception:
            continue

    if len(lats) < 2:
        return 0.0
    return round((max(lats) - min(lats)) * (max(lons) - min(lons)), 4)
