import os
import json
from pathlib import Path

# Base Paths
GHOSTLINK_DIR = "/etc/ghostlink"

# Known USB vendor:product IDs for adapter identification
RTL8812AU_USB_IDS = frozenset({"0bda:8812"})
RTL88X2BU_USB_IDS = frozenset({"0bda:b812"})
RTL8188EUS_USB_IDS = frozenset({"2357:010c"})
MT7612U_USB_IDS = frozenset({
    "0e8d:7612",   # MediaTek MT7612U reference design (Alfa AWUS036ACM, etc.)
    "0e8d:761a",   # MediaTek MT7662U (uses same mt76x2u driver)
    "2001:3a02",   # D-Link DWA-182 rev D
    "0b05:17d1",   # ASUS USB-AC55
    "148f:7612",   # Ralink/MediaTek MT7612U OEM
    "13b1:003e",   # Linksys WUSB6300 v2
})

PLATFORM_PROFILES = {
    "rpi_zero_w": {
        "label": "Raspberry Pi Zero W",
        "support": "tested",
        "zram_mb": 512,
        "gpu_mem_mb": 16,
        "overclock": "stock-safe baseline; no automatic CPU overclock",
        "notes": "armv6/low-memory profile; USB/power headroom is limited.",
    },
    "rpi_zero_2_w": {
        "label": "Raspberry Pi Zero 2 W",
        "support": "tested",
        "zram_mb": 1024,
        "gpu_mem_mb": 16,
        "overclock": "safe mild profile: arm_freq=1100",
        "notes": "low-memory quad-core profile; keep adapter power modest.",
    },
    "rpi_1": {
        "label": "Raspberry Pi 1",
        "support": "supported/untested",
        "zram_mb": 512,
        "gpu_mem_mb": 16,
        "overclock": "not applied by default",
        "notes": "best with lightweight workflows; external powered USB is recommended.",
    },
    "rpi_2": {
        "label": "Raspberry Pi 2",
        "support": "supported/untested",
        "zram_mb": 1024,
        "gpu_mem_mb": 16,
        "overclock": "not applied by default",
        "notes": "supported but not yet validated for Chapter 1.",
    },
    "rpi_3b": {
        "label": "Raspberry Pi 3B",
        "support": "tested",
        "zram_mb": 1024,
        "gpu_mem_mb": 16,
        "overclock": "safe mild profile: arm_freq=1300, core_freq=500, over_voltage=2",
        "notes": "USB 2.0 and shared bus constraints apply.",
    },
    "rpi_3b_plus": {
        "label": "Raspberry Pi 3 Model B+",
        "support": "supported/untested",
        "zram_mb": 1024,
        "gpu_mem_mb": 16,
        "overclock": "not applied by default (3B+ detected; set manually if desired)",
        "notes": "Pi 3B+ similar to 3B; auto-OC not applied to avoid 3B+ stability regression.",
    },
    "rpi_4": {
        "label": "Raspberry Pi 4",
        "support": "supported/untested",
        "zram_mb": 2048,
        "gpu_mem_mb": 16,
        "overclock": "not applied by default",
        "notes": "supported but not yet validated for Chapter 1.",
    },
    "rpi_5": {
        "label": "Raspberry Pi 5",
        "support": "tested",
        "zram_mb": 2048,
        "gpu_mem_mb": None,
        "overclock": "safe mild profile: arm_freq=2600",
        "notes": "Pi 5-only fan and PCIe tuning may be applied by setup; gpu_mem is firmware-managed.",
    },
    "unknown_rpi": {
        "label": "Unknown Raspberry Pi",
        "support": "supported/untested",
        "zram_mb": 1024,
        "gpu_mem_mb": None,
        "overclock": "not applied by default",
        "notes": "Raspberry Pi detected, but model did not match a named profile.",
    },
    "debian_sbc": {
        "label": "Generic Debian-based SBC",
        "support": "best-effort",
        "zram_mb": 1024,
        "gpu_mem_mb": None,
        "overclock": "not applicable",
        "notes": "Pi-specific boot, fan, PCIe, and raspi-config steps are skipped.",
    },
}

GHOSTLINK_LIB_DIR = "/var/lib/ghostlink"
GHOSTLINK_LOG_DIR = "/var/log/ghostlink"

DB_PATH = os.path.join(GHOSTLINK_LIB_DIR, "ghostlink.db")
CONFIG_PATH = os.path.join(GHOSTLINK_DIR, "config.json")
ADAPTER_MAP_PATH = os.path.join(GHOSTLINK_DIR, "adapters.json")

def ensure_paths():
    errors = []
    for p in [GHOSTLINK_DIR, GHOSTLINK_LIB_DIR, GHOSTLINK_LOG_DIR]:
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as e:
            errors.append(f"{p}: {e}")
    return errors

def path_status(path):
    p = Path(path)
    return {
        "path": str(p),
        "exists": p.exists(),
        "readable": os.access(path, os.R_OK) if p.exists() else False,
        "writable": os.access(path, os.W_OK) if p.exists() else False,
    }

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
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
            f.write("\n")
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
        os.makedirs(os.path.dirname(ADAPTER_MAP_PATH), exist_ok=True)
        with open(ADAPTER_MAP_PATH, "w") as f:
            json.dump(adapter_map, f, indent=4)
            f.write("\n")
        return True
    except Exception as e:
        return False

ensure_paths()
