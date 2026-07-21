from fastapi import APIRouter, HTTPException, status

from app.notifications import FileNotificationRepository, Notification, NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

notification_repository = FileNotificationRepository()
service = NotificationService(notification_repository)


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Уведомление не найдено")


@router.get("", response_model=list[Notification])
def list_notifications() -> list[Notification]:
    return service.list()


@router.get("/unread", response_model=list[Notification])
def unread_notifications() -> list[Notification]:
    return service.unread()


@router.patch("/{notification_id}/read", response_model=Notification)
def mark_notification_read(notification_id: str) -> Notification:
    notification = service.mark_read(notification_id)
    if notification is None:
        raise not_found()
    return notification


@router.patch("/read-all", response_model=list[Notification])
def mark_all_notifications_read() -> list[Notification]:
    return service.mark_all_read()


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: str) -> None:
    if not service.delete(notification_id):
        raise not_found()
