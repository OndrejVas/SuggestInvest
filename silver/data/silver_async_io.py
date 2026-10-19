"""
silver_async_io.py – Asynchronní I/O, atomické ukládání a dynamická TTL cache
=============================================================================
KROKY 23, 24 a 25 v Silver Replication Roadmap v3.0

Poskytuje:
1. Atomický I/O manažer (safe_write_json / safe_write_portfolio) odolný vůči pádům a Windows zámkům
2. SQLite inicializaci s WAL režimem (PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;)
3. Asynchronní HTTP fetcher pipeline (aiohttp) s exponenciálním backoffem a cache fallbackem
4. Dynamický TTL Cache Manager (5 min pro Tier-1 makro dny, 15 min standardně)
"""

from __future__ import annotations
import os
import sys
import time
import json
import asyncio
import sqlite3
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

logger = logging.getLogger("SilverAsyncIO")

# =====================================================================
# KROK 23: ATOMICKÝ I/O & SQLITE WAL MANAŽER
# =====================================================================

def safe_write_json(file_path: str, data: Any, retries: int = 5, retry_delay: float = 0.05) -> bool:
    """
    Atomický zápis JSON souboru.
    Zapisuje do dočasného souboru (.tmp.pid) a atomicky přejmenuje (os.replace).
    Na Windows řeší kolize se čtenáři a file-locky retry smyčkou.
    """
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    temp_path = f"{file_path}.tmp.{os.getpid()}_{int(time.time()*1000)}"
    
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
            
        for attempt in range(retries):
            try:
                os.replace(temp_path, file_path)
                return True
            except (PermissionError, OSError):
                if attempt < retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                else:
                    raise
    except Exception as e:
        logger.error(f"Chyba při atomickém zápisu do {file_path}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False
    return False


def init_sqlite_wal(db_path: str) -> sqlite3.Connection:
    """Otevře SQLite připojení a aktivuje WAL režim a busy_timeout."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA busy_timeout=5000;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    conn.commit()
    return conn


# =====================================================================
# KROK 25: DYNAMICKÝ TTL CACHE MANAGER
# =====================================================================

class DynamicTTLCacheManager:
    """
    Dynamická TTL cache:
    - Běžné dny: TTL 900 sekund (15 minut)
    - Tier-1 makro dny (FOMC, CPI, NFP, Caixin PMI): TTL 300 sekund (5 minut)
    """
    STANDARD_TTL_SEC: int = 900
    TIER1_MACRO_TTL_SEC: int = 300
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cache_dir = cache_dir or os.path.join(self.workspace, "data", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.is_tier1_macro_day: bool = False
        
    def set_macro_day_flag(self, is_macro_day: bool):
        self.is_tier1_macro_day = is_macro_day
        
    def get_effective_ttl(self) -> int:
        return self.TIER1_MACRO_TTL_SEC if self.is_tier1_macro_day else self.STANDARD_TTL_SEC
        
    def get(self, key: str) -> Optional[Any]:
        cache_file = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(cache_file):
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            cached_at = payload.get("_cached_at", 0)
            ttl = payload.get("_ttl", self.get_effective_ttl())
            if (time.time() - cached_at) < ttl:
                return payload.get("data")
        except Exception as e:
            logger.warning(f"Chyba při čtení cache {key}: {e}")
        return None
        
    def set(self, key: str, data: Any, custom_ttl: Optional[int] = None):
        cache_file = os.path.join(self.cache_dir, f"{key}.json")
        ttl = custom_ttl or self.get_effective_ttl()
        payload = {
            "_cached_at": time.time(),
            "_ttl": ttl,
            "_is_macro_day": self.is_tier1_macro_day,
            "data": data
        }
        safe_write_json(cache_file, payload)


# =====================================================================
# KROK 24: ASYNCIO BASE FETCHER PIPELINE
# =====================================================================

class AsyncBaseFetcher:
    """
    Bázová třída pro asynchronní stahování s timeouty, exponenciálním backoffem
    a automatickým fallbackem na poslední platnou cache.
    """
    def __init__(self, cache_manager: Optional[DynamicTTLCacheManager] = None):
        self.cache = cache_manager or DynamicTTLCacheManager()
        
    async def fetch_json_with_retry(
        self, 
        url: str, 
        cache_key: str, 
        headers: Optional[Dict[str, str]] = None,
        retries: int = 3, 
        timeout_sec: float = 10.0
    ) -> Optional[Any]:
        """Stáhne JSON z URL s retry smyčkou a fallbackem na cache."""
        cached_data = self.cache.get(cache_key)
        if cached_data is not None:
            return cached_data
            
        import aiohttp
        backoff = 1.0
        for attempt in range(1, retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=timeout_sec)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.cache.set(cache_key, data)
                            return data
                        else:
                            logger.warning(f"HTTP {response.status} pro {url} (pokus {attempt}/{retries})")
            except Exception as e:
                logger.warning(f"Výpadek fetchování {url} (pokus {attempt}/{retries}): {e}")
                
            if attempt < retries:
                await asyncio.sleep(backoff)
                backoff *= 2.0
                
        # Fallback na jakoukoliv starší cache i po expiraci
        cache_file = os.path.join(self.cache.cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    logger.info(f"Používám nouzovou prošlou cache pro {cache_key}")
                    return json.load(f).get("data")
            except Exception:
                pass
        return None
