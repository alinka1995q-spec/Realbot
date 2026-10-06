"""Ежедневное резервное копирование БД."""

import asyncio
import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("backups")
KEEP_LAST = 14  # хранить последние 14 копий


def _ensure_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_old() -> None:
    files = sorted(BACKUP_DIR.glob("backup_*"))
    extra = len(files) - KEEP_LAST
    for f in files[:max(0, extra)]:
        try:
            f.unlink()
        except OSError:
            pass


async def run_backup() -> str | None:
    """Делает бэкап БД. Возвращает путь к файлу."""
    settings = get_settings()
    _ensure_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if settings.use_sqlite:
        src = Path(settings.sqlite_path)
        if not src.exists():
            logger.warning("SQLite file %s not found", src)
            return None
        dst = BACKUP_DIR / f"backup_{stamp}.db.gz"
        # копируем и сжимаем
        def _do() -> Path:
            with src.open("rb") as fin, gzip.open(dst, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            return dst

        try:
            await asyncio.to_thread(_do)
            logger.info("SQLite backup created: %s", dst)
        except Exception as e:
            logger.exception("SQLite backup failed: %s", e)
            return None
    else:
        dst = BACKUP_DIR / f"backup_{stamp}.sql.gz"
        cmd = [
            "pg_dump",
            "-h", settings.postgres_host,
            "-p", str(settings.postgres_port),
            "-U", settings.postgres_user,
            "-d", settings.postgres_db,
            "--no-password",
        ]
        env = {**os.environ, "PGPASSWORD": settings.postgres_password}

        def _do() -> Path:
            with gzip.open(dst, "wb") as fout:
                proc = subprocess.run(cmd, env=env, capture_output=True, check=True)
                fout.write(proc.stdout)
            return dst

        try:
            await asyncio.to_thread(_do)
            logger.info("PG backup created: %s", dst)
        except FileNotFoundError:
            logger.warning("pg_dump not found - skipping postgres backup")
            return None
        except subprocess.CalledProcessError as e:
            logger.error("pg_dump failed: %s", e.stderr.decode() if e.stderr else "")
            return None
        except Exception as e:
            logger.exception("PG backup error: %s", e)
            return None

    _cleanup_old()
    return str(dst)
