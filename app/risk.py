import logging
from typing import Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Position, FollowerTrade, Settings, SystemEvent
from app.strategy import MirrorOrder

logger = logging.getLogger(__name__)

class RiskManager:
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
        
    def can_open_trade(self, order: MirrorOrder) -> Tuple[bool, str]:
        """Check if a trade can be opened based on risk rules"""
        try:
            # Check max risk per trade
            trade_usd = order.size * order.max_price
            if trade_usd > self.settings.max_trade_amount:
                return False, f"Trade size ${trade_usd:.2f} exceeds max ${self.settings.max_trade_amount}"
                
            # Check max open markets
            open_markets = self._get_open_markets_count()
            if open_markets >= self.settings.max_open_markets:
                return False, f"Already have {open_markets} open markets (max: {self.settings.max_open_markets})"
                
            # Check max exposure per market
            market_exposure = self._get_market_exposure(order.market_id)
            if market_exposure >= self.settings.max_exposure_per_market:
                return False, f"Market exposure ${market_exposure:.2f} exceeds limit ${self.settings.max_exposure_per_market}"
                
            # Check daily loss limit (simplified)
            daily_pnl = self._get_daily_pnl()
            if daily_pnl <= -self.settings.daily_loss_limit:
                return False, f"Daily PnL ${daily_pnl:.2f} below loss limit -${self.settings.daily_loss_limit}"
                
            # Check max trades per hour
            recent_trades = self._get_recent_trades_count()
            if recent_trades >= self.settings.max_trades_per_hour:
                return False, f"Already made {recent_trades} trades this hour (max: {self.settings.max_trades_per_hour})"
                
            return True, "OK"
            
        except Exception as e:
            logger.error(f"Error in risk check: {e}")
            return False, f"Risk check error: {e}"
            
    def on_trade_executed(self, trade):
        """Callback when a trade is executed"""
        # Update risk metrics, check for circuit breakers, etc.
        pass
        
    def _get_open_markets_count(self) -> int:
        """Count number of distinct markets with open positions"""
        return self.db.query(Position.market_id).distinct().count()
        
    def _get_market_exposure(self, market_id: str) -> float:
        """Calculate total exposure for a specific market"""
        positions = self.db.query(Position).filter(
            Position.market_id == market_id
        ).all()
        
        exposure = sum(pos.size * pos.average_price for pos in positions)
        return abs(exposure)  # Return absolute value
        
    def _get_daily_pnl(self) -> float:
        """Calculate today's PnL (simplified)"""
        # This is a simplified implementation
        # In production, you'd want more sophisticated PnL calculation
        today_trades = self.db.query(FollowerTrade).filter(
            func.date(FollowerTrade.executed_at) == func.current_date()
        ).all()
        
        return sum(trade.pnl or 0 for trade in today_trades)
        
    def _get_recent_trades_count(self) -> int:
        """Count trades in the last hour"""
        from datetime import datetime, timedelta
        
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        return self.db.query(FollowerTrade).filter(
            FollowerTrade.executed_at >= one_hour_ago
        ).count()
