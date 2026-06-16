from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.services.http_clients import get_default_http_client


class PaperNotesClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperNotesFile:
    path: str
    sha: str
    size: int
    html_url: str
    raw_url: str


class PaperNotesClient:
    def __init__(
        self,
        *,
        owner: str = "",
        repo: str = "",
        branch: str = "",
        docs_path: str = "",
        token: str = "",
    ) -> None:
        settings = get_settings()
        self.owner = owner or settings.paper_notes_repo_owner
        self.repo = repo or settings.paper_notes_repo_name
        self.branch = branch or settings.paper_notes_branch
        self.docs_path = (docs_path or settings.paper_notes_docs_path).strip("/")
        self.token = token or settings.paper_notes_github_token
        self.client = get_default_http_client()

    async def latest_commit_sha(self) -> str:
        data = await self._get_json(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/commits/{self.branch}"
        )
        sha = str((data.get("sha") if isinstance(data, dict) else "") or "")
        if not sha:
            raise PaperNotesClientError("GitHub commit response did not include sha")
        return sha

    async def list_markdown_files(self, *, max_files: int = 0) -> list[PaperNotesFile]:
        commit_sha = await self.latest_commit_sha()
        tree = await self._get_json(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/git/trees/{commit_sha}?recursive=1"
        )
        if isinstance(tree, dict) and tree.get("truncated"):
            return await self._list_markdown_files_from_contents(commit_sha, max_files=max_files)
        items = tree.get("tree") if isinstance(tree, dict) else None
        if not isinstance(items, list):
            raise PaperNotesClientError("GitHub tree response did not include tree")
        files: list[PaperNotesFile] = []
        prefix = f"{self.docs_path}/" if self.docs_path else ""
        for item in items:
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = str(item.get("path") or "")
            if not self._is_note_markdown(path, prefix):
                continue
            low = path.lower()
            sha = str(item.get("sha") or "")
            raw_url = f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{commit_sha}/{path}"
            html_url = f"https://github.com/{self.owner}/{self.repo}/blob/{commit_sha}/{path}"
            files.append(
                PaperNotesFile(
                    path=path,
                    sha=sha,
                    size=int(item.get("size") or 0),
                    html_url=html_url,
                    raw_url=raw_url,
                )
            )
            if max_files > 0 and len(files) >= max_files:
                break
        return files

    async def _list_markdown_files_from_contents(self, commit_sha: str, *, max_files: int = 0) -> list[PaperNotesFile]:
        files: list[PaperNotesFile] = []
        prefix = f"{self.docs_path}/" if self.docs_path else ""
        queue = [self.docs_path]
        while queue:
            path = queue.pop(0).strip("/")
            encoded_path = quote(path, safe="/")
            suffix = f"/{encoded_path}" if encoded_path else ""
            data = await self._get_json(
                f"https://api.github.com/repos/{self.owner}/{self.repo}/contents{suffix}?ref={commit_sha}"
            )
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_path = str(item.get("path") or "")
                item_type = str(item.get("type") or "")
                low = item_path.lower()
                if item_type == "dir":
                    if low.endswith("/assets") or low.endswith("/asset"):
                        continue
                    queue.append(item_path)
                    continue
                if item_type != "file" or not self._is_note_markdown(item_path, prefix):
                    continue
                raw_url = str(item.get("download_url") or "")
                if not raw_url:
                    raw_url = f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{commit_sha}/{quote(item_path, safe='/')}"
                html_url = str(item.get("html_url") or "")
                if not html_url:
                    html_url = f"https://github.com/{self.owner}/{self.repo}/blob/{commit_sha}/{quote(item_path, safe='/')}"
                files.append(
                    PaperNotesFile(
                        path=item_path,
                        sha=str(item.get("sha") or ""),
                        size=int(item.get("size") or 0),
                        html_url=html_url,
                        raw_url=raw_url,
                    )
                )
                if max_files > 0 and len(files) >= max_files:
                    return files
        return files

    def _is_note_markdown(self, path: str, prefix: str) -> bool:
        low = path.lower()
        return (
            path.startswith(prefix)
            and low.endswith(".md")
            and "/assets/" not in low
            and "/asset/" not in low
            and not low.endswith("/readme.md")
        )

    async def fetch_markdown(self, raw_url: str) -> str:
        try:
            resp = await self.client.get(raw_url, headers=self._headers(), timeout=30.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PaperNotesClientError(f"GitHub raw fetch failed: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise PaperNotesClientError(f"GitHub raw fetch failed: {exc}") from exc
        return resp.text

    async def _get_json(self, url: str) -> Any:
        try:
            resp = await self.client.get(url, headers=self._headers(), timeout=30.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:300]
            raise PaperNotesClientError(f"GitHub API {status}: {detail}") from exc
        except httpx.RequestError as exc:
            raise PaperNotesClientError(f"GitHub API request failed: {exc}") from exc
        return resp.json()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AI4Sec Paper-Notes radar/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
