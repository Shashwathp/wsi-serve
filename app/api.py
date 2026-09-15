import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.store import connect, create_job, progress, labels
from app.metrics import HTTP_LATENCY, QUEUE_LEN, QUEUE_DEPTH
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time

TILE_ROOT = Path(os.getenv("TILE_ROOT", "data/CRC-VAL-HE-7K"))
CLASSES = ["ADI", "BACK", "DEB", "LYM", "MUC", "MUS", "NORM", "STR", "TUM"]

app = FastAPI(title="wsi-serve")
r = connect(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

_ALL = None


def tile_pool():
    global _ALL
    if _ALL is None:
        _ALL = sorted(TILE_ROOT.rglob("*.tif"))
    return _ALL


class JobRequest(BaseModel):
    n_tiles: int = 200
    offset: int = 0


@app.post("/jobs", status_code=202)
def submit(req: JobRequest):
    t0 = time.perf_counter()
    pool = tile_pool()
    if not pool:
        raise HTTPException(500, f"no tiles under {TILE_ROOT}")
    chosen = pool[req.offset:req.offset + req.n_tiles]
    if not chosen:
        raise HTTPException(400, "offset past end of tile pool")
    job_id, n = create_job(r, chosen)
    HTTP_LATENCY.labels(endpoint="submit").observe(time.perf_counter() - t0)
    with open("/srv/results/submit_samples.csv", "a") as f:
        f.write(f"{time.time():.3f},{n},{time.perf_counter()-t0:.6f}\n")
    return {"job_id": job_id, "n_tiles": n}


@app.get("/jobs/{job_id}")
def status(job_id: str):
    t0 = time.perf_counter()
    p = progress(r, job_id)
    if p is None:
        raise HTTPException(404, "unknown job")
    HTTP_LATENCY.labels(endpoint="status").observe(time.perf_counter() - t0)
    return p


@app.get("/jobs/{job_id}/tiles")
def tiles(job_id: str):
    p = progress(r, job_id)
    if p is None:
        raise HTTPException(404, "unknown job")
    lab = labels(r, job_id)
    return {
        "job_id": job_id,
        "classes": CLASSES,
        "completed": p["completed"],
        "n_tiles": p["n_tiles"],
        "labels": lab,
    }


@app.get("/healthz")
def healthz():
    try:
        r.ping()
        return {"ok": True, "queue_depth": r.xlen("tiles")}
    except Exception as e:
        raise HTTPException(503, str(e))


@app.get("/metrics")
def metrics():
    try:
        QUEUE_LEN.set(r.xlen("tiles"))
        QUEUE_DEPTH.set(r.xpending("tiles", "workers")["pending"])
    except Exception:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
