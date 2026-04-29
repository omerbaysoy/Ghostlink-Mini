import os
import json
from pathlib import Path

# Base Paths
GHOSTLINK_DIR = "/etc/ghostlink"
GHOSTLINK_LIB_DIR = "/var/lib/ghostlink"
GHOSTLINK_LOG_DIR = "/var/log/ghostlink"

DB_PATH = os.path.join(GHOSTLINK_LIB_DIR, "ghostlink.db")
CONFIG_PATH = os.path.join(GHOSTLINK_DIR, "config.json")
ADAPTER_MAP_PATH = os.path.join(GHOSTLINK_DIR, "adapters.json")

# Ensure paths exist (mostly for local testing without root, though setup.sh makes these)
def ensure_paths():
    for p in [GHOSTLINK_DIR, GHOSTLINK_LIB_DIR, GHOSTLINK_LOG_DIR]:
        try:
            os.makedirs(p, exist_ok=True)
        except PermissionError:
            pass # We might not be root, handle gracefully if possible

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(config):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

def load_adapter_map():
    if not os.path.exists(ADAPTER_MAP_PATH):
        return {}
    try:
        with open(ADAPTER_MAP_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_adapter_map(adapter_map):
    try:
        with open(ADAPTER_MAP_PATH, "w") as f:
            json.dump(adapter_map, f, indent=4)
    except Exception as e:
        print(f"Error saving adapter map: {e}")

ensure_paths()
