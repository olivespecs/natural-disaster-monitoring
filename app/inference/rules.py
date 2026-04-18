"""Per-category scoring rules and thresholds for the heuristic inference engine."""

# Maps EONET category IDs → human-readable titles
CATEGORY_MAP = {
    "wildfires": "Wildfires",
    "severeStorms": "Severe Storms",
    "volcanoes": "Volcanoes",
    "floods": "Floods",
    "seaLakeIce": "Sea & Lake Ice",
    "dustHaze": "Dust & Haze",
    "landslides": "Landslides",
    "drought": "Drought",
    "waterColor": "Water Color",
    "manmade": "Manmade",
    "snow": "Snow",
    "earthquakes": "Earthquakes",
}

CATEGORY_ICONS = {
    "wildfires": "🔥",
    "severeStorms": "🌀",
    "volcanoes": "🌋",
    "floods": "🌊",
    "seaLakeIce": "🧊",
    "dustHaze": "🌫️",
    "landslides": "🗻",
    "drought": "☀️",
    "waterColor": "🔵",
    "manmade": "🏗️",
    "snow": "❄️",
    "earthquakes": "⚠️",
}

# Base severity score (0–100) per category when no magnitude data available
BASE_SEVERITY = {
    "wildfires": 55,
    "severeStorms": 65,
    "volcanoes": 70,
    "floods": 60,
    "seaLakeIce": 35,
    "dustHaze": 40,
    "landslides": 55,
    "drought": 50,
    "waterColor": 25,
    "manmade": 50,
    "snow": 30,
    "earthquakes": 65,
}

# Bonus added to severity based on geometry point count (proxy for event duration/spread).
# More tracked points = event has been active longer or spread further.
GEOMETRY_THRESHOLDS = [
    (100, 25),
    (50, 20),
    (20, 15),
    (10, 10),
    (5, 5),
    (1, 0),
]


def geometry_bonus(point_count: int) -> float:
    """Return severity bonus based on number of tracked geometry points."""
    for threshold, bonus in GEOMETRY_THRESHOLDS:
        if point_count >= threshold:
            return float(bonus)
    return 0.0


def severity_to_risk(score: float) -> str:
    """Convert continuous severity score to discrete risk level."""
    if score >= 80:
        return "CRITICAL"
    elif score >= 60:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    else:
        return "LOW"


def severity_to_trend(score: float, point_count: int) -> str:
    """Estimate event trend from severity and tracking duration."""
    if point_count > 20 and score > 70:
        return "ESCALATING"
    elif point_count > 50:
        return "STABLE"
    elif score < 40:
        return "DECLINING"
    else:
        return "STABLE"


# Heuristic recommendations — used as fallback if Gemini is unavailable
RECOMMENDATIONS = {
    "wildfires": {
        "CRITICAL": [
            "Issue mandatory evacuation orders for all zones in the fire perimeter",
            "Deploy all available aerial firefighting assets to the eastern flank",
            "Pre-position emergency shelters and activate Red Cross response",
        ],
        "HIGH": [
            "Prepare evacuation corridors and notify at-risk communities within 10km",
            "Pre-position firefighting crews on active flanks",
            "Monitor wind direction and humidity for rapid spread indicators",
        ],
        "MEDIUM": [
            "Set evacuation readiness for communities within 5km of fire perimeter",
            "Increase aerial surveillance frequency to every 2 hours",
            "Coordinate with local fire departments for mutual aid agreements",
        ],
        "LOW": [
            "Monitor fire perimeter growth and daily spread rate",
            "Brief local emergency services on current fire status",
            "Ensure all access roads and evacuation routes remain clear",
        ],
    },
    "severeStorms": {
        "CRITICAL": [
            "Issue hurricane/cyclone warnings for all coastal areas within the track",
            "Activate storm surge evacuation plans for low-lying coastal zones",
            "Open inland emergency shelters and pre-position rescue assets",
        ],
        "HIGH": [
            "Warn mariners and coastal communities of dangerous conditions",
            "Activate emergency response teams and pre-position rescue equipment",
            "Issue mandatory small craft advisory and port closures",
        ],
        "MEDIUM": [
            "Issue severe weather advisories for the affected region",
            "Advise public to delay non-essential travel",
            "Monitor for rapid intensification and flash flood potential",
        ],
        "LOW": [
            "Issue weather watches for potentially affected areas",
            "Monitor storm track and intensity forecasts hourly",
            "Advise sailors, fishermen, and aviation of developing conditions",
        ],
    },
    "volcanoes": {
        "CRITICAL": [
            "Evacuate all residents within the exclusion zone immediately",
            "Ground all commercial flights in ash dispersion corridors",
            "Deploy hazmat teams and respiratory protection equipment",
        ],
        "HIGH": [
            "Expand exclusion zone radius and enforce evacuation",
            "Monitor SO2 emissions and ash cloud dispersion trajectory",
            "Pre-position emergency services and medical teams downwind",
        ],
        "MEDIUM": [
            "Issue volcanic activity advisories to local population",
            "Brief aviation authorities on current ash cloud status",
            "Monitor seismic activity for escalation indicators",
        ],
        "LOW": [
            "Continue monitoring seismic sensors and gas emissions",
            "Brief local authorities on current volcanic alert level",
            "Advise public to stay informed and follow official guidance",
        ],
    },
    "floods": {
        "CRITICAL": [
            "Issue flash flood emergency warnings across all affected counties",
            "Deploy swift water rescue teams and helicopters immediately",
            "Open emergency shelters on high ground and activate evacuation",
        ],
        "HIGH": [
            "Pre-position rescue boats, helicopters, and dive teams",
            "Evacuate flood-prone areas and low-lying communities",
            "Notify downstream communities of potential inundation",
        ],
        "MEDIUM": [
            "Issue flood watches for all low-lying and riverside areas",
            "Open sandbag distribution centers at strategic locations",
            "Monitor river gauge readings and precipitation forecasts",
        ],
        "LOW": [
            "Monitor water levels at all upstream gauging stations",
            "Advise residents in floodplains to elevate valuable items",
            "Inspect and clear drainage infrastructure proactively",
        ],
    },
    "default": {
        "CRITICAL": [
            "Activate full emergency response protocols immediately",
            "Issue public safety warnings across all communication channels",
            "Deploy emergency resources and personnel to the affected area",
        ],
        "HIGH": [
            "Heighten emergency readiness and pre-position response teams",
            "Issue official warnings to the affected population",
            "Coordinate with federal and state emergency management agencies",
        ],
        "MEDIUM": [
            "Monitor situation development closely with hourly updates",
            "Brief local emergency services on current event status",
            "Issue precautionary advisories to potentially affected public",
        ],
        "LOW": [
            "Maintain passive monitoring and update event database",
            "Compile event data for situational awareness reports",
            "No immediate protective action required at this time",
        ],
    },
}


def get_recommendations(category_id: str, risk_level: str) -> list:
    """Return heuristic action recommendations for a category and risk level."""
    cat_rules = RECOMMENDATIONS.get(category_id, RECOMMENDATIONS["default"])
    return cat_rules.get(risk_level, RECOMMENDATIONS["default"].get(risk_level, []))
