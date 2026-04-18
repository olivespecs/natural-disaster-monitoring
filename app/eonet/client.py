import httpx
import logging
from typing import List, Optional

from app.models import EONETEvent
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_open_events(
    days: Optional[int] = None,
    limit: Optional[int] = None,
    category: Optional[str] = None,
    status: str = "open",
) -> List[EONETEvent]:
    """Fetch natural events from NASA EONET API v3."""
    params: dict = {"status": status}
    if days:
        params["days"] = days
    if limit:
        params["limit"] = limit
    if category:
        params["category"] = category

    url = f"{settings.eonet_api_url}/events"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            events: List[EONETEvent] = []
            for evt in data.get("events", []):
                try:
                    events.append(EONETEvent(**evt))
                except Exception as e:
                    logger.warning(f"Failed to parse event {evt.get('id')}: {e}")
            logger.info(f"EONET returned {len(events)} events")
            return events
        except httpx.HTTPStatusError as e:
            logger.error(f"EONET API HTTP error: {e.response.status_code} — {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"EONET API request failed: {e}")
            return []


async def fetch_categories() -> list:
    """Fetch event categories from EONET."""
    url = f"{settings.eonet_api_url}/categories"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json().get("categories", [])
        except Exception as e:
            logger.error(f"Failed to fetch categories: {e}")
            return []
