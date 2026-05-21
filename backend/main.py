import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from routes.upload import router as upload_router
import uvicorn


# ── Lifespan: widen the default thread pool ───────────────────────────────────
# Uvicorn's default pool is only ~5 threads. With blocking validation and
# file-export code running via asyncio.to_thread(), each concurrent user
# consumes one thread. 20 threads = 20 truly concurrent operations.
@asynccontextmanager
async def lifespan(_: FastAPI):
    pool_size = int(os.getenv("THREAD_POOL_WORKERS", "20"))
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=pool_size))
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": False, "message": exc.detail},
    )

app.include_router(upload_router)

if __name__ == "__main__":
    # Single worker with hot-reload for development.
    # For production set WORKERS=4 (or however many CPU cores you have);
    # reload is automatically disabled when workers > 1.
    workers = int(os.getenv("WORKERS", "1"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5002,
        workers=workers,
        reload=(workers == 1),
    )