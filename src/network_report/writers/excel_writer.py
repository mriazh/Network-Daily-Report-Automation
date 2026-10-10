"""Excel Monthly Workbook Writer."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

logger = logging.getLogger(__name__)


def write_daily_excel(
    template_path: Path,
    output_path: Path,
    day_number: int,
    payload: dict[str, Any],
) -> bool:
    sheet_name = f"{day_number:02d}"
    if output_path.exists():
        wb = load_workbook(output_path)
    else:
        # Copy template so all 31 pre-formatted sheets exist
        shutil.copy2(template_path, output_path)
        wb = load_workbook(output_path)

    if sheet_name not in wb.sheetnames:
        logger.error("Sheet %s not found in workbook.", sheet_name)
        return False

    ws = wb[sheet_name]

    def put(row: int, col: int, val: Any) -> None:
        if val is None or val == "":
            return
        cell = ws.cell(row=row, column=col)
        if not isinstance(cell, MergedCell):
            cell.value = val

    # Header Date
    date_str = payload.get("date_str")
    if date_str:
        put(4, 3, date_str)

    # Section A: IoT
    iot = payload.get("iot", {})
    put(10, 5, iot.get("status", "Normal"))
    put(11, 2, "Total Usage")
    put(11, 4, iot.get("total_usage_gb"))
    put(12, 4, iot.get("active_sessions"))

    # Top Daily 5
    for idx, (site, val) in enumerate(iot.get("top_daily", [])[:5]):
        put(16 + idx, 2, site)
        put(16 + idx, 4, val)
        put(16 + idx, 5, date_str)

    # Top Periodic 5
    for idx, (site, val) in enumerate(iot.get("top_periodic", [])[:5]):
        put(23 + idx, 2, site)
        put(23 + idx, 4, val)
        put(23 + idx, 5, iot.get("periodic_range_str", ""))

    # Section B: MRTG Circuits
    mrtg = payload.get("mrtg", {})

    # ASTINET: rows 32-37
    astinet = mrtg.get("ASTINET", [])
    for idx, circuit in enumerate(astinet[:6]):
        row = 32 + idx
        put(row, 4, circuit.get("capacity_str"))     # Capacity col D
        put(row, 5, circuit.get("status"))           # Status col E
        put(row, 6, circuit.get("utilization_pct"))  # Utilization % col F
        put(row, 7, circuit.get("remarks"))          # Remarks col G

    # Metro-E: rows 42-45
    metro = mrtg.get("Metro-E", [])
    for idx, circuit in enumerate(metro[:4]):
        row = 42 + idx
        put(row, 4, circuit.get("capacity_str"))     # Capacity col D
        put(row, 5, circuit.get("status"))
        put(row, 6, circuit.get("utilization_pct"))
        put(row, 7, circuit.get("remarks"))

    # VPN IP: rows 50-56
    vpn = mrtg.get("VPN IP", [])
    for idx, circuit in enumerate(vpn[:7]):
        row = 50 + idx
        put(row, 4, circuit.get("capacity_str"))     # Capacity col D
        put(row, 5, circuit.get("status"))
        put(row, 6, circuit.get("utilization_pct"))
        put(row, 7, circuit.get("remarks"))

    # Telkom Indibiz: row 61
    indibiz = mrtg.get("Telkom Indibiz", [])
    for idx, circuit in enumerate(indibiz[:1]):
        row = 61 + idx
        put(row, 4, circuit.get("capacity_str"))     # Capacity col D
        put(row, 5, circuit.get("status"))
        put(row, 6, circuit.get("utilization_pct"))
        put(row, 7, circuit.get("remarks"))

    # Section C.1: Nexthop Ping (rows 69-75)
    ping_results = payload.get("ping", [])
    for idx, ping in enumerate(ping_results[:7]):
        row = 69 + idx
        put(row, 3, "-")
        put(row, 5, round(ping.get("avg_latency_ms"), 2) if ping.get("avg_latency_ms") is not None else 0.0)
        put(row, 6, ping.get("packet_loss_pct") if ping.get("packet_loss_pct") is not None else 0.0)
        put(row, 7, ping.get("status"))
        put(row, 8, "-" if ping.get("status") == "Normal" else "Kendala koneksi")

    # Section C.2: PRTG
    prtg = payload.get("prtg", {})
    put(80, 4, prtg.get('up'))
    put(80, 5, 'Normal')
    put(80, 6, '-')
    put(81, 4, prtg.get('paused'))
    put(81, 5, 'Monitoring' if prtg.get('paused', 0) > 0 else 'Normal')
    put(81, 6, 'Sensor paused by admin' if prtg.get('paused', 0) > 0 else '-')

    # CPU & Mem
    for idx, (dev, val) in enumerate(payload.get("cpu", [])[:10]):
        put(86 + idx, 2, dev)
        put(86 + idx, 4, val)
        put(86 + idx, 6, "Normal" if val < 60.0 else "Warning")

    for idx, (dev, val) in enumerate(payload.get("memory", [])[:10]):
        put(100 + idx, 2, dev)
        put(100 + idx, 4, val)
        put(100 + idx, 6, "Normal" if val < 70.0 else "Monitoring")

    # Uptime
    uptime = payload.get("uptime", {})
    put(114, 2, "Device Uptime")
    put(114, 4, uptime.get("snmp"))
    put(114, 5, uptime.get("icmp"))
    put(114, 6, uptime.get("https"))
    put(114, 7, f"Device Uptime {uptime.get('device')}%")

    # Analisa
    put(119, 4, payload.get("analysis_cpu"))
    put(120, 4, payload.get("analysis_mem"))

    # AP & SSID
    ap = payload.get("ap", {})
    put(126, 5, ap.get("normal"))
    put(127, 5, ap.get("fault"))
    put(128, 5, ap.get("users"))
    put(133, 4, ap.get("indoor_ok"))
    put(134, 4, ap.get("outdoor_ok"))
    put(134, 5, ap.get("outdoor_fault"))
    if ap.get("fault_names"):
        put(134, 6, f"AP Fault: {', '.join(ap.get('fault_names'))}")

    # SSID
    for idx, (ssid, count) in enumerate(ap.get("ssid_distribution", {}).items()):
        put(139 + idx, 5, count)

    # Section E: Modem Orbit (rows 152-164)
    orbit_modems = payload.get("orbit", [])
    row = 152
    for modem in orbit_modems:
        packages = modem.get("packages", [])
        for pkg in packages:
            if row > 163:
                break
            put(row, 4, pkg.get("remaining_gb"))   # Remaining Quota col D
            put(row, 5, pkg.get("total_gb"))       # Total Quota col E
            put(row, 6, pkg.get("expiry_str"))     # Valid Until col F
            # Status: derive from remaining/total and expiry
            remaining = pkg.get("remaining_gb", 0)
            total = pkg.get("total_gb", 0)
            if total > 0:
                pct = (remaining / total) * 100
                if pct <= 0:
                    status = "Expired"
                elif pct <= 10:
                    status = "Expired Soon"
                else:
                    status = "Active"
            else:
                status = "Unknown"
            put(row, 7, status)                    # Status col G
            row += 1

    # Section F: Highlights
    highlights = payload.get("highlights", {})
    ap = payload.get("ap", {})

    # High Traffic: rows 170-173
    high_traffic = highlights.get("high_traffic", [])
    for idx, ht in enumerate(high_traffic[:4]):
        row = 170 + idx
        put(row, 2, ht.get("name"))
        put(row, 5, ht.get("remarks") or "Monitoring utilisasi bandwidth")
        put(row, 8, "Open" if ht.get("status") == "High Traffic" else "Normal")

    # Hardware Fault: row 177
    hardware_fault = ""
    if ap.get("fault_count", 0) > 0:
        hardware_fault = f"AP Fault : {ap.get('fault_count', 0)} ea."
        if ap.get("fault_names"):
            hardware_fault += f" ({', '.join(ap.get('fault_names'))})"
    elif ap.get("outdoor_fault", 0) > 0:
        hardware_fault = f"AP Outdoor Fault : {ap.get('outdoor_fault', 0)} ea."
        if ap.get("fault_names"):
            hardware_fault += f" ({', '.join(ap.get('fault_names'))})"

    if hardware_fault:
        put(177, 2, hardware_fault)
        put(177, 5, "Investigasi tim on-duty / vendor")
        put(177, 8, "Open")

    # Problem Open: row 183 - Leave completely EMPTY (do NOT write anything)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    logger.info("Successfully updated sheet %s in %s", sheet_name, output_path)
    return True