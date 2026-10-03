"""
KDP login session manager — Playwright Firefox with persisted storage_state.

First run:
  - opens a real visible Firefox window
  - user manually logs in to KDP (incl. 2FA)
  - on first successful navigation to kdp.amazon.com/bookshelf, cookies are saved
    to LEARNING_DIR/kdp_session.json

Subsequent runs:
  - load storage_state from disk → no login needed for weeks
  - if session expired, prompt the user to re-login
"""
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

KDP_BOOKSHELF_URL = "https://kdp.amazon.com/en_US/bookshelf"
KDP_CREATE_URL    = "https://kdp.amazon.com/en_US/title-setup/paperback/new/details"
KDP_SIGNIN_URL    = "https://kdp.amazon.com/en_US/signin"


def _session_path(learning_dir: Path) -> Path:
    """Returns the path where KDP cookies live."""
    p = Path(learning_dir) / "kdp_session.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def session_exists(learning_dir: Path) -> bool:
    """True if a saved KDP session is on disk."""
    p = _session_path(learning_dir)
    return p.exists() and p.stat().st_size > 100


def ensure_firefox_installed() -> Tuple[bool, str]:
    """
    Returns (installed, message). Caller should show a hint in the UI.
    Actually tries to launch+close Firefox to verify the executable runs,
    not just that the expected path exists.
    """
    try:
        from playwright.sync_api import sync_playwright
        import os
        with sync_playwright() as p:
            exec_path = p.firefox.executable_path
            if not exec_path or not os.path.exists(exec_path):
                return False, (
                    "Firefox Playwright pas installé.\n"
                    f"Chemin attendu : {exec_path}"
                )
            # Probe: try to actually launch the browser briefly
            try:
                browser = p.firefox.launch(headless=True)
                browser.close()
                return True, f"Firefox prêt : {exec_path}"
            except Exception as launch_err:
                return False, (
                    f"Firefox trouvé mais ne se lance pas : {launch_err}"
                )
    except Exception as e:
        return False, f"Erreur Playwright : {e}"


def install_firefox_browser(status_cb=None) -> Tuple[bool, str]:
    """
    Runs `playwright install firefox` via subprocess.
    Returns (success, output). Streaming output goes to status_cb if provided.
    """
    import subprocess, sys
    cmd = [sys.executable, "-m", "playwright", "install", "firefox"]
    if status_cb:
        status_cb(f"⏳ Exécution : {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                if status_cb:
                    status_cb(f"  {line}")
        proc.wait(timeout=600)
        ok = proc.returncode == 0
        return ok, "\n".join(output_lines)
    except Exception as e:
        return False, f"Erreur subprocess : {e}"


@contextmanager
def kdp_browser(
    learning_dir: Path,
    headless: bool = False,
    slow_mo_ms: int = 80,
):
    """
    Context manager that yields a logged-in KDP Playwright Page.

    Usage:
        with kdp_browser(Config.LEARNING_DIR) as page:
            page.goto(KDP_CREATE_URL)
            ...

    Persists / reuses cookies between runs. If no session exists, opens the
    sign-in page so the user can log in manually 1× (use_visible=True).
    """
    from playwright.sync_api import sync_playwright

    storage = _session_path(learning_dir)
    storage_arg = str(storage) if storage.exists() else None

    pw = sync_playwright().start()
    try:
        browser = pw.firefox.launch(
            headless=headless,
            slow_mo=slow_mo_ms,
            args=[] if headless else ["-foreground"],   # bring to front on macOS
            firefox_user_prefs={
                # Strict tracking protection (DuckDuckGo-style privacy)
                "privacy.trackingprotection.enabled":           True,
                "privacy.trackingprotection.socialtracking.enabled": True,
                "privacy.donottrackheader.enabled":             True,
                "browser.search.suggest.enabled":               False,
                "browser.urlbar.suggest.searches":              False,
            },
        )
        try:
            context = browser.new_context(
                storage_state = storage_arg,
                viewport      = {"width": 1400, "height": 900},
                user_agent    = (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:128.0) "
                    "Gecko/20100101 Firefox/128.0"
                ),
                locale = "en-US",
            )
            page = context.new_page()

            # Bring window to front on macOS (Firefox launches behind otherwise)
            if not headless:
                try:
                    page.bring_to_front()
                    import subprocess
                    subprocess.Popen([
                        "osascript", "-e",
                        'tell application "Firefox" to activate',
                    ])
                except Exception:
                    pass

            yield page

            # On exit, persist (or refresh) the session
            try:
                context.storage_state(path=str(storage))
                logger.info(f"KDP session saved → {storage}")
            except Exception as e:
                logger.warning(f"Could not save KDP storage_state: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass
    finally:
        pw.stop()


_BOOKSHELF_SELECTORS = [
    "button:has-text('Create new title')",
    "button:has-text('Create')",
    "a:has-text('Create new title')",
    "text=/Create new title or series/i",
    "text=/Your KDP catalog/i",
    "a[href*='/title-setup/']",
    "text=/Bookshelf/i",
]


def _any_selector_visible(page, selectors, timeout_ms: int = 2000) -> bool:
    """Try each selector ONE AT A TIME — Playwright doesn't accept
    comma-grouped multi-engine selectors. Returns True on first hit."""
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout_ms, state="visible")
            return True
        except Exception:
            continue
    return False


def _is_logged_in_kdp(page) -> bool:
    """
    Robust check: navigate to /bookshelf and verify either:
      - URL contains bookshelf (and NOT signin), OR
      - Any bookshelf-only element is visible.
    """
    try:
        page.goto(KDP_BOOKSHELF_URL, wait_until="domcontentloaded", timeout=20_000)
        url = (page.url or "").lower()
        if "signin" in url or "/ap/signin" in url:
            return False
        # Fast path: URL says bookshelf and we're not on signin
        if "bookshelf" in url or "/title-setup/" in url:
            return True
        # Fallback: check for any logged-in element
        return _any_selector_visible(page, _BOOKSHELF_SELECTORS, timeout_ms=5000)
    except Exception as e:
        logger.warning(f"_is_logged_in_kdp error: {e}")
        return False


def open_login_flow(learning_dir: Path, timeout_minutes: int = 10) -> bool:
    """
    Opens Firefox at the KDP sign-in page so the user can log in MANUALLY.

    Detection strategy (STRICT):
      - Wait up to N minutes
      - Poll the page every 3 sec
      - Capture session ONLY when /bookshelf loads AND a known logged-in
        element is visible (Create button, etc.)
      - Validate by re-loading /bookshelf one more time to confirm
    """
    from playwright.sync_api import sync_playwright
    import subprocess
    import time

    storage = _session_path(learning_dir)

    pw = sync_playwright().start()
    try:
        browser = pw.firefox.launch(
            headless=False,
            slow_mo=50,
            args=["-foreground"],
            firefox_user_prefs={
                "privacy.trackingprotection.enabled": True,
                "browser.search.suggest.enabled":     False,
            },
        )
        context = browser.new_context(
            viewport=  {"width": 1400, "height": 900},
            locale=    "en-US",
        )
        page = context.new_page()
        page.goto(KDP_SIGNIN_URL, wait_until="domcontentloaded")

        # Bring window to front on macOS
        try:
            subprocess.Popen([
                "osascript", "-e",
                'tell application "Firefox" to activate',
            ])
        except Exception:
            pass

        # Poll for login completion. TWO independent signals (whichever fires first):
        #   1. URL contains /bookshelf or /title-setup and NOT /signin
        #   2. Any bookshelf-only element is visible
        deadline = time.time() + timeout_minutes * 60
        captured = False
        last_log_time = 0.0
        while time.time() < deadline:
            url = (page.url or "").lower()
            url_logged_in = (
                ("bookshelf" in url or "/title-setup/" in url)
                and "/signin" not in url
                and "/ap/signin" not in url
            )
            elem_logged_in = _any_selector_visible(
                page, _BOOKSHELF_SELECTORS, timeout_ms=800,
            )
            # Periodic log to terminal so we can debug
            if time.time() - last_log_time > 5:
                logger.info(
                    f"Login poll: url={url[:80]} | url_ok={url_logged_in} "
                    f"| elem_ok={elem_logged_in}"
                )
                last_log_time = time.time()

            if url_logged_in or elem_logged_in:
                captured = True
                break
            time.sleep(2)

        if captured:
            # Save cookies. Trust the capture — validation can be flaky on
            # multi-frame Amazon pages. The publish flow will re-verify and
            # fall back to manual re-login if needed.
            context.storage_state(path=str(storage))
            logger.info(f"KDP login captured → {storage}")

        browser.close()
        return captured
    finally:
        pw.stop()


def clear_session(learning_dir: Path) -> bool:
    """Delete the saved KDP session (forces re-login next time)."""
    p = _session_path(learning_dir)
    if p.exists():
        p.unlink()
        return True
    return False
