"""
Workspace garbage collector.

Deletes workspace subdirectories older than TTL to prevent unbounded disk
growth from repeated simulation runs. Safe by default: only removes immediate
children of the workspace directory, never the workspace itself, and checks
is_relative_to to avoid traversing symlinks outside.
"""

import logging
import shutil
import time
from pathlib import Path
from typing import Union

logger = logging.getLogger("siliconscribe.cleanup")


def cleanup_old_workspaces(
    workspace: Union[str, Path] = "./workspace",
    ttl_hours: int = 24,
) -> int:
    """
    Delete subdirectories of `workspace` whose mtime is older than `ttl_hours`.

    Returns number of directories removed.
    """
    ws = Path(workspace).resolve()
    if not ws.exists() or not ws.is_dir():
        logger.info("cleanup: workspace %s does not exist or not a dir", ws)
        return 0

    if not isinstance(ttl_hours, int) or ttl_hours < 1:
        raise ValueError("ttl_hours must be >= 1")
    if ttl_hours > 720:
        raise ValueError("ttl_hours must be <= 720")
    now = time.time()
    ttl_seconds = ttl_hours * 3600
    removed = 0

    for child in list(ws.iterdir()):
        # Only consider directories; skip files at top level
        try:
            if not child.is_dir():
                continue
            # Ensure child is actually inside workspace (no symlink escape)
            try:
                if not child.resolve().is_relative_to(ws):
                    logger.warning("cleanup: skipping %s outside workspace", child)
                    continue
            except AttributeError:
                try:
                    child.resolve().relative_to(ws)
                except ValueError:
                    logger.warning("cleanup: skipping %s outside workspace", child)
                    continue

            mtime = child.stat().st_mtime
            age_hours = (now - mtime) / 3600
            if (now - mtime) > ttl_seconds:
                logger.info("cleanup: removing %s (age %.1fh > %dh)", child, age_hours, ttl_hours)
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except Exception as e:
            logger.exception("cleanup: failed to process %s: %s", child, e)
            continue

    logger.info("cleanup: removed %d workspaces from %s", removed, ws)
    return removed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up old workspace directories")
    parser.add_argument("--workspace", default="./workspace", help="Workspace directory")
    parser.add_argument("--ttl-hours", type=int, default=24, help="TTL in hours before deletion")
    parser.add_argument("--dry-run", action="store_true", help="Only list candidates, do not delete")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dry_run:
        ws = Path(args.workspace).resolve()
        now = time.time()
        ttl = args.ttl_hours * 3600
        for child in ws.iterdir() if ws.exists() else []:
            if child.is_dir():
                age = (now - child.stat().st_mtime) / 3600
                if age * 3600 > ttl:
                    print(f"would remove {child} age {age:.1f}h")
        else:
            print("no candidates")
    else:
        n = cleanup_old_workspaces(args.workspace, ttl_hours=args.ttl_hours)
        print(f"removed {n} directories")
