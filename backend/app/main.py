import asyncio
from datetime import time

from aiosmtplib import status
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.core.logging import get_logger
from .api.main import api_router
from .core.config import settings
from contextlib import asynccontextmanager
from .core.db import init_db, engine
from backend.app.core.health import health_checker, ServiceStatus

logger = get_logger()


async def startup_helath_check(timeout: float = 90.0) -> bool:
    """
    Perform a health check on the database connection during application startup.

    Args:
        timeout (float): The maximum time to wait for the health check to complete.

    Returns:
        bool: True if the health check is successful, False otherwise.
    """
    try:
        async with asyncio.timeout(timeout):
            retry_intervvals = [1, 2, 5, 10, 15]
            start_time = time.time()

            while True:
                is_healthy = await health_checker.wait_for_services()
                if is_healthy:
                    return True
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    logger.error("Services failed health check during startup.")
                    return False
                wait_time = retry_intervvals[
                    min(len(retry_intervvals) - 1, int(elapsed / 10))
                ]
                logger.warning(
                    f"Services not healthy yet. Retrying in {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
    except asyncio.TimeoutError:
        logger.error(f"Health check timed out after {timeout} seconds during startup.")
        return False
    except Exception as e:
        logger.error(f"Error during startup health check: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("Database initialized successfully")

        await health_checker.add_service("database", health_checker.check_database)
        await health_checker.add_service("celery", health_checker.check_celery)
        await health_checker.add_service("redis", health_checker.check_redis)
        yield
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
        await engine.dispose()
        await health_checker.cleanup()
        raise
    finally:
        logger.info("Shutting down")
        await engine.dispose()
        await health_checker.cleanup()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)


@app.get("/health", response_model=dict)
async def health_check():
    """
    Health check endpoint to verify the status of the application and its dependencies.

    Returns:
        dict: A dictionary containing the health status of the application and its dependencies.
    """
    try:
        health_status = await health_checker.check_all_services()

        if health_status["status"] == ServiceStatus.HEALTHY:
            status_code = status.HTTP_200_OK
        elif health_status["status"] == ServiceStatus.DEGRADED:
            status_code = status.HTTP_206_PARTIAL_CONTENT
        else:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return JSONResponse(content=health_status, status_code=status_code)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            content={"status": ServiceStatus.UNHEALTHY, "error": str(e)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


app.include_router(api_router, prefix=settings.API_V1_STR)
