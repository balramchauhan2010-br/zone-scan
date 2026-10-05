"""
dhan_api_helper.py
Dhan Broker API (DhanHQ) ka powerful wrapper - aapke Zone Scanner ke liye

Docs: https://dhanhq.co/docs/v2/
Install: pip install dhanhq
"""

import os
from typing import List, Dict, Optional
import pandas as pd

try:
    from dhanhq import dhanhq
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False

class DhanHelper:
    def __init__(self, client_id: str = None, access_token: str = None):
        """
        client_id: Dhan Client ID (ex: 1100000001)
        access_token: Dhan Access Token (JWT) - https://dhan.co par generate hota hai
        Streamlit secrets se lena best hai: st.secrets["DHAN_CLIENT_ID"]
        """
        if not DHAN_AVAILABLE:
            raise ImportError("dhanhq library install karo: pip install dhanhq")
        
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        
        if not self.client_id or not self.access_token:
            raise ValueError("DHAN_CLIENT_ID aur DHAN_ACCESS_TOKEN chahiye. Streamlit secrets ya env var me rakho.")
        
        self.dhan = dhanhq(self.client_id, self.access_token)
    
    # ---------- Market Data (aapke scanner ke liye powerful) ----------
    def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """Live LTP - NSE F&O stocks ke liye, Yahoo se tez aur reliable"""
        # Dhan API expects: { "NSE_EQ": [11536, 1333] } - security ID chahiye
        # Yahan simple wrapper - aapko symbol to securityId mapping banana padega
        # Dhan master file: https://images.dhan.co/api-data/api-scrip-master.csv
        try:
            # Example for NSE EQ
            # Convert trading symbol like RELIANCE to security ID via master CSV
            # Yahan demo ke liye direct LTP API call
            resp = self.dhan.ticker_data(securities={"NSE_EQ": symbols})  # symbols yahan security IDs hone chahiye
            return resp
        except Exception as e:
            print(f"Dhan LTP error: {e}")
            return {}

    def get_option_chain(self, underlying_symbol: str = "NIFTY", expiry: str = None):
        """Option chain + OI data - Zone ke saath confluence ke liye powerful"""
        try:
            # underlying: NIFTY, BANKNIFTY etc
            # expiry: YYYY-MM-DD format
            data = self.dhan.option_chain(
                under_security_id=13,  # 13 = NIFTY, 25 = BANKNIFTY (master se lo)
                under_exchange_segment="IDX_I",
                expiry=expiry
            )
            return data
        except Exception as e:
            print(f"Option chain error: {e}")
            return {}

    # ---------- Holdings & Portfolio ----------
    def get_holdings(self) -> pd.DataFrame:
        """Aapke holdings - Zone scanner ke saath P&L dekhne ke liye"""
        try:
            holdings = self.dhan.get_holdings()
            if holdings.get("status") == "success":
                df = pd.DataFrame(holdings.get("data", []))
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"Holdings error: {e}")
            return pd.DataFrame()

    def get_positions(self) -> pd.DataFrame:
        """Open positions - F&O ke liye"""
        try:
            pos = self.dhan.get_positions()
            if pos.get("status") == "success":
                return pd.DataFrame(pos.get("data", []))
            return pd.DataFrame()
        except Exception as e:
            print(f"Positions error: {e}")
            return pd.DataFrame()

    # ---------- Orders - Zone se direct trade ----------
    def place_order_from_zone(self, symbol: str, transaction_type: str, quantity: int, 
                              entry_price: float, sl_price: float, target_price: float,
                              order_type: str = "LIMIT", product_type: str = "INTRADAY"):
        """
        Zone se direct order - Demand zone par BUY, Supply par SELL
        transaction_type: BUY / SELL
        """
        try:
            # Security ID mapping needed - yahan demo
            order = self.dhan.place_order(
                security_id="11536",  # Example - aapko symbol se security_id map karna hai
                exchange_segment="NSE_EQ",
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product_type=product_type,
                price=entry_price,
                # BO (Bracket Order) ke liye SL aur Target
                # Dhan BO API alag hai - yahan simple limit order
            )
            return order
        except Exception as e:
            print(f"Order error: {e}")
            return {"status": "failed", "error": str(e)}

    # ---------- Corporate Actions & Events (Dhan se) ----------
    def get_corporate_actions(self, symbol: str):
        """Dhan API se corporate actions - bonus, split, dividend"""
        # Dhan directly corporate actions nahi deta, NSE API se lena padega
        # Yahan placeholder - neeche news_corporate_events.py dekho
        pass

# ---------- Security ID Mapping Helper ----------
def load_dhan_master():
    """
    Dhan master CSV download karo - isme NSE symbol -> securityId mapping hai
    https://images.dhan.co/api-data/api-scrip-master.csv
    Isko daily cache karo
    """
    import requests, io
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        resp = requests.get(url, timeout=10)
        df = pd.read_csv(io.StringIO(resp.text))
        # Filter NSE_EQ
        nse_eq = df[df["SEM_EXM_EXCH_ID"] == "NSE"]
        # Symbol mapping
        mapping = dict(zip(nse_eq["SEM_TRADING_SYMBOL"], nse_eq["SEM_SMST_SECURITY_ID"]))
        return mapping
    except Exception as e:
        print(f"Master load error: {e}")
        return {}

# Example usage in Streamlit:
"""
import streamlit as st
from dhan_api_helper import DhanHelper

# Streamlit secrets.toml me rakho:
# [dhan]
# client_id = "1100000001"
# access_token = "eyJ0eXAiOiJKV1QiLCJhbGci..."

@st.cache_resource
def get_dhan():
    return DhanHelper(
        client_id=st.secrets["dhan"]["client_id"],
        access_token=st.secrets["dhan"]["access_token"]
    )

dhan = get_dhan()
holdings_df = dhan.get_holdings()
st.dataframe(holdings_df)
"""
