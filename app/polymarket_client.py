# app/polymarket_client.py
import httpx
from typing import List, Dict, Optional
from datetime import datetime

class PolymarketClient:
    def __init__(self):
        self.base_url = "https://clob.polymarket.com"
        self.graphql_url = "https://gamma-api.polymarket.com/query"
        self.client = httpx.AsyncClient(timeout=20.0)

    async def get_recent_trades(self, wallet: str, limit: int = 50) -> List[Dict]:
        query = """
        query GetTrades($wallet: String!) {
          trades(where: {user: $wallet}, orderBy: timestamp, orderDirection: desc, first: $limit) {
            id
            market { id title }
            outcome
            amount
            price
            timestamp
          }
        }
        """
        variables = {"wallet": wallet.lower(), "limit": limit}
        resp = await self.client.post(self.graphql_url, json={"query": query, "variables": variables})
        resp.raise_for_status()
        return resp.json()["data"]["trades"]