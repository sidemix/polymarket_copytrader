import logging
import asyncio
from sqlalchemy.orm import Session

from app.models import FollowerTrade, Position, SystemEvent, Settings
from app.polymarket_client import PolymarketClient
from app.strategy import MirrorOrder

logger = logging.getLogger(__name__)

class TradeExecutor:
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
        
    async def execute_order(self, order: MirrorOrder) -> bool:
        """Execute a mirror order"""
        try:
            # Check if trading is enabled
            if self.settings.global_trading_status != "RUNNING":
                logger.info("Trading not RUNNING, skipping execution")
                return False
                
            # Execute the order
            if self.settings.dry_run_enabled:
                return await self._execute_dry_run(order)
            else:
                return await self._execute_live_trade(order)
                
        except Exception as e:
            logger.error(f"Error executing order: {e}")
            self._record_system_event("TRADE_ERROR", f"Failed to execute order: {e}", "ERROR")
            return False
            
    async def _execute_dry_run(self, order: MirrorOrder) -> bool:
        """Execute trade in dry-run mode (simulation)"""
        try:
            # Simulate trade execution
            logger.info(f"DRY_RUN: Executing {order.side} {order.size} @ max ${order.max_price}")
            
            # Record simulated trade
            follower_trade = FollowerTrade(
                leader_trade_id=order.leader_trade_id,
                market_id=order.market_id,
                outcome_id=order.outcome_id,
                side=order.side,
                size=order.size,
                price=order.max_price,  # Use max price as execution price in simulation
                status="SIMULATED",
                is_dry_run=True
            )
            
            self.db.add(follower_trade)
            self.db.commit()
            
            # Update position (simulated)
            self._update_position(order, order.max_price, is_dry_run=True)
            
            self._record_system_event(
                "TRADE_EXECUTED", 
                f"DRY_RUN: {order.side} {order.size} shares of {order.market_id}",
                "INFO",
                {"order": order.__dict__, "dry_run": True}
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error in dry run execution: {e}")
            self.db.rollback()
            return False
            
    async def _execute_live_trade(self, order: MirrorOrder) -> bool:
        """Execute live trade on Polymarket"""
        try:
            async with PolymarketClient() as client:
                # Place actual order
                result = await client.place_order(
                    market_id=order.market_id,
                    outcome_id=order.outcome_id,
                    side=order.side,
                    size=order.size,
                    max_price=order.max_price
                )
                
                if result.success:
                    # Record successful trade
                    follower_trade = FollowerTrade(
                        leader_trade_id=order.leader_trade_id,
                        market_id=order.market_id,
                        outcome_id=order.outcome_id,
                        side=order.side,
                        size=order.size,
                        price=order.max_price,  # In reality, you'd get actual execution price
                        status="EXECUTED",
                        is_dry_run=False
                    )
                    
                    self.db.add(follower_trade)
                    self.db.commit()
                    
                    # Update position
                    self._update_position(order, order.max_price, is_dry_run=False)
                    
                    self._record_system_event(
                        "TRADE_EXECUTED", 
                        f"LIVE: {order.side} {order.size} shares of {order.market_id}",
                        "INFO",
                        {"order": order.__dict__, "dry_run": False, "order_id": result.order_id}
                    )
                    
                    logger.info(f"Successfully executed live trade: {result.order_id}")
                    return True
                else:
                    # Record failed trade
                    follower_trade = FollowerTrade(
                        leader_trade_id=order.leader_trade_id,
                        market_id=order.market_id,
                        outcome_id=order.outcome_id,
                        side=order.side,
                        size=order.size,
                        price=order.max_price,
                        status="FAILED",
                        is_dry_run=False
                    )
                    
                    self.db.add(follower_trade)
                    self.db.commit()
                    
                    self._record_system_event(
                        "TRADE_FAILED", 
                        f"Failed to execute {order.side} order: {result.error}",
                        "ERROR",
                        {"order": order.__dict__, "error": result.error}
                    )
                    
                    logger.error(f"Trade execution failed: {result.error}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error in live trade execution: {e}")
            self.db.rollback()
            return False
            
    def _update_position(self, order: MirrorOrder, execution_price: float, is_dry_run: bool):
        """Update position after trade execution"""
        try:
            # Find existing position for this market/outcome
            position = self.db.query(Position).filter(
                Position.market_id == order.market_id,
                Position.outcome_id == order.outcome_id
            ).first()
            
            if position:
                # Update existing position
                if order.side == "YES":
                    # Buying YES shares
                    total_size = position.size + order.size
                    total_cost = (position.size * position.average_price) + (order.size * execution_price)
                    new_avg_price = total_cost / total_size if total_size > 0 else 0
                    
                    position.size = total_size
                    position.average_price = new_avg_price
                else:
                    # Buying NO shares (or selling)
                    # Simplified position management
                    total_size = position.size - order.size
                    if total_size <= 0:
                        # Position closed or reversed
                        self.db.delete(position)
                    else:
                        position.size = total_size
                        # Average price remains for remaining shares
                        
            else:
                # Create new position
                if order.side == "YES" and order.size > 0:
                    position = Position(
                        market_id=order.market_id,
                        outcome_id=order.outcome_id,
                        size=order.size,
                        average_price=execution_price
                    )
                    self.db.add(position)
                    
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error updating position: {e}")
            self.db.rollback()
            
    def _record_system_event(self, event_type: str, message: str, level: str, metadata: dict = None):
        """Record system event for auditing"""
        event = SystemEvent(
            event_type=event_type,
            message=message,
            level=level,
            metadata=metadata or {}
        )
        self.db.add(event)
        self.db.commit()
