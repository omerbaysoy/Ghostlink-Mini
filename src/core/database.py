import sqlite3
import os
import time
from .config import DB_PATH

def get_connection():
    # If the directory doesn't exist, try to make it
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO networks (ssid, bssid, channel, signal, encryption, interface)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ssid, bssid, channel, signal, encryption, interface))
    conn.commit()
    conn.close()

def save_pentest_job(ssid, bssid, adapter, tool, status, log_path):
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
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO credentials (pentest_id, ssid, bssid, password, adapter)
        VALUES (?, ?, ?, ?, ?)
    ''', (pentest_id, ssid, bssid, password, adapter))
    conn.commit()
    conn.close()

def get_credentials():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM credentials ORDER BY timestamp DESC')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_networks():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM networks ORDER BY timestamp DESC')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_pentests():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM pentests ORDER BY timestamp DESC')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_connection_status(cred_id, status):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE credentials SET connection_status = ? WHERE id = ?', (status, cred_id))
    conn.commit()
    conn.close()

def update_ap_status(cred_id, status):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE credentials SET ap_status = ? WHERE id = ?', (status, cred_id))
    conn.commit()
    conn.close()

def get_db_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM networks')
    total_networks = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM pentests')
    total_pentests = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM credentials')
    total_creds = c.fetchone()[0]
    
    # Latest records
    c.execute('SELECT * FROM pentests ORDER BY timestamp DESC LIMIT 5')
    latest_pentests = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return {
        "health": "OK" if os.path.exists(DB_PATH) else "Missing",
        "total_networks": total_networks,
        "total_pentests": total_pentests,
        "total_creds": total_creds,
        "latest_pentests": latest_pentests
    }

# Initialize on import
try:
    init_db()
except Exception as e:
    pass # Handle gracefully if we are not root and dir doesn't exist
