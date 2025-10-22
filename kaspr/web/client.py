"""Kaspr Web API client."""
from typing import Any, Dict
from yarl import URL
from .session import SessionManager

REBALANCE_URL = "/signal/rebalance"
STATUS_URL = "/status/"

class KasprWebClient(SessionManager):
    """Client for the Kaspr Web API."""

    def __init__(self, **kwargs: Any) -> None:
        headers = kwargs.get("headers") or {}
        headers["Content-Type"] = "application/json"
        super().__init__(**kwargs)

    async def rebalance(self, endpoint: URL) -> None:
        """Trigger a rebalance operation on the Kaspr cluster."""
        url = URL(endpoint).with_path(REBALANCE_URL)
        await self.post(url)

    async def get_status(self, endpoint: URL) -> Dict:
        """Get the status of the Kaspr cluster."""
        url = URL(endpoint).with_path(STATUS_URL)
        return await self.get(url)

    async def close(self):
        """Shutdown the client"""
        if self.session:
            await self.session.close()
