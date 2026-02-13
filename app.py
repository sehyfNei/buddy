"""Buddy Reader — start the server with: python app.py"""

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from buddy.api.routes import router, load_config, init_llm, init_knowledge

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("buddy")

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Buddy Reader", version="0.1.0")

# API routes
app.include_router(router)

# Serve frontend static files
frontend_dir = Path(__file__).parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")


@app.get("/")
async def index():
    return FileResponse(str(frontend_dir / "index.html"))


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    config = load_config()
    llm = init_llm(config)
    init_knowledge(config)

    ok = await llm.health_check()
    if ok:
        logger.info("LLM is reachable — Buddy is ready!")
    else:
        logger.warning(
            "LLM not reachable. Buddy will work but can't generate responses. "
            "Start your model server (e.g. 'ollama serve') and reload."
        )


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
