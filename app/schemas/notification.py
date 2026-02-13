from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    data: dict | None = None
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedNotifications(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int
