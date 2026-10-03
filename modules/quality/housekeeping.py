"""
Housekeeping utilities — auto-rotate debug files, prune old screenshots,
keep the repo from bloating over time.

Called once at app startup. Safe to run repeatedly.
"""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def prune_old_files(folder: Path, max_age_days: int, pattern: str = "*") -> int:
    """Delete files matching `pattern` in `folder` older than max_age_days.
    Returns the number of files deleted."""
    folder = Path(folder)
    if not folder.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for p in folder.rglob(pattern):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                deleted += 1
        except Exception:
            continue
    return deleted


def run_housekeeping(project_root: Path, learning_dir: Path) -> dict:
    """
    Periodic cleanup:
      - debug/ : keep last 7 days only
      - publishing_snaps/ : keep last 14 days only
      - cover_thumbs/ : keep all (small, fast lookup)
      - kdp_continue_now.flag : delete if stale (>1 hour)
    """
    project_root = Path(project_root)
    learning_dir = Path(learning_dir)
    stats = {}

    # Old debug chunks
    debug_dir = project_root / "output" / "debug"
    stats["debug_pruned"] = prune_old_files(debug_dir, max_age_days=7)

    # Old publishing screenshots
    snap_dir = learning_dir / "publishing_snaps"
    stats["snap_pruned"] = prune_old_files(snap_dir, max_age_days=14)

    # Stale continue-flag (if previous publish crashed without consuming)
    flag = learning_dir / "kdp_continue_now.flag"
    if flag.exists() and flag.stat().st_mtime < time.time() - 3600:
        try:
            flag.unlink()
            stats["stale_flag_deleted"] = True
        except Exception:
            pass

    return stats
