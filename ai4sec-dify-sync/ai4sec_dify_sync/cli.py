from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .ai4sec_reader import AI4SecReader
from .config import load_settings
from .dify_client import DifyClient, DifyConfig
from .state import StateStore
from .syncer import Syncer


BASE_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = load_settings(BASE_DIR)
    store = StateStore(settings.state_db)

    if args.command == "status":
        _status(store, args.paper_id, args.status, args.limit)
        return

    if args.command == "retry":
        count = store.reset_failed(args.paper_id)
        print(f"reset {count} failed sync(s)")
        return

    if not settings.dataset_id:
        raise SystemExit("DIFY_DATASET_ID or DIFY_DEFAULT_DATASET_ID is required")

    reader = AI4SecReader(settings.ai4sec_data_dir, settings.ai4sec_app_db)
    client = DifyClient(
        DifyConfig(
            dataset_id=settings.dataset_id,
            base_url=settings.dify_base_url,
            dataset_api_key=settings.dify_dataset_api_key,
            proxy_base_url=settings.dify_proxy_base_url,
            timeout_seconds=settings.timeout_seconds,
            indexing_technique=settings.indexing_technique,
            process_rule_mode=settings.process_rule_mode,
        )
    )
    syncer = Syncer(
        reader=reader,
        store=store,
        client=client,
        dataset_id=settings.dataset_id,
        max_attempts=settings.max_attempts,
        max_text_chars=settings.max_text_chars,
        dry_run=args.dry_run,
    )

    if args.command == "once":
        results = asyncio.run(syncer.sync_once(args.paper_id, retry_failed=args.retry_failed))
        for result in results:
            suffix = f" doc={result.document_id}" if result.document_id else ""
            message = f" {result.message}" if result.message else ""
            print(f"{result.paper_id}\t{result.status}{suffix}{message}")
        return

    if args.command == "watch":
        interval = args.interval or settings.poll_interval_seconds
        asyncio.run(syncer.watch(interval))
        return

    raise SystemExit(f"unknown command: {args.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai4sec-dify-sync")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    once = sub.add_parser("once", help="scan and sync ready papers once")
    once.add_argument("--paper-id", default="", help="sync only one paper_id")
    once.add_argument("--retry-failed", action="store_true", help="retry failed rows even if unchanged")
    once.add_argument("--dry-run", action="store_true", help="build text and hash without uploading")

    watch = sub.add_parser("watch", help="poll AI4Sec output and sync continuously")
    watch.add_argument("--interval", type=float, default=0.0, help="poll interval in seconds")
    watch.add_argument("--dry-run", action="store_true", help="build text and hash without uploading")

    status = sub.add_parser("status", help="show sync status rows")
    status.add_argument("--paper-id", default="", help="filter by paper_id")
    status.add_argument("--status", default="", help="filter by status")
    status.add_argument("--limit", type=int, default=50)

    retry = sub.add_parser("retry", help="reset failed rows to pending")
    retry.add_argument("--paper-id", default="", help="reset one paper_id")
    retry.set_defaults(dry_run=False)

    return parser


def _status(store: StateStore, paper_id: str, status: str, limit: int) -> None:
    rows = store.list(paper_id=paper_id, status=status, limit=limit)
    if not rows:
        print("no sync rows")
        return
    for row in rows:
        print(
            "\t".join(
                [
                    row.paper_id,
                    row.dataset_id,
                    row.status,
                    str(row.attempts),
                    row.source_hash[:12],
                    row.dify_document_id,
                    row.updated_at,
                    row.error_msg.replace("\n", " ")[:200],
                ]
            ).rstrip()
        )


if __name__ == "__main__":
    main()
