"""Command-line interface for Network Daily Report Automation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .collectors.mrtg import evaluate_circuit, query_indibiz_traffic_db
from .collectors.nexthop_ping import collect_nexthop_ping
from .config import load_config
from .notifier import GowaNotifier
from .pipeline import run_daily_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("network_report")


def _load_circuits(cfg) -> dict:
    """Load circuits from config/circuits.json (fallback to example)."""
    circuits_file = cfg.circuits_file
    if not circuits_file.exists():
        circuits_file = Path(__file__).resolve().parents[2] / "config" / "circuits.example.json"
    if circuits_file.exists():
        with open(circuits_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _build_mrtg_payload(circuits: dict, cfg, date_iso: str) -> dict:
    """Evaluate all circuit groups and build MRTG payload."""
    mrtg_payload = {}
    
    # ASTINET
    astinet_list = []
    for name, sid, cap in circuits.get("astinet", []):
        status = evaluate_circuit(name, sid, cap)
        astinet_list.append({
            "name": name,
            "sid": sid,
            "capacity_str": cap,
            "status": status.status,
            "utilization_pct": status.utilization_pct,
            "capacity_mbps": status.capacity_mbps,
            "max_mbps": status.max_mbps,
            "remarks": status.remarks,
        })
    mrtg_payload["ASTINET"] = astinet_list

    # Metro-E
    metro_list = []
    for name, sid, cap in circuits.get("metro_e", []):
        status = evaluate_circuit(name, sid, cap)
        metro_list.append({
            "name": name,
            "sid": sid,
            "capacity_str": cap,
            "status": status.status,
            "utilization_pct": status.utilization_pct,
            "capacity_mbps": status.capacity_mbps,
            "max_mbps": status.max_mbps,
            "remarks": status.remarks,
        })
    mrtg_payload["Metro-E"] = metro_list

    # VPN IP
    vpn_list = []
    for name, sid, cap in circuits.get("vpn_ip_osa", []):
        status = evaluate_circuit(name, sid, cap)
        vpn_list.append({
            "name": name,
            "sid": sid,
            "capacity_str": cap,
            "status": status.status,
            "utilization_pct": status.utilization_pct,
            "capacity_mbps": status.capacity_mbps,
            "max_mbps": status.max_mbps,
            "remarks": status.remarks,
        })
    mrtg_payload["VPN IP"] = vpn_list

    # Telkom Indibiz - query traffic.db
    indibiz_list = []
    indibiz_db = cfg.mrtg.cmp_db_path
    for name, sid, cap in circuits.get("telkom_indibiz", []):
        max_rx, max_tx = query_indibiz_traffic_db(indibiz_db, date_iso)
        status = evaluate_circuit(name, sid, cap, max_rx, max_tx)
        indibiz_list.append({
            "name": name,
            "sid": sid,
            "capacity_str": cap,
            "status": status.status,
            "utilization_pct": status.utilization_pct,
            "capacity_mbps": status.capacity_mbps,
            "max_mbps": status.max_mbps,
            "remarks": status.remarks,
        })
    mrtg_payload["Telkom Indibiz"] = indibiz_list

    return mrtg_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Network Daily Report Automation Runner")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run daily automated reporting pipeline")
    run_parser.add_argument("--date", default="yesterday", help="Target date to report (YYYY-MM-DD, 'today', or 'yesterday')")
    run_parser.add_argument("--send-wa", action="store_true", help="Send WhatsApp notice via GOWA")

    # Command: test-ping
    subparsers.add_parser("test-ping", help="Test ICMP ping to all 7 nexthop targets")

    # Command: test-wa
    wa_parser = subparsers.add_parser("test-wa", help="Send test WhatsApp message to verify GOWA bridge")
    wa_parser.add_argument("--message", default="[TEST] Network Daily Report Automation connection check.", help="Custom text")

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.command == "test-ping":
        print("Running ping test to 7 nexthop targets...")
        results = collect_nexthop_ping()
        for r in results:
            print(f"[{r.status:7s}] {r.name:25s} ({r.ip:15s}) - Loss: {r.packet_loss_pct}% Avg: {r.avg_latency_ms} ms")
        return 0

    elif args.command == "test-wa":
        notifier = GowaNotifier(cfg.gowa)
        ok = notifier.send_message(args.message)
        print(f"GOWA Send Result: {'SUCCESS' if ok else 'FAILED / DISABLED'}")
        return 0 if ok else 1

    elif args.command == "run":
        print(f"Executing daily report pipeline for: {args.date}...")
        result = run_daily_pipeline(args.date, args.send_wa)
        print(f"Excel: {result['excel_path']}")
        print(f"WhatsApp report: {result['wag_path']}")
        print(f"WhatsApp sent: {result['wa_sent']}")
        return 0

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
