import json, uuid, numpy as np, redis
from pathlib import Path

STREAM = "tiles"
GROUP = "workers"
RESULTS = Path("results/jobs")
EMBED_DIM = 768


def connect(url="redis://localhost:6379/0"):
    r = redis.Redis.from_url(url, decode_responses=True)
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError:
        pass
    return r


def create_job(r, tile_paths):
    job_id = uuid.uuid4().hex[:12]
    n = len(tile_paths)
    RESULTS.mkdir(parents=True, exist_ok=True)

    np.lib.format.open_memmap(
        RESULTS / f"{job_id}.npy", mode="w+",
        dtype=np.float32, shape=(n, EMBED_DIM)
    )
    r.hset(f"job:{job_id}", mapping={"n_tiles": n, "status": "running"})

    pipe = r.pipeline()
    for idx, p in enumerate(tile_paths):
        pipe.xadd(STREAM, {"job_id": job_id, "tile_idx": str(idx), "path": str(p)})
    pipe.execute()

    return job_id, n


def mark_done(r, job_id, tile_indices, embeddings, labels):
    arr = np.load(RESULTS / f"{job_id}.npy", mmap_mode="r+")
    for i, idx in enumerate(tile_indices):
        arr[idx] = embeddings[i]
    arr.flush()

    pipe = r.pipeline()
    for i, idx in enumerate(tile_indices):
        pipe.hset(f"job:{job_id}:labels", str(idx), int(labels[i]))
        pipe.setbit(f"job:{job_id}:done", idx, 1)
    pipe.execute()


def progress(r, job_id):
    meta = r.hgetall(f"job:{job_id}")
    if not meta:
        return None
    n = int(meta["n_tiles"])
    done = r.bitcount(f"job:{job_id}:done")
    return {
        "job_id": job_id,
        "n_tiles": n,
        "completed": done,
        "pct": round(100 * done / n, 1) if n else 0.0,
        "status": "complete" if done >= n else meta["status"],
    }


def labels(r, job_id):
    h = r.hgetall(f"job:{job_id}:labels")
    n = int(r.hget(f"job:{job_id}", "n_tiles") or 0)
    out = [-1] * n
    for k, v in h.items():
        out[int(k)] = int(v)
    return out
