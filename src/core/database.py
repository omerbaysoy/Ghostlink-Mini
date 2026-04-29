import sqlite3
import os
import time
from .config import DB_PATH

INIT_ERROR = None

def _db_dir():
    return os.path.dirname(DB_PATH)

def _permission_message():
    return (
        f"Database is not writable at {DB_PATH}. "
        "Run sudo ./setup.sh --update from the project directory, or run this command with sudo."
    )

def _ensure_writable_database():
    if not os.path.isdir(_db_dir()) or not os.access(_db_dir(), os.W_OK):
        raise RuntimeError(_permission_message())
    if os.path.exists(DB_PATH) and not os.access(DB_PATH, os.W_OK):
        raise RuntimeError(_permission_message())

def get_connection():
    try:
        os.makedirs(_db_dir(), exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"{_permission_message()} ({e})") from e

    if not os.access(_db_dir(), os.W_OK):
        if os.path.exists(DB_PATH) and os.access(DB_PATH, os.R_OK):
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        raise RuntimeError(_permission_message())

    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.Error as e:
        raise RuntimeError(f"Could not open database at {DB_PATH}: {e}") from e
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Networks Table (Scan results)
    c.execute('''
        CREATE TABLE IF NOT EXISTS networks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ssid TEXT,
            bssid TEXT,
            channel INTEGER,
            signal INTEGER,
            encryption TEXT,
            interface TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Pentests Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS pentests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_ssid TEXT,
            target_bssid TEXT,
            adapter TEXT,
            tool_used TEXT,
            result_status TEXT,
            log_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Credentials Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pentest_id INTEGER,
            ssid TEXT,
            bssid TEXT,
            password TEXT,
            adapter TEXT,
            connection_status TEXT DEFAULT 'Not Connected',
            ap_status TEXT DEFAULT 'Inactive',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(pentest_id) REFERENCES pentests(id)
        )
    ''')

    conn.commit()
    conn.close()

def save_scan_result(ssid, bssid, channel, signal, encryption, interface):
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO networks (ssid, bssid, channel, signal, encryption, interface)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ssid, bssid, channel, signal, encryption, interface))
    conn.commit()
    conn.close()

def save_pentest_job(ssid, bssid, adapter, tool, status, log_path):
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO pentests (target_ssid, target_bssid, adapter, tool_used, result_status, log_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ssid, bssid, adapter, tool, status, log_path))
    last_id = c.lastrowid
    conn.commit()
    conn.close()
    return last_id

def save_credential(pentest_id, ssid, bssid, password, adapter):
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO credentials (pentest_id, ssid, bssid, password, adapter)
        VALUES (?, ?, ?, ?, ?)
    ''', (pentest_id, ssid, bssid, password, adapter))
    conn.commit()
    conn.close()

def get_credentials():
    try:
        readonly = os.path.exists(DB_PATH) and (
            not os.access(_db_dir(), os.W_OK) or not os.access(DB_PATH, os.W_OK)
        )
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM credentials ORDER BY timestamp DESC')
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []

def get_networks():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM networks ORDER BY timestamp DESC')
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []

def get_pentests():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM pentests ORDER BY timestamp DESC')
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []

def update_connection_status(cred_id, status):
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE credentials SET connection_status = ? WHERE id = ?', (status, cred_id))
    conn.commit()
    conn.close()

def update_ap_status(cred_id, status):
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE credentials SET ap_status = ? WHERE id = ?', (status, cred_id))
    conn.commit()
    conn.close()

def get_db_stats():
    if INIT_ERROR and not os.path.exists(DB_PATH):
        return {
            "health": "Unavailable",
            "path": DB_PATH,
            "message": str(INIT_ERROR),
            "total_networks": 0,
            "total_pentests": 0,
            "total_creds": 0,
            "latest_pentests": []
        }

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM networks')
        total_networks = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM pentests')
        total_pentests = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM credentials')
        total_creds = c.fetchone()[0]

        c.execute('SELECT * FROM pentests ORDER BY timestamp DESC LIMIT 5')
        latest_pentests = [dict(row) for row in c.fetchall()]
        conn.close()

        return {
            "health": "Read-only" if readonly else "OK",
            "path": DB_PATH,
            "message": "" if not readonly else "Database is readable but not writable by this user.",
            "total_networks": total_networks,
            "total_pentests": total_pentests,
            "total_creds": total_creds,
            "latest_pentests": latest_pentests
        }
    except Exception as e:
        return {
            "health": "Unavailable",
            "path": DB_PATH,
            "message": str(e),
            "total_networks": 0,
            "total_pentests": 0,
            "total_creds": 0,
            "latest_pentests": []
        }

# Initialize on import
try:
    init_db()
except Exception as e:
    INIT_ERROR = e
