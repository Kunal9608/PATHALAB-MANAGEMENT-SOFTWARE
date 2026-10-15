"""Staff router."""
from fastapi import APIRouter, Depends, UploadFile, File, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin
from backend.app.schemas.staff import StaffCreate, StaffUpdate
from backend.app.services import staff_service, face_service

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("")
def list_staff(
    include_inactive: bool = False,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return staff_service.list_staff(
        db, include_inactive=include_inactive, q=q,
        is_active=is_active, page=page, page_size=page_size,
    )


@router.post("")
def create_staff(payload: StaffCreate, background_tasks: BackgroundTasks, admin=Depends(require_admin),
                 db: Session = Depends(get_db)):
    return staff_service.create_staff(db, payload, admin.id, background_tasks)


@router.get("/{staff_id}")
def get_staff(staff_id: str, current_user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    import uuid
    from fastapi import HTTPException
    from backend.app.models.user import RoleEnum

    target_uuid = uuid.UUID(staff_id)
    if current_user.role != RoleEnum.admin and current_user.id != target_uuid:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to view this staff member's profile"
        )
    return staff_service.get_staff(db, target_uuid)


@router.patch("/{staff_id}")
def update_staff(staff_id: str, payload: StaffUpdate,
                 admin=Depends(require_admin), db: Session = Depends(get_db)):
    import uuid
    return staff_service.update_staff(db, uuid.UUID(staff_id), payload, admin.id)


@router.delete("/{staff_id}")
def deactivate_staff(staff_id: str, admin=Depends(require_admin),
                     db: Session = Depends(get_db)):
    import uuid
    return staff_service.deactivate_staff(db, uuid.UUID(staff_id), admin.id)


@router.post("/{staff_id}/face-enroll")
async def face_enroll(staff_id: str, image: UploadFile = File(...),
                      current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    import uuid
    from fastapi import HTTPException
    from backend.app.models.user import RoleEnum
    
    target_uuid = uuid.UUID(staff_id)
    if current_user.role != RoleEnum.admin and current_user.id != target_uuid:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to enroll face data for this staff member"
        )
    
    # Read file bytes
    image_bytes = await image.read()

    # Perform multi-layer image validation
    from backend.app.core.upload_security import validate_file_upload
    allowed_image_exts = (".jpg", ".jpeg", ".png", ".webp")
    try:
        validate_file_upload(
            file_bytes=image_bytes,
            filename=image.filename,
            max_size=10 * 1024 * 1024,  # 10MB
            allowed_extensions=allowed_image_exts
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    return face_service.enroll_sample(db, target_uuid, image_bytes)
