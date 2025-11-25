# app/polymarket_client.py — WORKING VERSION
import httpx

class PolymarketClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Origin": "https://polymarket.com",
                "Referer": "https://polymarket.com/"
            }
        )

    async def get_recent_trades(self, wallet: str, limit: int = 50):
        query = """
        query GetUserTrades($user: String!, $first: Int!) {
          trades(where: {user: $user}, orderBy: timestamp, orderDirection: desc, first: $first) {
            id
            market { id title }
            outcome
            amount
            price
            timestamp
          }
        }
        """
        variables = {"user": wallet.lower(), "first": limit}
        resp = await self.client.post(
            "https://gamma-api.polymarket.com/query",
            json={"query": query, "variables": variables}
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("trades", [])