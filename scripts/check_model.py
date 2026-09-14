import time, torch
from transformers import AutoImageProcessor, AutoModel

device = "mps" if torch.backends.mps.is_available() else "cpu"
print("device:", device)

proc = AutoImageProcessor.from_pretrained("owkin/phikon")
model = AutoModel.from_pretrained("owkin/phikon").to(device).eval()

x = torch.randn(8, 3, 224, 224).to(device)

with torch.inference_mode():
    for _ in range(3):
        model(pixel_values=x)
    if device == "mps":
        torch.mps.synchronize()

    t = time.perf_counter()
    for _ in range(10):
        out = model(pixel_values=x)
    if device == "mps":
        torch.mps.synchronize()
    dt = time.perf_counter() - t

emb = out.last_hidden_state[:, 0, :]
print("embedding shape:", emb.shape)
print("tiles/sec:", round(80 / dt, 1))
