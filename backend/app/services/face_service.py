"""Face recognition service — embedding, matching, enrollment gate."""
import json
import logging
import uuid
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.app.repositories import attendance_repo, user_repo
from backend.app.config import settings

logger = logging.getLogger(__name__)

try:
    import face_recognition as fr_lib
    FACE_RECOGNITION_AVAILABLE = True
except (ImportError, Exception, SystemExit):
    fr_lib = None
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning("face_recognition library not operational — biometric face recognition is disabled")


def _compute_embedding(image_bytes: bytes) -> Optional[np.ndarray]:
    """Return 128-dim face embedding or None if face recognition is unavailable or no face found."""
    if not FACE_RECOGNITION_AVAILABLE or fr_lib is None:
        return None

    import io
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)
        face_locations = fr_lib.face_locations(img_array, model="hog")
        if len(face_locations) != 1:
            return None
        encodings = fr_lib.face_encodings(img_array, face_locations)
        if not encodings:
            return None
        return encodings[0]
    except Exception as e:
        logger.error(f"Face embedding error: {e}")
        return None


def _embedding_to_storage(embedding: np.ndarray):
    """Convert numpy array to storage format depending on pgvector availability."""
    from backend.app.models.face_embedding import VECTOR_AVAILABLE
    if VECTOR_AVAILABLE:
        return embedding.tolist()
    else:
        return json.dumps(embedding.tolist())


def _storage_to_embedding(stored) -> np.ndarray:
    """Convert stored value back to numpy array."""
    if isinstance(stored, str):
        return np.array(json.loads(stored), dtype=np.float32)
    elif isinstance(stored, list):
        return np.array(stored, dtype=np.float32)
    return np.array(stored, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def enroll_sample(db: Session, user_id: uuid.UUID, image_bytes: bytes) -> dict:
    """Biometric face enrollment is intentionally disabled in PathLab OS (SEC-02, SEC-04)."""
    from fastapi import HTTPException
    raise HTTPException(
        status_code=501,
        detail="Biometric face enrollment is intentionally disabled in PathLab OS."
    )


def recognize(db: Session, image_bytes: bytes) -> dict:
    """Biometric face recognition is intentionally disabled in PathLab OS (SEC-02, SEC-04)."""
    return {
        "matched": False,
        "reason": "Biometric face recognition is intentionally disabled in PathLab OS",
        "service_available": False,
    }
