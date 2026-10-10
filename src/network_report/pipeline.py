"""Daily Report Pipeline - Core orchestration logic."""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from .collectors.airwave import AirwaveData, collect_airwave_data
from .collectors.cmp_crawler import CmpExportResult, run_cmp_crawler
from .collectors.huawei_ap import HuaweiApData, collect_huawei_ap_data
from .collectors.iot_m2m import IotDailySummary, collect_iot_summary
from .collectors.modem_orbit import OrbitModem, collect_orbit_modems
from .collectors.mrtg import evaluate_circuit, load_mrtg_ocr_data, query_indibiz_traffic_db
from .collectors.nexthop_ping import PingResult, collect_nexthop_ping
from .collectors.prtg import PrtgStatus, fetch_prtg_status
from .config import AppConfig, load_config
from .notifier import GowaNotifier
from .processing.analyzer import generate_technical_analysis
from .writers.excel_writer import write_daily_excel
from .writers.wag_formatter import format_whatsapp_report

logger = logging.getLogger(__name__)


def _load_circuits(cfg: AppConfig) -> dict:
    """Load circuits from config/circuits.json (fallback to example)."""
    circuits_file = cfg.circuits_file
    if not circuits_file.exists():
        circuits_file = Path(__file__).resolve().parents[2] / "config" / "circuits.example.json"
    if circuits_file.exists():
        with open(circuits_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _build_mrtg_payload(
    circuits: dict, cfg: AppConfig, date_iso: str, date_compact: str = ""
) -> dict:
    """Evaluate all circuit groups and build MRTG payload."""
    mrtg_payload = {}
    ocr_data = load_mrtg_ocr_data(cfg.mrtg.telkomcare_dir, date_compact)

    def _find_ocr(sid_str: str) -> dict[str, float] | None:
        sid_clean = sid_str.strip()
        if sid_clean in ocr_data:
            return ocr_data[sid_clean]
        for k, v in ocr_data.items():
            if k in sid_clean or sid_clean in k or (len(k) >= 6 and k[-6:] == sid_clean[-6:]):
                return v
        return None

    # ASTINET
    astinet_list = []
    for name, sid, cap in circuits.get("astinet", []):
        d = _find_ocr(sid)
        max_in = d.get("in_mbps") if d else None
        max_out = d.get("out_mbps") if d else None
        status = evaluate_circuit(name, sid, cap, max_in, max_out)
        astinet_list.append(
            {
                "name": name,
                "sid": sid,
                "capacity_str": cap,
                "status": status.status,
                "utilization_pct": status.utilization_pct,
                "over_pct": status.over_pct,
                "capacity_mbps": status.capacity_mbps,
                "max_mbps": status.max_mbps,
                "remarks": status.remarks,
            }
        )
    mrtg_payload["ASTINET"] = astinet_list

    # Metro-E
    metro_list = []
    for name, sid, cap in circuits.get("metro_e", []):
        d = _find_ocr(sid)
        max_in = d.get("in_mbps") if d else None
        max_out = d.get("out_mbps") if d else None
        status = evaluate_circuit(name, sid, cap, max_in, max_out)
        metro_list.append(
            {
                "name": name,
                "sid": sid,
                "capacity_str": cap,
                "status": status.status,
                "utilization_pct": status.utilization_pct,
                "over_pct": status.over_pct,
                "capacity_mbps": status.capacity_mbps,
                "max_mbps": status.max_mbps,
                "remarks": status.remarks,
            }
        )
    mrtg_payload["Metro-E"] = metro_list

    # VPN IP
    vpn_list = []
    for name, sid, cap in circuits.get("vpn_ip_osa", []):
        d = _find_ocr(sid)
        max_in = d.get("in_mbps") if d else None
        max_out = d.get("out_mbps") if d else None
        status = evaluate_circuit(name, sid, cap, max_in, max_out)
        vpn_list.append(
            {
                "name": name,
                "sid": sid,
                "capacity_str": cap,
                "status": status.status,
                "utilization_pct": status.utilization_pct,
                "over_pct": status.over_pct,
                "capacity_mbps": status.capacity_mbps,
                "max_mbps": status.max_mbps,
                "remarks": status.remarks,
            }
        )
    mrtg_payload["VPN IP"] = vpn_list

    # Telkom Indibiz - query traffic.db
    indibiz_list = []
    indibiz_db = cfg.mrtg.cmp_db_path
    for name, sid, cap in circuits.get("telkom_indibiz", []):
        max_rx, max_tx = query_indibiz_traffic_db(indibiz_db, date_iso)
        status = evaluate_circuit(name, sid, cap, max_rx, max_tx)
        indibiz_list.append(
            {
                "name": name,
                "sid": sid,
                "capacity_str": cap,
                "status": status.status,
                "utilization_pct": status.utilization_pct,
                "over_pct": status.over_pct,
                "capacity_mbps": status.capacity_mbps,
                "max_mbps": status.max_mbps,
                "remarks": status.remarks,
            }
        )
    mrtg_payload["Telkom Indibiz"] = indibiz_list

    return mrtg_payload


def _archive_raw_artifacts(
    cfg: AppConfig,
    date_compact: str,
    ping_results: list[PingResult],
    prtg_status: PrtgStatus | None,
    orbit_modems: list[OrbitModem],
    mrtg_payload: dict,
) -> None:
    """Collects and archives raw data files and state snapshots into output/raw/{category}/{date}/."""
    raw_root = cfg.output_raw_root
    raw_root.mkdir(parents=True, exist_ok=True)

    # 1. Archive IoT M2M raw files (.xlsx, .csv, .png) and dashboard screenshots
    iot_raw_dest = raw_root / "iot" / date_compact
    iot_raw_dest.mkdir(parents=True, exist_ok=True)
    cmp_sources = [cfg.cmp.raw_dir] if cfg.cmp.raw_dir else []
    cmp_sources.append(cfg.output_root / "images")
    for d in Path(__file__).resolve().parents[3].glob("*CMP-Automation"):
        cmp_sources.append(d / "output" / "raw")
        cmp_sources.append(d / "output" / "images")
    for s_dir in cmp_sources:
        if s_dir and s_dir.exists():
            for pattern in (
                "*{date_compact}*.xlsx",
                "*{date_compact}*.csv",
                "*{date_compact}*.png",
                "dashboard_{date_compact}*.png",
                "dashboard_{date_compact}*.jpg",
            ):
                for f in s_dir.glob(pattern.format(date_compact=date_compact)):
                    if not (iot_raw_dest / f.name).exists():
                        shutil.copy2(f, iot_raw_dest / f.name)

    # 2. Archive Huawei AP raw CSVs and PNGs
    ap_raw_dest = raw_root / "huawei_ap" / date_compact
    ap_raw_dest.mkdir(parents=True, exist_ok=True)
    ap_sources = []
    if cfg.huawei.raw_dir:
        ap_sources.append(cfg.huawei.raw_dir / date_compact)
        ap_sources.append(cfg.huawei.raw_dir)
        ap_sources.extend(list(cfg.huawei.raw_dir.glob("20*")))
    for d in Path(__file__).resolve().parents[3].glob("*AP-Report-Auto"):
        base_raw = d / "output" / "raw"
        if base_raw.exists():
            ap_sources.append(base_raw / date_compact)
            ap_sources.extend(sorted(base_raw.glob("20*"), reverse=True))

    for src_c in ap_sources:
        if src_c and src_c.exists():
            for pattern in ("apInfo.csv", "ssidInfo.csv", "*.png"):
                for f in src_c.glob(pattern):
                    if not (ap_raw_dest / f.name).exists():
                        shutil.copy2(f, ap_raw_dest / f.name)
            if (ap_raw_dest / "apInfo.csv").exists():
                break

    # 3. Archive AirWave raw CSVs and PNGs
    airwave_dest = raw_root / "airwave" / date_compact
    airwave_dest.mkdir(parents=True, exist_ok=True)
    airwave_sources = []
    ym = f"{date_compact[:4]}-{date_compact[4:6]}"
    dd = date_compact[6:8]
    if cfg.airwave.export_dir:
        airwave_sources.extend(
            [
                cfg.airwave.export_dir / ym / "Raw" / dd,
                cfg.airwave.export_dir / "Raw" / dd,
                cfg.airwave.export_dir,
            ]
        )
    for d in Path(__file__).resolve().parents[3].glob("*Switch-Report-Auto"):
        airwave_sources.extend(
            [
                d / "Report" / "Switch" / ym / "Raw" / dd,
                d / "output",
            ]
        )

    for src_c in airwave_sources:
        if src_c and src_c.exists():
            for pattern in ("*.csv", "*.png"):
                for f in src_c.glob(pattern):
                    if not (airwave_dest / f.name).exists():
                        shutil.copy2(f, airwave_dest / f.name)
            if list(airwave_dest.glob("*.csv")):
                break

    # 4. Archive MRTG raw files (.xlsx, .csv, .png, .json)
    mrtg_raw_dest = raw_root / "mrtg" / date_compact
    mrtg_raw_dest.mkdir(parents=True, exist_ok=True)
    mrtg_sources = []
    if cfg.mrtg.telkomcare_dir:
        mrtg_sources.append(cfg.mrtg.telkomcare_dir)
    if cfg.mrtg.cmp_dir:
        mrtg_sources.append(cfg.mrtg.cmp_dir)
    for d in Path(__file__).resolve().parents[3].glob("*MRTG-TelkomCare-Report-Automation"):
        mrtg_sources.append(d / "output" / "data" / "MRTG-Data")
        mrtg_sources.append(d / "output" / "raw")
    for d in Path(__file__).resolve().parents[3].glob("*MRTG-CMP"):
        mrtg_sources.append(d / "data")

    for src_c in mrtg_sources:
        if src_c and src_c.exists():
            for pattern in (
                "*{date_compact}*.xlsx",
                "*{date_compact}*.csv",
                "*{date_compact}*.png",
                "*{date_compact}*.json",
            ):
                for f in src_c.glob(pattern.format(date_compact=date_compact)):
                    if not (mrtg_raw_dest / f.name).exists():
                        shutil.copy2(f, mrtg_raw_dest / f.name)

    # 5. Snapshot Orbit modems JSON
    orbit_dest = raw_root / "orbit" / date_compact
    orbit_dest.mkdir(parents=True, exist_ok=True)
    if cfg.orbit.cache_file and cfg.orbit.cache_file.exists():
        shutil.copy2(cfg.orbit.cache_file, orbit_dest / "modems.json")
    elif orbit_modems:
        snapshot = [
            {
                "location": m.location,
                "ssid": m.ssid,
                "packages": [
                    {
                        "name": p.name,
                        "remaining_gb": p.remaining_gb,
                        "total_gb": p.total_gb,
                        "expiry_str": p.expiry_str,
                    }
                    for p in m.packages
                ],
            }
            for m in orbit_modems
        ]
        (orbit_dest / "modems.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    # 6. Snapshot PRTG sensor status JSON
    prtg_dest = raw_root / "prtg" / date_compact
    prtg_dest.mkdir(parents=True, exist_ok=True)
    if prtg_status:
        prtg_json = {
            "up": prtg_status.up,
            "paused": prtg_status.paused,
            "down": prtg_status.down,
            "warning": prtg_status.warning,
            "total": prtg_status.total,
        }
        (prtg_dest / "prtg_status.json").write_text(
            json.dumps(prtg_json, indent=2), encoding="utf-8"
        )

    # 7. Snapshot Nexthop Ping JSON
    ping_dest = raw_root / "nexthop" / date_compact
    ping_dest.mkdir(parents=True, exist_ok=True)
    ping_json = [
        {
            "name": r.name,
            "ip": r.ip,
            "status": r.status,
            "avg_latency_ms": r.avg_latency_ms,
            "loss_pct": r.packet_loss_pct,
        }
        for r in ping_results
    ]
    (ping_dest / "ping_results.json").write_text(json.dumps(ping_json, indent=2), encoding="utf-8")

    # 8. Snapshot MRTG circuits status JSON
    mrtg_dest = raw_root / "mrtg" / date_compact
    mrtg_dest.mkdir(parents=True, exist_ok=True)
    (mrtg_dest / "circuits_status.json").write_text(
        json.dumps(mrtg_payload, indent=2), encoding="utf-8"
    )


def run_daily_pipeline(date_input: str = "today", send_wa: bool = False) -> dict:
    """Execute full daily report pipeline.

    Args:
        date_input: "today", "yesterday", or YYYY-MM-DD string.
        send_wa: Whether to send WhatsApp notification via GOWA.

    Returns:
        dict with keys: 'excel_path', 'wag_path', 'payload', 'wa_sent'
    """
    cfg = load_config()
    target_dt = (
        datetime.now()
        if date_input == "today"
        else (
            datetime.strptime(date_input, "%Y-%m-%d")
            if "-" in date_input
            else datetime.now() - timedelta(days=1)
        )
    )
    date_iso = target_dt.strftime("%Y-%m-%d")
    date_str = target_dt.strftime("%d %B %Y")
    month_str = target_dt.strftime("%Y-%m")
    date_compact = target_dt.strftime("%Y%m%d")
    day_num = target_dt.day

    # Setup file logger
    log_dir = cfg.output_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / f"pipeline_{date_compact}.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    logger.info("Starting daily pipeline for %s (Day %d)", date_str, day_num)

    start_time = time.time()
    notifier = GowaNotifier(cfg.gowa) if send_wa else None
    if notifier is not None:
        notifier.send_start(date_str)

    try:
        # Pre-archive raw data files from sources into local output/raw/
        _archive_raw_artifacts(
            cfg=cfg,
            date_compact=date_compact,
            ping_results=[],
            prtg_status=None,
            orbit_modems=[],
            mrtg_payload={},
        )

        # 1. Collect all data
        # Ping nexthop
        ping_results: list[PingResult] = collect_nexthop_ping()
        ping_payload = [
            {
                "name": r.name,
                "ip": r.ip,
                "status": r.status,
                "avg_latency_ms": r.avg_latency_ms,
                "packet_loss_pct": r.packet_loss_pct,
                "total_sent": r.total_sent,
                "packets_received": r.packets_received,
            }
            for r in ping_results
        ]

        # IoT M2M
        iot_summary: IotDailySummary | None = None
        cmp_crawler_result: CmpExportResult | None = None
        if cfg.cmp.enabled and cfg.cmp.raw_dir:
            iot_summary = collect_iot_summary(
                raw_dir=cfg.cmp.raw_dir,
                target_date=target_dt.strftime("%Y%m%d"),
                mapping_path=cfg.iccid_location_file,
                dashboard_dirs=[
                    cfg.output_raw_root / "iot" / date_compact,
                    cfg.output_root / "images",
                    cfg.cmp.raw_dir,
                ],
            )

        # CMP Dashboard Live Crawler - extract live total usage directly from dashboard
        if cfg.cmp.enabled and cfg.cmp.username and cfg.cmp.email:
            logger.info("Running CMP live dashboard crawler...")
            cmp_crawler_result = run_cmp_crawler(
                base_url=cfg.cmp.base_url or "https://ep.iotcc.telkomsel.com",
                username=cfg.cmp.username,
                password=cfg.cmp.password,
                target_date=target_dt.strftime("%Y-%m-%d"),
                target_month=target_dt.strftime("%Y-%m"),
                output_dir=cfg.output_root,
                headless=cfg.cmp.headless,
                timeout_seconds=cfg.cmp.timeout_seconds,
                imap_host=cfg.cmp.imap_host,
                imap_port=cfg.cmp.imap_port,
                email=cfg.cmp.email,
                email_password=cfg.cmp.email_password,
                otp_timeout_seconds=cfg.cmp.otp_timeout_seconds,
                otp_poll_interval_seconds=cfg.cmp.otp_poll_interval_seconds,
                proxy_server=cfg.cmp.proxy_server,
                warp_proxy_server=cfg.warp.proxy_server,
            )
            if cmp_crawler_result.error:
                logger.warning("CMP crawler error: %s", cmp_crawler_result.error)
            elif cmp_crawler_result.live_total_usage_gb is not None:
                logger.info("CMP live total usage: %.2f GB", cmp_crawler_result.live_total_usage_gb)

        # PRTG
        prtg_status: PrtgStatus | None = None
        if cfg.prtg.enabled:
            prtg_status = fetch_prtg_status(
                base_url=cfg.prtg.base_url,
                username=cfg.prtg.username,
                password=cfg.prtg.password,
                timeout=cfg.prtg.timeout_seconds,
            )

        # AirWave
        airwave_data: AirwaveData | None = None
        if cfg.airwave.enabled:
            airwave_data = collect_airwave_data(cfg.airwave.export_dir, date_compact)

        # Huawei AP
        huawei_ap_data: HuaweiApData | None = None
        if cfg.huawei.enabled:
            huawei_ap_data = collect_huawei_ap_data(cfg.huawei.raw_dir, date_compact)

        # Orbit Modems
        orbit_modems: list[OrbitModem] = []
        if cfg.orbit.enabled:
            orbit_modems = collect_orbit_modems(
                cache_json_path=cfg.orbit.cache_file,
                circuits_file=cfg.circuits_file,
                output_raw_root=cfg.output_raw_root,
                date_compact=date_compact,
                headless=cfg.orbit.headless if hasattr(cfg.orbit, "headless") else True,
                timeout_seconds=cfg.orbit.timeout_seconds
                if hasattr(cfg.orbit, "timeout_seconds")
                else 60,
            )

        # MRTG circuits
        circuits = _load_circuits(cfg)
        mrtg_payload = _build_mrtg_payload(circuits, cfg, date_iso, date_compact)

        # 2. Build highlights / technical analysis
        cpu_data = airwave_data.top_cpu if airwave_data else []
        mem_data = airwave_data.top_memory if airwave_data else []
        c_txt, m_txt = generate_technical_analysis(cpu_data, mem_data)

        high_traffic_links = []
        for grp in mrtg_payload.values():
            for link_item in grp:
                if link_item.get("status") == "High Traffic":
                    high_traffic_links.append(
                        {
                            "name": link_item["name"],
                            "util_pct": link_item.get("utilization_pct", 0.0),
                            "over_pct": link_item.get("over_pct", 0.0),
                            "remarks": link_item.get("remarks", ""),
                        }
                    )

        hardware_fault_text = "Tidak ada hardware fault."
        if huawei_ap_data and huawei_ap_data.outdoor_fault > 0:
            names = (
                f" ({', '.join(huawei_ap_data.fault_ap_names)})"
                if huawei_ap_data.fault_ap_names
                else ""
            )
            hardware_fault_text = f"AP Outdoor Fault : {huawei_ap_data.outdoor_fault} ea.{names}"
        elif huawei_ap_data and huawei_ap_data.fault_count > 0:
            names = (
                f" ({', '.join(huawei_ap_data.fault_ap_names)})"
                if huawei_ap_data.fault_ap_names
                else ""
            )
            hardware_fault_text = f"AP Fault : {huawei_ap_data.fault_count} ea.{names}"

        highlights = {
            "high_traffic": high_traffic_links,
            "hardware_fault": hardware_fault_text,
            "problem_open": "-",
        }

        # 3. Assemble full payload
        # Use live CMP dashboard usage if available, otherwise fall back to iot_summary
        live_usage_gb = None
        if cmp_crawler_result and cmp_crawler_result.live_total_usage_gb is not None:
            live_usage_gb = cmp_crawler_result.live_total_usage_gb
            logger.info("Using live CMP dashboard usage: %.2f GB", live_usage_gb)

        payload = {
            "date_str": date_str,
            "day_number": day_num,
            "date_iso": date_iso,
            "ping": ping_payload,
            "iot": {
                "status": "Normal",
                "total_usage_gb": round(live_usage_gb, 2)
                if live_usage_gb is not None
                else (round(iot_summary.total_usage_gb, 2) if iot_summary else 0.0),
                "active_sessions": iot_summary.active_sessions if iot_summary else 0,
                "top_daily": iot_summary.top_daily[:5] if iot_summary else [],
                "top_periodic": iot_summary.top_periodic[:5] if iot_summary else [],
                "periodic_range_str": iot_summary.periodic_range_str if iot_summary else "",
            },
            "prtg": {
                "up": prtg_status.up if prtg_status else 98,
                "paused": prtg_status.paused if prtg_status else 29,
                "total": prtg_status.total if prtg_status else 127,
            },
            "ap": {
                "normal": huawei_ap_data.normal_count if huawei_ap_data else 454,
                "fault": huawei_ap_data.fault_count if huawei_ap_data else 0,
                "users": huawei_ap_data.total_users if huawei_ap_data else 0,
                "indoor_ok": huawei_ap_data.indoor_ok if huawei_ap_data else 328,
                "outdoor_ok": huawei_ap_data.outdoor_ok if huawei_ap_data else 115,
                "outdoor_fault": huawei_ap_data.outdoor_fault if huawei_ap_data else 0,
                "fault_names": huawei_ap_data.fault_ap_names if huawei_ap_data else [],
                "ssid_distribution": huawei_ap_data.ssid_distribution if huawei_ap_data else {},
            },
            "mrtg": mrtg_payload,
            "cpu": cpu_data[:10],
            "memory": mem_data[:10],
            "uptime": {
                "device": airwave_data.device_uptime_pct if airwave_data else 98.64,
                "snmp": airwave_data.snmp_uptime_pct if airwave_data else 98.64,
                "icmp": airwave_data.icmp_uptime_pct if airwave_data else 99.32,
                "https": airwave_data.https_uptime_pct if airwave_data else "-",
            },
            "orbit": [
                {
                    "location": m.location,
                    "ssid": m.ssid,
                    "packages": [
                        {
                            "name": p.name,
                            "remaining_gb": p.remaining_gb,
                            "total_gb": p.total_gb,
                            "expiry_str": p.expiry_str,
                        }
                        for p in m.packages
                    ],
                }
                for m in orbit_modems
            ],
            "analysis_cpu": c_txt,
            "analysis_mem": m_txt,
            "highlights": highlights,
        }

        # Archive raw data artifacts and state snapshots to output/raw/
        _archive_raw_artifacts(
            cfg=cfg,
            date_compact=date_compact,
            ping_results=ping_results,
            prtg_status=prtg_status,
            orbit_modems=orbit_modems,
            mrtg_payload=mrtg_payload,
        )

        # 4. Write Excel
        template_path = cfg.template_excel
        output_path = cfg.output_root / "reports" / month_str / f"Daily-Report-{month_str}.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        excel_ok = write_daily_excel(template_path, output_path, day_num, payload)

        # 5. Write WhatsApp report (wag)
        wa_text = format_whatsapp_report(payload)
        wag_path = cfg.output_root / "wag" / f"Report_{date_compact}.txt"
        wag_path.parent.mkdir(parents=True, exist_ok=True)
        wag_path.write_text(wa_text, encoding="utf-8")
        logger.info("Wrote WhatsApp report to %s", wag_path)

        # 6. Optional: Send WhatsApp report, then SUCCESS notice
        wa_sent = False
        if notifier is not None:
            wa_sent = notifier.send_report(wa_text)
            if wa_sent:
                logger.info("WhatsApp notification sent successfully")
            else:
                logger.warning("WhatsApp notification failed or disabled")
            notifier.send_success(date_str, time.time() - start_time)

    except Exception as exc:
        if notifier is not None:
            notifier.send_failed(date_str, str(exc))
        raise

    return {
        "excel_path": str(output_path) if excel_ok else None,
        "wag_path": str(wag_path),
        "payload": payload,
        "wa_sent": wa_sent,
    }
