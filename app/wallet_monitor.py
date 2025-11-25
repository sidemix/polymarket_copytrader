# app/wallet_monitor.py
import asyncio
from datetime import datetime, timedelta
from app.polymarket_client import PolymarketClient
from app.db import get_db
from app.models import LeaderWallet, LeaderTrade
from sqlalchemy.orm import Session

client = PolymarketClient()

async def monitor_wallets():
    while True:
        db: Session = next(get_db())
        wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active == True).all()
        
        for wallet in wallets:
            try:
                trades = await client.get_recent_trades(wallet.address)
                for trade in trades:
                    if not db.query(LeaderTrade).filter(LeaderTrade.external_id == trade["id"]).first():
                        new_trade = LeaderTrade(
                            wallet_id=wallet.id,
                            external_id=trade["id"],
                            market_id=trade["market"]["id"],
                            outcome=trade["outcome"],
                            amount=float(trade["amount"]),
                            price=float(trade["price"]),
                            timestamp=datetime.fromtimestamp(int(trade["timestamp"])/1000)
                        )
                        db.add(new_trade)
                        from app.events import emit_trade
                        await emit_trade(new_trade, wallet)
                db.commit()
            except Exception as e:
                print(f"Error monitoring {wallet.address}: {e}")
        
        await asyncio.sleep(15)  # Check every 15 seconds