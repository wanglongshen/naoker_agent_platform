"""Idempotent repair for legacy runs with completed answer but no run_succeeded event.

Usage:
    cd backend
    PYTHONPATH=. python scripts/reconcile_completed_agent_runs.py          # dry-run
    PYTHONPATH=. python scripts/reconcile_completed_agent_runs.py --apply  # reconcile

Default (no flags) enumerates eligible run IDs and prints count only.
Never prints answer text.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reconcile_completed_agent_runs")


def _get_db_url() -> str:
    from app.core.config import get_settings

    settings = get_settings()
    return settings.test_database_url or settings.database_url


async def _reconcile(apply: bool = False) -> dict[str, int]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.repositories.agent_repository import AgentRepository

    db_url = _get_db_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    stats = {"eligible": 0, "reconciled": 0, "errors": 0}

    try:
        async with session_factory() as s:
            repo = AgentRepository(s)
            run_ids = await repo.find_reconcilable_completed_answer_run_ids()
            stats["eligible"] = len(run_ids)
            logger.info("Found %d eligible runs", len(run_ids))

            if not apply:
                if run_ids:
                    for rid in run_ids:
                        logger.info("eligible run_id=%s", rid)

        if apply:
            for run_id in run_ids:
                try:
                    async with session_factory() as s:
                        repo = AgentRepository(s)
                        run = await repo.get_run(run_id)
                        old_status = run.status if run else "unknown"

                        result = await repo.reconcile_completed_answer_run(run_id)
                        if result:
                            await s.commit()
                            run = await repo.get_run(run_id)
                            source_seq = (
                                run.result.get("source_event_sequence")
                                if run and run.result
                                else None
                            )
                            stats["reconciled"] += 1
                            logger.info(
                                "reconciled run_id=%s old_status=%s source_seq=%s action=succeeded",
                                run_id,
                                old_status,
                                source_seq,
                            )
                        else:
                            logger.info(
                                "skipped run_id=%s old_status=%s action=not_eligible",
                                run_id,
                                old_status,
                            )
                except Exception:
                    stats["errors"] += 1
                    logger.exception("Error reconciling run_id=%s", run_id)

    finally:
        await engine.dispose()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile runs with completed answers but no run_succeeded event"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply reconciliation (default: dry-run, print eligible count)",
    )
    args = parser.parse_args()

    stats = asyncio.run(_reconcile(apply=args.apply))

    logger.info(
        "Reconciliation complete: eligible=%d reconciled=%d errors=%d",
        stats["eligible"],
        stats["reconciled"],
        stats["errors"],
    )

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
