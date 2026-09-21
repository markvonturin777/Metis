"""Addestra il classificatore della wake word ed esporta in ONNX.

CONTRATTO, verificato ispezionando i modelli preaddestrati di openWakeWord:

    input  (batch, 16, 96) float32
    output (batch, 1)      float32, punteggio in [0, 1]

E' tutto: bastano torch e numpy. Il modulo `openwakeword.train` farebbe lo
stesso lavoro trascinandosi dietro speechbrain, datasets e pronouncing.

LA METRICA GIUSTA NON E' L'ACCURATEZZA
Con un set sbilanciato 1:2,7 a favore dei negativi, un modello che dice
sempre "no" ottiene il 73% di accuratezza ed e' inutile. Quello che conta e'
il tasso di falsi positivi a un tasso di mancati riconoscimenti accettabile:
NFR-6 chiede meno di un falso risveglio ogni 8 ore, NFR-7 meno del 10% di
mancati. Si valuta quindi il **FRR al FPR fissato**, e si sceglie la soglia
sulla curva, non a occhio.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

DATA = Path("wakeword/data")
OUT = Path("data/wakeword")
WINDOWS, FEATURES = 16, 96


class WakeWordNet(nn.Module):
    """Piccolo classificatore: appiattisce 16x96 e passa per due strati.

    Volutamente minuscolo (~50k parametri): gira su CPU a ogni blocco da
    80 ms, quindi deve costare praticamente nulla. Piu' capacita' qui non
    aiuterebbe — il lavoro pesante l'ha gia' fatto l'estrattore di embedding.
    """

    def __init__(self, hidden: int = 96, dropout: float = 0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(WINDOWS * FEATURES, hidden),
            nn.LayerNorm(hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.LayerNorm(hidden // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def load_split(seed: int = 0, val_frac: float = 0.15):
    pos = np.load(DATA / "features_positive.npy")
    neg = np.load(DATA / "features_negative.npy")
    parts, names = [neg], [f"negativi {neg.shape}"]

    # Negativi DURI, aggiunti dopo la prova dal vivo: la famiglia fonetica di
    # "ehi mi senti", che il modello confondeva con la wake word a 0,986.
    hard_path = DATA / "features_hard.npy"
    if hard_path.exists():
        hard = np.load(hard_path)
        parts.append(hard)
        names.append(f"duri {hard.shape}")
    neg = np.concatenate(parts)
    print(f"positivi {pos.shape}  " + "  ".join(names)
          + f"  rapporto 1:{len(neg) / len(pos):.1f}")

    X = np.concatenate([pos, neg]).astype(np.float32)
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))]).astype(np.float32)

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    n_val = int(len(X) * val_frac)
    return (X[n_val:], y[n_val:]), (X[:n_val], y[:n_val])


def frr_at_fpr(scores: np.ndarray, labels: np.ndarray, target_fpr: float) -> tuple[float, float]:
    """Tasso di mancati riconoscimenti al tasso di falsi positivi richiesto.

    Ritorna (frr, soglia). E' la metrica che conta: la soglia si sceglie
    fissando quanti falsi risvegli si e' disposti ad accettare.
    """
    neg = np.sort(scores[labels == 0])[::-1]
    if len(neg) == 0:
        return 0.0, 0.5
    k = max(0, min(len(neg) - 1, int(len(neg) * target_fpr)))
    thr = float(neg[k])
    pos = scores[labels == 1]
    return float((pos < thr).mean()), thr


def evaluate(model: nn.Module, X: np.ndarray, y: np.ndarray) -> dict:
    model.eval()
    with torch.no_grad():
        s = model(torch.from_numpy(X)).numpy().ravel()
    out = {"auc": float(_auc(s, y))}
    for fpr in (0.05, 0.01, 0.001):
        frr, thr = frr_at_fpr(s, y, fpr)
        out[f"frr@fpr{fpr}"] = frr
        out[f"thr@fpr{fpr}"] = thr
    return out


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1)
    n_pos, n_neg = (labels == 1).sum(), (labels == 0).sum()
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return float((ranks[labels == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def train(epochs: int, batch: int, lr: float, seed: int, nome: str) -> None:
    torch.manual_seed(seed)
    (Xtr, ytr), (Xva, yva) = load_split(seed)

    model = WakeWordNet()
    n_par = sum(p.numel() for p in model.parameters())
    print(f"parametri: {n_par:,}")

    # I positivi sono la minoranza e i mancati riconoscimenti sono il difetto
    # piu' visibile per l'utente: si pesano di piu' nella loss.
    pos_weight = float((ytr == 0).sum() / max(1, (ytr == 1).sum()))
    print(f"peso dei positivi nella loss: {pos_weight:.2f}")

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    Xtr_t, ytr_t = torch.from_numpy(Xtr), torch.from_numpy(ytr)

    best = {"frr@fpr0.01": 1.0}
    best_state = None

    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(Xtr_t))
        tot = 0.0
        for i in range(0, len(perm), batch):
            j = perm[i : i + batch]
            xb, yb = Xtr_t[j], ytr_t[j]
            p = model(xb).squeeze(1).clamp(1e-7, 1 - 1e-7)
            w = torch.where(yb > 0.5, pos_weight, 1.0)
            loss = -(w * (yb * torch.log(p) + (1 - yb) * torch.log(1 - p))).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss) * len(j)
        sched.step()

        m = evaluate(model, Xva, yva)
        marker = ""
        if m["frr@fpr0.01"] < best["frr@fpr0.01"]:
            best, best_state = m, {k: v.clone() for k, v in model.state_dict().items()}
            marker = "  <-- migliore"
        print(f"  ep {ep:2d}  loss {tot / len(Xtr):.4f}  AUC {m['auc']:.4f}  "
              f"FRR@1%FPR {m['frr@fpr0.01'] * 100:5.2f}%{marker}")

    model.load_state_dict(best_state)
    OUT.mkdir(parents=True, exist_ok=True)

    dummy = torch.zeros(1, WINDOWS, FEATURES)
    onnx_path = OUT / f"{nome}.onnx"
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["x"], output_names=["score"],
        dynamic_axes={"x": {0: "batch"}, "score": {0: "batch"}},
        opset_version=13,
    )

    # IL FILE DEVE BASTARE A SE STESSO (corretto il 2026-09-21)
    # L'esportatore scrive i pesi in un file esterno con un nome FISSO, e
    # tutti i modelli esportati finivano per puntare allo stesso. Copiare un
    # .onnx copiava solo il grafo: le "versioni" archiviate condividevano i
    # pesi, e ogni addestramento sovrascriveva silenziosamente quelle prima.
    # Abbiamo creduto per mezza giornata di avere in produzione un modello
    # che era stato sostituito. Qui si ricompatta tutto in un file solo.
    import onnx

    m = onnx.load(str(onnx_path))                 # risolve i dati esterni
    onnx.save_model(m, str(onnx_path), save_as_external_data=False)
    for orfano in OUT.glob(f"{nome}.onnx.data"):
        orfano.unlink()
    peso_kb = onnx_path.stat().st_size / 1024
    assert peso_kb > 100, (
        f"{onnx_path.name} pesa {peso_kb:.0f} KB: i pesi non sono dentro"
    )

    meta = {
        "phrase": "Hey Metis",
        "nome": nome,
        "negativi_duri": bool((DATA / "features_hard.npy").exists()),
        "parameters": n_par,
        "train_size": len(Xtr),
        "val_size": len(Xva),
        **{k: round(v, 5) for k, v in best.items()},
    }
    (OUT / f"{nome}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\nesportato: {onnx_path}")
    print(f"  AUC             {best['auc']:.4f}")
    for fpr in (0.05, 0.01, 0.001):
        print(f"  FPR {fpr * 100:5.1f}%  ->  mancati {best[f'frr@fpr{fpr}'] * 100:5.2f}%  "
              f"soglia {best[f'thr@fpr{fpr}']:.3f}")
    print("\n  La soglia da mettere in configurazione e' quella al FPR che si")
    print("  e' disposti ad accettare. NFR-6 chiede < 1 falso risveglio / 8 h.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--nome", default="hey_metis",
                    help="nome del modello esportato: ogni versione il suo file")
    a = ap.parse_args()
    train(a.epochs, a.batch, a.lr, a.seed, a.nome)


if __name__ == "__main__":
    main()
