"""Database migration utilities for running Alembic migrations."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from app.core.config.app_config import app_config
from app.core.deps import logger


async def run_database_migrations() -> None:
    """
    Run Alembic database migrations to upgrade to the latest version.

    This function runs 'alembic upgrade head' to ensure the database schema
    is up to date with the latest migrations.
    """
    try:
        await logger.a_info("Starting database migration process...")

        # Get the project root directory (where alembic.ini is located)
        project_root = Path(__file__).parent.parent.parent.parent

        # Set up the command to run alembic upgrade head
        cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]

        # Set environment variables for the subprocess
        env = {
            **dict(os.environ),
            "POSTGRES_SERVER": app_config.DATABASE_HOST,
            "POSTGRES_PORT": str(app_config.DATABASE_PORT),
            "POSTGRES_USER": app_config.DATABASE_USER,
            "POSTGRES_PASSWORD": app_config.DATABASE_PASSWORD,
            "POSTGRES_DB": app_config.DATABASE_NAME,
        }

        # Run the migration command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            await logger.a_info("Database migrations completed successfully")
            if stdout:
                await logger.a_info(f"Migration output: {stdout.decode().strip()}")
        else:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            await logger.a_error(f"Database migration failed: {error_msg}")
            raise RuntimeError(
                f"Migration failed with return code {process.returncode}: {error_msg}"
            )

    except Exception as e:
        await logger.a_error(f"Error running database migrations: {str(e)}")
        raise


def run_database_migrations_sync() -> None:
    """
    Synchronous version of run_database_migrations for use in non-async contexts.

    This function runs 'alembic upgrade head' to ensure the database schema
    is up to date with the latest migrations.
    """
    import os

    try:
        logger.info("Starting database migration process...")

        # Get the project root directory (where alembic.ini is located)
        project_root = Path(__file__).parent.parent.parent.parent

        # Set up the command to run alembic upgrade head
        cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]

        # Set environment variables for the subprocess
        env = {
            **dict(os.environ),
            "POSTGRES_SERVER": app_config.DATABASE_HOST,
            "POSTGRES_PORT": str(app_config.DATABASE_PORT),
            "POSTGRES_USER": app_config.DATABASE_USER,
            "POSTGRES_PASSWORD": app_config.DATABASE_PASSWORD,
            "POSTGRES_DB": app_config.DATABASE_NAME,
        }

        # Run the migration command
        result = subprocess.run(
            cmd,
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info("Database migrations completed successfully")
            if result.stdout:
                logger.info(f"Migration output: {result.stdout.strip()}")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            logger.info(f"Database migration failed: {error_msg}")
            raise RuntimeError(
                f"Migration failed with return code {result.returncode}: {error_msg}"
            )

    except Exception as e:
        logger.exception(f"Error running database migrations: {str(e)}")
        raise
