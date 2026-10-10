"""WhatsApp Broadcast Message Formatter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_default_pic() -> list[str]:
    cfg = Path(__file__).resolve().parents[3] / "config" / "circuits.json"
    if cfg.exists():
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                return json.load(f).get("pic_names", [])
        except Exception:
            pass
    return ["Staff Engineer 1", "Staff Engineer 2", "Staff Engineer 3", "Staff Engineer 4", "Staff Engineer 5"]


def format_whatsapp_report(payload: dict[str, Any]) -> str:
    date_str = payload.get("date_str", "01 Januari 2026")
    pic_list = payload.get("pic_list") or _load_default_pic()
    iot = payload.get("iot", {})
    mrtg = payload.get("mrtg", {})
    ping = payload.get("ping", [])
    prtg = payload.get("prtg", {})
    cpu = payload.get("cpu", [])
    mem = payload.get("memory", [])
    uptime = payload.get("uptime", {})
    ap = payload.get("ap", {})
    orbit = payload.get("orbit", [])
    highlights = payload.get("highlights", {})

    lines: list[str] = [
        "*MONITORING NETWORK INFRASTRUCTURE*",
        f"📅 {date_str}",
        "",
        "*PIC Network Support:*",
    ]
    for idx, pic in enumerate(pic_list, 1):
        lines.append(f"{idx}. {pic}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "*A. 🌐 Telkomsel IoT M2M*",
        "",
        "1. Service Overview",
        f"  a. Status → ✅ {iot.get('status', 'Normal')}",
        f"  b. Total Usage → {iot.get('total_usage_gb', 0.0):.2f} GB",
        f"  c. Active Session → {iot.get('active_sessions', 0)} Session",
        "",
        "2. 🔝 Top Daily Usage",
    ])
    for idx, (site, val) in enumerate(iot.get("top_daily", [])[:5], ord('a')):
        lines.append(f"  {chr(idx)}. {site} → {val:.2f} GB")

    lines.extend([
        "",
        "3. 🔝 Top Periodic Usage",
    ])
    for idx, (site, val) in enumerate(iot.get("top_periodic", [])[:5], ord('a')):
        lines.append(f"  {chr(idx)}. {site} → {val:.2f} GB")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "*B. 📊 Usage by MRTG*",
    ])
    for group_num, group_name in [(1, "ASTINET"), (2, "Metro-E"), (3, "VPN IP"), (4, "Telkom Indibiz")]:
        links = mrtg.get(group_name, []) or mrtg.get("Telkom Indibiz", []) if group_name == "Telkom Indibiz" else mrtg.get(group_name, [])
        lines.extend(["", f"{group_num}. {group_name}"])
        for idx, link_item in enumerate(links, ord('a')):
            if link_item.get("status") == "High Traffic":
                status_icon = "⚠️"
                extra = f" ({link_item.get('remarks', '')})"
            else:
                status_icon = "✅"
                extra = ""
            lines.append(f"  {chr(idx)}. {link_item.get('name')} (SID: {link_item.get('sid')}) ({link_item.get('capacity_str')}) → {status_icon} {link_item.get('status')}{extra}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "*C. 🔀 Switch & Core Infrastructure*",
        "",
        "1. 📡 Nexthop (Ping)",
    ])
    for idx, p in enumerate(ping, ord('a')):
        name = p.get('name')
        ip = p.get('ip')
        status = p.get('status')
        received = p.get('packets_received', 0)
        sent = p.get('total_sent', 4)
        loss_pct = p.get('loss_pct') or p.get('packet_loss_pct') or 0.0
        avg_ms = p.get('avg_latency_ms')
        if status == 'Normal':
            avg_str = f', Avg: {avg_ms:.1f} ms' if avg_ms is not None else ''
            lines.append(f'  {chr(idx)}. {name} → ✅ Normal (IP {ip}) (Loss: {loss_pct:.0f}% ({received}/{sent} Reply){avg_str})')
        elif status == 'Monitoring' or status == 'Warning':
            avg_str = f', Avg: {avg_ms:.1f} ms' if avg_ms is not None else ''
            lines.append(f'  {chr(idx)}. {name} → ⚠️ Monitoring (IP {ip}) (Loss: {loss_pct:.0f}% ({received}/{sent} Reply){avg_str})')
        else:  # Down
            lines.append(f'  {chr(idx)}. {name} → ⚠️ Down (IP {ip}) (Loss: 100% (0/{sent} Reply), Request Timeout)')

    lines.extend([
        "",
        "2. 🖥️ PRTG Sensors",
        f"  a. 🟢 UP → {prtg.get('up', 0)}",
        f"  b. ⏸️ Paused → {prtg.get('paused', 0)}",
        f"  c. Total → {prtg.get('total', 0)} Sensors",
        "",
        "3. ⚙️ Top 10 CPU Utilization",
    ])
    for idx, (dev, val) in enumerate(cpu[:10], ord('a')):
        lines.append(f"  {chr(idx)}. {dev} → {val:.2f}%")

    lines.extend([
        "",
        "4. 💾 Top 10 Memory Usage",
    ])
    for idx, (dev, val) in enumerate(mem[:10], ord('a')):
        warn = " (⚠️ Monitoring)" if "WLC" in dev.upper() and val >= 65 else ""
        lines.append(f"  {chr(idx)}. {dev} → {val:.2f}%{warn}")

    lines.extend([
        "",
        "5. ⏱️ Avg Uptime by Device",
        f"  a. Device Uptime → {uptime.get('device', 98.64)}%",
        f"  b. SNMP Comm Uptime → {uptime.get('snmp', 98.64)}%",
        f"  c. ICMP Comm Uptime → {uptime.get('icmp', 99.32)}%",
        f"  d. HTTPS Comm Uptime → {uptime.get('https', '-')}",
        "",
        "6. 📝 Analisa Utilisasi",
        f"  a. CPU: {payload.get('analysis_cpu', 'Beban normal.')}",
        f"  b. Memori: {payload.get('analysis_mem', 'Alokasi stabil.')}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "*D. 📶 AP Huawei (WAC)*",
        "",
        "1. Status Connectivity",
        f"  a. Normal → 🟢 {ap.get('normal', 454)}",
        f"  b. Fault → 🔴 {ap.get('fault', 0)}",
        f"  c. Connected Users → 👥 {ap.get('users', 0)}",
        "",
        "2. Status Fisik AP",
        f"  a. Indoor → ✅ {ap.get('indoor_ok', 328)} OK",
        f"  b. Outdoor → ✅ {ap.get('outdoor_ok', 115)} OK" + (f", ⚠️ {ap.get('outdoor_fault', 0)} Fault ({', '.join(ap.get('fault_names', []))})" if ap.get("outdoor_fault", 0) > 0 else ""),
        "",
        "3. 📊 User Distribution by SSID",
    ])
    for idx, (ssid_name, cnt) in enumerate(ap.get("ssid_distribution", {}).items(), ord('a')):
        lines.append(f"  {chr(idx)}. {ssid_name} → {cnt}")

    if orbit:
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "*E. 📱 Modem Orbit*",
        ])
        for idx, m in enumerate(orbit, 1):
            pkgs = m.get("packages", [])
            active = [p for p in pkgs if p] if pkgs else []
            if not active:
                p_text = "Kuota: - (No Active Package)"
            else:
                p = active[0]
                p_text = f"Kuota: {p.get('remaining_gb')} GB / {p.get('total_gb')} GB"
            lines.append(f"{idx}. {m.get('location')}: {p_text}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "*F. ⚠️ Highlights & Incident Follow-up*",
        "1. High Traffic:",
    ])
    ht_list = highlights.get("high_traffic", [])
    if ht_list:
        for idx, h in enumerate(ht_list, ord('a')):
            lines.append(f"  {chr(idx)}. {h.get('name')} ({h.get('remarks', '')})")
    else:
        lines.append("  a. Seluruh sirkuit terpantau Normal.")

    lines.extend([
        "2. Hardware Fault:",
        f"  a. {highlights.get('hardware_fault', 'Tidak ada hardware fault.')}",
        "3. Problem Open:",
        "  a. -",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🏁 Sekian laporan harian Network Support. Terima kasih.",
    ])

    return "\n".join(lines)
