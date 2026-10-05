"""
secure_config.py
API Keys ko bahut secure tarike se handle karna - bina key ke bhi fast kaam kare, key ho to auto-enable

Security Features:
- st.secrets se pehle try, phir env var, phir None (app crash nahi)
- Keys ko kabhi log/print/dataframe me mat dikhao
- Cache me key store nahi, sirf client object
- GitHub par secrets.toml push nahi hota (.gitignore)
"""

import os
import streamlit as st
from typing import Optional, Any

def get_secret(key_path: str, default: Any = None) -> Optional[str]:
    """
    Secure tarike se secret nikalo
    key_path examples:
      - "dhan.client_id" -> st.secrets["dhan"]["client_id"] ya env DHAN_CLIENT_ID
      - "gemini.api_key" -> st.secrets["gemini"]["api_key"] ya env GEMINI_API_KEY
      - "newsapi.api_key" -> optional
    """
    # 1. Try st.secrets (Streamlit Cloud ka sabse secure)
    try:
        parts = key_path.split(".")
        val = st.secrets
        for p in parts:
            val = val[p]
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    
    # 2. Try env var (local dev ke liye)
    # dhan.client_id -> DHAN_CLIENT_ID, gemini.api_key -> GEMINI_API_KEY
    env_key = key_path.replace(".", "_").upper()
    try:
        val = os.getenv(env_key)
        if val and str(val).strip():
            return str(val).strip()
        # Also try without underscore: DHAN_CLIENT_ID, GEMINI_API_KEY
        # Already handled, but try alternative
        alt_key = env_key.replace("_", "")
        val2 = os.getenv(alt_key)
        if val2 and str(val2).strip():
            return str(val2).strip()
    except Exception:
        pass
    
    # 3. Fallback default (None = feature disabled, app fast chalega)
    return default

def is_dhan_configured() -> bool:
    """Dhan API configured hai kya? Bina key ke bhi app chalega"""
    cid = get_secret("dhan.client_id")
    token = get_secret("dhan.access_token") or get_secret("dhan.access_token")
    # Also check alternative naming
    if not cid:
        cid = get_secret("DHAN_CLIENT_ID")
    if not token:
        token = get_secret("DHAN_ACCESS_TOKEN") or get_secret("dhan.access_token")
    return bool(cid and token)

def is_gemini_configured() -> bool:
    """Gemini API configured hai kya?"""
    key = get_secret("gemini.api_key") or get_secret("GEMINI_API_KEY")
    return bool(key)

def is_newsapi_configured() -> bool:
    return bool(get_secret("newsapi.api_key") or get_secret("NEWSAPI_API_KEY"))

def get_dhan_creds():
    """Secure Dhan creds return - kabhi print mat karo"""
    client_id = get_secret("dhan.client_id") or get_secret("DHAN_CLIENT_ID")
    access_token = get_secret("dhan.access_token") or get_secret("DHAN_ACCESS_TOKEN")
    return client_id, access_token

def get_gemini_key():
    return get_secret("gemini.api_key") or get_secret("GEMINI_API_KEY")

def mask_key(key: str) -> str:
    """Key ko mask karke dikhana - security ke liye"""
    if not key or len(key) < 8:
        return "****"
    return key[:4] + "****" + key[-4:]

# Example secrets.toml (ye file .streamlit/secrets.toml me rakho, GitHub par push mat karo)
"""
# .streamlit/secrets.toml - EXAMPLE, isko copy karke apna bharo
# Ye file gitignore me honi chahiye

[dhan]
client_id = "1100000001"  # Dhan Client ID
access_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."  # JWT token, 24h valid hota hai, daily refresh karna pad sakta hai

[gemini]
api_key = "AIzaSyD..."  # https://aistudio.google.com/app/apikey se lo

[newsapi]
# Optional - global news ke liye
api_key = "your_newsapi_key"

# FII DII, NSE data ke liye koi key nahi chahiye - free hai
"""
