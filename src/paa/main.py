"""HTTP 入口。当前只有健康检查，业务模块按 ROADMAP 逐步接入。"""

from fastapi import FastAPI

from . import __version__
from .config import get_settings

app = FastAPI(title="PAA", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "env": get_settings().env}
