"""
Overlay Visualizer Server for Multi-Agent Supply Chain (P1, H1, H2, R1, R2).
Serves real-time WebSocket events and visual graph dashboard.
Does NOT modify any existing project code.
"""

import asyncio
import datetime
import glob
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OVERLAY_SERVER")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Supply Chain Network Overlay Visualizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections
active_connections: List[WebSocket] = []

# In-memory history of recent events (last 100)
event_history: List[Dict[str, Any]] = []
recent_signatures: Set[str] = set()

# Node endpoints configuration
NODES = {
    "P1": {"name": "Producent P1", "port": 8001, "type": "PRODUCER", "url": "http://127.0.0.1:8001"},
    "H1": {"name": "Hurtownia H1", "port": 8004, "type": "WHOLESALE", "url": "http://127.0.0.1:8004"},
    "H2": {"name": "Hurtownia H2", "port": 8005, "type": "WHOLESALE", "url": "http://127.0.0.1:8005"},
    "R1": {"name": "Restauracja R1", "port": 8002, "type": "RESTAURANT", "url": "http://127.0.0.1:8002"},
    "R2": {"name": "Restauracja R2", "port": 8022, "mcp_port": 8003, "type": "RESTAURANT", "url": "http://127.0.0.1:8022"},
}

DB_PATHS = {
    "P1": BASE_DIR / "producer" / "producer.db",
    "H1": BASE_DIR / "warehouse-1" / "data" / "warehouse1.db",
    "H2": BASE_DIR / "warehouse-2" / "warehouse2.db",
    "R1": BASE_DIR / "restaurant-1" / "data" / "restaurant.db",
    "R2": BASE_DIR / "restaurant-2" / "data" / "restauracja_2.db",
}

# DB tracking for highest seen IDs
last_seen_db_ids = {
    "P1": 0,
    "H1": 0,
    "H2": 0,
    "R1": 0,
    "R2": 0,
}

# File offsets for log tailing
log_file_offsets: Dict[str, int] = {}


# In-memory deduplication cache: signature -> timestamp
recent_event_timestamps: Dict[str, float] = {}


async def broadcast_event(event: Dict[str, Any], bypass_dedup: bool = False):
    """Broadcasts a supply-chain packet event to all connected WebSocket clients."""
    src = event.get('source') or ''
    tgt = event.get('target') or ''
    mtype = event.get('message_type') or ''
    item_info = event.get('item') or {}
    item_name = str(item_info.get('name') or '').lower().strip()
    qty = str(item_info.get('quantity') or '')
    sig = f"{src}->{tgt}:{mtype}:{item_name}:{qty}"
    deliv_sig = f"{src}->{tgt}:DELIVERY"

    now_ts = time.time()
    # Deduplicate packets arriving within time window unless bypassed
    if not bypass_dedup:
        # Never allow duplicate DELIVERY between same source and target within 3.5 seconds
        if mtype == "DELIVERY":
            if deliv_sig in recent_event_timestamps and (now_ts - recent_event_timestamps[deliv_sig]) < 3.5:
                logger.info(f"[DEDUP IGNORED] Skipping duplicate DELIVERY packet: {deliv_sig}")
                return
        if sig in recent_event_timestamps and (now_ts - recent_event_timestamps[sig]) < 2.5:
            logger.info(f"[DEDUP IGNORED] Skipping duplicate event packet: {sig}")
            return

    # Always register timestamps (even when bypass_dedup=True) to prevent subsequent poller duplicates
    recent_event_timestamps[sig] = now_ts
    if mtype == "DELIVERY":
        recent_event_timestamps[deliv_sig] = now_ts
    
    # Store event in history
    event["id"] = f"evt-{int(now_ts * 1000)}"
    if "timestamp" not in event:
        event["timestamp"] = datetime.datetime.now().strftime("%H:%M:%S")
        
    event_history.append(event)
    if len(event_history) > 100:
        event_history.pop(0)

    logger.info(f"[GRAPH EVENT] {src} -> {tgt}: {mtype} ({event.get('summary')})")

    dead_connections = []
    payload = json.dumps({"type": "packet", "data": event})
    for ws in list(active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead_connections.append(ws)

    for dead in dead_connections:
        if dead in active_connections:
            active_connections.remove(dead)


is_scenario_running: bool = False
last_scenario_end_time: float = 0.0


async def broadcast_scenario_start(scenario_id: int, title: str, description: str):
    """Broadcasts the beginning of a trading demonstration scenario."""
    global is_scenario_running
    is_scenario_running = True
    payload = json.dumps({
        "type": "scenario_start",
        "data": {
            "scenario_id": scenario_id,
            "title": title,
            "description": description,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
        }
    })
    for ws in list(active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            pass


async def broadcast_scenario_end(scenario_id: int, title: str, summary: str):
    """Broadcasts the successful completion of a trading demonstration scenario."""
    global is_scenario_running, last_scenario_end_time
    is_scenario_running = False
    last_scenario_end_time = time.time()
    payload = json.dumps({
        "type": "scenario_end",
        "data": {
            "scenario_id": scenario_id,
            "title": title,
            "summary": summary,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
        }
    })
    for ws in list(active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            pass


async def broadcast_node_state(node_data: Dict[str, Any]):
    """Broadcasts updated node state (balances, stock, health) to clients."""
    payload = json.dumps({"type": "node_state", "data": node_data})
    dead = []
    for ws in list(active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for d in dead:
        if d in active_connections:
            active_connections.remove(d)


# =============================================================================
# Database Poller & Data Fetcher
# =============================================================================

def get_node_details():
    """Extracts live balances, stock items, and health status for all 5 nodes."""
    status_summary = {}

    # P1
    try:
        p1_db = DB_PATHS["P1"]
        if p1_db.exists():
            with sqlite3.connect(p1_db, timeout=1.0) as conn:
                products = conn.execute("SELECT product_code, name, stock_quantity, unit_price FROM products").fetchall()
                tx_count = conn.execute("SELECT count(*) FROM sales_transactions").fetchone()[0]
                status_summary["P1"] = {
                    "online": True,
                    "balance": None, # Producer is pure supplier
                    "stock_count": len(products),
                    "stock": [{"name": p[1], "quantity": p[2], "price": p[3]} for p in products],
                    "transactions_count": tx_count,
                }
    except Exception as e:
        status_summary["P1"] = {"online": False, "error": str(e), "stock": []}

    # H1
    try:
        h1_db = DB_PATHS["H1"]
        if h1_db.exists():
            with sqlite3.connect(h1_db, timeout=1.0) as conn:
                bal = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
                products = conn.execute("SELECT name, quantity, price FROM products").fetchall()
                tx_count = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
                status_summary["H1"] = {
                    "online": True,
                    "balance": float(bal[0]) if bal else 0.0,
                    "stock_count": len(products),
                    "stock": [{"name": p[0], "quantity": p[1], "price": p[2]} for p in products],
                    "transactions_count": tx_count,
                }
    except Exception as e:
        status_summary["H1"] = {"online": False, "error": str(e), "stock": []}

    # H2
    try:
        h2_db = DB_PATHS["H2"]
        if h2_db.exists():
            with sqlite3.connect(h2_db, timeout=1.0) as conn:
                bal = conn.execute("SELECT ballance FROM wallet_warehouse2 ORDER BY id DESC LIMIT 1").fetchone()
                products = conn.execute("SELECT name, quantity, price FROM warehouse2").fetchall()
                tx_count = conn.execute("SELECT count(*) FROM wallet_warehouse2").fetchone()[0]
                status_summary["H2"] = {
                    "online": True,
                    "balance": float(bal[0]) if bal else 0.0,
                    "stock_count": len(products),
                    "stock": [{"name": p[0], "quantity": p[1], "price": p[2]} for p in products],
                    "transactions_count": tx_count,
                }
    except Exception as e:
        status_summary["H2"] = {"online": False, "error": str(e), "stock": []}

    # R1
    try:
        r1_db = DB_PATHS["R1"]
        if r1_db.exists():
            with sqlite3.connect(r1_db, timeout=1.0) as conn:
                bal = conn.execute("SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'").fetchone()
                items = conn.execute("SELECT name, quantity, safety_threshold, unit FROM inventory").fetchall()
                tx_count = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
                status_summary["R1"] = {
                    "online": True,
                    "balance": float(bal[0]) if bal else 0.0,
                    "stock_count": len(items),
                    "stock": [{"name": i[0], "quantity": i[1], "threshold": i[2], "unit": i[3]} for i in items],
                    "transactions_count": tx_count,
                }
    except Exception as e:
        status_summary["R1"] = {"online": False, "error": str(e), "stock": []}

    # R2
    try:
        r2_db = DB_PATHS["R2"]
        if r2_db.exists():
            with sqlite3.connect(r2_db, timeout=1.0) as conn:
                bal = conn.execute("SELECT balans FROM konto WHERE id = 1").fetchone()
                items = conn.execute("SELECT nazwa_produktu, ilosc, jednostka, prog_bezpieczenstwa FROM magazyn").fetchall()
                tx_count = conn.execute("SELECT count(*) FROM historia_transakcji").fetchone()[0]
                status_summary["R2"] = {
                    "online": True,
                    "balance": float(bal[0]) if bal else 0.0,
                    "stock_count": len(items),
                    "stock": [{"name": i[0], "quantity": i[1], "unit": i[2], "threshold": i[3]} for i in items],
                    "transactions_count": tx_count,
                }
    except Exception as e:
        status_summary["R2"] = {"online": False, "error": str(e), "stock": []}

    return status_summary


async def poll_databases_loop():
    """Periodically queries databases to find newly completed transactions."""
    # Initialize maximum IDs
    for node, p in DB_PATHS.items():
        if not p.exists():
            continue
        try:
            with sqlite3.connect(p, timeout=1.0) as conn:
                if node == "P1":
                    r = conn.execute("SELECT max(id) FROM sales_transactions").fetchone()
                    last_seen_db_ids["P1"] = r[0] or 0
                elif node == "H1":
                    r = conn.execute("SELECT max(id) FROM transactions").fetchone()
                    last_seen_db_ids["H1"] = r[0] or 0
                elif node == "H2":
                    r = conn.execute("SELECT max(id) FROM wallet_warehouse2").fetchone()
                    last_seen_db_ids["H2"] = r[0] or 0
                elif node == "R1":
                    r = conn.execute("SELECT max(id) FROM transactions").fetchone()
                    last_seen_db_ids["R1"] = r[0] or 0
                elif node == "R2":
                    r = conn.execute("SELECT max(id) FROM historia_transakcji").fetchone()
                    last_seen_db_ids["R2"] = r[0] or 0
        except Exception:
            pass

    logger.info(f"Initialized database baseline IDs: {last_seen_db_ids}")

    while True:
        try:
            await asyncio.sleep(1.2)
            scenario_active = is_scenario_running or ((time.time() - last_scenario_end_time) < 3.0)

            # Check P1 sales
            p1_db = DB_PATHS["P1"]
            if p1_db.exists():
                with sqlite3.connect(p1_db, timeout=1.0) as conn:
                    rows = conn.execute(
                        "SELECT id, product_code, quantity, unit_price, total_cost, buyer_id FROM sales_transactions WHERE id > ? ORDER BY id ASC",
                        (last_seen_db_ids["P1"],),
                    ).fetchall()
                    for r in rows:
                        last_seen_db_ids["P1"] = max(last_seen_db_ids["P1"], r[0])
                        buyer = r[5] or "H1"
                        if not scenario_active:
                            await broadcast_event({
                                "source": "P1",
                                "target": buyer,
                                "message_type": "DELIVERY",
                                "summary": f"Dostawa P1 -> {buyer}: {r[2]}x {r[1]} ({r[4]} PLN)",
                                "item": {"name": r[1], "quantity": r[2], "price": r[3]},
                                "total_cost": r[4],
                                "raw_json": {
                                    "sender_id": "P1",
                                    "receiver_id": buyer,
                                    "message_type": "DELIVERY",
                                    "item": {"name": r[1], "quantity": r[2], "price": r[3]},
                                    "total_cost": r[4],
                                },
                            })

            # Check R2 deliveries
            r2_db = DB_PATHS["R2"]
            if r2_db.exists():
                with sqlite3.connect(r2_db, timeout=1.0) as conn:
                    rows = conn.execute(
                        "SELECT id, typ_akcji, od_kogo, produkt, ilosc, koszt, data FROM historia_transakcji WHERE id > ? ORDER BY id ASC",
                        (last_seen_db_ids["R2"],),
                    ).fetchall()
                    for r in rows:
                        last_seen_db_ids["R2"] = max(last_seen_db_ids["R2"], r[0])
                        seller = r[2] or "H1"
                        if "DOSTAWA" in (r[1] or "") and not scenario_active:
                            await broadcast_event({
                                "source": seller,
                                "target": "R2",
                                "message_type": "DELIVERY",
                                "summary": f"Dostawa {seller} -> R2: {r[4]}x {r[3]} ({r[5]} PLN)",
                                "item": {"name": r[3], "quantity": r[4], "price": round(r[5] / (r[4] or 1), 2)},
                                "total_cost": r[5],
                                "raw_json": {
                                    "sender_id": seller,
                                    "receiver_id": "R2",
                                    "message_type": "DELIVERY",
                                    "item": {"name": r[3], "quantity": r[4]},
                                    "total_cost": r[5],
                                },
                            })

            # Check R1 purchases
            r1_db = DB_PATHS["R1"]
            if r1_db.exists():
                with sqlite3.connect(r1_db, timeout=1.0) as conn:
                    rows = conn.execute(
                        "SELECT id, account_id, transaction_type, amount, currency, description FROM transactions WHERE id > ? ORDER BY id ASC",
                        (last_seen_db_ids["R1"],),
                    ).fetchall()
                    for r in rows:
                        last_seen_db_ids["R1"] = max(last_seen_db_ids["R1"], r[0])
                        desc = r[5] or ""
                        seller = "H1"
                        if "H2" in desc or "Hurtownia 2" in desc:
                            seller = "H2"
                        if not scenario_active:
                            m_desc = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|x)?\s*([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)", desc)
                            item_name = m_desc.group(2) if m_desc else "towar"
                            item_qty = float(m_desc.group(1)) if m_desc else 1.0
                            await broadcast_event({
                                "source": seller,
                                "target": "R1",
                                "message_type": "DELIVERY",
                                "step": 5,
                                "step_title": "Dostawa i Rozliczenie (Zewnętrzny Zakup)",
                                "summary": f"Zakup R1: {desc} ({r[3]} PLN)",
                                "narrative": f"Wykryto nową transakcję w bazie danych Restauracji R1: {desc} ({r[3]} PLN). Magazyn i portfel zostały zaktualizowane.",
                                "rule": "Automatyczna synchronizacja: Nakładka na bieżąco monitoruje bazy SQLite i natychmiast wizualizuje zakupy uruchomione z terminala.",
                                "item": {"name": item_name, "quantity": item_qty},
                                "total_cost": r[3],
                                "raw_json": {
                                    "source": seller,
                                    "target": "R1",
                                    "message_type": "DELIVERY",
                                    "amount": r[3],
                                    "currency": r[4],
                                    "description": desc,
                                    "item": {"name": item_name, "quantity": item_qty},
                                }
                            })

            # Check H1 sales & purchases
            h1_db = DB_PATHS["H1"]
            if h1_db.exists():
                with sqlite3.connect(h1_db, timeout=1.0) as conn:
                    rows = conn.execute(
                        "SELECT id, partner, type, item_name, quantity, total_cost FROM transactions WHERE id > ? ORDER BY id ASC",
                        (last_seen_db_ids["H1"],),
                    ).fetchall()
                    for r in rows:
                        last_seen_db_ids["H1"] = max(last_seen_db_ids["H1"], r[0])
                        partner = r[1] or ""
                        tx_type = r[2] or ""
                        if tx_type == "PURCHASE":
                            src, tgt = "P1", "H1"
                        else:
                            src = "H1"
                            tgt = "R1" if ("R1" in partner or "1" in partner) else "R2"
                        if not scenario_active:
                            await broadcast_event({
                                "source": src,
                                "target": tgt,
                                "message_type": "DELIVERY",
                                "step": 5,
                                "step_title": "Dostawa i Rozliczenie (Zewnętrzny Zakup)",
                                "summary": f"Transakcja H1 ({tx_type}): {r[4]}x {r[3]} ({r[5]} PLN)",
                                "narrative": f"Wykryto nową transakcję w bazie Hurtowni H1: {tx_type} {r[4]}x {r[3]} ({r[5]} PLN) z {partner}.",
                                "rule": "Automatyczna synchronizacja: Aktualizacja w bazie SQLite Hurtowni H1.",
                                "item": {"name": r[3], "quantity": r[4]},
                                "total_cost": r[5],
                                "raw_json": {
                                    "source": src,
                                    "target": tgt,
                                    "message_type": "DELIVERY",
                                    "item": {"name": r[3], "quantity": r[4]},
                                    "total_cost": r[5],
                                    "type": tx_type
                                }
                            })

            # Send updated node state
            state = get_node_details()
            await broadcast_node_state(state)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"DB poller loop error: {e}")


# =============================================================================
# Log Tailer for Real-Time MCP / CNP Protocol Packets
# =============================================================================

def find_task_logs() -> List[Path]:
    """Dynamically finds all task log files in antigravity and local workspace."""
    user_home = Path(os.path.expanduser("~"))
    pattern = str(user_home / ".gemini" / "antigravity" / "brain" / "*" / ".system_generated" / "tasks" / "*.log")
    files = [Path(p) for p in glob.glob(pattern)]
    # Also include any local .log in the workspace
    for p in BASE_DIR.glob("**/*.log"):
        if "overlay" not in str(p) and p.is_file():
            files.append(p)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


async def tail_logs_loop():
    """Tails all task logs to intercept CNP messages as they are sent."""
    # Pre-populate offsets to current ends of files so we don't replay old history
    logs = find_task_logs()
    for log_path in logs:
        try:
            log_file_offsets[str(log_path)] = log_path.stat().st_size
        except Exception:
            pass

    logger.info(f"Initialized log tailing on {len(logs)} task log files.")

    # CNP Regex patterns
    r1_avail_re = re.compile(r"\[CNP:AVAILABILITY_CHECK\] Sprawdzanie dostępności dla '([^']+)' \(ilość=([\d\.]+)\) w hurtowniach:\s*(\[[^\]]+\])")
    r1_quotes_re = re.compile(r"\[CNP:MCP_QUOTES\] Towar '([^']+)' \(qty=([\d\.]+)\) jest dostępny w:\s*(\[[^\]]+\])")
    r1_eval_re = re.compile(r"\[CNP:EVALUATION\].*?Wholesaler '([^']+)': total_cost=([\d\.]+) PLN \(unit_price=([\d\.]+) PLN\)", re.DOTALL)
    r1_accept_re = re.compile(r"\[CNP:ACCEPT_OFFER\] Składanie zamówienia w hurtowni '([^']+)' \(koszt:\s*([\d\.]+)\s*PLN\)")
    r1_rejected_re = re.compile(r"\[CNP:ORDER_REJECTED\] Hurtownia '([^']+)' odrzuciła zamówienie \(powód: ([^)]+)\)")
    r1_confirmed_re = re.compile(r"\[CNP:ORDER_CONFIRMED\] Hurtownia '([^']+)' potwierdziła przyjęcie zamówienia")
    r1_deliv_re = re.compile(r"\[CNP:DELIVERY\] Przyjęto dostawę ([\d\.]+)x '([^']+)' od hurtowni '([^']+)'")
    
    r2_mcp_deliv_re = re.compile(r"\[SERWER MCP\]:\s*Przyjęto dostawę ([\d\.]+)x\s*([A-Za-z\s]+)\s*od\s*([A-Z0-9]+)")
    r2_avail_re = re.compile(r"STATUS DOSTĘPNOŚCI:\s*([\d\.]+)x\s*([A-Za-z\s]+)")
    r2_accept_re = re.compile(r"Zakup ([\d\.]+) kg ([A-Za-z\s]+) w hurtowni ([A-Z0-9]+) został pomyślnie sfinalizowany")
    
    h1_deliv_re = re.compile(r"Otrzymano dostawę od P1:\s*([\d\.]+)\s*kg\s*([A-Za-z\s]+)\s*\(koszt:\s*([\d\.]+)\s*PLN\)")
    h2_sold_re = re.compile(r"H2 sold ([\d\.]+) of ([A-Za-z\s]+)")

    while True:
        try:
            await asyncio.sleep(0.5)
            active_logs = find_task_logs()

            for log_file in active_logs:
                fpath = str(log_file)
                if not log_file.exists():
                    continue

                curr_size = log_file.stat().st_size
                prev_offset = log_file_offsets.get(fpath, curr_size)

                if curr_size <= prev_offset:
                    log_file_offsets[fpath] = curr_size
                    continue

                # Read new chunk
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(prev_offset)
                        new_content = f.read()
                        log_file_offsets[fpath] = f.tell()
                except Exception:
                    continue

                # Parse lines
                for line in new_content.splitlines():
                    # 1. R1 Availability check
                    m = r1_avail_re.search(line)
                    if m:
                        item, qty, whs_str = m.group(1), float(m.group(2)), m.group(3)
                        whs = [w.strip(" '\"") for w in whs_str.strip("[]").split(",") if w.strip()]
                        for w in whs:
                            await broadcast_event({
                                "source": "R1",
                                "target": w,
                                "message_type": "AVAILABILITY_REQUEST",
                                "summary": f"Sprawdzenie dostępności: {qty}x {item}",
                                "item": {"name": item, "quantity": qty},
                                "raw_json": {
                                    "sender_id": "R1",
                                    "receiver_id": w,
                                    "message_type": "AVAILABILITY_REQUEST",
                                    "item": {"name": item, "quantity": qty},
                                },
                            })
                            await asyncio.sleep(0.15)
                            # Sim response
                            await broadcast_event({
                                "source": w,
                                "target": "R1",
                                "message_type": "AVAILABILITY_RESPONSE",
                                "summary": f"Potwierdzenie dostępności: {item} (dostępne)",
                                "item": {"name": item, "quantity": qty},
                                "is_available": True,
                                "raw_json": {
                                    "sender_id": w,
                                    "receiver_id": "R1",
                                    "message_type": "AVAILABILITY_RESPONSE",
                                    "item": {"name": item, "quantity": qty},
                                    "is_available": True,
                                },
                            })

                    # 2. R1 Quotes (CALL_FOR_PROPOSAL)
                    m = r1_quotes_re.search(line)
                    if m:
                        item, qty, whs_str = m.group(1), float(m.group(2)), m.group(3)
                        whs = [w.strip(" '\"") for w in whs_str.strip("[]").split(",") if w.strip()]
                        for w in whs:
                            await broadcast_event({
                                "source": "R1",
                                "target": w,
                                "message_type": "CALL_FOR_PROPOSAL",
                                "summary": f"Zapytanie ofertowe: {qty}x {item}",
                                "item": {"name": item, "quantity": qty},
                                "raw_json": {
                                    "sender_id": "R1",
                                    "receiver_id": w,
                                    "message_type": "CALL_FOR_PROPOSAL",
                                    "item": {"name": item, "quantity": qty},
                                },
                            })

                    # 3. R1 Proposal received
                    if "[CNP:EVALUATION]" in line and "total_cost=" in line:
                        m_wh = re.search(r"Wholesaler '([^']+)': total_cost=([\d\.]+) PLN \(unit_price=([\d\.]+) PLN\)", line)
                        if m_wh:
                            wh, cost, price = m_wh.group(1), float(m_wh.group(2)), float(m_wh.group(3))
                            await broadcast_event({
                                "source": wh,
                                "target": "R1",
                                "message_type": "PROPOSAL",
                                "summary": f"Oferta cenowa od {wh}: {cost} PLN ({price} PLN/kg)",
                                "total_cost": cost,
                                "item": {"price": price},
                                "raw_json": {
                                    "sender_id": wh,
                                    "receiver_id": "R1",
                                    "message_type": "PROPOSAL",
                                    "total_cost": cost,
                                    "item": {"price": price},
                                },
                            })

                    # 4. R1 Accept proposal
                    m = r1_accept_re.search(line)
                    if m:
                        wh, cost = m.group(1), float(m.group(2))
                        await broadcast_event({
                            "source": "R1",
                            "target": wh,
                            "message_type": "ACCEPT_PROPOSAL",
                            "summary": f"Akceptacja oferty u {wh}: {cost} PLN",
                            "total_cost": cost,
                            "raw_json": {
                                "sender_id": "R1",
                                "receiver_id": wh,
                                "message_type": "ACCEPT_PROPOSAL",
                                "total_cost": cost,
                            },
                        })

                    # 4b. R1 Order Confirmation from Wholesaler
                    m = r1_confirmed_re.search(line)
                    if m:
                        wh = m.group(1)
                        await broadcast_event({
                            "source": wh,
                            "target": "R1",
                            "message_type": "ACCEPT_PROPOSAL",
                            "summary": f"Potwierdzenie akceptacji zamówienia: {wh} -> R1",
                            "raw_json": {
                                "sender_id": wh,
                                "receiver_id": "R1",
                                "message_type": "ACCEPT_PROPOSAL",
                                "status": "ORDER_CONFIRMED",
                            },
                        })

                    # 4c. R1 Order Rejection from Wholesaler (Race Condition / Out of stock)
                    m = r1_rejected_re.search(line)
                    if m:
                        wh, reason = m.group(1), m.group(2)
                        await broadcast_event({
                            "source": wh,
                            "target": "R1",
                            "message_type": "REJECT_PROPOSAL",
                            "summary": f"Odrzucenie zamówienia przez {wh} (powód: {reason}). Przejście do fallback.",
                            "raw_json": {
                                "sender_id": wh,
                                "receiver_id": "R1",
                                "message_type": "REJECT_PROPOSAL",
                                "reason": reason,
                            },
                        })

                    # 5. R1 Delivery
                    m = r1_deliv_re.search(line)
                    if m:
                        qty, item, wh = float(m.group(1)), m.group(2), m.group(3)
                        await broadcast_event({
                            "source": wh,
                            "target": "R1",
                            "message_type": "DELIVERY",
                            "summary": f"Dostawa {wh} -> R1: {qty}x {item}",
                            "item": {"name": item, "quantity": qty},
                            "raw_json": {
                                "sender_id": wh,
                                "receiver_id": "R1",
                                "message_type": "DELIVERY",
                                "item": {"name": item, "quantity": qty},
                            },
                        })

                    # 6. R2 Delivery on MCP server
                    m = r2_mcp_deliv_re.search(line)
                    if m:
                        qty, item, sender = float(m.group(1)), m.group(2).strip(), m.group(3).strip()
                        await broadcast_event({
                            "source": sender,
                            "target": "R2",
                            "message_type": "DELIVERY",
                            "summary": f"Dostawa {sender} -> R2: {qty}x {item}",
                            "item": {"name": item, "quantity": qty},
                            "raw_json": {
                                "sender_id": sender,
                                "receiver_id": "R2",
                                "message_type": "DELIVERY",
                                "item": {"name": item, "quantity": qty},
                            },
                        })

                    # 7. H1 Delivery from P1
                    m = h1_deliv_re.search(line)
                    if m:
                        qty, item, cost = float(m.group(1)), m.group(2).strip(), float(m.group(3))
                        await broadcast_event({
                            "source": "P1",
                            "target": "H1",
                            "message_type": "DELIVERY",
                            "summary": f"Dostawa P1 -> H1: {qty}kg {item} ({cost} PLN)",
                            "item": {"name": item, "quantity": qty},
                            "total_cost": cost,
                            "raw_json": {
                                "sender_id": "P1",
                                "receiver_id": "H1",
                                "message_type": "DELIVERY",
                                "item": {"name": item, "quantity": qty},
                                "total_cost": cost,
                            },
                        })

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Log tailer loop error: {e}")


# =============================================================================
# Startup & Lifespan Tasks
# =============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Overlay Background Tasks...")
    asyncio.create_task(tail_logs_loop())
    asyncio.create_task(poll_databases_loop())


# =============================================================================
# WebSockets & REST Endpoints
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"Client connected. Active clients: {len(active_connections)}")

    # Send initial snapshot
    init_state = get_node_details()
    await websocket.send_text(json.dumps({
        "type": "init",
        "nodes": NODES,
        "state": init_state,
        "history": event_history[-30:],
    }))

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            action = data.get("action")
            if action == "refresh":
                st = get_node_details()
                await websocket.send_text(json.dumps({"type": "node_state", "data": st}))
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info(f"Client disconnected. Active clients: {len(active_connections)}")


@app.get("/api/state")
async def api_get_state():
    """Returns current state of all nodes and active connections."""
    return {
        "nodes": NODES,
        "state": get_node_details(),
        "history": event_history,
    }


class TriggerCookRequest(BaseModel):
    dish_name: str = "Pizza Margherita Classica"
    quantity: int = 1
    auto_reorder: bool = True


@app.post("/api/trigger/cook")
async def api_trigger_cook(req: TriggerCookRequest):
    """Triggers R1 kitchen cooking and auto-reorder."""
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post("http://127.0.0.1:8002/cook", json=req.model_dump())
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trigger/audit")
async def api_trigger_audit():
    """Triggers R1 autonomous pantry audit."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post("http://127.0.0.1:8002/audit")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChatPromptRequest(BaseModel):
    target: str = "R1"  # "R1", "R2", "H1"
    prompt: str


@app.post("/api/trigger/chat")
async def api_trigger_chat(req: ChatPromptRequest):
    """Dispatches a natural language command or info query to specified node."""
    if req.target == "H2":
        try:
            import sys
            h2_dir = str(BASE_DIR / "warehouse-2")
            if h2_dir not in sys.path:
                sys.path.insert(0, h2_dir)
            from agent import agent as h2_agent
            config = {"configurable": {"thread_id": "h2-overlay-session"}}
            result = await h2_agent.ainvoke({"messages": [("user", req.prompt)]}, config)
            raw = result["messages"][-1].content
            if isinstance(raw, list):
                resp_text = "\n".join([b.get("text", str(b)) for b in raw if isinstance(b, dict) and "text" in b])
            else:
                resp_text = str(raw)
            return {"status": "success", "response": resp_text, "odpowiedz": resp_text, "node": "H2"}
        except Exception as e:
            logger.error(f"Błąd Agenta H2: {e}", exc_info=True)
            return {"status": "error", "response": f"Błąd Agenta H2: {e}", "odpowiedz": f"Błąd Agenta H2: {e}"}

    target_url = NODES.get(req.target, {}).get("url")
    if not target_url:
        raise HTTPException(status_code=400, detail=f"Unknown target: {req.target}")

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            if req.target == "R2":
                res = await client.post(f"{target_url}/chat", json={"polecenie": req.prompt})
                data = res.json()
                text = data.get("odpowiedz") or data.get("response") or str(data)
                return {"status": "success", "response": text, "odpowiedz": text, "node": "R2", "watek_zresetowany": data.get("watek_zresetowany", False)}
            else:
                res = await client.post(f"{target_url}/chat", json={"prompt": req.prompt})
                data = res.json()
                text = data.get("response") or data.get("odpowiedz") or str(data)
                return {"status": "success", "response": text, "odpowiedz": text, "node": req.target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Global state for Human-in-the-Loop authorization
active_hitl_event: Optional[asyncio.Event] = None
hitl_decision: Optional[str] = None


class HitlDecisionRequest(BaseModel):
    decision: str = "approve"  # "approve" or "reject"


@app.post("/api/simulate/hitl-confirm")
async def api_simulate_hitl_confirm(req: HitlDecisionRequest):
    """Processes operator's approval or rejection for Human-in-the-Loop scenario."""
    global hitl_decision, active_hitl_event
    hitl_decision = req.decision
    if active_hitl_event and not active_hitl_event.is_set():
        active_hitl_event.set()
    logger.info(f"[HITL CONFIRM] Operator decision: {req.decision}")
    return {"status": "success", "decision": req.decision}


@app.post("/api/simulate/reset")
async def api_simulate_reset():
    """Resets visual history and refreshes node states."""
    event_history.clear()
    recent_signatures.clear()
    recent_event_timestamps.clear()
    state = get_node_details()
    await broadcast_node_state(state)
    return {"status": "reset", "state": state}


@app.post("/api/simulate/demo-flow")
async def api_simulate_demo_flow():
    """
    SCENARIUSZ 1: STANDARDOWY CYKL HANDLU (CNP) - ŚCIEŻKA SUKCESU
    Restauracja R1 (Kupujący) -> Hurtownie H1 i H2 (Sprzedawcy)
    Weryfikacja dostępności, oferty, wybór najtańszego (H1), milczenie wobec H2, dostawa i rozliczenie ACID.
    """
    async def run_demo():
        await broadcast_scenario_start(
            1,
            "Scenariusz 1: Standardowy Cykl Handlu (CNP)",
            "Restauracja R1 potrzebuje 5 kg mąki do wypieku pizzy. Sonduje rynek u dwóch hurtowni (H1 i H2), wybiera najtańszą ofertę, zawiera kontrakt i odbiera dostawę."
        )
        await asyncio.sleep(1.0)

        # Baseline check
        try:
            if DB_PATHS["R1"].exists():
                with sqlite3.connect(DB_PATHS["R1"], timeout=2.0) as conn:
                    bal = conn.execute("SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'").fetchone()
                    if bal and bal[0] < 20.0:
                        conn.execute("UPDATE financial_account SET balance = balance + 500.0 WHERE account_id = 'R1_WALLET'")
            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=2.0) as conn:
                    stock = conn.execute("SELECT quantity FROM products WHERE name = 'flour'").fetchone()
                    if stock and stock[0] < 10:
                        conn.execute("UPDATE products SET quantity = quantity + 50 WHERE name = 'flour'")
        except Exception as e:
            logger.warning(f"Error ensuring baseline for demo: {e}")

        # KROK 1: Weryfikacja Dostępności Towaru
        await broadcast_event({
            "scenario_id": 1,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R1",
            "target": "H1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Zapytanie o dostępność 5 kg mąki -> Hurtownia H1",
            "narrative": "Restauracja R1 sonduje rynek hurtowy i weryfikuje, czy Hurtownia H1 posiada na magazynie co najmniej 5 kg mąki pszennej.",
            "rule": "Zasada CNP Krok 1: Przed rozpoczęciem negocjacji cenowej kupujący sprawdza fizyczną obecność towaru, odrzucając sprzedawców bez zapasów.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 1,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R1",
            "target": "H2",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Zapytanie o dostępność 5 kg mąki -> Hurtownia H2",
            "narrative": "Restauracja R1 równolegle weryfikuje dostępność tego samego surowca u alternatywnego dostawcy – Hurtowni H2.",
            "rule": "Konkurencja rynkowa: Zapytania są rozsyłane równolegle, aby uzyskać optymalne warunki zakupu.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # KROK 1b: Odpowiedź sprzedawców o dostępności
        await broadcast_event({
            "scenario_id": 1,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: Hurtownia H1 potwierdza dostępność towaru (is_available: true)",
            "narrative": "Hurtownia H1 weryfikuje bazę danych i potwierdza: towar jest dostępny od ręki w wystarczającej ilości.",
            "rule": "Filtracja oferentów: Pozytywna odpowiedź kwalifikuje Hurtownię H1 do drugiego etapu (składania ofert cenowych).",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "item": {"name": "flour", "quantity": 5.0}, "is_available": True}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 1,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H2",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: Hurtownia H2 potwierdza dostępność towaru (is_available: true)",
            "narrative": "Hurtownia H2 również weryfikuje bazę SQLite i deklaruje gotowość do realizacji zamówienia.",
            "rule": "Obaj dostawcy zakwalifikowani: Kupujący R1 przechodzi do zbierania ofert cenowych od obu partnerów.",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "item": {"name": "flour", "quantity": 5.0}, "is_available": True}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # KROK 2: Zbieranie Ofert Cenowych (CFP)
        await broadcast_event({
            "scenario_id": 1,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R1",
            "target": "H1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: Zaproszenie do złożenia oferty cenowej (CFP) -> H1",
            "narrative": "Restauracja R1 składa formalne zapytanie ofertowe (CALL_FOR_PROPOSAL) o wycenę 5 kg mąki do Hurtowni H1.",
            "rule": "Zasada CNP Krok 2: Zapytanie ofertowe jest kierowane wyłącznie do zweryfikowanych wcześniej sprzedawców.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 1,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R1",
            "target": "H2",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: Zaproszenie do złożenia oferty cenowej (CFP) -> H2",
            "narrative": "Restauracja R1 jednocześnie składa analogiczne zapytanie ofertowe do Hurtowni H2.",
            "rule": "Standaryzacja zapytań: Oba zapytania mają identyczną specyfikację wolumenu i surowca.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # KROK 2b: Oferty sprzedawców (PROPOSAL)
        await broadcast_event({
            "scenario_id": 1,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H1",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H1: 3.50 PLN/kg (Łącznie: 17.50 PLN)",
            "narrative": "Hurtownia H1 przedstawia wiążącą ofertę: cena jednostkowa wynosi 3.50 PLN/kg, całkowity koszt to 17.50 PLN.",
            "rule": "Wiążący charakter oferty: Sprzedawca gwarantuje podaną cenę na czas trwania procedury przetargowej.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 1,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H2",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H2: 4.00 PLN/kg (Łącznie: 20.00 PLN)",
            "narrative": "Hurtownia H2 składa ofertę konkurencyjną: cena 4.00 PLN/kg, całkowity koszt wynosi 20.00 PLN.",
            "rule": "Kompletność ofert: Kupujący zebrał komplet ofert i przystępuje do ich automatycznej analizy.",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 4.00}, "total_cost": 20.00}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # KROK 3: Wybór Najlepszej Oferty
        await broadcast_event({
            "scenario_id": 1,
            "step": 3,
            "step_title": "Wybór Najlepszej Oferty",
            "source": "R1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 3: Analiza ofert -> Wybór Hurtowni H1 (17.50 PLN vs 20.00 PLN)",
            "narrative": "Restauracja R1 stosuje algorytm min(total_cost). Oferta H1 (17.50 PLN) jest o 2.50 PLN tańsza od H2. Wobec H2 zastosowano zasadę milczenia.",
            "rule": "Zasada Milczenia (Silence Rule): Zgodnie z protokołem CNP, oferta przegranego (H2) po prostu wygasa. Kupujący nie generuje zbędnego ruchu w sieci.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"action": "EVALUATE_OFFERS", "selected": "H1", "total_cost": 17.50, "ignored_silent": "H2", "savings": 2.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # KROK 4: Zawarcie Kontraktu (ACCEPT_PROPOSAL)
        await broadcast_event({
            "scenario_id": 1,
            "step": 4,
            "step_title": "Zawarcie Kontraktu i Rezerwacja",
            "source": "R1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Kupujący akceptuje ofertę Hurtowni H1 (ACCEPT_PROPOSAL)",
            "narrative": "Restauracja R1 przesyła oficjalną akceptację oferty do Hurtowni H1 na kwotę 17.50 PLN.",
            "rule": "Zasada CNP Krok 4: Wiążące zamówienie. Oferta zostaje przekształcona w prawomocny kontrakt handlowy.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.5)

        # KROK 4b: Sprzedawca potwierdza zamówienie
        await broadcast_event({
            "scenario_id": 1,
            "step": 4,
            "step_title": "Zawarcie Kontraktu i Rezerwacja",
            "source": "H1",
            "target": "R1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Hurtownia H1 potwierdza przyjęcie zamówienia (ORDER_CONFIRMED)",
            "narrative": "Hurtownia H1 weryfikuje bazę danych, rezerwuje 5 kg mąki i odsyła potwierdzenie przyjęcia zamówienia do Kupującego.",
            "rule": "Dwuetapowe zatwierdzenie: Sprzedawca przed wydaniem towaru ostatecznie rezerwuje zasoby magazynowe.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "ACCEPT_PROPOSAL", "status": "ORDER_CONFIRMED", "total_cost": 17.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # KROK 5: Rozliczenie ACID w SQLite i Fizyczna Dostawa
        try:
            if DB_PATHS["R1"].exists():
                with sqlite3.connect(DB_PATHS["R1"], timeout=3.0) as conn:
                    conn.execute("UPDATE financial_account SET balance = balance - 17.50, updated_at = CURRENT_TIMESTAMP WHERE account_id = 'R1_WALLET'")
                    conn.execute("UPDATE inventory SET quantity = quantity + 5 WHERE name = 'flour'")
                    cur_r1 = conn.execute(
                        "INSERT INTO transactions (account_id, transaction_type, amount, currency, description) VALUES (?, ?, ?, ?, ?)",
                        ("R1_WALLET", "EXPENSE", 17.50, "PLN", "Zakup 5 kg mąki od Hurtownia 1 (CNP Sukces)")
                    )
                    last_seen_db_ids["R1"] = max(last_seen_db_ids["R1"], cur_r1.lastrowid or 0)
                    conn.commit()

            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=3.0) as conn:
                    conn.execute("UPDATE account SET balance = balance + 17.50 WHERE id = 1")
                    conn.execute("UPDATE products SET quantity = quantity - 5 WHERE name = 'flour'")
                    cur_h1 = conn.execute(
                        "INSERT INTO transactions (partner, type, item_name, quantity, total_cost) VALUES (?, ?, ?, ?, ?)",
                        ("Restauracja R1", "SALE", "flour", 5, 17.50)
                    )
                    last_seen_db_ids["H1"] = max(last_seen_db_ids["H1"], cur_h1.lastrowid or 0)
                    conn.commit()

            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for CNP Success (R1, H1).")
        except Exception as e:
            logger.error(f"Error executing balance update in demo: {e}", exc_info=True)

        # KROK 5: Fizyczna dostawa towaru (DELIVERY)
        await broadcast_event({
            "scenario_id": 1,
            "step": 5,
            "step_title": "Rozliczenie Finansowe i Dostawa",
            "source": "H1",
            "target": "R1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: Hurtownia H1 realizuje dostawę 5 kg mąki do R1 (DELIVERY)",
            "narrative": "Hurtownia H1 dostarcza towar do Restauracji R1. Salda obu stron w SQLite zostały zbilansowane: R1: -17.50 PLN (+5 kg mąki), H1: +17.50 PLN (-5 kg mąki).",
            "rule": "Spójność ACID: Płatność i zmiana stanów magazynowych dokonują się atomowo w bazach SQLite obu agentów.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "DELIVERY", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50, "status": "DELIVERED"}
        }, bypass_dedup=True)

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())
        await broadcast_scenario_end(1, "Scenariusz 1: Standardowy Cykl Handlu Zakończony Sukcesem", "Wszystkie 5 kroków protokołu CNP zostało zrealizowanych. Surowiec dotarł do spiżarni R1, środki przekazane do H1.")

    asyncio.create_task(run_demo())
    return {"status": "started", "scenario_id": 1, "message": "Uruchomiono standardowy 5-etapowy proces CNP."}


@app.post("/api/simulate/demo-reject-flow")
async def api_simulate_demo_reject_flow():
    """
    SCENARIUSZ 2: ODRZUCENIE PRZEZ SPRZEDAWCĘ I AUTOMATYCZNY FALLBACK
    Hurtownia H1 odrzuca (brak towaru z powodu wyprzedania w międzyczasie) -> R1 natychmiast kupuje u H2.
    """
    async def run_reject_demo():
        await broadcast_scenario_start(
            2,
            "Scenariusz 2: Odrzucenie i Automatyczny Fallback",
            "Restauracja R1 wybiera najtańszą Hurtownię H1, lecz towar zostaje w międzyczasie wyprzedany (Race Condition). H1 odrzuca ofertę, a autonomiczny agent R1 bez zatrzymywania natychmiast zawiera kontrakt z kolejną hurtownią (H2)."
        )
        await asyncio.sleep(1.0)

        # Krok 1: Weryfikacja dostępności
        await broadcast_event({
            "scenario_id": 2,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R1",
            "target": "H1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Sprawdzenie dostępności 5 kg mąki w Hurtowni H1",
            "narrative": "Restauracja R1 pyta Hurtownię H1 o dostępność 5 kg mąki.",
            "rule": "Krok 1 CNP: Wstępna filtracja oferentów.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 2,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R1",
            "target": "H2",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Sprawdzenie dostępności 5 kg mąki w Hurtowni H2",
            "narrative": "Restauracja R1 pyta Hurtownię H2 o dostępność 5 kg mąki.",
            "rule": "Równoległe badanie rynku.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 1b: Obie hurtownie potwierdzają
        await broadcast_event({
            "scenario_id": 2,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: H1 potwierdza dostępność (w tym momencie towar jeszcze jest)",
            "narrative": "Hurtownia H1 zgłasza dostępność mąki.",
            "rule": "Dostępność chwilowa: W systemach rozproszonych stan magazynu może ulec zmianie przed złożeniem zamówienia.",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "is_available": True}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 2,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H2",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: H2 potwierdza dostępność",
            "narrative": "Hurtownia H2 również potwierdza obecność mąki.",
            "rule": "Obie hurtownie zakwalifikowane do etapu ofert.",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "is_available": True}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2: Pobranie ofert (CFP)
        await broadcast_event({
            "scenario_id": 2,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R1",
            "target": "H1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: CFP do Hurtowni H1",
            "narrative": "R1 wysyła zapytanie ofertowe do H1.",
            "rule": "Protokół CNP Krok 2.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 2,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R1",
            "target": "H2",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: CFP do Hurtowni H2",
            "narrative": "R1 wysyła zapytanie ofertowe do H2.",
            "rule": "Protokół CNP Krok 2.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2b: Oferty sprzedawców
        await broadcast_event({
            "scenario_id": 2,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H1",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H1: 3.50 PLN/kg (Razem: 17.50 PLN)",
            "narrative": "H1 proponuje 3.50 PLN/kg (17.50 PLN).",
            "rule": "Oferta nr 1 w rankingu cenowym.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 2,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H2",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H2: 4.00 PLN/kg (Razem: 20.00 PLN)",
            "narrative": "H2 proponuje 4.00 PLN/kg (20.00 PLN).",
            "rule": "Oferta nr 2 w rankingu cenowym (rezerwowa).",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 4.00}, "total_cost": 20.00}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # Krok 3: Wybór najtańszego (H1)
        await broadcast_event({
            "scenario_id": 2,
            "step": 3,
            "step_title": "Wybór Najlepszej Oferty",
            "source": "R1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 3: Wybór oferty H1 (17.50 PLN), H2 zachowana jako Fallback",
            "narrative": "Restauracja R1 wybiera tańszą ofertę H1, zachowując ofertę H2 w pamięci na wypadek problemów z realizacją.",
            "rule": "Strategia Fallback: Przygotowanie planu awaryjnego na wypadek braku towaru u pierwszego wybranego sprzedawcy.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"action": "EVALUATE_OFFERS", "primary_choice": "H1", "fallback_choice": "H2"}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 4: Próba akceptacji u H1
        await broadcast_event({
            "scenario_id": 2,
            "step": 4,
            "step_title": "Zawarcie Kontraktu / Obsługa Wyjątku",
            "source": "R1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Próba akceptacji oferty w Hurtowni H1 (ACCEPT_PROPOSAL)",
            "narrative": "Restauracja R1 wysyła akceptację do Hurtowni H1 na kwotę 17.50 PLN.",
            "rule": "Krok 4 CNP.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 4: ODRZUCENIE PRZEZ H1 (Brak towaru / Race Condition)
        await broadcast_event({
            "scenario_id": 2,
            "step": 4,
            "step_title": "Odrzucenie Zamówienia (Brak Towaru)",
            "source": "H1",
            "target": "R1",
            "message_type": "REJECT_PROPOSAL",
            "summary": "Krok 4: ❌ Hurtownia H1 odrzuca zamówienie: Towar wyprzedany w międzyczasie!",
            "narrative": "Hurtownia H1 weryfikuje bazę danych przed potwierdzeniem rezerwacji: inny klient wykupił ostatnie zapasy mąki ułamek sekundy wcześniej! H1 zwraca oficjalny błąd REJECT_PROPOSAL (OUT_OF_STOCK).",
            "rule": "Obsługa Wyścigu Zasobów (Race Condition): Sprzedawca chroni spójność magazynu i nie potwierdza zamówienia bez pokrycia w towarze.",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "REJECT_PROPOSAL",
                "reason": "OUT_OF_STOCK: Towar został wyprzedany w międzyczasie przez inną transakcję",
                "status": "REJECTED"
            }
        }, bypass_dedup=True)
        await asyncio.sleep(2.2)

        # Krok 4b: AUTOMATYCZNY FALLBACK KUPUJĄCEGO DO H2
        await broadcast_event({
            "scenario_id": 2,
            "step": 4,
            "step_title": "Automatyczny Fallback do Oferty Rezerwowej",
            "source": "R1",
            "target": "H2",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4 (Fallback): R1 natychmiast zawiera kontrakt z Hurtownią H2 (20.00 PLN)",
            "narrative": "Autonomiczny agent R1 nie poddaje się i nie angażuje człowieka. Natychmiast sięga po drugą ofertę ze swojej listy (Hurtownia H2: 20.00 PLN) i wysyła do niej ACCEPT_PROPOSAL.",
            "rule": "Odporność Agentowa (Resilience): Agent automatycznie koryguje plan bez konieczności ponawiania całej procedury przetargowej od zera.",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 4.00}, "total_cost": 20.00, "fallback_mode": True}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 4c: H2 potwierdza zamówienie
        await broadcast_event({
            "scenario_id": 2,
            "step": 4,
            "step_title": "Zawarcie Kontraktu z Dostawcą Rezerwowym",
            "source": "H2",
            "target": "R1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Hurtownia H2 potwierdza przyjęcie zamówienia (ORDER_CONFIRMED)",
            "narrative": "Hurtownia H2 weryfikuje stan magazynowy, rezerwuje 5 kg mąki i odsyła potwierdzenie przyjęcia zamówienia.",
            "rule": "Skuteczna finalizacja rezerwy: Transakcja została pomyślnie skierowana do alternatywnego dostawcy.",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "ACCEPT_PROPOSAL", "status": "ORDER_CONFIRMED", "total_cost": 20.00}
        }, bypass_dedup=True)
        await asyncio.sleep(1.5)

        # Krok 5: Bilansowanie bazy w SQLite dla transakcji R1 <-> H2
        try:
            if DB_PATHS["R1"].exists():
                with sqlite3.connect(DB_PATHS["R1"], timeout=3.0) as conn:
                    conn.execute("UPDATE financial_account SET balance = balance - 20.00, updated_at = CURRENT_TIMESTAMP WHERE account_id = 'R1_WALLET'")
                    conn.execute("UPDATE inventory SET quantity = quantity + 5 WHERE name = 'flour'")
                    cur_r1 = conn.execute(
                        "INSERT INTO transactions (account_id, transaction_type, amount, currency, description) VALUES (?, ?, ?, ?, ?)",
                        ("R1_WALLET", "EXPENSE", 20.00, "PLN", "Zakup 5 kg mąki od Hurtownia 2 (Fallback po Reject w H1)")
                    )
                    last_seen_db_ids["R1"] = max(last_seen_db_ids["R1"], cur_r1.lastrowid or 0)
                    conn.commit()

            if DB_PATHS["H2"].exists():
                with sqlite3.connect(DB_PATHS["H2"], timeout=3.0) as conn:
                    conn.execute("UPDATE warehouse2 SET quantity = quantity - 5 WHERE LOWER(name) = 'flour'")
                    last_bal_row = conn.execute("SELECT ballance FROM wallet_warehouse2 ORDER BY id DESC LIMIT 1").fetchone()
                    last_bal = float(last_bal_row[0]) if last_bal_row else 1000.0
                    cur_h2 = conn.execute(
                        "INSERT INTO wallet_warehouse2 (sender_id, receiver_id, type, ballance) VALUES (?, ?, ?, ?)",
                        ("R1", "H2", "INCOME", last_bal + 20.00)
                    )
                    last_seen_db_ids["H2"] = max(last_seen_db_ids["H2"], cur_h2.lastrowid or 0)
                    conn.commit()

            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for CNP Reject & Fallback (R1, H2).")
        except Exception as e:
            logger.error(f"Error executing balance update in reject demo: {e}", exc_info=True)

        # Krok 5: Hurtownia H2 dostarcza towar
        await broadcast_event({
            "scenario_id": 2,
            "step": 5,
            "step_title": "Rozliczenie Finansowe i Dostawa",
            "source": "H2",
            "target": "R1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: Hurtownia H2 dostarcza 5 kg mąki do R1 (DELIVERY)",
            "narrative": "Hurtownia H2 dostarcza towar do Restauracji R1. Salda zbilansowane: R1: -20.00 PLN (+5 kg mąki), H2: +20.00 PLN (-5 kg mąki).",
            "rule": "Finalizacja procedury awaryjnej: Mimo odmowy pierwszego sprzedawcy, łańcuch dostaw restauracji zachował ciągłość operacyjną.",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "DELIVERY", "item": {"name": "flour", "quantity": 5.0, "price": 4.00}, "total_cost": 20.00, "status": "DELIVERED"}
        }, bypass_dedup=True)

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())
        await broadcast_scenario_end(2, "Scenariusz 2: Procedura Odrzucenia i Fallback Zakończona Sukcesem", "Agent R1 samodzielnie obsłużył brak towaru u pierwszego oferenta i pomyślnie zaopatrzył restaurację u sprzedawcy rezerwowego.")

    asyncio.create_task(run_reject_demo())
    return {"status": "started", "scenario_id": 2, "message": "Uruchomiono cykl CNP z odrzuceniem i procedurą Fallback."}


@app.post("/api/simulate/h1-p1-flow")
async def api_simulate_h1_p1_flow():
    """
    SCENARIUSZ 3: DOSTAWA HURTOWA OD PRODUCENTA (H1 -> P1)
    Hurtownia H1 staje się Kupującym, a Producent P1 Sprzedającym.
    Demonstracja rekurencyjności protokołu w łańcuchu dostaw.
    """
    async def run_h1_p1():
        await broadcast_scenario_start(
            3,
            "Scenariusz 3: Dostawa Hurtowa od Producenta (H1 -> P1)",
            "Hurtownia H1 uzupełnia stan magazynowy, zamawiając 25 kg mąki bezpośrednio u Producenta P1 po cenie fabrycznej (2.50 PLN/kg). Demonstruje to rekurencyjną rolę agentów (Hurtownia jako kupujący)."
        )
        await asyncio.sleep(1.0)

        # Krok 1: H1 sprawdza dostępność u P1
        await broadcast_event({
            "scenario_id": 3,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H1",
            "target": "P1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Hurtownia H1 pyta Producenta P1 o 25 kg mąki",
            "narrative": "Hurtownia H1, działając jako Kupujący, sonduje moce produkcyjne i stan magazynowy Producenta P1 na 25 kg mąki.",
            "rule": "Rekurencja protokołu: Rola kupującego i sprzedającego powtarza się na każdym szczeblu wielopoziomowego łańcucha dostaw.",
            "item": {"name": "flour", "quantity": 25.0},
            "raw_json": {"sender_id": "H1", "receiver_id": "P1", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 25.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 1b: P1 potwierdza dostępność
        await broadcast_event({
            "scenario_id": 3,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "P1",
            "target": "H1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: Producent P1 potwierdza dostępność partii hurtowej",
            "narrative": "Producent P1 potwierdza: partia 25 kg mąki jest dostępna na magazynie fabrycznym.",
            "rule": "Kwalifikacja zamówienia hurtowego.",
            "item": {"name": "flour", "quantity": 25.0},
            "is_available": True,
            "raw_json": {"sender_id": "P1", "receiver_id": "H1", "message_type": "AVAILABILITY_RESPONSE", "item": {"name": "flour", "quantity": 25.0}, "is_available": True}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2: H1 wysyła zapytanie ofertowe (CFP)
        await broadcast_event({
            "scenario_id": 3,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H1",
            "target": "P1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: Hurtownia H1 żąda oferty cenowej hurtowej u P1",
            "narrative": "Hurtownia H1 wysyła formalne zapytanie ofertowe (CFP) o cenę fabryczną dla wolumenu hurtowego 25 kg.",
            "rule": "Krok 2 CNP w relacji B2B.",
            "item": {"name": "flour", "quantity": 25.0},
            "raw_json": {"sender_id": "H1", "receiver_id": "P1", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 25.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2b: P1 składa ofertę fabryczną
        await broadcast_event({
            "scenario_id": 3,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "P1",
            "target": "H1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta fabryczna P1: 2.50 PLN/kg (Razem: 62.50 PLN)",
            "narrative": "Producent P1 proponuje hurtową cenę fabryczną 2.50 PLN/kg, co daje łącznie 62.50 PLN za 25 kg mąki.",
            "rule": "Cena producenta: Niższy koszt bazowy pozwala hurtowni wygenerować marżę przy dalszej odsprzedaży restauracjom.",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {"sender_id": "P1", "receiver_id": "H1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 25.0, "price": 2.50}, "total_cost": 62.50}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # Krok 3: Analiza oferty przez Hurtownię H1
        await broadcast_event({
            "scenario_id": 3,
            "step": 3,
            "step_title": "Wybór Najlepszej Oferty",
            "source": "H1",
            "target": "H1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 3: Hurtownia H1 weryfikuje budżet i akceptuje marżę hurtową",
            "narrative": "Hurtownia H1 sprawdza stan swojego konta firmowego i stwierdza pełną opłacalność zakupu po cenie fabrycznej 2.50 PLN/kg.",
            "rule": "Weryfikacja płynności finansowej: Agent kupujący sprawdza stan portfela przed podjęciem zobowiązania.",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {"action": "EVALUATE_OFFERS", "producer": "P1", "margin_check": "APPROVED", "total_cost": 62.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 4: H1 akceptuje ofertę u P1
        await broadcast_event({
            "scenario_id": 3,
            "step": 4,
            "step_title": "Zawarcie Kontraktu Hurtowego",
            "source": "H1",
            "target": "P1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Hurtownia H1 akceptuje ofertę Producenta P1 (ACCEPT_PROPOSAL)",
            "narrative": "Hurtownia H1 zatwierdza kontrakt na dostawę 25 kg mąki za kwotę 62.50 PLN.",
            "rule": "Krok 4 CNP.",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "P1", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "flour", "quantity": 25.0, "price": 2.50}, "total_cost": 62.50}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 4b: P1 potwierdza akceptację
        await broadcast_event({
            "scenario_id": 3,
            "step": 4,
            "step_title": "Zawarcie Kontraktu Hurtowego",
            "source": "P1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Producent P1 potwierdza zamówienie fabryczne (ORDER_CONFIRMED)",
            "narrative": "Producent P1 rejestruje zamówienie w systemie fabrycznym i rezerwuje paletę mąki do wysyłki.",
            "rule": "Rezerwacja mocy produkcyjnych.",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {"sender_id": "P1", "receiver_id": "H1", "message_type": "ACCEPT_PROPOSAL", "status": "ORDER_CONFIRMED"}
        }, bypass_dedup=True)
        await asyncio.sleep(1.5)

        # Krok 5: Bilansowanie bazy danych w SQLite u P1 i H1
        try:
            if DB_PATHS["P1"].exists():
                with sqlite3.connect(DB_PATHS["P1"], timeout=3.0) as conn:
                    conn.execute("UPDATE products SET stock_quantity = stock_quantity - 25.0 WHERE product_code = 'flour'")
                    cur_p1 = conn.execute(
                        "INSERT INTO sales_transactions (product_code, quantity, unit_price, total_cost, buyer_id, transaction_date) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                        ("flour", 25.0, 2.50, 62.50, "H1")
                    )
                    last_seen_db_ids["P1"] = max(last_seen_db_ids["P1"], cur_p1.lastrowid or 0)
                    conn.commit()

            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=3.0) as conn:
                    conn.execute("UPDATE account SET balance = balance - 62.50 WHERE id = 1")
                    conn.execute("UPDATE products SET quantity = quantity + 25 WHERE name = 'flour'")
                    cur_h1 = conn.execute(
                        "INSERT INTO transactions (partner, type, item_name, quantity, total_cost) VALUES (?, ?, ?, ?, ?)",
                        ("P1", "PURCHASE", "flour", 25, 62.50)
                    )
                    last_seen_db_ids["H1"] = max(last_seen_db_ids["H1"], cur_h1.lastrowid or 0)
                    conn.commit()

            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for H1 -> P1 procurement.")
        except Exception as e:
            logger.error(f"Error executing H1 -> P1 balance update: {e}", exc_info=True)

        # Krok 5: Producent P1 dostarcza towar do H1
        await broadcast_event({
            "scenario_id": 3,
            "step": 5,
            "step_title": "Rozliczenie Finansowe i Dostawa",
            "source": "P1",
            "target": "H1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: Producent P1 dostarcza 25 kg mąki do Hurtowni H1 (DELIVERY)",
            "narrative": "Producent P1 realizuje dostawę fabryczną do Hurtowni H1. Magazyn H1 powiększa się o 25 kg mąki, a saldo zostaje obciążone kwotą 62.50 PLN.",
            "rule": "Finalizacja kontraktu B2B w SQLite.",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {"sender_id": "P1", "receiver_id": "H1", "message_type": "DELIVERY", "item": {"name": "flour", "quantity": 25.0, "price": 2.50}, "total_cost": 62.50, "status": "DELIVERED"}
        }, bypass_dedup=True)

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())
        await broadcast_scenario_end(3, "Scenariusz 3: Zaopatrzenie Hurtowe Zakończone Sukcesem", "Hurtownia H1 uzupełniła stan magazynowy o 25 kg mąki u Producenta P1, przygotowując się do dalszej dystrybucji.")

    asyncio.create_task(run_h1_p1())
    return {"status": "started", "scenario_id": 3, "message": "Uruchomiono 5-etapowy proces CNP dla Hurtownia H1 -> Producent P1."}


@app.post("/api/simulate/hitl-flow")
async def api_simulate_hitl_flow():
    """
    SCENARIUSZ 4: DECYZJA CZŁOWIEKA (HUMAN-IN-THE-LOOP) - RESTAURACJA R2
    Restauracja R2 poszukuje 10 kg sera Mozzarella.
    Agent porównuje oferty H1 i H2, wybiera najtańszą (H1: 85 PLN vs H2: 145 PLN),
    lecz ZGODNIE Z POLITYKĄ HITL wstrzymuje transakcję i oczekuje na kliknięcie człowieka w UI!
    Po zatwierdzeniu przez operatora, transakcja zostaje sfinalizowana w SQLite.
    """
    global active_hitl_event, hitl_decision
    active_hitl_event = asyncio.Event()
    hitl_decision = None

    async def run_hitl():
        global hitl_decision
        await broadcast_scenario_start(
            4,
            "Scenariusz 4: Decyzja Człowieka (Human-in-the-Loop)",
            "Restauracja R2 zamawia 10 kg sera Mozzarella. Polityka firmy nakazuje autoryzację każdego zakupu przez człowieka. Agent autonomicznie porówna oferty, przygotuje rekomendację i zatrzyma się, czekając na Twoją zgodę."
        )
        await asyncio.sleep(1.0)

        # Krok 1: R2 sprawdza dostępność 10 kg Mozzarelli w H1 i H2
        await broadcast_event({
            "scenario_id": 4,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R2",
            "target": "H1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Restauracja R2 sprawdza dostępność 10 kg sera Mozzarella w H1",
            "narrative": "Agent Restauracji 2 (R2) sonduje rynek pod kątem 10 kg sera Mozzarella w Hurtowni H1.",
            "rule": "Krok 1 CNP.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "raw_json": {"sender_id": "R2", "receiver_id": "H1", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "Mozzarella", "quantity": 10.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 4,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "R2",
            "target": "H2",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: Restauracja R2 sprawdza dostępność 10 kg sera Mozzarella w H2",
            "narrative": "Agent R2 równolegle sprawdza dostępność sera Mozzarella w Hurtowni H2.",
            "rule": "Równoległe zapytanie ofertowe.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "raw_json": {"sender_id": "R2", "receiver_id": "H2", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "Mozzarella", "quantity": 10.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 1b: Hurtownie potwierdzają dostępność
        await broadcast_event({
            "scenario_id": 4,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H1",
            "target": "R2",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: Hurtownia H1 potwierdza dostępność Mozzarelli",
            "narrative": "Hurtownia H1 zgłasza dostępność sera Mozzarella (140 kg na stanie).",
            "rule": "Oferent zakwalifikowany.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "is_available": True,
            "raw_json": {"sender_id": "H1", "receiver_id": "R2", "message_type": "AVAILABILITY_RESPONSE", "is_available": True}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 4,
            "step": 1,
            "step_title": "Weryfikacja Dostępności Towaru",
            "source": "H2",
            "target": "R2",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: Hurtownia H2 potwierdza dostępność Mozzarelli",
            "narrative": "Hurtownia H2 również potwierdza obecność Mozzarelli (58 kg na stanie).",
            "rule": "Oferent zakwalifikowany.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "is_available": True,
            "raw_json": {"sender_id": "H2", "receiver_id": "R2", "message_type": "AVAILABILITY_RESPONSE", "is_available": True}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2: Pobranie ofert (CFP)
        await broadcast_event({
            "scenario_id": 4,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R2",
            "target": "H1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: CFP na 10 kg Mozzarelli -> H1",
            "narrative": "Restauracja R2 wzywa Hurtownię H1 do złożenia oferty cenowej.",
            "rule": "Krok 2 CNP.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "raw_json": {"sender_id": "R2", "receiver_id": "H1", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "Mozzarella", "quantity": 10.0}}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 4,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "R2",
            "target": "H2",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: CFP na 10 kg Mozzarelli -> H2",
            "narrative": "Restauracja R2 wzywa Hurtownię H2 do złożenia oferty cenowej.",
            "rule": "Krok 2 CNP.",
            "item": {"name": "Mozzarella", "quantity": 10.0},
            "raw_json": {"sender_id": "R2", "receiver_id": "H2", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "Mozzarella", "quantity": 10.0}}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # Krok 2b: Oferty sprzedawców (H1 dużo tańsza!)
        await broadcast_event({
            "scenario_id": 4,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H1",
            "target": "R2",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H1: 8.50 PLN/kg (Razem: 85.00 PLN)",
            "narrative": "Hurtownia H1 składa bardzo atrakcyjną ofertę: 8.50 PLN/kg, co daje łącznie 85.00 PLN za 10 kg Mozzarelli.",
            "rule": "Oferta wiodąca w rankingu.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"sender_id": "H1", "receiver_id": "R2", "message_type": "PROPOSAL", "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50}, "total_cost": 85.00}
        }, bypass_dedup=True)

        await broadcast_event({
            "scenario_id": 4,
            "step": 2,
            "step_title": "Zbieranie Ofert Cenowych (CFP)",
            "source": "H2",
            "target": "R2",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H2: 14.50 PLN/kg (Razem: 145.00 PLN)",
            "narrative": "Hurtownia H2 oferuje tę samą ilość w cenie 14.50 PLN/kg (całkowity koszt: 145.00 PLN).",
            "rule": "Różnica w cenie wynosi aż 60.00 PLN na korzyść H1.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 14.50},
            "total_cost": 145.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R2", "message_type": "PROPOSAL", "item": {"name": "Mozzarella", "quantity": 10.0, "price": 14.50}, "total_cost": 145.00}
        }, bypass_dedup=True)
        await asyncio.sleep(2.0)

        # Krok 3: Analiza i Wybór Rekomendacji
        await broadcast_event({
            "scenario_id": 4,
            "step": 3,
            "step_title": "Wybór Najlepszej Oferty",
            "source": "R2",
            "target": "R2",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 3: Agent R2 wybiera H1 (85.00 PLN), oszczędność 60.00 PLN",
            "narrative": "Agent R2 wylicza, że oferta Hurtowni H1 (85.00 PLN) pozwala zaoszczędzić 60.00 PLN w stosunku do H2 (145.00 PLN). Rekomendacja zakupu zostaje przygotowana.",
            "rule": "Nadzorowana Autonomia (HITL): Zanim kontrakt zostanie podpisany, agent R2 ma obowiązek uzyskać akceptację człowieka.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"action": "EVALUATE_OFFERS", "recommended": "H1", "total_cost": 85.00, "alternative": "H2", "savings": 60.00}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # KROK 4: WSTRZYMANIE I OCZEKIWANIE NA DECYZJĘ CZŁOWIEKA (HITL)
        await broadcast_event({
            "scenario_id": 4,
            "step": 4,
            "step_title": "Weryfikacja i Decyzja Człowieka (HITL)",
            "source": "R2",
            "target": "OPERATOR",
            "message_type": "WAITING_HUMAN_APPROVAL",
            "summary": "Krok 4: ⚠️ WYMAGANA AKCEPTACJA CZŁOWIEKA: Zakup 10 kg Mozzarelli za 85.00 PLN",
            "narrative": "AGENT R2 ZATRZYMUJE TRANSAKCJĘ! Zgodnie z polityką Human-in-the-Loop, agent nie obciąża konta restauracji bez potwierdzenia. Kliknij przycisk 'Zatwierdź zakup' w panelu po prawej stronie, aby autoryzować wydatek.",
            "rule": "Reguła Bezpieczeństwa HITL: Wydatki powyżej ustalonego progu wymagają fizycznego podpisu/potwierdzenia przez uprawnionego pracownika restauracji.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "requires_approval": True,
            "raw_json": {
                "sender_id": "R2",
                "receiver_id": "OPERATOR_UI",
                "message_type": "WAITING_HUMAN_APPROVAL",
                "item": {"name": "Mozzarella", "quantity": 10.0, "unit_price": 8.50},
                "total_cost": 85.00,
                "seller": "H1",
                "status": "AWAITING_APPROVAL"
            }
        }, bypass_dedup=True)

        logger.info("[HITL] Waiting up to 30 seconds for operator decision...")
        try:
            await asyncio.wait_for(active_hitl_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.info("[HITL] Timeout reached. Defaulting to auto-approve for demonstration.")
            hitl_decision = "approve"

        # Rozpatrzenie decyzji
        if hitl_decision == "reject":
            await broadcast_event({
                "scenario_id": 4,
                "step": 4,
                "step_title": "Anulowanie przez Człowieka",
                "source": "OPERATOR",
                "target": "R2",
                "message_type": "REJECT_PROPOSAL",
                "summary": "Krok 4: ❌ Operator odrzucił transakcję. Proces anulowany.",
                "narrative": "Człowiek odrzucił wniosek o zakup. Agent R2 szanuje decyzję operatora i natychmiast anuluje procedurę, nie obciążając budżetu restauracji.",
                "rule": "Nadrzędność człowieka: Decyzja operatora ma priorytet bezwzględny nad autonomią agenta.",
                "raw_json": {"status": "REJECTED_BY_OPERATOR", "reason": "Operator manually declined the purchase."}
            }, bypass_dedup=True)
            await broadcast_scenario_end(4, "Scenariusz 4 Zakończony: Transakcja Anulowana", "Decyzją człowieka transakcja została bezpiecznie przerwana bez wydatkowania środków.")
            return

        # Jeśli zatwierdzone (approve):
        await broadcast_event({
            "scenario_id": 4,
            "step": 4,
            "step_title": "Autoryzacja Udzielona przez Człowieka",
            "source": "OPERATOR",
            "target": "R2",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: ✅ Operator zatwierdził wydatek 85.00 PLN. Agent finalizuje zakup.",
            "narrative": "Operator udzielił autoryzacji! Agent R2 przystępuje do formalnego zawarcia kontraktu z Hurtownią H1.",
            "rule": "Podpisanie cyfrowe: Zgoda człowieka zwalnia blokadę finansową agenta.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"status": "APPROVED_BY_OPERATOR", "total_cost": 85.00}
        }, bypass_dedup=True)
        await asyncio.sleep(1.5)

        # R2 wysyła formalny ACCEPT_PROPOSAL do H1
        await broadcast_event({
            "scenario_id": 4,
            "step": 4,
            "step_title": "Zawarcie Kontraktu z Hurtownią",
            "source": "R2",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: R2 składa zamówienie w Hurtowni H1 (ACCEPT_PROPOSAL)",
            "narrative": "Restauracja R2 wysyła oficjalną akceptację oferty do Hurtowni H1 (85.00 PLN).",
            "rule": "Krok 4 CNP.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"sender_id": "R2", "receiver_id": "H1", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50}, "total_cost": 85.00}
        }, bypass_dedup=True)
        await asyncio.sleep(1.8)

        # H1 potwierdza akceptację
        await broadcast_event({
            "scenario_id": 4,
            "step": 4,
            "step_title": "Zawarcie Kontraktu z Hurtownią",
            "source": "H1",
            "target": "R2",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Hurtownia H1 potwierdza przyjęcie zamówienia (ORDER_CONFIRMED)",
            "narrative": "Hurtownia H1 rezerwuje 10 kg Mozzarelli i potwierdza gotowość do wysyłki.",
            "rule": "Rezerwacja zasobów sprzedawcy.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"sender_id": "H1", "receiver_id": "R2", "message_type": "ACCEPT_PROPOSAL", "status": "ORDER_CONFIRMED"}
        }, bypass_dedup=True)
        await asyncio.sleep(1.5)

        # Krok 5: Bilansowanie baz w SQLite (R2 i H1)
        try:
            # 1. R2: odejmuje 85.00 PLN, dodaje 10 kg Mozzarelli
            if DB_PATHS["R2"].exists():
                with sqlite3.connect(DB_PATHS["R2"], timeout=3.0) as conn:
                    conn.execute("UPDATE konto SET balans = balans - 85.00 WHERE id = 1")
                    conn.execute("UPDATE magazyn SET ilosc = ilosc + 10 WHERE LOWER(nazwa_produktu) = 'mozzarella'")
                    cur_r2 = conn.execute(
                        "INSERT INTO historia_transakcji (typ_akcji, od_kogo, produkt, ilosc, koszt, data) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                        ("DOSTAWA CNP (HITL)", "H1", "Mozzarella", 10.0, 85.00)
                    )
                    last_seen_db_ids["R2"] = max(last_seen_db_ids["R2"], cur_r2.lastrowid or 0)
                    conn.commit()

            # 2. H1: odejmuje 10 kg sera mozzarella, dodaje 85.00 PLN do konta
            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=3.0) as conn:
                    conn.execute("UPDATE account SET balance = balance + 85.00 WHERE id = 1")
                    conn.execute("UPDATE products SET quantity = quantity - 10 WHERE name = 'mozzarella'")
                    cur_h1 = conn.execute(
                        "INSERT INTO transactions (partner, type, item_name, quantity, total_cost) VALUES (?, ?, ?, ?, ?)",
                        ("Restauracja R2", "SALE", "mozzarella", 10, 85.00)
                    )
                    last_seen_db_ids["H1"] = max(last_seen_db_ids["H1"], cur_h1.lastrowid or 0)
                    conn.commit()

            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for HITL (R2, H1).")
        except Exception as e:
            logger.error(f"Error executing balance update in HITL demo: {e}", exc_info=True)

        # Krok 5: Hurtownia H1 dostarcza Mozzarellę do R2
        await broadcast_event({
            "scenario_id": 4,
            "step": 5,
            "step_title": "Rozliczenie Finansowe i Dostawa",
            "source": "H1",
            "target": "R2",
            "message_type": "DELIVERY",
            "summary": "Krok 5: Hurtownia H1 dostarcza 10 kg sera Mozzarella do Restauracji R2 (DELIVERY)",
            "narrative": "Hurtownia H1 dostarcza ser do kuchni Restauracji 2. Bazy danych zbilansowane: R2: -85.00 PLN (+10 kg Mozzarella), H1: +85.00 PLN (-10 kg Mozzarella).",
            "rule": "Spójność ACID i pełna ewidencja transakcji pod nadzorem człowieka.",
            "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50},
            "total_cost": 85.00,
            "raw_json": {"sender_id": "H1", "receiver_id": "R2", "message_type": "DELIVERY", "item": {"name": "Mozzarella", "quantity": 10.0, "price": 8.50}, "total_cost": 85.00, "status": "DELIVERED"}
        }, bypass_dedup=True)

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())
        await broadcast_scenario_end(4, "Scenariusz 4: Transakcja Nadzorowana (HITL) Zakończona Sukcesem", "Agent R2 wynegocjował optymalne warunki, uzyskał zgodę człowieka, a transakcja została bezpiecznie rozliczona.")

    asyncio.create_task(run_hitl())
    return {"status": "started", "scenario_id": 4, "message": "Uruchomiono cykl handlu z procedurą Human-in-the-Loop."}


# Serve static web frontend
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
