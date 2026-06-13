from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .ai4sec_reader import AI4SecReader, PaperSource
from .dify_client import DifyClient
from .document import SourceDocument, build_from_blocks, build_from_paper_ir
from .state import StateStore

logger = logging.getLogger("ai4sec_dify_sync")


@dataclass(frozen=True)
class SyncResult:
    paper_id: str
    status: str
    message: str = ""
    document_id: str = ""


class Syncer:
    def __init__(
        self,
        reader: AI4SecReader,
        store: StateStore,
        client: DifyClient,
        dataset_id: str,
        max_attempts: int = 5,
        max_text_chars: int = 0,
        dry_run: bool = False,
    ) -> None:
        self.reader = reader
        self.store = store
        self.client = client
        self.dataset_id = dataset_id
        self.max_attempts = max_attempts
        self.max_text_chars = max_text_chars
        self.dry_run = dry_run

    async def sync_once(self, paper_id: str = "", retry_failed: bool = False) -> list[SyncResult]:
        sources = self.reader.list_ready_papers()
        if paper_id:
            sources = [source for source in sources if source.paper_id == paper_id]
        results: list[SyncResult] = []
        for source in sources:
            result = await self.sync_source(source, retry_failed=retry_failed)
            results.append(result)
        return results

    async def watch(self, interval_seconds: float) -> None:
        while True:
            try:
                results = await self.sync_once()
                changed = [result for result in results if result.status not in {"skipped", "ignored"}]
                if changed:
                    for result in changed:
                        logger.info("%s %s %s", result.paper_id, result.status, result.message)
                else:
                    logger.info("no pending changes")
            except Exception:
                logger.exception("sync loop failed")
            await asyncio.sleep(interval_seconds)

    async def sync_source(self, source: PaperSource, retry_failed: bool = False) -> SyncResult:
        try:
            document = self._build_document(source)
        except Exception as exc:
            self.store.mark_failed(source.paper_id, self.dataset_id, "", str(exc))
            return SyncResult(source.paper_id, "failed", str(exc))

        if not document.text:
            self.store.mark_failed(source.paper_id, self.dataset_id, document.source_hash, "empty document text")
            return SyncResult(source.paper_id, "failed", "empty document text")

        existing = self.store.get(source.paper_id, self.dataset_id)
        if (
            existing
            and existing.status in {"synced", "skipped"}
            and existing.source_hash == document.source_hash
            and not retry_failed
        ):
            return SyncResult(source.paper_id, "skipped", "source unchanged", existing.dify_document_id)

        if (
            existing
            and existing.status == "failed"
            and existing.source_hash == document.source_hash
            and existing.attempts >= self.max_attempts
            and not retry_failed
        ):
            return SyncResult(source.paper_id, "ignored", f"max attempts reached: {existing.attempts}")

        if self.dry_run:
            return SyncResult(
                source.paper_id,
                "dry-run",
                f"{len(document.text)} chars hash={document.source_hash[:12]}",
            )

        self.store.mark_pending(source.paper_id, self.dataset_id, document.source_hash)

        try:
            self.store.mark_running(source.paper_id, self.dataset_id, document.source_hash)
            doc_id = await self.client.create_document_by_text(document.name, document.text)
            self.store.mark_synced(source.paper_id, self.dataset_id, document.source_hash, doc_id)
            return SyncResult(source.paper_id, "synced", document.name, doc_id)
        except Exception as exc:
            self.store.mark_failed(source.paper_id, self.dataset_id, document.source_hash, str(exc))
            return SyncResult(source.paper_id, "failed", str(exc))

    def _build_document(self, source: PaperSource) -> SourceDocument:
        title = source.title or self.reader.read_title_from_db(source.paper_id)
        if source.paper_ir_path and source.paper_ir_path.exists():
            return build_from_paper_ir(
                source.paper_id,
                source.paper_ir_path,
                fallback_title=title,
                max_chars=self.max_text_chars,
            )
        blocks = self.reader.read_blocks_from_db(source.paper_id)
        return build_from_blocks(
            source.paper_id,
            blocks,
            fallback_title=title,
            max_chars=self.max_text_chars,
        )
