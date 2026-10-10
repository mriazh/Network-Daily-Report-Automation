"""MRTG Network Connectivity Collector."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CircuitStatus:
    name: str
    sid: str
    capacity_str: str
    capacity_mbps: float
    max_mbps: float | None
    utilization_pct: float | None
    over_pct: float | None
    over_mbps: float | None
    direction: str | None
    status: str  # "Normal" / "High Traffic" / "Fault"
    remarks: str


def parse_capacity_to_mbps(cap_str: str) -> float:
    cap = cap_str.strip().upper()
    if "GB" in cap:
        num = float(cap.replace("GB", "").strip())
        return num * 1024.0
    if "MB" in cap:
        return float(cap.replace("MB", "").strip())
    return 10.0


def parse_mrtg_speed_mbps(text: str | None) -> float:
    """Parses MRTG speed string like '12.31 M', '745.11 k', or '623.25' into numeric Mbps."""
    if not text or text == "-" or "n/a" in str(text).lower():
        return 0.0
    val_clean = str(text).replace(",", ".").strip()
    match = re.search(r"([\d.]+)\s*([kKmMgG])?", val_clean)
    if not match:
        return 0.0
    num = float(match.group(1))
    unit = (match.group(2) or "").upper()
    if unit == "K":
        return num / 1000.0
    elif unit == "M":
        return num
    elif unit == "G":
        return num * 1000.0
    else:
        return num / 1_000_000.0  # Raw bps without unit


def evaluate_circuit(
    name: str,
    sid: str,
    capacity_str: str,
    max_in_mbps: float | None = None,
    max_out_mbps: float | None = None,
    threshold_pct: float = 100.0,
) -> CircuitStatus:
    cap_mbps = parse_capacity_to_mbps(capacity_str)
    in_val = max_in_mbps or 0.0
    out_val = max_out_mbps or 0.0
    highest = max(in_val, out_val)

    if highest <= 0.0:
        return CircuitStatus(
            name=name,
            sid=sid,
            capacity_str=capacity_str,
            capacity_mbps=cap_mbps,
            max_mbps=None,
            utilization_pct=None,
            over_pct=None,
            over_mbps=None,
            direction=None,
            status="Normal",
            remarks="-",
        )

    util_pct = (highest / cap_mbps) * 100.0
    if util_pct > threshold_pct:
        over = round(util_pct - 100.0, 2)
        over_mbps = round(highest - cap_mbps, 2)
        direction = "inbound" if in_val >= out_val else "outbound"
        status = "High Traffic"
        remarks = f"High Traffic ({direction} >{over_mbps:.2f} MB / >{over:.2f}%)"
        return CircuitStatus(
            name=name,
            sid=sid,
            capacity_str=capacity_str,
            capacity_mbps=cap_mbps,
            max_mbps=highest,
            utilization_pct=round(util_pct, 2),
            over_pct=over,
            over_mbps=over_mbps,
            direction=direction,
            status=status,
            remarks=remarks,
        )
    else:
        status = "Normal"
        remarks = "-"
        return CircuitStatus(
            name=name,
            sid=sid,
            capacity_str=capacity_str,
            capacity_mbps=cap_mbps,
            max_mbps=highest,
            utilization_pct=round(util_pct, 2),
            over_pct=None,
            over_mbps=None,
            direction=None,
            status=status,
            remarks=remarks,
        )


def load_mrtg_ocr_data(
    report_root: Path | None,
    date_compact: str,
) -> dict[str, dict[str, float]]:
    """Loads parsed OCR data from MRTG-Monthly-Report-ocr-YYYY-MM.ocr-audit.jsonl."""
    results: dict[str, dict[str, float]] = {}
    if not report_root:
        return results

    ym = f"{date_compact[:4]}-{date_compact[4:6]}"
    audit_files = [
        report_root / f"MRTG-Monthly-Report-ocr-{ym}.ocr-audit.jsonl",
        report_root / "reports" / f"MRTG-Monthly-Report-ocr-{ym}.ocr-audit.jsonl",
    ]
    # Check sibling MRTG-TelkomCare-Report-Automation if not found
    for d in Path(__file__).resolve().parents[4].glob("*MRTG-TelkomCare-Report-Automation"):
        audit_files.append(d / "output" / "reports" / f"MRTG-Monthly-Report-ocr-{ym}.ocr-audit.jsonl")

    target_file = next((f for f in audit_files if f.exists()), None)
    if not target_file:
        logger.info("No MRTG OCR audit file found for %s", ym)
        return results

    logger.info("Loading MRTG OCR results from %s for date %s", target_file, date_compact)
    with open(target_file, mode="r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("date") == date_compact:
                    sid = str(entry.get("target_id", "")).strip()
                    vals = entry.get("final_values", {})
                    results[sid] = {
                        "in_mbps": parse_mrtg_speed_mbps(vals.get("Inbound_Maximum")),
                        "out_mbps": parse_mrtg_speed_mbps(vals.get("Outbound_Maximum")),
                    }
            except Exception:
                continue

    return results


def query_indibiz_traffic_db(db_path: Path | None, date_iso: str) -> tuple[float | None, float | None]:
    """Queries max rx_bps and tx_bps from MRTG-CMP SQLite traffic.db for date YYYY-MM-DD."""
    if not db_path or not db_path.exists():
        return None, None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(rx_bps), MAX(tx_bps) FROM traffic_samples WHERE timestamp LIKE ?", (f"{date_iso}%",))
        row = cur.fetchone()
        conn.close()
        if row and (row[0] is not None or row[1] is not None):
            max_rx = (row[0] or 0.0) / 1_000_000.0  # bps -> Mbps
            max_tx = (row[1] or 0.0) / 1_000_000.0
            return max_rx, max_tx
    except Exception as exc:
        logger.warning("Failed querying Indibiz traffic from %s: %s", db_path, exc)
    return None, None
