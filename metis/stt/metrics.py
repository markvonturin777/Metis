"""Metriche di accuratezza per lo STT.

NORMALIZZAZIONE DEI NUMERI (aggiunta il 2026-09-20)
La prima versione contava `diciassette` -> `17` come errore. Non lo e': Whisper
normalizza i numeri in cifre, e per un assistente vocale le due forme sono
semanticamente identiche — a valle la cifra e' persino piu' comoda da parsare.
Su un campione di 10 frasi questo gonfiava il WER dal 11,4% al 14,3%, cioe'
faceva la differenza fra rispettare NFR-5 e non rispettarlo.

Gli accenti invece si MANTENGONO: in italiano distinguono parole diverse
(`e`/`è`, `pero`/`però`).
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
from num2words import num2words

_DIGITS = re.compile(r"\d+")
_PUNCT = re.compile(r"[^\w\sàèéìòóùç]")


def _digits_to_words(s: str) -> str:
    def sub(m: re.Match[str]) -> str:
        try:
            return " " + num2words(int(m.group()), lang="it") + " "
        except Exception:
            return m.group()

    return _DIGITS.sub(sub, s)


def normalize(s: str) -> str:
    """Forma canonica per il confronto: minuscole, niente punteggiatura,
    numeri scritti in lettere, spazi compattati."""
    s = unicodedata.normalize("NFC", s.lower())
    s = _digits_to_words(s)
    s = _PUNCT.sub(" ", s)
    return " ".join(s.split())


def wer(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """Word Error Rate per distanza di Levenshtein sulle parole.

    Ritorna (tasso, numero di errori, parole di riferimento).
    """
    r, h = normalize(reference).split(), normalize(hypothesis).split()
    if not r:
        return 0.0, 0, 0
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    errors = int(d[len(r), len(h)])
    return errors / len(r), errors, len(r)


def diff_words(reference: str, hypothesis: str) -> list[tuple[str, str]]:
    """Differenze allineate fra riferimento e ipotesi.

    Il confronto posizione-per-posizione non va bene: dopo una sola
    cancellazione tutte le parole successive slittano e sembrano sbagliate.
    Su una frase di 7 parole con 3 errori veri ne mostrava 7. Qui si
    ricostruisce l'allineamento dalla matrice di Levenshtein, cosi' il numero
    di differenze mostrate coincide con quello contato da wer().
    """
    r, h = normalize(reference).split(), normalize(hypothesis).split()
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)

    out: list[tuple[str, str]] = []
    i, j = len(r), len(h)
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if r[i - 1] == h[j - 1] else 1
            if d[i, j] == d[i - 1, j - 1] + cost:
                if cost:
                    out.append((r[i - 1], h[j - 1]))      # sostituzione
                i, j = i - 1, j - 1
                continue
        if i > 0 and d[i, j] == d[i - 1, j] + 1:
            out.append((r[i - 1], "—"))                   # cancellazione
            i -= 1
        else:
            out.append(("—", h[j - 1]))                   # inserimento
            j -= 1
    return list(reversed(out))
