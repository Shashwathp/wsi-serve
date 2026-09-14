import time, numpy as np, torch
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from transformers import AutoModel

ROOT = Path("data/CRC-VAL-HE-7K")
CLASSES = sorted([d.name for d in ROOT.iterdir() if d.is_dir()])
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


class Tiles(Dataset):
    def __init__(self):
        self.items = []
        for ci, c in enumerate(CLASSES):
            for p in sorted((ROOT / c).glob("*.tif")):
                self.items.append((p, ci))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, y = self.items[i]
        img = Image.open(p).convert("RGB").resize((224, 224), Image.BILINEAR)
        x = torch.from_numpy(np.asarray(img)).permute(2, 0, 1).float() / 255.0
        return (x - MEAN) / STD, y


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = AutoModel.from_pretrained("owkin/phikon").to(device).eval()

    ds = Tiles()
    print(f"{len(ds)} tiles, {len(CLASSES)} classes: {CLASSES}")
    dl = DataLoader(ds, batch_size=32, num_workers=4, shuffle=False)

    embs, labels = [], []
    t0 = time.perf_counter()
    with torch.inference_mode():
        for i, (x, y) in enumerate(dl):
            out = model(pixel_values=x.to(device))
            embs.append(out.last_hidden_state[:, 0, :].float().cpu().numpy())
            labels.append(y.numpy())
            if i % 20 == 0:
                print(f"  batch {i}/{len(dl)}", flush=True)

    E = np.concatenate(embs)
    Y = np.concatenate(labels)
    dt = time.perf_counter() - t0

    np.savez("results/embeddings.npz", E=E, Y=Y, classes=np.array(CLASSES))
    print(f"\n{E.shape} in {dt:.1f}s ({len(ds)/dt:.1f} tiles/sec)")
    print("saved to results/embeddings.npz")


if __name__ == "__main__":
    main()
