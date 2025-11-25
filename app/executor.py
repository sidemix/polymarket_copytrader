# app/executor.py
import asyncio
from app.models import LeaderTrade, FollowerTrade
from app.db import get_db

async def execute_trades():
    while True:
        db = next(get_db())
        pending = db.query(LeaderTrade).filter(LeaderTrade.processed == False).limit(10).all()
        for trade in pending:
            # DRY RUN MODE
            if getattr(settings, "DRY_RUN_ENABLED", True):
                print(f"[DRY RUN] Would copy {trade.amount} on {trade.market_id}")
            else:
                print(f"[LIVE] EXECUTING COPY TRADE: {trade.amount} on {trade.market_id}")
            
            # Mark as processed
            trade.processed = True
            db.add(FollowerTrade(
                leader_trade_id=trade.id,
                amount=trade.amount * 0.2,  # 20% sizing
                dry_run=True
            ))
        db.commit()
        await asyncio.sleep(5)