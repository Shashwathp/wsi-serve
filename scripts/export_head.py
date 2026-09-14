import pickle, numpy as np
d = pickle.load(open("results/head.pkl", "rb"))
np.savez("results/head.npz",
         W=d["clf"].coef_.astype(np.float32),
         b=d["clf"].intercept_.astype(np.float32),
         classes=np.array(d["classes"]))
print("W", d["clf"].coef_.shape, "b", d["clf"].intercept_.shape)
