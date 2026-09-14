import numpy as np, pickle
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

d = np.load("results/embeddings.npz", allow_pickle=True)
E, Y, CLASSES = d["E"], d["Y"], list(d["classes"])

Etr, Ete, Ytr, Yte = train_test_split(
    E, Y, test_size=0.3, random_state=0, stratify=Y
)
print(f"train {Etr.shape[0]}, test {Ete.shape[0]}")

clf = LogisticRegression(max_iter=2000, C=1.0, n_jobs=-1)
clf.fit(Etr, Ytr)

pred = clf.predict(Ete)
print(f"\naccuracy: {accuracy_score(Yte, pred):.4f}\n")
print(classification_report(Yte, pred, target_names=CLASSES, digits=3))

with open("results/head.pkl", "wb") as f:
    pickle.dump({"clf": clf, "classes": CLASSES}, f)
print("saved to results/head.pkl")
