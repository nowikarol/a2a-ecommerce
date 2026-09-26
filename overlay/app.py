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


async def broadcast_event(event: Dict[str, Any]):
    """Broadcasts a supply-chain packet event to all connected WebSocket clients."""
    src = event.get('source') or ''
    tgt = event.get('target') or ''
    mtype = event.get('message_type') or ''
    item_info = event.get('item') or {}
    item_name = str(item_info.get('name') or '').lower().strip()
    qty = str(item_info.get('quantity') or '')
    sig = f"{src}->{tgt}:{mtype}:{item_name}:{qty}"
    
    now_ts = time.time()
    # Deduplicate exact duplicate packets arriving within 3.5 seconds
    if sig in recent_event_timestamps and (now_ts - recent_event_timestamps[sig]) < 3.5:
        logger.info(f"[DEDUP IGNORED] Skipping duplicate event packet: {sig}")
        return
    recent_event_timestamps[sig] = now_ts
    
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
    for ws in active_connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead_connections.append(ws)

    for dead in dead_connections:
        if dead in active_connections:
            active_connections.remove(dead)


async def broadcast_node_state(node_data: Dict[str, Any]):
    """Broadcasts updated node state (balances, stock, health) to clients."""
    payload = json.dumps({"type": "node_state", "data": node_data})
    dead = []
    for ws in active_connections:
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
                        if "DOSTAWA" in (r[1] or ""):
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
    """Dynamically finds all task log files in antigravity tasks folder."""
    user_home = Path(os.path.expanduser("~"))
    pattern = str(user_home / ".gemini" / "antigravity" / "brain" / "*" / ".system_generated" / "tasks" / "*.log")
    files = [Path(p) for p in glob.glob(pattern)]
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


@app.post("/api/simulate/demo-flow")
async def api_simulate_demo_flow():
    """
    KROK PO KROKU ZGODNIE ZE SPECYFIKACJĄ PROTOKOŁU (docs/PROTOCOL_SPECIFICATION.md):
    Ścieżka A: Sukces (Kupujący R1 -> Sprzedający H1 i H2)
    1. Kupujący R1 -> Sprzedający H1, H2: check_availability (AVAILABILITY_REQUEST)
    2. Sprzedający H1, H2 -> Kupujący R1: availability-response (AVAILABILITY_RESPONSE)
    3. Kupujący R1 -> Sprzedający H1, H2: request_offer (CALL_FOR_PROPOSAL)
    4. Sprzedający H1, H2 -> Kupujący R1: response-offer (PROPOSAL, H1: 3.50 PLN/kg, H2: 4.00 PLN/kg)
    5. Kupujący R1 ocenia oferty wg reguły min(total_cost) -> wybór H1 (17.50 PLN).
    6. Kupujący R1 -> Sprzedający H1: accept_offer (ACCEPT_PROPOSAL).
       Sprzedający H1 weryfikuje stan i odpowiada: H1 -> R1: accept-offer (ACCEPT_PROPOSAL).
       ZASADA MILCZENIA: Oferta H2 milcząco wygasa, brak jakichkolwiek komunikatów do H2.
    7. Sprzedający H1 bilansuje bazę i realizuje dostawę: H1 -> R1: receive_delivery (DELIVERY).
       Kupujący R1 bilansuje portfel i magazyn.
    """
    async def run_demo():
        # Zapewnienie minimalnego budżetu i stanu w bazach SQLite
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

        # Pobranie rzeczywistego stanu z bazy
        h1_stock_qty = 50.0
        h2_stock_qty = 45.0
        try:
            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=1.0) as conn:
                    row = conn.execute("SELECT quantity FROM products WHERE name = 'flour'").fetchone()
                    if row:
                        h1_stock_qty = float(row[0])
            if DB_PATHS["H2"].exists():
                with sqlite3.connect(DB_PATHS["H2"], timeout=1.0) as conn:
                    row = conn.execute("SELECT quantity FROM warehouse2 WHERE LOWER(name) = 'flour'").fetchone()
                    if row:
                        h2_stock_qty = float(row[0])
        except Exception:
            pass

        # KROK 1: Weryfikacja Dostępności Towaru (Kupujący -> Sprzedający A, B)
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: check_availability(flour, 5 kg) -> H1",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H1",
                "message_type": "AVAILABILITY_REQUEST",
                "item": {"name": "flour", "quantity": 5.0}
            }
        })
        await broadcast_event({
            "source": "R1",
            "target": "H2",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: check_availability(flour, 5 kg) -> H2",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H2",
                "message_type": "AVAILABILITY_REQUEST",
                "item": {"name": "flour", "quantity": 5.0}
            }
        })
        await asyncio.sleep(1.8)

        # KROK 1: Odpowiedź sprzedawców o dostępności
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": f"Krok 1: availability-response (is_available: true, stan: {int(h1_stock_qty)} kg)",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": "flour", "quantity": 5.0},
                "is_available": True,
                "available_quantity": h1_stock_qty
            }
        })
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": f"Krok 1: availability-response (is_available: true, stan: {int(h2_stock_qty)} kg)",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": "flour", "quantity": 5.0},
                "is_available": True,
                "available_quantity": h2_stock_qty
            }
        })
        await asyncio.sleep(1.8)

        # KROK 2: Pobranie Ofert Cenowych (tylko od dostępnych)
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: request_offer(flour, 5 kg) -> H1",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H1",
                "message_type": "CALL_FOR_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0}
            }
        })
        await broadcast_event({
            "source": "R1",
            "target": "H2",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: request_offer(flour, 5 kg) -> H2",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H2",
                "message_type": "CALL_FOR_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0}
            }
        })
        await asyncio.sleep(1.8)

        # KROK 2: Sprzedawcy składają oferty cenowe (PROPOSAL)
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: response-offer od H1: 3.50 PLN/kg (Razem: 17.50 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
                "total_cost": 17.50
            }
        })
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: response-offer od H2: 4.00 PLN/kg (Razem: 20.00 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
                "total_cost": 20.00
            }
        })
        await asyncio.sleep(2.0)

        # KROK 3 & 4: Kupujący wybiera min(total_cost) -> H1.
        # Kupujący wywołuje accept_offer u H1 (ACCEPT_PROPOSAL).
        # UWAGA: Zasada milczenia wobec H2 (brak wiadomości do H2, oferta milcząco wygasa).
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Wybór min(cena) -> accept_offer(H1, 17.50 PLN). Oferta H2 milcząco wygasa.",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
                "total_cost": 17.50
            }
        })
        await asyncio.sleep(1.8)

        # KROK 4: Sprzedawca H1 weryfikuje bazę i potwierdza akceptację (Ścieżka A)
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Sprzedawca H1 potwierdza akceptację zamówienia (rezerwacja towaru)",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
                "total_cost": 17.50,
                "status": "ORDER_CONFIRMED"
            }
        })
        await asyncio.sleep(1.5)

        # KROK 5: Bilansowanie bazy danych w SQLite i fizyczna dostawa towaru
        try:
            # 1. Bilansowanie u Kupującego R1 (odejmuje saldo, dodaje mąkę, zapisuje transakcję)
            if DB_PATHS["R1"].exists():
                with sqlite3.connect(DB_PATHS["R1"], timeout=3.0) as conn:
                    conn.execute("UPDATE financial_account SET balance = balance - 17.50, updated_at = CURRENT_TIMESTAMP WHERE account_id = 'R1_WALLET'")
                    conn.execute("UPDATE inventory SET quantity = quantity + 5 WHERE name = 'flour'")
                    conn.execute(
                        "INSERT INTO transactions (account_id, transaction_type, amount, currency, description) VALUES (?, ?, ?, ?, ?)",
                        ("R1_WALLET", "EXPENSE", 17.50, "PLN", "Zakup 5 kg mąki od Hurtownia 1 (CNP Sukces)")
                    )
                    conn.commit()

            # 2. Bilansowanie u Sprzedawcy H1 (dodaje saldo, odejmuje mąkę, zapisuje transakcję)
            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=3.0) as conn:
                    conn.execute("UPDATE account SET balance = balance + 17.50 WHERE id = 1")
                    conn.execute("UPDATE products SET quantity = quantity - 5 WHERE name = 'flour'")
                    conn.execute(
                        "INSERT INTO transactions (partner, type, item_name, quantity, total_cost) VALUES (?, ?, ?, ?, ?)",
                        ("Restauracja R1", "SALE", "flour", 5, 17.50)
                    )
                    conn.commit()

            # Natychmiastowe odświeżenie UI
            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for CNP Success (R1, H1).")
        except Exception as e:
            logger.error(f"Error executing balance update in demo: {e}", exc_info=True)

        # KROK 5: Sprzedawca H1 realizuje dostawę (receive_delivery)
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: receive_delivery: H1 dostarcza 5 kg mąki do R1 (rozliczono 17.50 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "DELIVERY",
                "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
                "total_cost": 17.50,
                "status": "DELIVERED"
            }
        })

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())

    asyncio.create_task(run_demo())
    return {"status": "started", "message": "Uruchomiono standardowy 5-etapowy proces CNP (Ścieżka Sukces)."}


@app.post("/api/simulate/demo-reject-flow")
async def api_simulate_demo_reject_flow():
    """
    KROK PO KROKU ZGODNIE ZE SPECYFIKACJĄ PROTOKOŁU (docs/PROTOCOL_SPECIFICATION.md):
    Ścieżka B: Towar wyprzedany w międzyczasie (Odrzucenie przez Sprzedawcę i Fallback Kupującego)
    1. Kupujący R1 -> H1, H2: check_availability (AVAILABILITY_REQUEST)
    2. H1, H2 -> R1: availability-response (AVAILABILITY_RESPONSE)
    3. R1 -> H1, H2: request_offer (CALL_FOR_PROPOSAL)
    4. H1, H2 -> R1: response-offer (PROPOSAL, H1: 3.50 PLN/kg, H2: 4.00 PLN/kg)
    5. R1 ocenia oferty wg reguły min(total_cost) -> wybór najtańszego H1.
    6. Kupujący R1 -> Sprzedający H1: accept_offer (ACCEPT_PROPOSAL).
       Weryfikacja stanu przez H1: brak towaru na stanie (Race Condition / towar wyprzedany)!
       SPRZEDAWCA H1 -> KUPUJĄCY R1: reject.json (REJECT_PROPOSAL ❌)!
    7. FALLBACK KUPUJĄCEGO:
       Kupujący R1 natychmiast przechodzi do kolejnej oferty z listy (H2).
       Kupujący R1 -> Sprzedający H2: accept_offer (ACCEPT_PROPOSAL).
       Sprzedający H2 -> Kupujący R1: accept-offer (ACCEPT_PROPOSAL 🤝).
    8. Sprzedający H2 bilansuje bazę i realizuje dostawę: H2 -> R1: receive_delivery (DELIVERY 🚚).
       Kupujący R1 bilansuje portfel i magazyn.
    """
    async def run_reject_demo():
        # Krok 1: Weryfikacja dostępności
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: check_availability(flour, 5 kg) -> H1",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        })
        await broadcast_event({
            "source": "R1",
            "target": "H2",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: check_availability(flour, 5 kg) -> H2",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "AVAILABILITY_REQUEST", "item": {"name": "flour", "quantity": 5.0}}
        })
        await asyncio.sleep(1.8)

        # Krok 1b: Odpowiedź o dostępności
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: availability-response: H1 (is_available: true)",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "item": {"name": "flour", "quantity": 5.0}, "is_available": True}
        })
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: availability-response: H2 (is_available: true)",
            "item": {"name": "flour", "quantity": 5.0},
            "is_available": True,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "AVAILABILITY_RESPONSE", "item": {"name": "flour", "quantity": 5.0}, "is_available": True}
        })
        await asyncio.sleep(1.8)

        # Krok 2: Pobranie ofert
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: request_offer(flour, 5 kg) -> H1",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        })
        await broadcast_event({
            "source": "R1",
            "target": "H2",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: request_offer(flour, 5 kg) -> H2",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {"sender_id": "R1", "receiver_id": "H2", "message_type": "CALL_FOR_PROPOSAL", "item": {"name": "flour", "quantity": 5.0}}
        })
        await asyncio.sleep(1.8)

        # Krok 2b: Oferty sprzedawców
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H1: 3.50 PLN/kg (Razem: 17.50 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "H1", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        })
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: Oferta H2: 4.00 PLN/kg (Razem: 20.00 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {"sender_id": "H2", "receiver_id": "R1", "message_type": "PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 4.00}, "total_cost": 20.00}
        })
        await asyncio.sleep(2.0)

        # Krok 3 & 4: Kupujący wybiera najtańszą ofertę (H1) i wywołuje accept_offer
        await broadcast_event({
            "source": "R1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Wybór min(cena) -> accept_offer(H1, 17.50 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 3.50},
            "total_cost": 17.50,
            "raw_json": {"sender_id": "R1", "receiver_id": "H1", "message_type": "ACCEPT_PROPOSAL", "item": {"name": "flour", "quantity": 5.0, "price": 3.50}, "total_cost": 17.50}
        })
        await asyncio.sleep(1.8)

        # Krok 4: SPRZEDAWCA H1 WERYFIKUJE STAN I ODRZUCA (Ścieżka B: Race condition / brak towaru)
        await broadcast_event({
            "source": "H1",
            "target": "R1",
            "message_type": "REJECT_PROPOSAL",
            "summary": "Krok 4 (Ścieżka B): Sprzedawca H1 odrzuca zamówienie (brak towaru / wyprzedany w międzyczasie)",
            "item": {"name": "flour", "quantity": 5.0},
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "R1",
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0},
                "reason": "OUT_OF_STOCK: Towar wyprzedany w międzyczasie"
            }
        })
        await asyncio.sleep(2.0)

        # Krok 4 (Fallback Kupującego): R1 natychmiast przechodzi do kolejnej oferty (H2)
        await broadcast_event({
            "source": "R1",
            "target": "H2",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Fallback Kupującego -> accept_offer u kolejnego sprzedawcy: H2 (20.00 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {
                "sender_id": "R1",
                "receiver_id": "H2",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
                "total_cost": 20.00
            }
        })
        await asyncio.sleep(1.8)

        # Krok 4: Sprzedawca H2 potwierdza akceptację
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Sprzedawca H2 potwierdza przyjęcie zamówienia (rezerwacja towaru)",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
                "total_cost": 20.00,
                "status": "ORDER_CONFIRMED"
            }
        })
        await asyncio.sleep(1.5)

        # Krok 5: Bilansowanie bazy w SQLite dla transakcji R1 <-> H2
        try:
            # 1. R1: odejmuje 20.00 PLN, dodaje 5 kg mąki
            if DB_PATHS["R1"].exists():
                with sqlite3.connect(DB_PATHS["R1"], timeout=3.0) as conn:
                    conn.execute("UPDATE financial_account SET balance = balance - 20.00, updated_at = CURRENT_TIMESTAMP WHERE account_id = 'R1_WALLET'")
                    conn.execute("UPDATE inventory SET quantity = quantity + 5 WHERE name = 'flour'")
                    conn.execute(
                        "INSERT INTO transactions (account_id, transaction_type, amount, currency, description) VALUES (?, ?, ?, ?, ?)",
                        ("R1_WALLET", "EXPENSE", 20.00, "PLN", "Zakup 5 kg mąki od Hurtownia 2 (Fallback po Reject w H1)")
                    )
                    conn.commit()

            # 2. H2: odejmuje 5 kg mąki, dopisuje 20.00 PLN do wallet_warehouse2
            if DB_PATHS["H2"].exists():
                with sqlite3.connect(DB_PATHS["H2"], timeout=3.0) as conn:
                    conn.execute("UPDATE warehouse2 SET quantity = quantity - 5 WHERE LOWER(name) = 'flour'")
                    last_bal_row = conn.execute("SELECT ballance FROM wallet_warehouse2 ORDER BY id DESC LIMIT 1").fetchone()
                    last_bal = float(last_bal_row[0]) if last_bal_row else 1000.0
                    conn.execute(
                        "INSERT INTO wallet_warehouse2 (sender_id, receiver_id, type, ballance) VALUES (?, ?, ?, ?)",
                        ("R1", "H2", "INCOME", last_bal + 20.00)
                    )
                    conn.commit()

            # Natychmiastowe odświeżenie UI
            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for CNP Reject & Fallback (R1, H2).")
        except Exception as e:
            logger.error(f"Error executing balance update in reject demo: {e}", exc_info=True)

        # Krok 5: Sprzedawca H2 dostarcza towar
        await broadcast_event({
            "source": "H2",
            "target": "R1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: receive_delivery: H2 dostarcza 5 kg mąki do R1 (rozliczono 20.00 PLN)",
            "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
            "total_cost": 20.00,
            "raw_json": {
                "sender_id": "H2",
                "receiver_id": "R1",
                "message_type": "DELIVERY",
                "item": {"name": "flour", "quantity": 5.0, "price": 4.00},
                "total_cost": 20.00,
                "status": "DELIVERED"
            }
        })

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())

    asyncio.create_task(run_reject_demo())
    return {"status": "started", "message": "Uruchomiono cykl CNP ze Ścieżką B (Odrzucenie przez sprzedawcę i Fallback kupującego)."}


@app.post("/api/simulate/h1-p1-flow")
async def api_simulate_h1_p1_flow():
    """
    KROK PO KROKU ZGODNIE ZE SPECYFIKACJĄ PROTOKOŁU DLA RELACJI HURTOWNIA ➔ PRODUCENT:
    Hurtownia H1 (Kupujący) i Producent P1 (Sprzedający):
    1. Kupujący H1 -> Sprzedający P1: check_availability (AVAILABILITY_REQUEST na 25 kg mąki)
    2. Sprzedający P1 -> Kupujący H1: availability-response (AVAILABILITY_RESPONSE)
    3. Kupujący H1 -> Sprzedający P1: request_offer (CALL_FOR_PROPOSAL)
    4. Sprzedający P1 -> Kupujący H1: response-offer (PROPOSAL, 2.50 PLN/kg -> 62.50 PLN)
    5. H1 ocenia ofertę i weryfikuje budżet w portfelu.
    6. Kupujący H1 -> Sprzedający P1: accept_offer (ACCEPT_PROPOSAL).
       Sprzedający P1 weryfikuje bazę i odpowiada: P1 -> H1: accept-offer (ACCEPT_PROPOSAL).
    7. Sprzedający P1 bilansuje bazę i realizuje dostawę: P1 -> H1: receive_delivery (DELIVERY).
       Kupujący H1 bilansuje portfel i magazyn.
    """
    async def run_h1_p1():
        # Krok 1: H1 sprawdza dostępność u P1
        await broadcast_event({
            "source": "H1",
            "target": "P1",
            "message_type": "AVAILABILITY_REQUEST",
            "summary": "Krok 1: check_availability(flour, 25 kg) -> P1",
            "item": {"name": "flour", "quantity": 25.0},
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "P1",
                "message_type": "AVAILABILITY_REQUEST",
                "item": {"name": "flour", "quantity": 25.0}
            }
        })
        await asyncio.sleep(1.8)

        # Krok 1b: P1 potwierdza dostępność
        await broadcast_event({
            "source": "P1",
            "target": "H1",
            "message_type": "AVAILABILITY_RESPONSE",
            "summary": "Krok 1: availability-response od P1 (is_available: true)",
            "item": {"name": "flour", "quantity": 25.0},
            "is_available": True,
            "raw_json": {
                "sender_id": "P1",
                "receiver_id": "H1",
                "message_type": "AVAILABILITY_RESPONSE",
                "item": {"name": "flour", "quantity": 25.0},
                "is_available": True
            }
        })
        await asyncio.sleep(1.8)

        # Krok 2: H1 wysyła zapytanie ofertowe (CFP) do P1
        await broadcast_event({
            "source": "H1",
            "target": "P1",
            "message_type": "CALL_FOR_PROPOSAL",
            "summary": "Krok 2: request_offer(flour, 25 kg) -> P1",
            "item": {"name": "flour", "quantity": 25.0},
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "P1",
                "message_type": "CALL_FOR_PROPOSAL",
                "item": {"name": "flour", "quantity": 25.0}
            }
        })
        await asyncio.sleep(1.8)

        # Krok 2b: P1 składa ofertę z rabatem hurtowym
        await broadcast_event({
            "source": "P1",
            "target": "H1",
            "message_type": "PROPOSAL",
            "summary": "Krok 2: response-offer od P1: 2.50 PLN/kg (Razem: 62.50 PLN)",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {
                "sender_id": "P1",
                "receiver_id": "H1",
                "message_type": "PROPOSAL",
                "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
                "total_cost": 62.50
            }
        })
        await asyncio.sleep(2.0)

        # Krok 4: H1 akceptuje ofertę u P1 (accept_offer)
        await broadcast_event({
            "source": "H1",
            "target": "P1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: accept_offer u Producenta P1 (62.50 PLN)",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {
                "sender_id": "H1",
                "receiver_id": "P1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
                "total_cost": 62.50
            }
        })
        await asyncio.sleep(1.8)

        # Krok 4b: P1 potwierdza akceptację
        await broadcast_event({
            "source": "P1",
            "target": "H1",
            "message_type": "ACCEPT_PROPOSAL",
            "summary": "Krok 4: Producent P1 potwierdza przyjęcie zamówienia (rezerwacja)",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {
                "sender_id": "P1",
                "receiver_id": "H1",
                "message_type": "ACCEPT_PROPOSAL",
                "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
                "total_cost": 62.50,
                "status": "ORDER_CONFIRMED"
            }
        })
        await asyncio.sleep(1.5)

        # Krok 5: Bilansowanie bazy danych u P1 i H1
        try:
            # 1. P1: odejmuje 25 kg mąki, rejestruje sprzedaż w sales_transactions
            if DB_PATHS["P1"].exists():
                with sqlite3.connect(DB_PATHS["P1"], timeout=3.0) as conn:
                    conn.execute("UPDATE products SET stock_quantity = stock_quantity - 25.0 WHERE product_code = 'flour'")
                    cur_p1 = conn.execute(
                        "INSERT INTO sales_transactions (product_code, quantity, unit_price, total_cost, buyer_id, transaction_date) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                        ("flour", 25.0, 2.50, 62.50, "H1")
                    )
                    last_seen_db_ids["P1"] = max(last_seen_db_ids["P1"], cur_p1.lastrowid or 0)
                    conn.commit()

            # 2. H1: dodaje 25 kg mąki do produktów, odejmuje 62.50 PLN z konta, rejestruje transakcję
            if DB_PATHS["H1"].exists():
                with sqlite3.connect(DB_PATHS["H1"], timeout=3.0) as conn:
                    conn.execute("UPDATE account SET balance = balance - 62.50 WHERE id = 1")
                    conn.execute("UPDATE products SET quantity = quantity + 25 WHERE name = 'flour'")
                    conn.execute(
                        "INSERT INTO transactions (partner, type, item_name, quantity, total_cost) VALUES (?, ?, ?, ?, ?)",
                        ("P1", "PURCHASE", "flour", 25, 62.50)
                    )
                    conn.commit()

            updated_state = get_node_details()
            await broadcast_node_state(updated_state)
            logger.info("Real balance & inventory updated for H1 -> P1 procurement.")
        except Exception as e:
            logger.error(f"Error executing H1 -> P1 balance update: {e}", exc_info=True)

        # Krok 5: Producent P1 dostarcza towar do H1
        await broadcast_event({
            "source": "P1",
            "target": "H1",
            "message_type": "DELIVERY",
            "summary": "Krok 5: receive_delivery: P1 dostarcza 25 kg mąki do H1 (rozliczono 62.50 PLN)",
            "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
            "total_cost": 62.50,
            "raw_json": {
                "sender_id": "P1",
                "receiver_id": "H1",
                "message_type": "DELIVERY",
                "item": {"name": "flour", "quantity": 25.0, "price": 2.50},
                "total_cost": 62.50,
                "status": "DELIVERED"
            }
        })

        await asyncio.sleep(0.5)
        await broadcast_node_state(get_node_details())

    asyncio.create_task(run_h1_p1())
    return {"status": "started", "message": "Uruchomiono 5-etapowy proces CNP dla Hurtownia H1 ➔ Producent P1."}


# Serve static web frontend
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
