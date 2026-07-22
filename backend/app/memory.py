from __future__ import annotations

import logging
import resource

logger = logging.getLogger("uvicorn.error")


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes. Render is Linux.
    return round(usage / 1024, 2) if usage > 10_000 else round(usage / (1024 * 1024), 2)


def log_memory(stage: str) -> None:
    logger.info("\n=== Memory Diagnostics ===\nstage: %s\nrss_mb: %.2f", stage, rss_mb())
