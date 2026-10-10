"""Native CMP (Cisco Jasper / Control Center) Crawler for Telkomsel IoT M2M using Playwright."""

from __future__ import annotations

import imaplib
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from network_report.config import load_config

logger = logging.getLogger(__name__)


@dataclass
class CmpExportResult:
    daily_file: Path | None = None
    monthly_file: Path | None = None
    error: str | None = None
    live_total_usage_gb: float | None = None


def _resolve_proxy_server(cfg_cmp_proxy: str = "", cfg_warp_proxy: str = "") -> str | None:
    """Resolve proxy server from explicit config, env var, or WARP default.

    Priority:
    1. cfg_cmp_proxy  (explicit CMP proxy, e.g. CMP_PROXY_SERVER)
    2. cfg_warp_proxy (WARP proxy_url from config)
    3. CMP_PROXY_SERVER environment variable
    4. WARP local socks5 default on Linux, only while WARP is active
    """
    if cfg_cmp_proxy:
        return cfg_cmp_proxy
    if cfg_warp_proxy:
        return cfg_warp_proxy

    env_proxy = os.getenv("CMP_PROXY_SERVER")
    if env_proxy:
        return env_proxy

    # ponytail: assumes WARP runs its socks5 listener on the documented default
    # port. Add WARP_PROXY_SOCKS_PORT when a custom port is in use.
    if sys.platform.startswith("linux") and load_config().warp.enabled:
        return "socks5://127.0.0.1:40001"
    return None


def _get_firefox_user_agent() -> str:
    """Return a standard desktop Firefox user-agent."""
    return "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _fetch_otp_from_imap(
    imap_host: str,
    imap_port: int,
    email: str,
    email_password: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> str | None:
    """
    Connect to IMAP and retrieve the 6-digit OTP from email subject 'CMP - YOUR TOKEN'.

    Args:
        imap_host: IMAP server host
        imap_port: IMAP server port (typically 993 for SSL)
        email: Email address
        email_password: Email password
        timeout_seconds: Total time to wait for OTP
        poll_interval_seconds: Time between IMAP polls

    Returns:
        6-digit OTP string or None if not found within timeout
    """
    if not all([imap_host, email, email_password]):
        logger.warning("IMAP credentials incomplete; skipping OTP retrieval")
        return None

    deadline = time.time() + timeout_seconds
    subject_pattern = re.compile(r"CMP\s*-\s*YOUR\s*TOKEN", re.IGNORECASE)
    otp_pattern = re.compile(r"\b(\d{6})\b")

    while time.time() < deadline:
        try:
            with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
                mail.login(email, email_password)
                mail.select("INBOX", readonly=True)

                # Search for recent emails with matching subject
                typ, data = mail.search(None, "SUBJECT", "CMP")
                if typ != "OK" or not data[0]:
                    logger.debug("No emails with 'CMP' in subject found")
                else:
                    # Check most recent emails first
                    email_ids = data[0].split()[-10:]  # Last 10 emails
                    for eid in reversed(email_ids):
                        typ, msg_data = mail.fetch(eid, "(RFC822)")
                        if typ != "OK":
                            continue
                        import email as email_lib

                        msg = email_lib.message_from_bytes(msg_data[0][1])
                        subject = msg.get("Subject", "")
                        if subject_pattern.search(subject):
                            # Search body for 6-digit OTP
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body += part.get_payload(decode=True).decode(
                                            errors="ignore"
                                        )
                            else:
                                body = msg.get_payload(decode=True).decode(errors="ignore")

                            match = otp_pattern.search(body)
                            if match:
                                otp = match.group(1)
                                logger.info("Retrieved OTP from email: %s", otp)
                                return otp
        except (imaplib.IMAP4.error, OSError, UnicodeDecodeError, KeyError) as e:
            logger.debug("IMAP fetch attempt failed: %s", e)

        time.sleep(poll_interval_seconds)

    logger.warning("OTP not found within %d seconds", timeout_seconds)
    return None


def _wait_for_download(page: Page, timeout: int = 60000) -> Path | None:
    """Wait for a download to complete and return the file path."""
    try:
        with page.expect_download(timeout=timeout) as download_info:
            # The download should be triggered by the export button click
            pass
        download = download_info.value
        # Save to a temporary location first
        suggested_name = download.suggested_filename
        temp_path = Path.cwd() / "tmp" / suggested_name
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(temp_path)
        logger.info("Downloaded file: %s", temp_path)
        return temp_path
    except Exception:  # noqa: BLE001
        logger.warning("Download wait failed")
        return None


def _login_cmp(
    page: Page,
    base_url: str,
    username: str,
    password: str,
    timeout: int,
    imap_host: str = "",
    imap_port: int = 993,
    email: str = "",
    email_password: str = "",
    otp_timeout_seconds: int = 120,
    otp_poll_interval_seconds: int = 5,
) -> bool:
    """Login to CMP portal with CAS and OTP handling."""
    try:
        logger.info("Navigating to CMP login: %s", base_url)
        page.goto(base_url, wait_until="commit", timeout=timeout)

        # Wait for login form - CAS login page
        page.wait_for_selector(
            'input[name="username"], input[id="username"], input[type="text"]', timeout=timeout
        )

        # Fill credentials
        page.fill('input[name="username"], input[id="username"], input[type="text"]', username)
        page.fill('input[name="password"], input[id="password"], input[type="password"]', password)

        # Click login button
        page.click(
            'button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Sign In")'
        )

        # Wait for navigation after login - could be OTP page
        page.wait_for_timeout(3000)

        # Check for OTP/2FA page
        token_input_selectors = [
            "input[id='token']",
            "#token",
            "input[name='token']",
            "input[name='otp']",
            "input[placeholder*='Token' i]",
            "input[placeholder*='OTP' i]",
        ]

        otp_page_detected = False
        for sel in token_input_selectors:
            if page.locator(sel).count() > 0:
                otp_page_detected = True
                logger.info("OTP page detected, retrieving OTP via IMAP")
                break

        if otp_page_detected:
            # Retrieve OTP from email
            otp = _fetch_otp_from_imap(
                imap_host=imap_host,
                imap_port=imap_port,
                email=email,
                email_password=email_password,
                timeout_seconds=otp_timeout_seconds,
                poll_interval_seconds=otp_poll_interval_seconds,
            )

            if not otp:
                logger.error("Failed to retrieve OTP from email")
                return False

            # Fill OTP and submit
            for sel in token_input_selectors:
                if page.locator(sel).count() > 0:
                    page.fill(sel, otp)
                    break

            # Click submit/verify button
            page.click("input[name='_eventId_submit']")
            page.wait_for_timeout(3000)
            logger.info("OTP submitted successfully")

        logger.info("CMP login successful")
        return True
    except Exception:
        logger.exception("CMP login failed")
        return False


def _handle_2fa_if_needed(page: Page, timeout: int) -> bool:
    """Handle 2FA if presented (e.g., OTP via email)."""
    try:
        # Check for 2FA/OTP page
        otp_selectors = [
            'input[name="otp"]',
            'input[name="code"]',
            'input[placeholder*="OTP" i]',
            'input[placeholder*="code" i]',
            "#otp",
            "#verificationCode",
        ]
        for sel in otp_selectors:
            if page.locator(sel).count() > 0:
                logger.info("2FA/OTP page detected, but automated OTP retrieval not implemented")
                logger.info("Please implement OTP retrieval via IMAP or manual entry")
                return False
        return True
    except Exception:  # noqa: BLE001
        logger.debug("2FA check error")
        return True


def _navigate_to_dashboard(page: Page, timeout: int) -> bool:
    """Navigate to CMP Dashboard and wait for dashboard container."""
    dashboard_url = "https://ep.iotcc.telkomsel.com/#!dashboard"
    try:
        logger.info("Navigating to CMP Dashboard: %s", dashboard_url)
        page.goto(dashboard_url, wait_until="commit", timeout=timeout)

        # Wait for dashboard container
        dashboard_selectors = [
            ".dashboard-container",
            ".v-dashboard",
            "[class*='dashboard']",
        ]
        for sel in dashboard_selectors:
            try:
                page.wait_for_selector(sel, timeout=10000)
                logger.info("Dashboard container found: %s", sel)
                return True
            except Exception as e:
                logger.debug("Dashboard selector %s not found: %s", sel, e)
                continue

        logger.warning("Dashboard container not found with known selectors")
        return False
    except Exception:
        logger.exception("Navigation to Dashboard failed")
        return False


def _extract_live_usage_from_dashboard(page: Page, timeout: int) -> tuple[str | None, float | None]:
    """
    Extract live total usage value from dashboard DOM.

    Returns:
        Tuple of (raw_text, usage_gb) where usage_gb is the parsed float value in GB
    """
    value_selectors = [
        "div.spark-value.huge",
        "div.v-label-spark-value.huge",
        "div.huge",
        "[class*='spark-value'][class*='huge']",
        "[class*='huge']:has-text('GB')",
    ]

    for sel in value_selectors:
        try:
            elements = page.locator(sel)
            count = elements.count()
            for i in range(count):
                text = elements.nth(i).inner_text(timeout=5000).strip()
                if text and ("GB" in text.upper() or "TB" in text.upper() or "MB" in text.upper()):
                    logger.info("Found live usage value: %s (selector: %s)", text, sel)
                    # Parse the value
                    usage_gb = _parse_usage_to_gb(text)
                    return text, usage_gb
        except Exception as e:
            logger.debug("Error extracting usage with selector %s: %s", sel, e)
            continue

    logger.warning("Live usage value not found on dashboard")
    return None, None


def _parse_usage_to_gb(text: str) -> float | None:
    """Parse usage text like '238.78 GB' or '1.5 TB' to float GB."""
    import re

    text = text.strip().upper().replace(",", "")
    # Match patterns like "238.78 GB", "1.5 TB", "500 MB"
    match = re.search(r"([\d.]+)\s*(TB|GB|MB)", text)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    if unit == "TB":
        return value * 1024
    elif unit == "GB":
        return value
    elif unit == "MB":
        return value / 1024

    return None


def _save_dashboard_screenshot_and_sidecar(
    page: Page,
    output_dir: Path,
    date_compact: str,
    dashboard_text: str | None,
) -> Path | None:
    """
    Take screenshot of dashboard element and save sidecar .txt file.

    Returns:
        Path to screenshot or None if failed
    """
    try:
        # Create output directory: output/raw/iot/{date_compact}/
        iot_raw_dir = output_dir / "raw" / "iot" / date_compact
        iot_raw_dir.mkdir(parents=True, exist_ok=True)

        # Screenshot filename
        screenshot_path = iot_raw_dir / f"dashboard_{date_compact}.png"
        sidecar_path = iot_raw_dir / f"dashboard_{date_compact}.txt"

        # Try to screenshot the dashboard container specifically
        dashboard_selectors = [
            ".dashboard-container",
            ".v-dashboard",
            "[class*='dashboard']",
        ]

        element = None
        for sel in dashboard_selectors:
            loc = page.locator(sel).first
            if loc.count() > 0:
                element = loc
                break

        if element:
            element.screenshot(path=str(screenshot_path))
        else:
            # Fallback: full page screenshot
            page.screenshot(path=str(screenshot_path))

        logger.info("Dashboard screenshot saved to: %s", screenshot_path)

        # Write sidecar file with extracted text
        if dashboard_text:
            sidecar_path.write_text(dashboard_text, encoding="utf-8")
            logger.info("Dashboard sidecar text saved to: %s", sidecar_path)

        return screenshot_path
    except Exception:
        logger.exception("Failed to save dashboard screenshot/sidecar")
        return None


def _navigate_to_usage_query(page: Page, timeout: int) -> bool:
    """Navigate to Reports -> Usage Query page."""
    try:
        # Try various navigation paths
        nav_paths = [
            ("Reports", "Usage Query"),
            ("Laporan", "Query Penggunaan"),
            ("Usage", "Query"),
        ]

        for menu, submenu in nav_paths:
            try:
                # Click main menu
                page.click(f'text="{menu}"', timeout=5000)
                page.wait_for_timeout(1000)
                # Click submenu
                page.click(f'text="{submenu}"', timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout)
                logger.info("Navigated to Usage Query via %s -> %s", menu, submenu)
                return True
            except Exception:  # noqa: BLE001, S112
                continue

        # Fallback: CMP portal uses SPA hash routing, so the fragment
        # (!reports) is never sent to the server and the page stays on the
        # same document. Navigate with wait_until="commit".
        page.goto("https://ep.iotcc.telkomsel.com/#!reports", wait_until="commit", timeout=timeout)
        return True
    except Exception:
        logger.exception("Navigation to Usage Query failed")
        return False


def _set_report_type_and_date(page: Page, report_type: str, target_date: str, timeout: int) -> bool:
    """Set report type (Daily/Monthly) and target date/month."""
    try:
        # Select Report Type dropdown
        type_selectors = [
            'select[name="reportType"]',
            'select[id="reportType"]',
            'select:has(option:has-text("Daily"))',
            'select:has(option:has-text("Monthly"))',
        ]

        for sel in type_selectors:
            if page.locator(sel).count() > 0:
                page.select_option(sel, label=report_type)
                logger.info("Selected Report Type: %s", report_type)
                break
        else:
            logger.warning("Could not find Report Type dropdown")
            return False

        page.wait_for_timeout(1000)

        # Set date/month
        if report_type.lower() == "daily":
            # Daily: set specific date
            date_selectors = [
                'input[name="startDate"]',
                'input[id="startDate"]',
                'input[type="date"]',
                'input[placeholder*="Date" i]',
            ]
            for sel in date_selectors:
                if page.locator(sel).count() > 0:
                    page.fill(sel, target_date)
                    # Also set end date same as start for daily
                    end_sel = sel.replace("start", "end")
                    if page.locator(end_sel).count() > 0:
                        page.fill(end_sel, target_date)
                    logger.info("Set Daily date: %s", target_date)
                    break
        else:
            # Monthly: set month (YYYY-MM)
            month_selectors = [
                'input[name="month"]',
                'input[id="month"]',
                'input[placeholder*="Month" i]',
                'select[name="month"]',
            ]
            for sel in month_selectors:
                if page.locator(sel).count() > 0:
                    if page.locator(sel).evaluate("el => el.tagName") == "SELECT":
                        page.select_option(sel, label=target_date)
                    else:
                        page.fill(sel, target_date)
                    logger.info("Set Monthly period: %s", target_date)
                    break

        return True
    except Exception:
        logger.exception("Failed to set report type/date")
        return False


def _sort_and_export(page: Page, timeout: int) -> Path | None:
    """Sort by Total Data Usage descending and export to XLSX."""
    try:
        # Click Search/Submit
        search_selectors = [
            'button:has-text("Search")',
            'button:has-text("Cari")',
            'button[type="submit"]',
            'input[type="submit"]',
        ]
        for sel in search_selectors:
            if page.locator(sel).count() > 0:
                page.click(sel)
                break
        else:
            logger.warning("Could not find Search button")
            return None

        # Wait for results table
        page.wait_for_selector('table, [role="grid"], .data-table', timeout=timeout)
        page.wait_for_timeout(2000)

        # Sort by Total Data Usage descending
        sort_selectors = [
            'th:has-text("Total Data Usage")',
            'th:has-text("Total Usage")',
            'th:has-text("Data Usage")',
            'th[data-field*="usage" i]',
        ]
        for sel in sort_selectors:
            if page.locator(sel).count() > 0:
                # Click twice for descending
                page.click(sel)
                page.wait_for_timeout(500)
                page.click(sel)
                logger.info("Sorted by Total Data Usage descending")
                break

        # Click Export/Download button
        export_selectors = [
            'button:has-text("Export")',
            'button:has-text("Download")',
            'button:has-text("Ekspor")',
            'a:has-text("Export")',
            'button[id*="export" i]',
            'button[class*="export" i]',
        ]
        for sel in export_selectors:
            if page.locator(sel).count() > 0:
                # Wait for download
                with page.expect_download(timeout=timeout) as download_info:
                    page.click(sel)
                download = download_info.value
                suggested_name = download.suggested_filename
                temp_path = Path.cwd() / "tmp" / suggested_name
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(temp_path)
                logger.info("Exported file: %s", temp_path)
                return temp_path

        logger.warning("Could not find Export button")
        return None
    except Exception:
        logger.exception("Sort and export failed")
        return None


def run_cmp_crawler(
    base_url: str,
    username: str,
    password: str,
    target_date: str,  # YYYY-MM-DD
    target_month: str,  # YYYY-MM
    output_dir: Path,
    headless: bool = True,
    timeout_seconds: int = 60,
    imap_host: str = "",
    imap_port: int = 993,
    email: str = "",
    email_password: str = "",
    otp_timeout_seconds: int = 120,
    otp_poll_interval_seconds: int = 5,
    proxy_server: str = "",
    warp_proxy_server: str = "",
) -> CmpExportResult:
    """
    Run the CMP crawler to export both Daily and Monthly usage reports,
    and extract live dashboard usage.

    Args:
        base_url: CMP portal login URL
        username: CMP username
        password: CMP password
        target_date: Target date for daily report (YYYY-MM-DD)
        target_month: Target month for monthly report (YYYY-MM)
        output_dir: Directory to save exported files
        headless: Run browser in headless mode
        timeout_seconds: Timeout for page operations
        imap_host: IMAP host for OTP email retrieval
        imap_port: IMAP port
        email: Email address for OTP
        email_password: Email password
        otp_timeout_seconds: OTP retrieval timeout
        otp_poll_interval_seconds: OTP polling interval
        proxy_server: Explicit proxy server for CMP (e.g., "socks5://127.0.0.1:40001")
        warp_proxy_server: WARP proxy server from config

    Returns:
        CmpExportResult with paths to downloaded files and live_total_usage_gb
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = timeout_seconds * 1000
    date_compact = target_date.replace("-", "")

    # Resolve proxy server
    resolved_proxy = _resolve_proxy_server(proxy_server, warp_proxy_server)
    if resolved_proxy:
        logger.info("Using proxy server: %s", resolved_proxy)

    with sync_playwright() as p:
        # Use Firefox with standard desktop user-agent to bypass portal restrictions
        launch_args = {"headless": headless}
        if resolved_proxy:
            launch_args["proxy"] = {"server": resolved_proxy}
        browser = p.firefox.launch(**launch_args)
        context = browser.new_context(accept_downloads=True, user_agent=_get_firefox_user_agent())
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        result = CmpExportResult()

        try:
            # Step 1: Login with CAS and OTP handling
            if not _login_cmp(
                page,
                base_url,
                username,
                password,
                timeout_ms,
                imap_host=imap_host,
                imap_port=imap_port,
                email=email,
                email_password=email_password,
                otp_timeout_seconds=otp_timeout_seconds,
                otp_poll_interval_seconds=otp_poll_interval_seconds,
            ):
                result.error = "Login failed"
                return result

            # Step 2: Navigate to Dashboard and extract live usage
            if _navigate_to_dashboard(page, timeout_ms):
                dashboard_text, live_usage_gb = _extract_live_usage_from_dashboard(page, timeout_ms)
                if live_usage_gb is not None:
                    result.live_total_usage_gb = live_usage_gb
                    logger.info("Live total usage extracted: %.2f GB", live_usage_gb)

                # Save screenshot and sidecar
                _save_dashboard_screenshot_and_sidecar(
                    page, output_dir, date_compact, dashboard_text
                )
            else:
                logger.warning("Failed to navigate to dashboard; skipping live usage extraction")

            # Step 3: Handle 2FA if needed (fallback check)
            if not _handle_2fa_if_needed(page, timeout_ms):
                result.error = "2FA required but not automated"
                return result

            # Step 4: Navigate to Usage Query
            if not _navigate_to_usage_query(page, timeout_ms):
                result.error = "Navigation to Usage Query failed"
                return result

            # --- Daily Export ---
            logger.info("Starting Daily export for %s", target_date)
            if _set_report_type_and_date(page, "Daily", target_date, timeout_ms):
                daily_temp = _sort_and_export(page, timeout_ms)
                if daily_temp and daily_temp.exists():
                    # Move to output directory with standardized name
                    final_name = f"report_{date_compact}_DAILY_USAGE_by_SIM.xlsx"
                    final_path = output_dir / final_name
                    daily_temp.rename(final_path)
                    result.daily_file = final_path
                    logger.info("Daily export saved to: %s", final_path)

            # --- Monthly Export ---
            logger.info("Starting Monthly export for %s", target_month)
            if _set_report_type_and_date(page, "Monthly", target_month, timeout_ms):
                monthly_temp = _sort_and_export(page, timeout_ms)
                if monthly_temp and monthly_temp.exists():
                    # Move to output directory with standardized name
                    final_name = f"report_{target_month.replace('-', '')}_MONTHLY_USAGE_by_SIM.xlsx"
                    final_path = output_dir / final_name
                    monthly_temp.rename(final_path)
                    result.monthly_file = final_path
                    logger.info("Monthly export saved to: %s", final_path)

        except Exception:
            logger.exception("CMP crawler failed")
            result.error = "Crawler failed"
        finally:
            context.close()
            browser.close()

    return result
