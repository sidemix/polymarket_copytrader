import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .db import get_db
from .models import LeaderWallet, LeaderTrade, SystemEvent
from .polymarket_client import client

logger = logging.getLogger("copytrader")

async def monitor_wallets():
    while True:
        if settings.BOT_STATUS != "RUNNING":
            await asyncio.sleep(5)
            continue

        db: Session = next(get_db())
        try:
            active_wallets = db.query(LeaderWallet).filter(LeaderWallet.is_active).all()
            for wallet in active_wallets:
                last_trade = db.query(LeaderTrade).filter(
                    LeaderTrade.leader_wallet_id == wallet.id
                ).order_by(LeaderTrade.executed_at.desc()).first()

                since = int((last_trade.executed_at.timestamp() if last_trade else 0) * 1000)
                new_trades = await client.get_trades_for_wallet(wallet.address, since)

                for t in new_trades:
                    # Idempotency
                    exists = db.query(LeaderTrade).filter(LeaderTrade.external_trade_id == t.trade_id).first()
                    if not exists:
                        db_trade = LeaderTrade(
                            leader_wallet_id=wallet.id,
                            external_trade_id=t.trade_id,
                            market_id=t.market_id,
                            outcome_id=t.outcome_id,
                            side=t.side,
                            size=t.size,
                            price=t.price,
                            executed_at=datetime.fromtimestamp(t.timestamp / 1000),
                            raw_data=t.__dict__
                        )
                        db.add(db_trade)
                        db.commit()
                        # Emit to executor
                        asyncio.create_task(process_new_leader_trade(db_trade.id))

            db.close()
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        await asyncio.sleep(settings.WALLET_POLL_INTERVAL)