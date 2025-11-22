import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.orm import Session

from app.models import LeaderWallet, LeaderTrade, SystemEvent
from app.polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)

class WalletMonitor:
    def __init__(self, db: Session):
        self.db = db
        self.is_running = False
        self.last_check_times: Dict[int, datetime] = {}
        
    async def start_monitoring(self):
        """Start monitoring all active leader wallets"""
        self.is_running = True
        logger.info("Wallet monitor started")
        
        while self.is_running:
            try:
                await self._monitor_cycle()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in wallet monitor cycle: {e}")
                await asyncio.sleep(10)  # Shorter sleep on error
                
    async def stop_monitoring(self):
        """Stop the wallet monitor"""
        self.is_running = False
        logger.info("Wallet monitor stopped")
        
    async def _monitor_cycle(self):
        """Single monitoring cycle"""
        active_wallets = self.db.query(LeaderWallet).filter(
            LeaderWallet.is_active == True
        ).all()
        
        if not active_wallets:
            logger.info("No active wallets to monitor")
            return
            
        async with PolymarketClient() as client:
            for wallet in active_wallets:
                await self._check_wallet_trades(wallet, client)
                
    async def _check_wallet_trades(self, wallet: LeaderWallet, client: PolymarketClient):
        """Check for new trades from a specific wallet"""
        try:
            # Determine since when to check trades
            since = self.last_check_times.get(wallet.id)
            if not since:
                # First check - look back 1 hour
                since = datetime.utcnow() - timedelta(hours=1)
                
            # Fetch new trades
            new_trades = await client.get_trades_for_wallet(wallet.address, since)
            
            if new_trades:
                logger.info(f"Found {len(new_trades)} new trades for wallet {wallet.nickname}")
                
                # Process each new trade
                for trade_dto in new_trades:
                    await self._process_leader_trade(wallet, trade_dto)
                    
                # Update last check time
                self.last_check_times[wallet.id] = datetime.utcnow()
                
            # Update wallet last monitored timestamp
            wallet.last_monitored = datetime.utcnow()
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error checking trades for wallet {wallet.address}: {e}")
            
    async def _process_leader_trade(self, wallet: LeaderWallet, trade_dto):
        """Process a single leader trade"""
        try:
            # Check if trade already exists
            existing_trade = self.db.query(LeaderTrade).filter(
                LeaderTrade.external_trade_id == trade_dto.external_trade_id
            ).first()
            
            if existing_trade:
                return  # Trade already processed
                
            # Create new leader trade record
            leader_trade = LeaderTrade(
                external_trade_id=trade_dto.external_trade_id,
                wallet_id=wallet.id,
                market_id=trade_dto.market_id,
                outcome_id=trade_dto.outcome_id,
                side=trade_dto.side,
                size=trade_dto.size,
                price=trade_dto.price,
                executed_at=trade_dto.executed_at,
                category=trade_dto.category
            )
            
            self.db.add(leader_trade)
            self.db.commit()
            
            # Log system event
            system_event = SystemEvent(
                event_type="LEADER_TRADE",
                message=f"New trade detected from {wallet.nickname}",
                level="INFO",
                metadata={
                    "wallet_id": wallet.id,
                    "market_id": trade_dto.market_id,
                    "side": trade_dto.side,
                    "size": trade_dto.size,
                    "price": trade_dto.price
                }
            )
            self.db.add(system_event)
            self.db.commit()
            
            logger.info(f"Recorded new leader trade: {trade_dto.external_trade_id}")
            
            # TODO: Emit event for strategy processing
            # await self._emit_trade_event(leader_trade)
            
        except Exception as e:
            logger.error(f"Error processing leader trade {trade_dto.external_trade_id}: {e}")
            self.db.rollback()
