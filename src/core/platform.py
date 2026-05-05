import os
import platform as py_platform
import shlex
import subprocess

from .config import PLATFORM_PROFILES


def _read_text(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace").replace("\x00", "").strip()
    except OSError:
        return ""


def _run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", 1
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    return "\n".join(part for part in [stdout, stderr] if part), result.returncode


def _parse_os_release():
    data = {}
    text = _read_text("/etc/os-release")
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


def _cpuinfo_value(name):
    text = _read_text("/proc/cpuinfo")
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == name.lower():
            return value.strip()
    return ""


def _raspberry_pi_model():
    model = _read_text("/proc/device-tree/model")
    if model:
        return model
    model = _cpuinfo_value("Model")
    if model:
        return model
    hardware = _cpuinfo_value("Hardware")
    if hardware.lower().startswith("bcm"):
        return "Raspberry Pi (model unknown)"
    return ""


def _dpkg_architecture():
    out, code = _run_cmd("dpkg --print-architecture")
    if code == 0 and out:
        return out.splitlines()[0].strip()
    return py_platform.machine() or "unknown"


def _classify_profile(model):
    lowered = (model or "").lower()
    if "raspberry pi" not in lowered:
        return "debian_sbc"
    if "zero 2" in lowered:
        return "rpi_zero_2_w"
    if "zero" in lowered:
        return "rpi_zero_w"
    if "raspberry pi 5" in lowered:
        return "rpi_5"
    if "raspberry pi 4" in lowered:
        return "rpi_4"
    if "raspberry pi 3 model b plus" in lowered or "raspberry pi 3b+" in lowered:
        return "rpi_3b_plus"
    if "raspberry pi 3 model b" in lowered:
        return "rpi_3b"
    if "raspberry pi 3" in lowered:
        return "unknown_rpi"
    if "raspberry pi 2" in lowered:
        return "rpi_2"
    if "raspberry pi model" in lowered or "raspberry pi 1" in lowered:
        return "rpi_1"
    return "unknown_rpi"


def detect_platform():
    os_release = _parse_os_release()
    model = _raspberry_pi_model()
    profile = _classify_profile(model)
    metadata = PLATFORM_PROFILES.get(profile, PLATFORM_PROFILES["debian_sbc"])
    codename = (
        os_release.get("VERSION_CODENAME")
        or os_release.get("UBUNTU_CODENAME")
        or os_release.get("DEBIAN_CODENAME")
        or "unknown"
    )

    return {
        "model": model or "Generic Debian-based SBC",
        "profile": profile,
        "profile_label": metadata["label"],
        "support": metadata["support"],
        "notes": metadata["notes"],
        "pretty_name": os_release.get("PRETTY_NAME") or py_platform.platform(),
        "codename": codename,
        "os_id": os_release.get("ID", "unknown"),
        "os_id_like": os_release.get("ID_LIKE", ""),
        "architecture": _dpkg_architecture(),
        "machine": py_platform.machine() or "unknown",
        "kernel": py_platform.release() or "unknown",
        "zram_mb": metadata["zram_mb"],
        "gpu_mem_mb": metadata["gpu_mem_mb"],
        "overclock": metadata["overclock"],
    }


def is_raspberry_pi_profile(profile):
    return profile.startswith("rpi_") or profile == "unknown_rpi"


def _boot_config_path():
    for path in ["/boot/firmware/config.txt", "/boot/config.txt"]:
        if os.path.exists(path):
            return path
    return None


def _boot_config_values():
    path = _boot_config_path()
    values = {}
    if not path:
        return path, values
    text = _read_text(path)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return path, values


def get_zram_status():
    swaps = _read_text("/proc/swaps")
    zram_lines = [line for line in swaps.splitlines()[1:] if "zram" in line]
    if zram_lines:
        total_kb = 0
        for line in zram_lines:
            parts = line.split()
            if len(parts) >= 3 and parts[2].isdigit():
                total_kb += int(parts[2])
        total_mb = total_kb // 1024 if total_kb else 0
        size = f"{total_mb} MB" if total_mb else "size unknown"
        return f"Active ({size}, {len(zram_lines)} device(s))"

    config = _read_text("/etc/default/zramswap")
    configured = []
    for key in ["ALGO", "PERCENT", "SIZE"]:
        for line in config.splitlines():
            if line.startswith(f"{key}="):
                configured.append(line.strip())
                break
    if configured:
        return "Configured but inactive/not detected (" + ", ".join(configured) + ")"
    return "Inactive/not detected"


def get_overclock_status(platform_info=None):
    info = platform_info or detect_platform()
    profile = info["profile"]
    if not is_raspberry_pi_profile(profile):
        return "Not applicable on generic Debian SBC"

    path, values = _boot_config_values()
    if not path:
        return "Unknown (Raspberry Pi boot config not found)"

    keys = ["arm_freq", "core_freq", "gpu_freq", "over_voltage", "over_voltage_delta"]
    configured = [f"{key}={values[key]}" for key in keys if key in values]
    if configured:
        return f"Configured in {path}: " + ", ".join(configured)
    return f"Not configured in boot config; profile default: {info['overclock']}"


def get_gpu_memory_status(platform_info=None):
    info = platform_info or detect_platform()
    profile = info["profile"]
    if not is_raspberry_pi_profile(profile):
        return "Not applicable on generic Debian SBC"

    path, values = _boot_config_values()
    target = info.get("gpu_mem_mb")
    if not path:
        return "Unknown (Raspberry Pi boot config not found)"
    if "gpu_mem" in values:
        return f"Configured in {path}: gpu_mem={values['gpu_mem']} MB"
    if target:
        return f"Not configured; setup target minimum is {target} MB"
    return "Not configured"


def get_fan_config_status(platform_info=None):
    info = platform_info or detect_platform()
    if info["profile"] != "rpi_5":
        return "Not applicable (not Raspberry Pi 5)"
    path = _boot_config_path()
    if not path:
        return "Unknown (boot config not found)"
    text = _read_text(path)
    if "fan_temp0=" in text:
        return f"Configured in {path}"
    return f"Not configured in {path}; setup will apply Active Cooler profile"


def _command_exists(name):
    _, code = _run_cmd(f"command -v {shlex.quote(name)}")
    return code == 0


def _module_available(module):
    _, code = _run_cmd(f"modinfo {shlex.quote(module)}")
    return code == 0


def get_driver_compatibility_warnings(platform_info=None):
    info = platform_info or detect_platform()
    warnings = []

    if os.name != "posix":
        warnings.append("Driver checks are only meaningful on Linux; current host is not POSIX/Linux.")
        return warnings

    if info["codename"] not in {"bookworm", "trixie", "unknown"}:
        warnings.append(
            f"OS codename is {info['codename']}; Chapter 1 targets Raspberry Pi OS/Debian Bookworm and Trixie."
        )

    headers_path = f"/lib/modules/{info['kernel']}/build"
    if not os.path.isdir(headers_path):
        warnings.append(f"Kernel headers are missing at {headers_path}; DKMS driver builds may fail.")

    if not _command_exists("dkms"):
        warnings.append("dkms is not installed; RTL8812AU, RTL88x2BU, and RTL8188EUS builds need it.")

    rtl8812au_modules = ["88XXau", "8812au", "rtw_8812au", "rtw88_8812au", "rtl8xxxu"]
    if not any(_module_available(module) for module in rtl8812au_modules):
        warnings.append("No RTL8812AU candidate module is visible via modinfo.")

    if not _module_available("mt76x2u"):
        warnings.append("mt76x2u is not visible via modinfo; MT7612U may need firmware/kernel support.")

    rtl88x2bu_modules = ["rtw_8822bu", "rtw88_8822bu", "88x2bu"]
    if not any(_module_available(module) for module in rtl88x2bu_modules):
        warnings.append("No RTL88x2BU AP-role candidate module is visible via modinfo.")

    rtl8188eus_modules = ["8188eu", "r8188eu", "rtl8xxxu"]
    if not any(_module_available(module) for module in rtl8188eus_modules):
        warnings.append("No RTL8188EUS backup-role candidate module is visible via modinfo.")

    return warnings
