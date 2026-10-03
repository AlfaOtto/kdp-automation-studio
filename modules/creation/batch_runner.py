"""
Background batch runner — survives Streamlit page navigation.

PROBLEM:
  Streamlit reruns the entire script on every interaction. If a user clicks
  Settings while a 5-minute batch is running in Creation, the script dies and
  the batch is lost. session_state can't help because the script execution
  itself is interrupted.

SOLUTION:
  Run the batch in a daemon Thread that lives in module memory (not in
  Streamlit's per-rerun script context). Module globals persist across all
  reruns and pages, so the thread keeps working even when the user navigates
  away. When they return to Creation page, the UI reads the module state and
  displays current progress / final results.

USAGE:
  start_batch_in_background(niches=..., anthropic_key=..., ...)
  state = get_batch_state()
  if state["running"]: show progress
  if state["results"]: show results
"""
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Module-level state — shared across all Streamlit reruns + pages.
# Each key is intentionally simple and thread-safe-by-design (single writer).
_BATCH_STATE: Dict = {
    "running":      False,
    "started_at":   None,
    "finished_at":  None,
    "progress":     0,
    "log":          [],        # rolling list of status messages
    "results":      None,      # final list of result dicts
    "error":        None,      # string error if batch crashed
    "thread":       None,      # the actual Thread object (internal)
    "niches":       [],        # niches being processed
    "cancelled":    False,
}

_LOG_LOCK = threading.Lock()   # log list is the only multi-writer field


def get_batch_state() -> Dict:
    """Returns the live state dict (NOT a copy — read-only intended)."""
    return _BATCH_STATE


def is_running() -> bool:
    return bool(_BATCH_STATE.get("running"))


def reset_batch_state() -> None:
    """Forces a clean state. Use when user clicks 'Reset' on a stuck batch."""
    _BATCH_STATE.update({
        "running":     False,
        "started_at":  None,
        "finished_at": None,
        "progress":    0,
        "log":         [],
        "results":     None,
        "error":       None,
        "thread":      None,
        "niches":      [],
        "cancelled":   False,
    })


def cancel_batch() -> None:
    """Signals the batch to stop after the current product."""
    _BATCH_STATE["cancelled"] = True


def start_batch_in_background(
    *,
    niches: List[str],
    anthropic_key: str,
    openai_key: str,
    output_dir: Path,
    learning_dir: Optional[Path] = None,
    excluded_variants: Optional[List[str]] = None,
    use_interior_images: bool = True,
    format_override: Optional[Dict] = None,   # {trim_size_w, trim_size_h, paper_type}
    generate_aplus: bool = True,
    highcontent_item_images: bool = False,
    make_epub: bool = False,
) -> bool:
    """
    Starts a background thread running run_batch with the given parameters.
    Returns True on success, False if a batch is already running.
    """
    if is_running():
        logger.warning("Refusing to start batch — another is already running")
        return False

    # Reset state for fresh run
    reset_batch_state()
    _BATCH_STATE["running"]    = True
    _BATCH_STATE["started_at"] = time.time()
    _BATCH_STATE["niches"]     = list(niches)

    def _status_cb(msg: str) -> None:
        with _LOG_LOCK:
            _BATCH_STATE["log"].append(msg)
            # Keep log to a reasonable size
            if len(_BATCH_STATE["log"]) > 500:
                _BATCH_STATE["log"] = _BATCH_STATE["log"][-300:]

    def _progress_cb(v: float) -> None:
        try:
            _BATCH_STATE["progress"] = min(100, max(0, int(v)))
        except Exception:
            pass

    def _runner() -> None:
        try:
            # Import here to avoid circular imports at module load time
            from modules.creation.batch import run_batch
            results = run_batch(
                niches              = niches,
                anthropic_key       = anthropic_key,
                openai_key          = openai_key,
                output_dir          = output_dir,
                status_cb           = _status_cb,
                progress_cb         = _progress_cb,
                learning_dir        = learning_dir,
                excluded_variants   = excluded_variants,
                use_interior_images = use_interior_images,
                format_override     = format_override,
                generate_aplus      = generate_aplus,
                highcontent_item_images = highcontent_item_images,
                make_epub           = make_epub,
            )
            _BATCH_STATE["results"] = results
        except Exception as e:
            logger.exception("Batch background thread crashed")
            _BATCH_STATE["error"] = str(e)
            with _LOG_LOCK:
                _BATCH_STATE["log"].append(f"❌ Erreur fatale : {e}")
        finally:
            _BATCH_STATE["running"]     = False
            _BATCH_STATE["finished_at"] = time.time()
            _BATCH_STATE["progress"]    = 100

    thread = threading.Thread(target=_runner, daemon=True, name="kdp-batch")
    _BATCH_STATE["thread"] = thread
    thread.start()
    logger.info(f"Background batch started for {len(niches)} niche(s)")
    return True


def elapsed_seconds() -> float:
    """Returns seconds since the current (or last) batch started. 0 if none."""
    start = _BATCH_STATE.get("started_at")
    if not start:
        return 0.0
    end = _BATCH_STATE.get("finished_at") or time.time()
    return max(0.0, end - start)
