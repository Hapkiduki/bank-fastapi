"""Business logic for next-of-kin records (max 3 per user, one primary)."""

from uuid import UUID

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.core.exceptions import NotFoundError, ValidationFailedError
from backend.app.core.logging import get_logger
from backend.app.next_of_kin.models import NextOfKin
from backend.app.next_of_kin.schema import (
    NextOfKinCreateSchema,
    NextOfKinReadSchema,
    NextOfKinUpdateSchema,
)

logger = get_logger()

MAX_NEXT_OF_KIN = 3


async def get_next_of_kin_count(user_id: UUID, session: AsyncSession) -> int:
    """Count the user's next-of-kin records without loading them."""
    statement = (
        select(func.count())
        .select_from(NextOfKin)
        .where(NextOfKin.user_id == user_id)
    )
    result = await session.exec(statement)
    return result.one()


async def get_primary_next_of_kin(
    user_id: UUID, session: AsyncSession
) -> NextOfKin | None:
    statement = select(NextOfKin).where(
        NextOfKin.user_id == user_id, NextOfKin.is_primary
    )
    result = await session.exec(statement)
    return result.first()


async def validate_next_of_kin_creation(
    user_id: UUID, is_primary: bool, session: AsyncSession
) -> int:
    """Enforce the per-user cap and single-primary rule; returns the count."""
    current_count = await get_next_of_kin_count(user_id, session)
    if current_count >= MAX_NEXT_OF_KIN:
        raise ValidationFailedError(
            f"Maximum number of kin ({MAX_NEXT_OF_KIN}) already reached."
        )

    if is_primary:
        existing_primary = await get_primary_next_of_kin(user_id, session)
        if existing_primary:
            raise ValidationFailedError("A primary next of kin already exists.")

    return current_count


async def create_next_of_kin(
    user_id: UUID, next_of_kin_data: NextOfKinCreateSchema, session: AsyncSession
) -> NextOfKinReadSchema:
    """Add a next of kin; the very first one automatically becomes primary."""
    current_count = await validate_next_of_kin_creation(
        user_id, next_of_kin_data.is_primary, session
    )

    if current_count == 0:
        next_of_kin_data.is_primary = True

    next_of_kin = NextOfKin(**next_of_kin_data.model_dump())
    next_of_kin.user_id = user_id

    session.add(next_of_kin)
    await session.commit()
    await session.refresh(next_of_kin)

    logger.info(f"Next of kin created successfully for user: {user_id}")

    return NextOfKinReadSchema.model_validate(next_of_kin)


async def get_user_next_of_kins(
    user_id: UUID, session: AsyncSession
) -> list[NextOfKin]:
    statement = select(NextOfKin).where(NextOfKin.user_id == user_id)
    result = await session.exec(statement)
    return list(result.all())


async def get_user_next_of_kin(
    user_id: UUID, next_of_kin_id: UUID, session: AsyncSession
) -> NextOfKin:
    statement = select(NextOfKin).where(
        NextOfKin.user_id == user_id, NextOfKin.id == next_of_kin_id
    )
    result = await session.exec(statement)

    next_of_kin = result.first()

    if not next_of_kin:
        raise NotFoundError("Next of kin not found")
    return next_of_kin


async def update_next_of_kin(
    user_id: UUID,
    next_of_kin_id: UUID,
    update_data: NextOfKinUpdateSchema,
    session: AsyncSession,
) -> NextOfKin:
    """Update a next of kin, transferring the primary flag when requested."""
    next_of_kin = await get_user_next_of_kin(user_id, next_of_kin_id, session)

    if update_data.is_primary is not None:
        if update_data.is_primary:
            existing_primary = await get_primary_next_of_kin(user_id, session)
            if existing_primary and existing_primary.id != next_of_kin_id:
                existing_primary.is_primary = False
                session.add(existing_primary)
        else:
            total_count = await get_next_of_kin_count(user_id, session)
            if total_count == 1:
                raise ValidationFailedError(
                    "Cannot unset primary next of kin when there is only one"
                )
    update_dict = update_data.model_dump(exclude_unset=True)

    for key, value in update_dict.items():
        setattr(next_of_kin, key, value)

    session.add(next_of_kin)
    await session.commit()
    await session.refresh(next_of_kin)

    logger.info(f"Updated next of kin: {next_of_kin_id} for user: {user_id}")

    return next_of_kin


async def delete_next_of_kin(
    user_id: UUID, next_of_kin_id: UUID, session: AsyncSession
) -> dict[str, str]:
    """Delete a next of kin while guaranteeing at least one remains."""
    total_count = await get_next_of_kin_count(user_id, session)
    if total_count <= 1:
        raise ValidationFailedError(
            "Cannot delete the only next of kin",
            action="At least one next of kin must be maintained",
        )
    next_of_kin = await get_user_next_of_kin(user_id, next_of_kin_id, session)
    await session.delete(next_of_kin)
    await session.commit()
    logger.info(f"Next of kin deleted: {next_of_kin_id} for user: {user_id}")
    return {"status": "success", "message": "Next of kin deleted successfully"}
