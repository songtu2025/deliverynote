"""批次交货文件与自营收货入库文件的 HTTP 入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, File, UploadFile, status
from sqlalchemy.orm import Session

from .batch_file_edits import BatchFileEditor
from .batch_file_uploads import BatchFileUploader
from .dependencies import RequestDependencies
from .models import User
from .schemas import FileOrderPayload


def register_batch_file_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    uploader: BatchFileUploader,
    editor: BatchFileEditor,
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.post("/api/self-operated-batches/{batch_id}/inbound-file")
    async def upload_self_operated_inbound_file(
        batch_id: int,
        file: UploadFile = File(...),
        user: User = Depends(current_user),
        session: Session = Depends(get_session),
    ):
        return await uploader.replace_inbound(session, batch_id, file, user.id)

    @app.post(
        "/api/batches/{batch_id}/files",
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_batch_file(
        batch_id: int,
        file: UploadFile = File(...),
        user: User = Depends(current_user),
        session: Session = Depends(get_session),
    ):
        return await uploader.append(session, batch_id, file, user.id)

    @app.delete("/api/batches/{batch_id}/files/{file_id}")
    def delete_batch_file(
        batch_id: int,
        file_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return editor.delete(session, batch_id, file_id, user.id)

    @app.put("/api/batches/{batch_id}/files/order")
    def reorder_batch_files(
        batch_id: int,
        payload: FileOrderPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return editor.reorder(session, batch_id, payload, user.id)
