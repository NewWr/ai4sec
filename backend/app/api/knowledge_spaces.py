from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    KnowledgeSpaceDifyDatasetCreateRequest,
    KnowledgeSpaceDifyDatasetResponse,
    KnowledgeSpaceDifyDocumentsResponse,
    KnowledgeSpaceDifyMarkdownResponse,
    KnowledgeSpaceItemCopyRequest,
    KnowledgeSpaceItemMoveRequest,
    KnowledgeSpaceItemRemoveRequest,
    KnowledgeSpaceItemResyncRequest,
    KnowledgeSpaceItemResponse,
    KnowledgeSpaceItemUpdateRequest,
    KnowledgeSpaceItemsResponse,
    KnowledgeSpaceResponse,
    KnowledgeSpacesResponse,
    KnowledgeSpaceUpdateRequest,
)
from app.rate_limit import limiter
from app.services import knowledge_spaces as spaces
from app.services.dify_client import DifyError

router = APIRouter(tags=["knowledge-spaces"])


def _bad_request(exc: ValueError) -> HTTPException:
    msg = str(exc)
    status = 404 if "not found" in msg.lower() else 400
    return HTTPException(status_code=status, detail=msg)


def _dify_error(exc: DifyError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "message": exc.message,
            "upstream_status": exc.upstream_status,
            "upstream_detail": exc.detail,
        },
    )


@router.get("/knowledge-spaces", response_model=KnowledgeSpacesResponse)
@limiter.limit("60/minute")
async def list_knowledge_spaces(request: Request):
    del request
    return KnowledgeSpacesResponse(
        spaces=[KnowledgeSpaceResponse(**row) for row in await spaces.list_spaces()]
    )


@router.get("/knowledge-spaces/{space_id}/items", response_model=KnowledgeSpaceItemsResponse)
@limiter.limit("60/minute")
async def list_knowledge_space_items(
    request: Request,
    space_id: str,
    item_kind: str = "",
    limit: int = 100,
    offset: int = 0,
):
    del request
    try:
        return KnowledgeSpaceItemsResponse(
            space=KnowledgeSpaceResponse(**await spaces.get_space(space_id)),
            items=[
                KnowledgeSpaceItemResponse(**row)
                for row in await spaces.list_space_items(
                    space_id,
                    item_kind=item_kind,
                    limit=limit,
                    offset=offset,
                )
            ],
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/knowledge-spaces/{space_id}", response_model=KnowledgeSpaceResponse)
@limiter.limit("30/minute")
async def update_knowledge_space(request: Request, space_id: str, req: KnowledgeSpaceUpdateRequest):
    del request
    try:
        return KnowledgeSpaceResponse(**await spaces.update_space(space_id, req.model_dump(exclude_unset=True)))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge-spaces/{space_id}/dify-dataset", response_model=KnowledgeSpaceDifyDatasetResponse)
@limiter.limit("10/minute")
async def create_knowledge_space_dify_dataset(
    request: Request,
    space_id: str,
    req: KnowledgeSpaceDifyDatasetCreateRequest,
):
    del request
    try:
        return KnowledgeSpaceDifyDatasetResponse(
            **await spaces.create_dify_dataset_for_space(
                space_id,
                name=req.name,
                indexing_technique=req.indexing_technique,
                permission=req.permission,
            )
        )
    except DifyError as exc:
        raise _dify_error(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/knowledge-spaces/{space_id}/dify-documents", response_model=KnowledgeSpaceDifyDocumentsResponse)
@limiter.limit("60/minute")
async def list_knowledge_space_dify_documents(
    request: Request,
    space_id: str,
    page: int = 1,
    limit: int = 20,
):
    del request
    try:
        return KnowledgeSpaceDifyDocumentsResponse(
            **await spaces.list_space_dify_documents(space_id, page=page, limit=limit)
        )
    except DifyError as exc:
        raise _dify_error(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get(
    "/knowledge-spaces/{space_id}/dify-documents/{document_id}/markdown",
    response_model=KnowledgeSpaceDifyMarkdownResponse,
)
@limiter.limit("30/minute")
async def get_knowledge_space_dify_markdown(request: Request, space_id: str, document_id: str):
    del request
    try:
        return KnowledgeSpaceDifyMarkdownResponse(
            **await spaces.get_space_dify_markdown(space_id, document_id)
        )
    except DifyError as exc:
        raise _dify_error(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge-spaces/items/move", response_model=KnowledgeSpaceItemResponse)
@limiter.limit("30/minute")
async def move_knowledge_space_item(request: Request, req: KnowledgeSpaceItemMoveRequest):
    del request
    try:
        return KnowledgeSpaceItemResponse(
            **await spaces.move_item(
                space_id=req.space_id,
                item_kind=req.item_kind,
                item_id=req.item_id,
                target_space_id=req.target_space_id,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge-spaces/items/copy", response_model=KnowledgeSpaceItemResponse)
@limiter.limit("30/minute")
async def copy_knowledge_space_item(request: Request, req: KnowledgeSpaceItemCopyRequest):
    del request
    try:
        return KnowledgeSpaceItemResponse(
            **await spaces.copy_item(
                space_id=req.space_id,
                item_kind=req.item_kind,
                item_id=req.item_id,
                target_space_id=req.target_space_id,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge-spaces/items/remove", status_code=204)
@limiter.limit("30/minute")
async def remove_knowledge_space_item(request: Request, req: KnowledgeSpaceItemRemoveRequest):
    del request
    try:
        await spaces.remove_item(
            space_id=req.space_id,
            item_kind=req.item_kind,
            item_id=req.item_id,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return None


@router.patch("/knowledge-spaces/items/update", response_model=KnowledgeSpaceItemResponse)
@limiter.limit("30/minute")
async def update_knowledge_space_item(request: Request, req: KnowledgeSpaceItemUpdateRequest):
    del request
    try:
        return KnowledgeSpaceItemResponse(
            **await spaces.update_item(
                space_id=req.space_id,
                item_kind=req.item_kind,
                item_id=req.item_id,
                updates=req.model_dump(exclude={"space_id", "item_kind", "item_id"}, exclude_unset=True),
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/knowledge-spaces/items/resync", response_model=KnowledgeSpaceItemResponse)
@limiter.limit("10/minute")
async def resync_knowledge_space_item(request: Request, req: KnowledgeSpaceItemResyncRequest):
    del request
    try:
        return KnowledgeSpaceItemResponse(
            **await spaces.resync_item(
                space_id=req.space_id,
                item_kind=req.item_kind,
                item_id=req.item_id,
                force=req.force,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
