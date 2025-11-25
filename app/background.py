# app/background.py
import asyncio
from app.wallet_monitor import monitor_wallets
from app.executor import execute_trades

def start_background_tasks():
    asyncio.create_task(monitor_wallets())
    asyncio.create_task(execute_trades())
    print("Background tasks started: monitor + executor")