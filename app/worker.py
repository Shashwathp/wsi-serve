import os, sys, time, pickle, numpy as np, torch
from PIL import Image
from transformers import AutoModel
from app.store import connect, mark_done, STREAM, GROUP
from app.metrics import (BATCH_LATENCY, BATCH_SIZE, TILES_DONE,
                        RECLAIMS, QUEUE_DEPTH, QUEUE_LEN)
from prometheus_client import start_http_server

NAME = sys.argv[1] if len(sys.argv) > 1 else f"w-{os.getpid()}"
BATCH = int(os.getenv("BATCH_SIZE", "16"))
WAIT_MS = int(os.getenv("BATCH_WAIT_MS", "200"))
IDLE_MS = int(os.getenv("CLAIM_IDLE_MS", "10000"))
DEVICE = os.getenv("DEVICE", "auto")

MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


def pick_device():
    if DEVICE != "auto":
        return DEVICE
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_tile(path):
    img = Image.open(path).convert("RGB").resize((224, 224), Image.BILINEAR)
    x = torch.from_numpy(np.array(img)).permute(2, 0, 1).float() / 255.0
    return (x - MEAN) / STD


def gather(r):
    """Fill a batch, but never wait longer than WAIT_MS."""
    _, claimed, _ = r.xautoclaim(STREAM, GROUP, NAME,
                                 min_idle_time=IDLE_MS, count=BATCH)
    if claimed:
        print(f"[{NAME}] reclaimed {len(claimed)}", flush=True)
        RECLAIMS.inc()
        return claimed

    batch, deadline = [], time.monotonic() + WAIT_MS / 1000
    while len(batch) < BATCH:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        resp = r.xreadgroup(GROUP, NAME, {STREAM: ">"},
                            count=BATCH - len(batch),
                            block=max(1, int(remaining * 1000)))
        if resp and resp[0][1]:
            batch.extend(resp[0][1])
        else:
            break
    return batch


def main():
    device = pick_device()
    print(f"[{NAME}] device={device} batch={BATCH} wait={WAIT_MS}ms", flush=True)
    start_http_server(9100)

    model = AutoModel.from_pretrained("owkin/phikon").to(device).eval()
    hd = np.load("results/head.npz", allow_pickle=True)
    W, b = hd["W"], hd["b"]
    r = connect(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    while True:
        batch = gather(r)
        if not batch:
            continue

        t0 = time.perf_counter()
        ids = [e[0] for e in batch]
        job_id = batch[0][1]["job_id"]
        idxs = [int(e[1]["tile_idx"]) for e in batch]

        x = torch.stack([load_tile(e[1]["path"]) for e in batch]).to(device)
        with torch.inference_mode():
            emb = model(pixel_values=x).last_hidden_state[:, 0, :].float().cpu().numpy()
        labels = (emb @ W.T + b).argmax(1)

        mark_done(r, job_id, idxs, emb, labels)
        r.xack(STREAM, GROUP, *ids)

        dt = time.perf_counter() - t0
        BATCH_LATENCY.observe(dt)
        BATCH_SIZE.observe(len(batch))
        TILES_DONE.labels(outcome="ok").inc(len(batch))
        QUEUE_LEN.set(r.xlen(STREAM))
        try:
            QUEUE_DEPTH.set(r.xpending(STREAM, GROUP)["pending"])
        except Exception:
            pass
        with open("/srv/results/batch_samples.csv", "a") as f:
            f.write(f"{time.time():.3f},{len(batch)},{dt:.6f}\n")
        print(f"[{NAME}] {len(batch)} tiles in {dt*1000:.0f}ms "
              f"({len(batch)/dt:.1f}/s)", flush=True)


if __name__ == "__main__":
    main()
