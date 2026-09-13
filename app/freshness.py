"""Single mutation point for published-layer data freshness.

``revision`` and ``data_updated_at`` describe *published data* content, not
layer metadata. Every path that can change publicly served features must call
``touch_layer_data`` in the same transaction as the change.
"""

import uuid

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models import Layer


def touch_layer_data(session: Session, layer_id: uuid.UUID) -> None:
    session.execute(
        update(Layer)
        .where(Layer.id == layer_id)
        .values(
            revision=Layer.revision + 1,
            data_updated_at=func.now(),
            updated_at=func.now(),
        )
    )
