"""Business logic for user profiles (KYC data, photos via Cloudinary)."""

import uuid

from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.auth.models import User
from backend.app.core.exceptions import ForbiddenError, NotFoundError, ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.core.tasks.image_upload import upload_profile_image_task
from backend.app.user_profile.enums import ImageTypeEnum
from backend.app.user_profile.models import Profile
from backend.app.user_profile.schema import (
    ProfileCreateSchema,
    ProfileUpdateSchema,
    RoleChoicesSchema,
)

logger = get_logger()


async def get_user_profile(user_id: uuid.UUID, session: AsyncSession) -> Profile | None:
    statement = select(Profile).where(Profile.user_id == user_id)
    result = await session.exec(statement)
    return result.first()


async def create_user_profile(
    user_id: uuid.UUID, profile_data: ProfileCreateSchema, session: AsyncSession
) -> Profile:
    existing_profile = await get_user_profile(user_id, session)

    if existing_profile:
        raise ValidationFailedError("Profile already exists for this user")

    profile_data_dict = profile_data.model_dump()

    profile = Profile(user_id=user_id, **profile_data_dict)
    session.add(profile)

    await session.commit()
    await session.refresh(profile)

    logger.info(f"Created profile for user {user_id}")
    return profile


async def update_user_profile(
    user_id: uuid.UUID, profile_data: ProfileUpdateSchema, session: AsyncSession
) -> Profile:
    """Update profile fields; photo URLs are only set via the upload flow."""
    profile = await get_user_profile(user_id, session)
    if not profile:
        raise NotFoundError(
            "Profile not found", action="Please create a profile first"
        )
    update_data = profile_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if field not in [
            "profile_photo_url",
            "id_photo_url",
            "signature_photo_url",
        ]:
            setattr(profile, field, value)

    await session.commit()
    await session.refresh(profile)

    logger.info(f"Updated profile for user {user_id}")
    return profile


def initiate_image_upload(
    file_content: bytes,
    image_type: ImageTypeEnum,
    content_type: str,
    user_id: uuid.UUID,
) -> str:
    """Queue an async Cloudinary upload via Celery; returns the task id."""
    task = upload_profile_image_task.delay(
        file_content, image_type.value, str(user_id), content_type
    )
    return task.id


async def update_profile_image_url(
    user_id: uuid.UUID,
    image_type: ImageTypeEnum,
    image_url: str,
    session: AsyncSession,
) -> Profile:
    """Persist the Cloudinary URL for one of the profile's image slots."""
    profile = await get_user_profile(user_id, session)
    if not profile:
        raise NotFoundError(
            "Profile not found", action="Please create a profile first"
        )
    field_mapping = {
        ImageTypeEnum.PROFILE_PHOTO: "profile_photo_url",
        ImageTypeEnum.ID_PHOTO: "id_photo_url",
        ImageTypeEnum.SIGNATURE_PHOTO: "signature_photo_url",
    }

    field_name = field_mapping.get(image_type)

    if not field_name:
        raise ValidationFailedError(f"Invalid image type: {image_type}")

    setattr(profile, field_name, image_url)

    await session.commit()

    await session.refresh(profile)

    return profile


async def get_user_with_profile(user_id: uuid.UUID, session: AsyncSession) -> User:
    statement = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.profile))
    )
    result = await session.exec(statement)
    user = result.first()

    if not user:
        raise NotFoundError("User not found")
    return user


async def get_all_user_profiles(
    session: AsyncSession,
    current_user: User,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[User], int]:
    """Paginated user+profile listing, restricted to branch managers.

    Uses ``COUNT(*)`` instead of loading every row, and eager-loads profiles
    (fixed N+1: previously each user triggered a separate refresh).
    """
    if current_user.role != RoleChoicesSchema.BRANCH_MANAGER:
        raise ForbiddenError(
            "Access denied",
            action="Only branch managers can access all profiles",
        )

    count_statement = select(func.count()).select_from(User)
    result = await session.exec(count_statement)
    total_count = result.one()

    statement = (
        select(User)
        .offset(skip)
        .limit(limit)
        .order_by(col(User.created_at).desc())
        .options(selectinload(User.profile))
    )
    result = await session.exec(statement)
    users = result.all()

    return list(users), total_count
