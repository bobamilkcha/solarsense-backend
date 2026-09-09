from typing import Annotated

from app.core.database.database import get_session
from app.core.logging.service import get_log_service
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Singleton

logger = get_log_service()

# Dependencies

DBSession = Annotated[AsyncSession, Depends(get_session)]
