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

# --- Face recognition is disabled right now per user request ---
fr_lib = None
FACE_RECOGNITION_AVAILABLE = False
logger.warning("face_recognition explicitly disabled — using stub mode for face enrollment")


def _compute_embedding(image_bytes: bytes) -> Optional[np.ndarray]:
    """Return 128-dim face embedding or None if no single face found."""
    if not FACE_RECOGNITION_AVAILABLE or fr_lib is None:
        # Stub: return random unit vector for development without dlib
        vec = np.random.rand(128).astype(np.float32)
        return vec / np.linalg.norm(vec)

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
    """FR-2.2 — Capture one face sample. Activates account when min samples reached."""
    embedding = _compute_embedding(image_bytes)

    if embedding is None:
        return {
            "accepted": False,
            "reason": "Expected exactly one clearly visible face. Please try again.",
            "sample_count": attendance_repo.count_embeddings_for_user(db, user_id),
            "face_registered": False,
            "is_active": False,
        }

    # Store embedding
    sample_count_before = attendance_repo.count_embeddings_for_user(db, user_id)
    sample_index = sample_count_before + 1
    attendance_repo.add_embedding(db, user_id, _embedding_to_storage(embedding), sample_index)

    sample_count = sample_count_before + 1
    face_registered = False
    is_active = False

    # FR-2.2: activate when minimum samples reached
    if sample_count >= settings.FACE_MIN_SAMPLES:
        user_repo.update_user(db, user_id, face_registered=True, is_active=True)
        face_registered = True
        is_active = True

    db.commit()

    return {
        "accepted": True,
        "sample_count": sample_count,
        "face_registered": face_registered,
        "is_active": is_active,
        "message": (
            f"Sample {sample_count} captured. "
            + ("Account is now active!" if is_active else f"{settings.FACE_MIN_SAMPLES - sample_count} more needed.")
        ),
    }


def recognize(db: Session, image_bytes: bytes) -> dict:
    """FR-3.1 — Recognize face against all enrolled embeddings."""
    probe_embedding = _compute_embedding(image_bytes)

    if probe_embedding is None:
        return {
            "matched": False,
            "reason": "No single clear face detected in frame",
        }

    # Load all stored embeddings
    all_embeddings = attendance_repo.get_all_embeddings(db)
    if not all_embeddings:
        return {"matched": False, "reason": "No enrolled faces in system"}

    # Find best match (cosine similarity)
    best_user_id = None
    best_score = -1.0

    for fe in all_embeddings:
        stored_vec = _storage_to_embedding(fe.embedding)
        score = _cosine_similarity(probe_embedding, stored_vec)
        if score > best_score:
            best_score = score
            best_user_id = fe.user_id

    threshold = settings.FACE_MATCH_THRESHOLD

    if best_score < threshold or not best_user_id:
        return {
            "matched": False,
            "reason": f"Face not recognized clearly (confidence: {best_score:.2f})",
            "confidence": best_score,
        }

    user = user_repo.get_by_id(db, best_user_id)
    return {
        "matched": True,
        "user_id": str(best_user_id),
        "user_name": user.name if user else "Unknown",
        "confidence": best_score,
    }
