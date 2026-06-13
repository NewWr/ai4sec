from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import sqlite3
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from app.config import get_settings
from app.db import database as db
from app.services.http_clients import get_default_http_client

logger = logging.getLogger("scholar.mineru")

_MAX_ZIP_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
_MAX_ZIP_MEMBERS = 100_000  # guard against archives with an absurd file count
_mineru_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mineru")
_cancel_events: dict[str, threading.Event] = {}
_cancel_events_lock = threading.Lock()


class MinerUPollTimeoutError(TimeoutError):
    def __init__(
        self,
        batch_id: str,
        elapsed_s: float,
        poll_count: int,
        last_state_counts: dict[str, int],
        timeout_s: int,
    ) -> None:
        self.batch_id = batch_id
        self.elapsed_s = elapsed_s
        self.poll_count = poll_count
        self.last_state_counts = last_state_counts
        self.timeout_s = timeout_s
        super().__init__(
            "MinerU batch timed out "
            f"batch={batch_id} elapsed={elapsed_s:.0f}s timeout={timeout_s}s "
            f"polls={poll_count} last_states={last_state_counts}. "
            "The remote MinerU task may still finish later; retry this paper after checking parse status."
        )


class MinerUCancelledError(RuntimeError):
    pass


def cancel_parse(parse_id: str) -> bool:
    parse_id = (parse_id or "").strip()
    if not parse_id:
        return False
    with _cancel_events_lock:
        event = _cancel_events.get(parse_id)
    if event is None:
        return False
    event.set()
    return True


def _register_cancel_event(parse_id: str) -> threading.Event:
    event = threading.Event()
    with _cancel_events_lock:
        _cancel_events[parse_id] = event
    return event


def _unregister_cancel_event(parse_id: str) -> None:
    with _cancel_events_lock:
        _cancel_events.pop(parse_id, None)


def _safe_zip_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip with path-traversal and zip-bomb protection.

    Path traversal is rejected up front. The uncompressed-size limit is then
    enforced against the *actual* bytes written during extraction — the declared
    ``file_size`` in the central directory can be forged, so a pre-check on it
    alone is bypassable; streaming each member and counting real bytes is not.
    """
    dest_resolved = dest.resolve()
    members = zf.infolist()
    if len(members) > _MAX_ZIP_MEMBERS:
        raise ValueError(f"Zip has too many members ({len(members)} > {_MAX_ZIP_MEMBERS})")

    # Pass 1: reject absolute paths / traversal before writing anything.
    for info in members:
        member_path = (dest / info.filename).resolve()
        if not member_path.is_relative_to(dest_resolved):
            raise ValueError(f"Zip path traversal detected: {info.filename}")

    # Pass 2: stream each member, capping total bytes actually written.
    size_limit_mb = _MAX_ZIP_EXTRACTED_SIZE // (1024 * 1024)
    written_total = 0
    for info in members:
        target = dest / info.filename
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                written_total += len(chunk)
                if written_total > _MAX_ZIP_EXTRACTED_SIZE:
                    raise ValueError(f"Zip extracted size exceeds limit ({size_limit_mb} MB)")
                out.write(chunk)


class MinerUClient:
    """Async-friendly MinerU API client. Reimplemented to avoid importing
    paper_converter which has heavy dependencies (mineru_clean_markdown)."""

    def __init__(self, token: str, api_base: str):
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = 60
        self.retries = 8
        self.backoff = 2.0
        self.max_sleep = 120.0

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _compute_sleep(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return max(0.0, min(float(retry_after), self.max_sleep))
        jitter = 0.7 + random.random() * 0.6
        return max(0.5, min(self.max_sleep, (self.backoff ** attempt) * jitter))

    async def _request_json(
        self, method: str, url: str, json_body: Optional[dict] = None
    ) -> dict[str, Any]:
        retryable = {408, 425, 429, 500, 502, 503, 504}
        http_client = get_default_http_client()

        for attempt in range(self.retries + 1):
            try:
                resp = await http_client.request(
                    method,
                    url,
                    headers=self.headers,
                    json=json_body,
                    timeout=self.timeout,
                )
                if resp.status_code in retryable and attempt < self.retries:
                    await asyncio.sleep(self._compute_sleep(attempt))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception:
                if attempt == self.retries:
                    raise
                await asyncio.sleep(self._compute_sleep(attempt))
        raise RuntimeError(f"Request failed: {url}")

    async def create_upload_urls_batch_async(
        self, files: list[dict[str, Any]], model_version: str = "vlm"
    ) -> tuple[str, list[str]]:
        payload = {"files": files, "model_version": model_version}
        data = await self._request_json("POST", f"{self.api_base}/file-urls/batch", payload)
        if data.get("code") != 0:
            raise RuntimeError(f"create_upload_urls_batch failed: {data}")
        return data["data"]["batch_id"], data["data"]["file_urls"]

    async def get_batch_results_async(self, batch_id: str) -> dict[str, Any]:
        data = await self._request_json("GET", f"{self.api_base}/extract-results/batch/{batch_id}")
        if data.get("code") != 0:
            raise RuntimeError(f"get_batch_results failed: {data}")
        return data["data"]
async def _put_upload(upload_url: str, file_path: Path) -> None:
    """Upload file to presigned URL with async httpx. No Content-Type header."""
    retryable = {408, 425, 429, 500, 502, 503, 504}
    http_client = get_default_http_client()

    for attempt in range(7):
        try:
            response = await http_client.put(
                upload_url,
                content=_file_byte_stream(file_path),
                headers={"Content-Length": str(file_path.stat().st_size)},
                timeout=600,
            )
            if response.status_code in retryable and attempt < 6:
                jitter = 0.7 + random.random() * 0.6
                await asyncio.sleep(max(0.5, min(120.0, (2.0 ** attempt) * jitter)))
                continue
            if response.status_code not in (200, 201):
                raise RuntimeError(f"Upload HTTP {response.status_code}: {response.text[:200]}")
            return
        except Exception:
            if attempt >= 6:
                raise
            await asyncio.sleep(max(0.5, min(120.0, (2.0 ** attempt) * 0.9)))
    raise RuntimeError(f"Upload failed: {file_path.name}")


async def _file_byte_stream(file_path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    with open(file_path, "rb") as f:
        while True:
            chunk = await loop.run_in_executor(_mineru_pool, f.read, chunk_size)
            if not chunk:
                return
            yield chunk


async def _download_file(url: str, out_path: Path) -> None:
    """Download file with async httpx retry and atomic write."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    retryable = {408, 425, 429, 500, 502, 503, 504}
    http_client = get_default_http_client()
    loop = asyncio.get_running_loop()

    for attempt in range(7):
        try:
            async with http_client.stream("GET", url, timeout=300) as response:
                if response.status_code in retryable and attempt < 6:
                    await response.aclose()
                    await asyncio.sleep(max(0.5, min(120.0, (2.0 ** attempt) * 0.9)))
                    continue
                response.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            await loop.run_in_executor(_mineru_pool, f.write, chunk)
            tmp.replace(out_path)
            return
        except Exception:
            tmp.unlink(missing_ok=True)
            if attempt >= 6:
                raise
            await asyncio.sleep(max(0.5, min(120.0, (2.0 ** attempt) * 0.9)))
    raise RuntimeError(f"Download failed: {url}")


def _update_parse_poll_sync(
    parse_id: str,
    *,
    remote_batch_id: str = "",
    poll_count: int | None = None,
    state_counts: dict[str, int] | None = None,
) -> None:
    if not parse_id:
        return

    assignments = ["updated_at = datetime('now')"]
    params: list[Any] = []
    if remote_batch_id:
        assignments.append("remote_batch_id = ?")
        params.append(remote_batch_id)
    if poll_count is not None:
        assignments.append("poll_count = ?")
        params.append(poll_count)
    if state_counts is not None:
        assignments.append("last_state_counts = ?")
        params.append(json.dumps(state_counts, ensure_ascii=True))
        assignments.append("last_poll_at = datetime('now')")

    params.append(parse_id)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db.get_db_path(), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            f"UPDATE mineru_parses SET {', '.join(assignments)} WHERE parse_id = ?",
            params,
        )
        conn.commit()
    except Exception as exc:
        logger.debug("MinerU poll metadata update skipped parse_id=%s: %s", parse_id, exc)
    finally:
        if conn is not None:
            conn.close()


def _poll_until_done_sync(
    client: Any,
    batch_id: str,
    sleep_s: int = 6,
    timeout_s: int = 3600,
    *,
    time_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_poll: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Poll MinerU batch until all tasks are done or failed."""
    from collections import Counter
    t0 = time_fn()
    poll_count = 0
    last_state_counts: dict[str, int] = {}
    while True:
        poll_count += 1
        data = client.get_batch_results(batch_id)
        results = data.get("extract_result") or data.get("extract_results") or []
        if results:
            states = [r.get("state") for r in results]
            last_state_counts = dict(Counter(states))
            elapsed_s = time_fn() - t0
            if on_poll:
                on_poll({
                    "batch_id": batch_id,
                    "poll_count": poll_count,
                    "state_counts": last_state_counts,
                    "elapsed_s": elapsed_s,
                })
            if poll_count % 5 == 1:  # Log every 5th poll to avoid spam
                logger.info(
                    f"MinerU poll #{poll_count} batch={batch_id}: "
                    f"{last_state_counts} ({elapsed_s:.0f}s elapsed)"
                )
            if all(s in ("done", "failed") for s in states):
                logger.info(
                    f"MinerU poll DONE after {poll_count} polls in "
                    f"{elapsed_s:.0f}s: {last_state_counts}"
                )
                return results
        else:
            elapsed_s = time_fn() - t0
            if on_poll:
                on_poll({
                    "batch_id": batch_id,
                    "poll_count": poll_count,
                    "state_counts": {},
                    "elapsed_s": elapsed_s,
                })
        if elapsed_s >= timeout_s:
            raise MinerUPollTimeoutError(
                batch_id=batch_id,
                elapsed_s=elapsed_s,
                poll_count=poll_count,
                last_state_counts=last_state_counts,
                timeout_s=timeout_s,
            )
        if cancel_event is not None:
            if cancel_event.wait(sleep_s):
                raise MinerUCancelledError("Cancelled by user")
        else:
            sleep_fn(sleep_s)


def _is_cancelled(cancel_event: threading.Event | tuple[threading.Event, ...] | None) -> bool:
    if cancel_event is None:
        return False
    if isinstance(cancel_event, tuple):
        return any(event.is_set() for event in cancel_event)
    return cancel_event.is_set()


async def _sleep_or_cancel(
    cancel_event: threading.Event | tuple[threading.Event, ...] | None,
    sleep_s: float,
) -> None:
    if cancel_event is None:
        await asyncio.sleep(sleep_s)
        return
    deadline = time.monotonic() + sleep_s
    while True:
        if _is_cancelled(cancel_event):
            raise MinerUCancelledError("Cancelled by user")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.2, remaining))


async def _poll_until_done(
    client: MinerUClient,
    batch_id: str,
    sleep_s: int = 6,
    timeout_s: int = 3600,
    *,
    time_fn: Callable[[], float] = time.time,
    on_poll: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | tuple[threading.Event, ...] | None = None,
) -> list[dict[str, Any]]:
    """Async poll MinerU batch until all tasks are done or failed."""
    from collections import Counter

    t0 = time_fn()
    poll_count = 0
    last_state_counts: dict[str, int] = {}
    while True:
        poll_count += 1
        data = await client.get_batch_results_async(batch_id)
        results = data.get("extract_result") or data.get("extract_results") or []
        if results:
            states = [r.get("state") for r in results]
            last_state_counts = dict(Counter(states))
            elapsed_s = time_fn() - t0
            if on_poll:
                on_poll({
                    "batch_id": batch_id,
                    "poll_count": poll_count,
                    "state_counts": last_state_counts,
                    "elapsed_s": elapsed_s,
                })
            if poll_count % 5 == 1:
                logger.info(
                    f"MinerU poll #{poll_count} batch={batch_id}: "
                    f"{last_state_counts} ({elapsed_s:.0f}s elapsed)"
                )
            if all(s in ("done", "failed") for s in states):
                logger.info(
                    f"MinerU poll DONE after {poll_count} polls in "
                    f"{elapsed_s:.0f}s: {last_state_counts}"
                )
                return results
        else:
            elapsed_s = time_fn() - t0
            if on_poll:
                on_poll({
                    "batch_id": batch_id,
                    "poll_count": poll_count,
                    "state_counts": {},
                    "elapsed_s": elapsed_s,
                })
        if elapsed_s >= timeout_s:
            raise MinerUPollTimeoutError(
                batch_id=batch_id,
                elapsed_s=elapsed_s,
                poll_count=poll_count,
                last_state_counts=last_state_counts,
                timeout_s=timeout_s,
            )
        await _sleep_or_cancel(cancel_event, sleep_s)


def _get_client() -> MinerUClient:
    settings = get_settings()
    return MinerUClient(token=settings.mineru_token, api_base=settings.mineru_api_base)


def _raise_if_cancelled(cancel_event: threading.Event | tuple[threading.Event, ...] | None) -> None:
    if _is_cancelled(cancel_event):
        raise MinerUCancelledError("Cancelled by user")


def _extract_zip_to_dir(zip_path: Path, extract_dir: Path) -> int:
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        _safe_zip_extract(zf, extract_dir)
    return sum(1 for _ in extract_dir.rglob("*") if _.is_file())


async def parse_pdf(paper_id: str, parse_id: str) -> Path:
    """Parse a single PDF via MinerU batch API. Returns the output directory."""
    settings = get_settings()
    paper_dir = settings.data_dir / "papers" / paper_id
    pdf_path = paper_dir / "original.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = paper_dir / "mineru" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    await db.execute(
        "UPDATE mineru_parses SET status = 'running', updated_at = datetime('now') WHERE parse_id = ?",
        (parse_id,),
    )

    cancel_event = _register_cancel_event(parse_id)
    try:
        result_dir = await _parse_pdf_async(pdf_path, output_dir, paper_id, parse_id, cancel_event)
        await db.execute(
            "UPDATE mineru_parses SET status = 'done', output_dir = ?, updated_at = datetime('now') WHERE parse_id = ?",
            (str(result_dir), parse_id),
        )
        return result_dir
    except MinerUCancelledError as e:
        await db.execute(
            "UPDATE mineru_parses SET status = 'failed', error_msg = 'Cancelled by user', updated_at = datetime('now') WHERE parse_id = ?",
            (parse_id,),
        )
        raise e
    except asyncio.CancelledError:
        await db.execute(
            "UPDATE mineru_parses SET status = 'failed', error_msg = 'Cancelled by user', updated_at = datetime('now') WHERE parse_id = ? AND status IN ('pending', 'running')",
            (parse_id,),
        )
        raise
    except Exception as e:
        await db.execute(
            "UPDATE mineru_parses SET status = 'failed', error_msg = ?, updated_at = datetime('now') WHERE parse_id = ?",
            (str(e), parse_id),
        )
        raise
    finally:
        _unregister_cancel_event(parse_id)


async def _parse_pdf_async(
    pdf_path: Path,
    output_dir: Path,
    paper_id: str,
    parse_id: str,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Async MinerU parsing; only local zip extraction uses the MinerU thread pool."""
    t_total = time.perf_counter()
    settings = get_settings()
    client = _get_client()
    data_id = paper_id[:20]
    files_payload = [{"name": pdf_path.name, "data_id": data_id}]

    t0 = time.perf_counter()
    batch_id, upload_urls = await client.create_upload_urls_batch_async(
        files=files_payload,
        model_version=settings.mineru_model_version,
    )
    _update_parse_poll_sync(parse_id, remote_batch_id=batch_id)
    logger.info(f"[{paper_id}] MinerU create_upload_urls: {time.perf_counter()-t0:.2f}s batch_id={batch_id}")

    _raise_if_cancelled(cancel_event)
    t0 = time.perf_counter()
    size_mb = pdf_path.stat().st_size / 1024 / 1024
    await _put_upload(upload_urls[0], pdf_path)
    logger.info(f"[{paper_id}] MinerU upload: {time.perf_counter()-t0:.2f}s ({size_mb:.1f} MB)")

    _raise_if_cancelled(cancel_event)
    t0 = time.perf_counter()
    results = await _poll_until_done(
        client,
        batch_id,
        sleep_s=max(1, settings.mineru_poll_interval_seconds),
        timeout_s=max(1, settings.mineru_parse_timeout_seconds),
        cancel_event=cancel_event,
        on_poll=lambda event: _update_parse_poll_sync(
            parse_id,
            remote_batch_id=batch_id,
            poll_count=int(event["poll_count"]),
            state_counts=event["state_counts"],
        ),
    )
    logger.info(f"[{paper_id}] MinerU poll: {time.perf_counter()-t0:.1f}s (remote processing)")

    for r in results:
        if r.get("state") == "failed":
            raise RuntimeError(f"MinerU parse failed: {r.get('err_msg', 'unknown')}")

        zip_url = r.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("No zip URL in MinerU response")

        _raise_if_cancelled(cancel_event)
        t0 = time.perf_counter()
        zip_path = output_dir / f"{data_id}.zip"
        await _download_file(zip_url, zip_path)
        zip_mb = zip_path.stat().st_size / 1024 / 1024
        logger.info(f"[{paper_id}] MinerU download: {time.perf_counter()-t0:.2f}s ({zip_mb:.1f} MB)")

        _raise_if_cancelled(cancel_event)
        t0 = time.perf_counter()
        extract_dir = output_dir / data_id
        loop = asyncio.get_running_loop()
        n_files = await loop.run_in_executor(_mineru_pool, _extract_zip_to_dir, zip_path, extract_dir)
        logger.info(f"[{paper_id}] MinerU extract: {time.perf_counter()-t0:.2f}s ({n_files} files)")

        logger.info(f"[{paper_id}] MinerU TOTAL: {time.perf_counter()-t_total:.1f}s")
        return extract_dir

    raise RuntimeError("No results from MinerU batch")


async def parse_pdf_batch(paper_ids: list[str], parse_ids: list[str]) -> list[Path]:
    """Parse multiple PDFs in a single MinerU batch."""
    settings = get_settings()

    pdf_paths: list[Path] = []
    data_ids: list[str] = []
    files_payload: list[dict[str, Any]] = []

    for paper_id in paper_ids:
        paper_dir = settings.data_dir / "papers" / paper_id
        pdf_path = paper_dir / "original.pdf"
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        data_id = paper_id[:20]
        pdf_paths.append(pdf_path)
        data_ids.append(data_id)
        files_payload.append({"name": pdf_path.name, "data_id": data_id})

    for parse_id in parse_ids:
        await db.execute(
            "UPDATE mineru_parses SET status = 'running', updated_at = datetime('now') WHERE parse_id = ?",
            (parse_id,),
        )

    cancel_events = tuple(_register_cancel_event(parse_id) for parse_id in parse_ids)
    try:
        client = _get_client()
        batch_id, upload_urls = await client.create_upload_urls_batch_async(
            files=files_payload,
            model_version=settings.mineru_model_version,
        )
        for parse_id in parse_ids:
            _update_parse_poll_sync(parse_id, remote_batch_id=batch_id)
        _raise_if_cancelled(cancel_events)

        await asyncio.gather(*[
            _put_upload(path, upload_url)
            for path, upload_url in zip(pdf_paths, upload_urls)
        ])
        _raise_if_cancelled(cancel_events)

        def _on_batch_poll(event: dict[str, Any]) -> None:
            for parse_id in parse_ids:
                _update_parse_poll_sync(
                    parse_id,
                    remote_batch_id=batch_id,
                    poll_count=int(event["poll_count"]),
                    state_counts=event["state_counts"],
                )

        results = await _poll_until_done(
            client,
            batch_id,
            sleep_s=max(1, settings.mineru_poll_interval_seconds),
            timeout_s=max(1, settings.mineru_batch_timeout_seconds),
            cancel_event=cancel_events,
            on_poll=_on_batch_poll,
        )

        result_dirs: list[Path] = []
        loop = asyncio.get_running_loop()
        for r, pid, did in zip(results, paper_ids, data_ids):
            out = settings.data_dir / "papers" / pid / "mineru" / "raw"
            out.mkdir(parents=True, exist_ok=True)

            if r.get("state") == "failed":
                result_dirs.append(out)
                continue

            zip_url = r.get("full_zip_url")
            if not zip_url:
                result_dirs.append(out)
                continue

            _raise_if_cancelled(cancel_events)
            zp = out / f"{did}.zip"
            await _download_file(zip_url, zp)

            _raise_if_cancelled(cancel_events)
            ed = out / did
            await loop.run_in_executor(_mineru_pool, _extract_zip_to_dir, zp, ed)
            result_dirs.append(ed)
    except MinerUCancelledError:
        await db.execute_many(
            "UPDATE mineru_parses SET status = 'failed', error_msg = 'Cancelled by user', updated_at = datetime('now') WHERE parse_id = ?",
            [(parse_id,) for parse_id in parse_ids],
        )
        raise
    except asyncio.CancelledError:
        await db.execute_many(
            "UPDATE mineru_parses SET status = 'failed', error_msg = 'Cancelled by user', updated_at = datetime('now') WHERE parse_id = ? AND status IN ('pending', 'running')",
            [(parse_id,) for parse_id in parse_ids],
        )
        raise
    finally:
        for parse_id in parse_ids:
            _unregister_cancel_event(parse_id)

    for parse_id, result_dir in zip(parse_ids, result_dirs):
        has_content = (result_dir / "content_list.json").exists() or list(result_dir.glob("**/content_list.json"))
        if has_content:
            await db.execute(
                "UPDATE mineru_parses SET status = 'done', output_dir = ?, updated_at = datetime('now') WHERE parse_id = ?",
                (str(result_dir), parse_id),
            )
        else:
            await db.execute(
                "UPDATE mineru_parses SET status = 'failed', error_msg = 'No content_list.json found', updated_at = datetime('now') WHERE parse_id = ?",
                (parse_id,),
            )

    return result_dirs
