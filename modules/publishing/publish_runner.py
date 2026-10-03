"""
Background runner for KDP publishing — Streamlit-friendly.

Same pattern as batch_runner.py: spawns a daemon thread, exposes state via
module globals. UI polls state every rerun without blocking.

KEY FEATURE: user can signal "I'm done with the manual step, continue NOW"
by calling signal_continue(). The publish_to_kdp_draft polling loops detect
this flag immediately and stop waiting.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Module-level state — survives Streamlit reruns (singleton)
_STATE: Dict = {
    "running":     False,
    "started_at":  None,
    "finished_at": None,
    "log":         [],
    "result":      None,
    "error":       None,
    "current_step": "",
}
_LOG_LOCK = threading.Lock()


CONTINUE_FLAG_NAME = "kdp_continue_now.flag"


# ── State accessors ──────────────────────────────────────────────────────────

def is_running() -> bool:
    return bool(_STATE.get("running"))


def get_state() -> Dict:
    """Returns a snapshot of state for the UI to render."""
    with _LOG_LOCK:
        return {
            "running":      _STATE.get("running", False),
            "log":          list(_STATE.get("log") or []),
            "result":       _STATE.get("result"),
            "error":        _STATE.get("error"),
            "current_step": _STATE.get("current_step", ""),
            "started_at":   _STATE.get("started_at"),
            "finished_at":  _STATE.get("finished_at"),
        }


def reset_state() -> None:
    with _LOG_LOCK:
        _STATE.update({
            "running": False, "started_at": None, "finished_at": None,
            "log": [], "result": None, "error": None, "current_step": "",
        })


# ── Continue signal (manual override) ────────────────────────────────────────

def _flag_path(learning_dir: Path) -> Path:
    return Path(learning_dir) / CONTINUE_FLAG_NAME


def signal_continue(learning_dir: Path) -> None:
    """UI writes this flag. Polling loops in uploader.py check and break."""
    p = _flag_path(learning_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(time.time()))
    logger.info(f"Continue signal written → {p}")


def was_signalled(learning_dir: Path, consume: bool = True) -> bool:
    """True if the user clicked 'Continue' since last consumption."""
    p = _flag_path(learning_dir)
    if not p.exists():
        return False
    if consume:
        try:
            p.unlink()
        except Exception:
            pass
    return True


def clear_signal(learning_dir: Path) -> None:
    """Force-clear any pending signal."""
    p = _flag_path(learning_dir)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


# ── Runner ───────────────────────────────────────────────────────────────────

def start_publish(
    *,
    listing:      Dict,
    interior_pdf: Path,
    cover_pdf:    Path,
    learning_dir: Path,
    headless:     bool = False,
) -> bool:
    """Start publication in a daemon thread. Returns True if started, False if busy."""
    if is_running():
        logger.warning("Refusing to start publish — another is already running")
        return False

    reset_state()
    clear_signal(learning_dir)   # avoid stale signal from previous run
    _STATE["running"]    = True
    _STATE["started_at"] = time.time()

    def _push(msg: str) -> None:
        with _LOG_LOCK:
            _STATE["log"].append(msg)
            if len(_STATE["log"]) > 300:
                _STATE["log"] = _STATE["log"][-200:]
            # Heuristic: track current step
            low = msg.lower()
            if "étape 1" in low or "step 1" in low or "détails" in low:
                _STATE["current_step"] = "details"
            elif "étape 2" in low or "step 2" in low or "contenu" in low or "manuscript" in low:
                _STATE["current_step"] = "content"
            elif "étape 3" in low or "step 3" in low or "pricing" in low or "prix" in low:
                _STATE["current_step"] = "pricing"
            elif "login" in low or "session" in low:
                _STATE["current_step"] = "login"

    def _runner() -> None:
        try:
            # Late import to avoid circular load
            from modules.publishing.uploader import publish_to_kdp_draft
            result = publish_to_kdp_draft(
                listing      = listing,
                interior_pdf = interior_pdf,
                cover_pdf    = cover_pdf,
                learning_dir = learning_dir,
                status_cb    = _push,
                headless     = headless,
            )
            _STATE["result"] = {
                "success":         result.success,
                "step_reached":    result.step_reached,
                "screenshot_path": str(result.screenshot_path) if result.screenshot_path else None,
                "error_message":   result.error_message,
                "draft_url":       result.draft_url,
            }
        except Exception as e:
            logger.exception("Publish thread crashed")
            _STATE["error"] = str(e)
            _push(f"❌ Erreur fatale : {e}")
        finally:
            _STATE["running"]     = False
            _STATE["finished_at"] = time.time()

    threading.Thread(target=_runner, daemon=True, name="kdp-publish").start()
    return True
