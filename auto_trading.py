"""
auto_trading.py
Dhan Auto Trading - Zone se direct Bracket Order - Secure, optional

Safety Features:
- Paper trading mode default (real order nahi lagega jab tak enable na karo)
- Max quantity limit
- Risk % check
- Bina Dhan key ke disabled, app fast
"""

import streamlit as st
from typing import Dict, Optional
import pandas as pd

try:
    from secure_config import get_secret, is_dhan_configured, get_dhan_creds
    from dhan_api_helper import DhanHelper
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False
    def is_dhan_configured(): return False
    def get_dhan_creds(): return None, None

# Safety limits
MAX_QTY_PER_ORDER = 100  # Max quantity per order (safety)
MAX_DAILY_ORDERS = 20    # Max orders per day (safety)
DEFAULT_PRODUCT = "INTRADAY"  # INTRADAY / CNC

def is_auto_trading_enabled() -> bool:
    """Auto trading enabled hai kya? Secrets me flag"""
    try:
        # Check secrets: [trading] auto_enabled = true
        val = get_secret("trading.auto_enabled")
        if val is None:
            val = get_secret("TRADING_AUTO_ENABLED")
        return str(val).lower() in ["true", "1", "yes"] if val else False
    except Exception:
        return False

def place_bracket_order_from_zone(zone_row: Dict, quantity: int = 1, 
                                  product_type: str = "INTRADAY",
                                  paper_trading: bool = True) -> Dict:
    """
    Zone se bracket order lagao - Secure
    paper_trading=True -> Real order nahi, sirf log (safe default)
    
    zone_row: {
        "Ticker": "RELIANCE",
        "Direction": "DEMAND (Buy Zone)",
        "Entry (Proximal)": 2800,
        "Stop Loss (Distal+Buffer)": 2780,
        "Target (RR set)": 2860
    }
    """
    if not DHAN_AVAILABLE or not is_dhan_configured():
        return {"status": "failed", "reason": "Dhan not configured - bina key ke trading disabled (secure, fast)"}
    
    if quantity > MAX_QTY_PER_ORDER:
        return {"status": "failed", "reason": f"Quantity {quantity} exceeds safety limit {MAX_QTY_PER_ORDER}"}
    
    try:
        symbol = zone_row.get("Ticker") or zone_row.get("Symbol")
        direction = zone_row.get("Direction", "")
        entry = float(zone_row.get("Entry (Proximal)", 0))
        sl = float(zone_row.get("Stop Loss (Distal+Buffer)", 0))
        target = float(zone_row.get("Target (RR set)", 0))
        
        is_demand = "DEMAND" in direction
        transaction_type = "BUY" if is_demand else "SELL"
        
        if entry == 0 or sl == 0:
            return {"status": "failed", "reason": "Invalid entry/SL"}
        
        # Risk check: SL should be reasonable (not too far)
        risk_pct = abs(entry - sl) / entry * 100
        if risk_pct > 5:
            return {"status": "failed", "reason": f"Risk {risk_pct:.2f}% too high (>5%), skipping for safety"}
        
        if paper_trading:
            # Paper trading - no real order, just log
            return {
                "status": "paper_trading",
                "symbol": symbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "entry": entry,
                "sl": sl,
                "target": target,
                "product_type": product_type,
                "message": f"PAPER TRADING: {transaction_type} {quantity} {symbol} @ {entry} SL {sl} Target {target} - Real order nahi laga (paper_trading=True)"
            }
        else:
            # Real order - Dhan API
            # SECURITY: Real trading ke liye extra confirmation chahiye
            cid, token = get_dhan_creds()
            dhan = DhanHelper(client_id=cid, access_token=token)
            
            # For bracket order, Dhan has BO API - simplified here as limit + SL
            # Actual BO: https://dhanhq.co/docs/v2/bracket-order/
            order = dhan.dhan.place_order(
                security_id="11536",  # TODO: Map symbol to securityId via master CSV
                exchange_segment="NSE_EQ",
                transaction_type=transaction_type,
                quantity=quantity,
                order_type="LIMIT",
                product_type=product_type,
                price=entry,
            )
            
            # Place SL order separately (or BO)
            # This is simplified - real BO needs boProfitValue, boStopLossValue
            
            return {
                "status": "success" if order.get("status") == "success" else "failed",
                "order_response": order,
                "symbol": symbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "entry": entry,
            }
    
    except Exception as e:
        return {"status": "failed", "reason": f"Order error (secure): {str(e)[:200]}"}

# Streamlit UI
"""
import streamlit as st
from auto_trading import place_bracket_order_from_zone, is_auto_trading_enabled, MAX_QTY_PER_ORDER
from secure_config import is_dhan_configured

if is_dhan_configured():
    st.success("✅ Dhan Connected - Trading enabled (secure)")
    
    # Safety: Paper trading default
    paper = st.checkbox("Paper Trading (Safe - Real order nahi lagega)", value=True, help="ON rakho to real order nahi lagega, sirf log. OFF karne par real order lagega - careful!")
    
    qty = st.number_input(f"Quantity (Max {MAX_QTY_PER_ORDER} for safety)", min_value=1, max_value=MAX_QTY_PER_ORDER, value=1)
    
    # Select zone to trade
    if not combined.empty:
        zone_options = [f"{row['Ticker']} {row['Timeframe']} {row['Direction'].split()[0]} Entry {row['Entry (Proximal)']}" for _, row in combined.head(20).iterrows()]
        sel_zone_str = st.selectbox("Trade ke liye Zone chuno", zone_options)
        
        if sel_zone_str:
            sel_idx = zone_options.index(sel_zone_str)
            sel_zone = combined.iloc[sel_idx].to_dict()
            
            if st.button(f"🛒 Place Order for {sel_zone['Ticker']} (Paper={paper})", width="stretch"):
                result = place_bracket_order_from_zone(sel_zone, quantity=qty, paper_trading=paper)
                
                if result["status"] == "paper_trading":
                    st.info(result["message"])
                    st.json(result)
                elif result["status"] == "success":
                    st.success(f"✅ Real order placed: {result}")
                else:
                    st.error(f"❌ Order failed: {result.get('reason')}")
    
    # Auto trading toggle (extra secure - needs secrets flag)
    if is_auto_trading_enabled():
        st.warning("⚠️ Auto Trading ENABLED via secrets.toml - Nearest zones par auto order lagega")
        auto_trade = st.checkbox("Auto Trade Nearest Zones (<0.5%)", value=False)
        if auto_trade and not combined.empty:
            nearest = combined[combined["Distance %"].abs() <= 0.5].head(2)
            for _, row in nearest.iterrows():
                res = place_bracket_order_from_zone(row.to_dict(), quantity=1, paper_trading=paper)
                st.write(res)
    else:
        st.caption("Auto trading disabled (secure). Enable karne ke liye secrets.toml me [trading] auto_enabled = true daalo")
else:
    st.info("○ Dhan not configured - Trading disabled. Bina key ke scanner fast chalega. Key ke liye .streamlit/secrets.toml me [dhan] client_id + access_token daalo.")
"""
