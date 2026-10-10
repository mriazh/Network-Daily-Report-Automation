"""Configuration management for Network Daily Report Automation."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
OUTPUT_DIR = ROOT_DIR / "output"
GITHUB_DIR = ROOT_DIR.parents[0]

# Load environment from config/.env
ENV_FILE = CONFIG_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


def _resolve_with_fallback(primary: str | None, *fallbacks: Path) -> Path | None:
    """Resolve primary path from env, fallback to sibling directories if empty/missing data files."""
    candidates = []
    if primary:
        p = Path(primary)
        cand = ROOT_DIR / p if not p.is_absolute() else p
        candidates.append(cand)
    candidates.extend(fallbacks)

    # 1. Prefer candidate that is an existing file
    for c in candidates:
        if c.is_file() and c.exists():
            return c

    # 2. Prefer candidate directory that actually contains data files
    for c in candidates:
        if c.is_dir() and c.exists():
            if any(c.glob("*.xlsx")) or any(c.glob("*.csv")) or any(c.glob("*.json")) or any(c.glob("*.png")):
                return c
            if any(c.glob("20*/*.csv")) or any(c.glob("Raw/*/*.csv")) or any(c.glob("20*/*.png")):
                return c

    # 3. Fallback to first existing directory
    for c in candidates:
        if c.exists():
            return c

    return candidates[0] if candidates else None


class GowaSettings(BaseModel):
    enabled: bool = Field(default=False)
    base_url: str = Field(default="http://localhost:3000")
    device_id: str = Field(default="default")
    group_jid: str = Field(default="")
    timeout_seconds: int = Field(default=20)
    tls_verify: bool = Field(default=True)


class CheckpointSettings(BaseModel):
    enabled: bool = Field(default=False)
    trac_path: str = Field(default="trac")
    site: str = Field(default="CORP-VPN")
    gateway: str = Field(default="CORP-GATEWAY01")
    username: str = Field(default="")
    password: str = Field(default="")
    connect_timeout_seconds: int = Field(default=60)


class WarpSettings(BaseModel):
    enabled: bool = Field(default=False)
    cli_path: str = Field(default="warp-cli")
    mode: str = Field(default="proxy")
    proxy_port: int = Field(default=40000)
    auto_connect: bool = Field(default=True)
    trace_url: str = Field(default="https://www.cloudflare.com/cdn-cgi/trace")
    proxy_server: str = Field(default="")


class CmpSettings(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="")
    username: str = Field(default="")
    password: str = Field(default="")
    headless: bool = Field(default=True)
    timeout_seconds: int = Field(default=60)
    imap_host: str = Field(default="")
    imap_port: int = Field(default=993)
    email: str = Field(default="")
    email_password: str = Field(default="")
    otp_timeout_seconds: int = Field(default=120)
    otp_poll_interval_seconds: int = Field(default=5)
    raw_dir: Path | None = None
    proxy_server: str = Field(default="")


class MrtgSettings(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="")
    username: str = Field(default="")
    password: str = Field(default="")
    totp_secret: str = Field(default="")
    gemini_api_key: str = Field(default="")
    gemini_models: str = Field(default="gemini-1.5-flash,gemini-2.0-flash")
    telkomcare_dir: Path | None = None
    cmp_dir: Path | None = None
    cmp_db_path: Path | None = None


class PrtgSettings(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="http://127.0.0.1:8080")
    username: str = Field(default="")
    password: str = Field(default="")
    timeout_seconds: int = Field(default=15)


class AirwaveSettings(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="")
    username: str = Field(default="")
    password: str = Field(default="")
    headless: bool = Field(default=True)
    report_title: str = Field(default="Uptime ALL device switch")
    poll_interval_seconds: int = Field(default=15)
    poll_timeout_minutes: int = Field(default=10)
    export_dir: Path | None = None


class HuaweiSettings(BaseModel):
    enabled: bool = Field(default=True)
    base_url: str = Field(default="")
    login_path: str = Field(default="/view/login.html")
    username: str = Field(default="")
    password: str = Field(default="")
    headless: bool = Field(default=True)
    login_timeout_seconds: int = Field(default=45)
    export_timeout_seconds: int = Field(default=180)
    nav_timeout_seconds: int = Field(default=60)
    raw_dir: Path | None = None


class OrbitSettings(BaseModel):
    enabled: bool = Field(default=True)
    cache_file: Path | None = None
    headless: bool = Field(default=True)
    timeout_seconds: int = Field(default=60)


class AppConfig(BaseModel):
    timezone: str = Field(default="Asia/Jakarta")
    log_level: str = Field(default="INFO")
    schedule_time: str = Field(default="23:00")
    
    # Paths
    template_excel: Path = Field(default_factory=lambda: CONFIG_DIR / "Template-Daily-Report.xlsx")
    template_wag: Path = Field(default_factory=lambda: CONFIG_DIR / "Template-Daily-WAG.md")
    iccid_location_file: Path = Field(default_factory=lambda: CONFIG_DIR / "ICCID-Location.xlsx")
    circuits_file: Path = Field(default_factory=lambda: CONFIG_DIR / "circuits.json")
    output_root: Path = Field(default_factory=lambda: OUTPUT_DIR)
    output_raw_root: Path = Field(default_factory=lambda: OUTPUT_DIR / "raw")
    
    # Integrations
    gowa: GowaSettings = Field(default_factory=GowaSettings)
    checkpoint: CheckpointSettings = Field(default_factory=CheckpointSettings)
    warp: WarpSettings = Field(default_factory=WarpSettings)
    
    # Source Subsystems
    cmp: CmpSettings = Field(default_factory=CmpSettings)
    mrtg: MrtgSettings = Field(default_factory=MrtgSettings)
    prtg: PrtgSettings = Field(default_factory=PrtgSettings)
    airwave: AirwaveSettings = Field(default_factory=AirwaveSettings)
    huawei: HuaweiSettings = Field(default_factory=HuaweiSettings)
    orbit: OrbitSettings = Field(default_factory=OrbitSettings)
    
    # Nexthop
    ping_count: int = Field(default=5)
    ping_timeout_seconds: int = Field(default=2)


def load_config() -> AppConfig:
    def _opt_path(val: str | None) -> Path | None:
        return Path(val) if val and val.strip() else None

    gowa = GowaSettings(
        enabled=os.getenv("GOWA_ENABLED", "false").lower() in ("true", "1", "yes"),
        base_url=os.getenv("GOWA_BASE_URL", "http://localhost:3000"),
        device_id=os.getenv("GOWA_DEVICE_ID", "default"),
        group_jid=os.getenv("GOWA_GROUP_JID", ""),
        timeout_seconds=int(os.getenv("GOWA_TIMEOUT_SECONDS", "20")),
        tls_verify=os.getenv("GOWA_TLS_VERIFY", "true").lower() in ("true", "1", "yes"),
    )
    checkpoint = CheckpointSettings(
        enabled=os.getenv("CHECKPOINT_ENABLED", "false").lower() in ("true", "1", "yes"),
        trac_path=os.getenv("CHECKPOINT_TRAC_PATH", "trac"),
        site=os.getenv("CHECKPOINT_SITE", "CORP-VPN"),
        gateway=os.getenv("CHECKPOINT_GATEWAY", "CORP-GATEWAY01"),
        username=os.getenv("CHECKPOINT_USERNAME", ""),
        password=os.getenv("CHECKPOINT_PASSWORD", ""),
        connect_timeout_seconds=int(os.getenv("CHECKPOINT_CONNECT_TIMEOUT_SECONDS", "60")),
    )
    warp = WarpSettings(
        enabled=os.getenv("WARP_ENABLED", "false").lower() in ("true", "1", "yes"),
        cli_path=os.getenv("WARP_CLI_PATH", "warp-cli"),
        mode=os.getenv("WARP_MODE", "proxy"),
        proxy_port=int(os.getenv("WARP_PROXY_PORT", "40000")),
        auto_connect=os.getenv("WARP_AUTO_CONNECT", "true").lower() in ("true", "1", "yes"),
        trace_url=os.getenv("WARP_TRACE_URL", "https://www.cloudflare.com/cdn-cgi/trace"),
        proxy_server=os.getenv("WARP_PROXY_SERVER", ""),
    )
    cmp_fallbacks = [ROOT_DIR / "output" / "raw" / "iot"]
    if GITHUB_DIR.exists():
        cmp_fallbacks.extend([d / "output" / "raw" for d in GITHUB_DIR.glob("*CMP-Automation")])

    cmp_set = CmpSettings(
        enabled=os.getenv("CMP_ENABLED", "true").lower() in ("true", "1", "yes"),
        base_url=os.getenv("CMP_BASE_URL", ""),
        username=os.getenv("CMP_USERNAME", ""),
        password=os.getenv("CMP_PASSWORD", ""),
        headless=os.getenv("CMP_HEADLESS", "true").lower() in ("true", "1", "yes"),
        timeout_seconds=int(os.getenv("CMP_TIMEOUT_SECONDS", "60")),
        imap_host=os.getenv("CMP_IMAP_HOST") or os.getenv("MAIL_IMAP_HOST", ""),
        imap_port=int(os.getenv("CMP_IMAP_PORT") or os.getenv("MAIL_IMAP_PORT", "993")),
        email=os.getenv("CMP_EMAIL") or os.getenv("MAIL_EMAIL", ""),
        email_password=os.getenv("CMP_EMAIL_PASSWORD") or os.getenv("MAIL_PASSWORD", ""),
        otp_timeout_seconds=int(os.getenv("OTP_TIMEOUT_SECONDS", "120")),
        otp_poll_interval_seconds=int(os.getenv("OTP_POLL_INTERVAL_SECONDS", "5")),
        raw_dir=_resolve_with_fallback(os.getenv("CMP_RAW_DIR"), *cmp_fallbacks),
        proxy_server=os.getenv("CMP_PROXY_SERVER", ""),
    )
    mrtg_set = MrtgSettings(
        enabled=os.getenv("MRTG_ENABLED", "true").lower() in ("true", "1", "yes"),
        base_url=os.getenv("TELKOMCARE_BASE_URL", ""),
        username=os.getenv("TELKOMCARE_USERNAME", "") or os.getenv("TELKOM_USER", ""),
        password=os.getenv("TELKOMCARE_PASSWORD", "") or os.getenv("TELKOM_PASSWORD", ""),
        totp_secret=os.getenv("TOTP_SECRET", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_models=os.getenv("GEMINI_MODELS", "gemini-1.5-flash,gemini-2.0-flash"),
        telkomcare_dir=_resolve_with_fallback(
            os.getenv("MRTG_TELKOMCARE_DIR"),
            GITHUB_DIR / "MRTG-TelkomCare-Report-Automation" / "output" / "data" / "MRTG-Data",
            ROOT_DIR / "output" / "raw" / "mrtg",
        ),
        cmp_dir=_resolve_with_fallback(
            os.getenv("MRTG_CMP_DIR"),
            GITHUB_DIR / "MRTG-CMP" / "data",
            ROOT_DIR / "output" / "raw" / "mrtg_secondary",
        ),
        cmp_db_path=_resolve_with_fallback(
            os.getenv("MRTG_CMP_DB_PATH"),
            GITHUB_DIR / "MRTG-CMP" / "data" / "traffic.db",
            ROOT_DIR / "output" / "raw" / "mrtg_secondary" / "data" / "traffic.db",
        ),
    )
    prtg_set = PrtgSettings(
        enabled=os.getenv("PRTG_ENABLED", "true").lower() in ("true", "1", "yes"),
        base_url=os.getenv("PRTG_BASE_URL", "http://127.0.0.1:8080"),
        username=os.getenv("PRTG_USERNAME", ""),
        password=os.getenv("PRTG_PASSWORD", ""),
        timeout_seconds=int(os.getenv("PRTG_TIMEOUT_SECONDS", "15")),
    )
    airwave_set = AirwaveSettings(
        enabled=os.getenv("AIRWAVE_ENABLED", "true").lower() in ("true", "1", "yes"),
        base_url=os.getenv("AIRWAVE_BASE_URL", "") or os.getenv("AIRWAVE_URL", ""),
        username=os.getenv("AIRWAVE_USERNAME", ""),
        password=os.getenv("AIRWAVE_PASSWORD", ""),
        headless=os.getenv("AIRWAVE_HEADLESS", "true").lower() in ("true", "1", "yes"),
        report_title=os.getenv("AIRWAVE_REPORT_TITLE", "Uptime ALL device switch"),
        poll_interval_seconds=int(os.getenv("AIRWAVE_POLL_INTERVAL_SECONDS", "15")),
        poll_timeout_minutes=int(os.getenv("AIRWAVE_POLL_TIMEOUT_MINUTES", "10")),
        export_dir=_resolve_with_fallback(
            os.getenv("AIRWAVE_EXPORT_DIR"),
            GITHUB_DIR / "Switch-Report-Auto" / "Report" / "Switch" / "2026-10" / "Output",
            ROOT_DIR / "output" / "raw" / "airwave",
        ),
    )
    huawei_set = HuaweiSettings(
        enabled=os.getenv("HUAWEI_ENABLED", "true").lower() in ("true", "1", "yes"),
        base_url=os.getenv("HUAWEI_BASE_URL", ""),
        login_path=os.getenv("HUAWEI_LOGIN_PATH", "/view/login.html"),
        username=os.getenv("HUAWEI_USERNAME", ""),
        password=os.getenv("HUAWEI_PASSWORD", ""),
        headless=os.getenv("HUAWEI_HEADLESS", "true").lower() in ("true", "1", "yes"),
        login_timeout_seconds=int(os.getenv("HUAWEI_LOGIN_TIMEOUT_SECONDS", "45")),
        export_timeout_seconds=int(os.getenv("HUAWEI_EXPORT_TIMEOUT_SECONDS", "180")),
        nav_timeout_seconds=int(os.getenv("HUAWEI_NAV_TIMEOUT_SECONDS", "60")),
        raw_dir=_resolve_with_fallback(
            os.getenv("HUAWEI_RAW_DIR"),
            GITHUB_DIR / "AP-Report-Auto" / "output" / "raw" / "20261010",
            ROOT_DIR / "output" / "raw" / "huawei_ap",
        ),
    )
    orbit_set = OrbitSettings(
        enabled=os.getenv("ORBIT_ENABLED", "true").lower() in ("true", "1", "yes"),
        cache_file=_resolve_with_fallback(
            os.getenv("ORBIT_CACHE_FILE"),
            GITHUB_DIR / "MRTG-CMP" / "data" / "orbit_cache" / "modems.json",
            ROOT_DIR / "output" / "raw" / "orbit" / "modems.json",
        ),
        headless=os.getenv("ORBIT_HEADLESS", "true").lower() in ("true", "1", "yes"),
        timeout_seconds=int(os.getenv("ORBIT_TIMEOUT_SECONDS", "60")),
    )

    return AppConfig(
        timezone=os.getenv("TIMEZONE", "Asia/Jakarta"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        schedule_time=os.getenv("DAILY_SCHEDULE_TIME", "23:00"),
        gowa=gowa,
        checkpoint=checkpoint,
        warp=warp,
        cmp=cmp_set,
        mrtg=mrtg_set,
        prtg=prtg_set,
        airwave=airwave_set,
        huawei=huawei_set,
        orbit=orbit_set,
        ping_count=int(os.getenv("PING_COUNT", "5")),
        ping_timeout_seconds=int(os.getenv("PING_TIMEOUT_SECONDS", "2")),
    )
