"""常驻服务入口：python -m paa.serve"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("paa.main:app", host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
