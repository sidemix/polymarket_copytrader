import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime

from app.models import LeaderTrade, Settings, SystemEvent
from app.polymarket_client import PolymarketClient, MarketDTO

logger = logging.getLogger(__name__)

class MirrorOrder:
    def __init__(self, leader_trade_id: int, market_id: str, outcome_id: str, 
                 side: str, size: float, max_price: float):
        self.leader_trade_id = leader_trade_id
        self.market_id = market_id
        self.outcome_id = outcome_id
        self.side = side
        self.size = size
        self.max_price = max_price

class CopyStrategy:
    def __init__(self, db: Session):
        self.db = db
        self.settings = self._load_settings()
        
    def _load_settings(self) -> Settings:
        """Load current settings"""
        settings = self.db.query(Settings).first()
        if not settings:
            settings = Settings()
            self.db.add(settings)
            self.db.commit()
        return settings
        
    async def process_leader_trade(self, leader_trade: LeaderTrade) -> Optional[MirrorOrder]:
        """Process a leader trade and generate mirror order if applicable"""
        try:
            # Check global trading status
            if self.settings.global_trading_status != "RUNNING":
                logger.info("Trading is not RUNNING, skipping trade")
                return None
                
            # Filter by market volume
            market_info = await self._get_market_info(leader_trade.market_id)
            if not market_info or market_info.volume < self.settings.min_market_volume:
                logger.info(f"Market {leader_trade.market_id} volume too low")
                return None
                
            # Filter by days to resolution
            if market_info.resolution_time:
                resolution_dt = datetime.fromisoformat(market_info.resolution_time.replace("Z", "+00:00"))
                days_to_resolution = (resolution_dt - datetime.utcnow()).days
                if days_to_resolution > self.settings.max_days_to_resolution:
                    logger.info(f"Market resolution too far out: {days_to_resolution} days")
                    return None
                    
            # Filter by allowed categories (future enhancement)
            # if leader_trade.category not in self.allowed_categories:
            #     return None
                
            # Calculate trade size
            trade_size = self._calculate_trade_size(leader_trade)
            if trade_size <= 0:
                logger.info("Calculated trade size is zero or negative")
                return None
                
            # Apply slippage limit
            max_price = self._apply_slippage(leader_trade.price)
            
            # Create mirror order
            mirror_order = MirrorOrder(
                leader_trade_id=leader_trade.id,
                market_id=leader_trade.market_id,
                outcome_id=leader_trade.outcome_id,
                side=leader_trade.side,
                size=trade_size,
                max_price=max_price
            )
            
            logger.info(f"Generated mirror order: {mirror_order.side} {mirror_order.size} @ max ${mirror_order.max_price}")
            return mirror_order
            
        except Exception as e:
            logger.error(f"Error processing leader trade {leader_trade.id}: {e}")
            return None
            
    async def _get_market_info(self, market_id: str) -> Optional[MarketDTO]:
        """Get market information with caching"""
        async with PolymarketClient() as client:
            return await client.get_market_info(market_id)
            
    def _calculate_trade_size(self, leader_trade: LeaderTrade) -> float:
        """Calculate follower trade size based on leader trade and settings"""
        # Simple fixed percentage of leader trade size
        percentage = self.settings.copy_trade_percentage / 100.0
        base_size = leader_trade.size * percentage
        
        # Apply maximum trade amount limit
        max_amount = self.settings.max_trade_amount
        price = leader_trade.price
        
        # Calculate USD value and cap it
        usd_value = base_size * price
        if usd_value > max_amount:
            usd_value = max_amount
            
        # Convert back to shares
        capped_size = usd_value / price if price > 0 else 0
        
        return round(capped_size, 4)
        
    def _apply_slippage(self, price: float) -> float:
        """Apply slippage to price (increase for buys, decrease for sells)"""
        slippage_pct = 0.02  # 2% slippage
        return price * (1 + slippage_pct)
