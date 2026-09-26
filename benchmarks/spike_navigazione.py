"""PHASE2, giorno 0 — cosa funziona davvero su questa macchina.

    python benchmarks/spike_navigazione.py cdp
    python benchmarks/spike_navigazione.py uia --finestra "Google Chrome" --giri 5
    python benchmarks/spike_navigazione.py uia --finestra "Visual Studio Code" --confronta
    python benchmarks/spike_navigazione.py uia --finestra Facebook --cattura

Le misure decidono D-NAV 1: da dove si leggono gli elementi cliccabili.

CDP
Da Chrome 136 `--remote-debugging-port` e' ignorato sul profilo
predefinito. Qui si guarda la sessione vera (la porta 9222 e' aperta?) e si
prova la porta su un profilo temporaneo, in una seconda istanza che il banco
apre e chiude da solo. Il profilo predefinito si prova solo con
`--profilo-predefinito`, e solo se Chrome e' chiuso: il banco non chiude
niente dell'utente.

UIA
Una chiamata sola, `FindAllBuildCache`, con la condizione gia' dentro:
tipi cliccabili E non fuori schermo. Nome, tipo e rettangolo tornano nella
cache della stessa chiamata, senza un giro fra processi per ogni proprieta'.
E' il modo che il piano chiede ("filtrando alla sorgente, mai l'albero
intero"); `--confronta` misura anche il visitatore in ampiezza di
`metis/tools/uia.py`, per sapere quanto si guadagna.

Il primo giro su Chrome puo' essere diverso dagli altri: Chrome accende
l'accessibilita' del contenuto quando si accorge che un client UIA la
chiede. Per questo si fanno piu' giri e si riportano separati.

NON TOCCA NIENTE: legge l'albero, non clicca, non porta finestre davanti.
`--cattura` salva un'immagine dello schermo con i rettangoli trovati, per
vedere a occhio se le coordinate cadono dove devono.
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from metis.tools.display import set_dpi_awareness

# Prima di tutto: senza, i rettangoli sarebbero virtualizzati.
set_dpi_awareness()

RISULTATI = Path(__file__).with_name("results")
CATTURE = Path("data/catture/spike")
PORTA_VERA = 9222
PORTA_PROVA = 9223
SOGLIA_MS = 1000.0

# ControlType cliccabili (D-NAV 5: link, pulsanti, schede, caselle di spunta),
# con gli id di UIAutomationClient.h. Le voci di menu ci sono perche' nelle
# applicazioni native sono la meta' delle cose che si cliccano.
TIPI = {
    50000: "pulsante",           # Button
    50031: "pulsante",           # SplitButton
    50005: "link",               # Hyperlink
    50019: "scheda",             # TabItem
    50002: "spunta",             # CheckBox
    50013: "spunta",             # RadioButton
    50011: "menu",               # MenuItem
}
P_NOME = 30005
P_TIPO = 30003
P_RECT = 30001
P_FUORI = 30022
DISCENDENTI = 4


# --- CDP -----------------------------------------------------------------------

def porta_aperta(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.15):
            return True
    except OSError:
        return False


def _chrome_utente() -> list[str]:
    """Le righe di comando dei Chrome principali (non i figli) in esecuzione."""
    import psutil

    righe = []
    for p in psutil.process_iter(["name", "cmdline"]):
        if (p.info["name"] or "").lower() != "chrome.exe":
            continue
        riga = " ".join(p.info["cmdline"] or [])
        if "--type=" not in riga:
            righe.append(riga)
    return righe


def _chiudi_prova(porta: int) -> int:
    import psutil

    n = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        if (p.info["name"] or "").lower() != "chrome.exe":
            continue
        if f"remote-debugging-port={porta}" in " ".join(p.info["cmdline"] or []):
            try:
                p.kill()
                n += 1
            except Exception:                    # noqa: BLE001
                pass
    return n


def _prova_porta(args: list[str], porta: int, attesa_s: float = 15.0) -> dict:
    from metis.security.guards import ALLOWLIST_APP

    exe = str(ALLOWLIST_APP["chrome"].percorso)
    t0 = time.perf_counter()
    subprocess.Popen([exe, f"--remote-debugging-port={porta}", *args,
                      "--no-first-run", "--no-default-browser-check",
                      "about:blank"])
    while time.perf_counter() - t0 < attesa_s:
        if porta_aperta(porta):
            return {"aperta": True, "ms": round((time.perf_counter() - t0) * 1000)}
        time.sleep(0.1)
    return {"aperta": False, "ms": None}


def spike_cdp(profilo_predefinito: bool) -> dict:
    utente = _chrome_utente()
    versione = ""
    try:
        from metis.security.guards import ALLOWLIST_APP
        import win32api

        exe = str(ALLOWLIST_APP["chrome"].percorso)
        info = win32api.GetFileVersionInfo(exe, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        versione = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:                            # noqa: BLE001
        pass

    esito: dict = {
        "chrome": versione,
        "sessione_vera": {
            "chrome_aperto": bool(utente),
            "avviato_con_la_porta": any("remote-debugging-port" in r for r in utente),
            "porta_9222_aperta": porta_aperta(PORTA_VERA),
        },
    }
    print(f"Chrome {versione}")
    print(f"  sessione vera: aperto={bool(utente)}, "
          f"porta 9222 aperta={esito['sessione_vera']['porta_9222_aperta']}")

    with tempfile.TemporaryDirectory(prefix="metis-spike-") as tmp:
        r = _prova_porta([f"--user-data-dir={tmp}", "--new-window"], PORTA_PROVA)
        esito["profilo_temporaneo"] = r
        print(f"  profilo temporaneo, porta {PORTA_PROVA}: "
              f"{'aperta in ' + str(r['ms']) + ' ms' if r['aperta'] else 'NON si apre'}")
        _chiudi_prova(PORTA_PROVA)
        time.sleep(1.5)                           # i file del profilo, prima di cancellarlo

    if profilo_predefinito:
        if _chrome_utente():
            esito["profilo_predefinito"] = {"provato": False,
                                            "motivo": "Chrome aperto: non lo chiudo io"}
            print("  profilo predefinito: NON provato, Chrome e' aperto. "
                  "Chiudilo del tutto e rilancia con --profilo-predefinito")
        else:
            r = _prova_porta([], PORTA_VERA)
            esito["profilo_predefinito"] = {"provato": True, **r}
            print(f"  profilo predefinito, porta {PORTA_VERA}: "
                  f"{'aperta' if r['aperta'] else 'NON si apre'}")
            # Chrome resta aperto: e' il profilo dell'utente, lo chiude lui.
    return esito


# --- UIA -----------------------------------------------------------------------

@dataclass
class Voce:
    nome: str
    tipo: str
    rect: tuple[int, int, int, int]


def _client():
    import uiautomation.uiautomation as m

    c = m._AutomationClient.instance()
    return c.IUIAutomation


def _condizione(uia):
    tipi = [uia.CreatePropertyCondition(P_TIPO, t) for t in TIPI]
    o = tipi[0]
    for t in tipi[1:]:
        o = uia.CreateOrCondition(o, t)
    visibili = uia.CreatePropertyCondition(P_FUORI, False)
    return uia.CreateAndCondition(o, visibili)


def _cache(uia):
    c = uia.CreateCacheRequest()
    for p in (P_NOME, P_TIPO, P_RECT, P_FUORI):
        c.AddProperty(p)
    return c


def _dentro(r, cornice) -> bool:
    """Il rettangolo ha area e cade (almeno in parte) dentro la finestra."""
    l, t, rr, b = r
    L, T, R, B = cornice
    return rr > l and b > t and rr > L and l < R and b > T and t < B


def leggi(hwnd: int, cornice) -> tuple[list[Voce], dict]:
    uia = _client()
    cond = _condizione(uia)
    cache = _cache(uia)

    t0 = time.perf_counter()
    radice = uia.ElementFromHandle(hwnd)
    t1 = time.perf_counter()
    arr = radice.FindAllBuildCache(DISCENDENTI, cond, cache)
    t2 = time.perf_counter()
    n = arr.Length if arr is not None else 0
    voci: list[Voce] = []
    for i in range(n):
        el = arr.GetElement(i)
        try:
            rc = el.CachedBoundingRectangle
            r = (rc.left, rc.top, rc.right, rc.bottom)
            if not _dentro(r, cornice):
                continue
            voci.append(Voce((el.CachedName or "")[:80],
                             TIPI.get(el.CachedControlType, "?"), r))
        except Exception:                        # noqa: BLE001
            continue
    t3 = time.perf_counter()
    return voci, {"radice_ms": round((t1 - t0) * 1000, 1),
                  "findall_ms": round((t2 - t1) * 1000, 1),
                  "estrazione_ms": round((t3 - t2) * 1000, 1),
                  "totale_ms": round((t3 - t0) * 1000, 1),
                  "restituiti": n, "visibili": len(voci)}


def _visitatore_vecchio(hwnd: int) -> dict:
    """Lo stesso lavoro con il percorso in ampiezza di `uia.py`."""
    from metis.tools import uia as vecchio

    t0 = time.perf_counter()
    try:
        trovati = vecchio.candidati(hwnd, "", "qualsiasi")
    except Exception as exc:                     # noqa: BLE001
        return {"errore": str(exc)}
    return {"totale_ms": round((time.perf_counter() - t0) * 1000, 1),
            "trovati": len(trovati)}


def _trova_finestra(pezzo: str):
    from metis.tools import finestre

    tutte = [i for i in finestre.elenca() if pezzo.lower() in i.titolo.lower()]
    if not tutte:
        sys.exit(f"nessuna finestra con '{pezzo}' nel titolo")
    if len(tutte) > 1:
        print("  piu' finestre, prendo la prima:",
              "; ".join(i.titolo[:50] for i in tutte))
    return tutte[0]


def _cattura(i, voci: list[Voce], nome: str) -> Path | None:
    """Uno scatto della finestra con i rettangoli sopra. Solo per gli occhi."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen

    app = QGuiApplication.instance() or QGuiApplication([])
    l, t, r, b = i.rect
    schermo = QGuiApplication.screenAt(QRect(l, t, 1, 1).center()) \
        or QGuiApplication.primaryScreen()
    g = schermo.geometry()
    dpr = schermo.devicePixelRatio()
    img = schermo.grabWindow(0, int((l - g.x() * dpr) / dpr), int((t - g.y() * dpr) / dpr),
                             int((r - l) / dpr), int((b - t) / dpr)).toImage()
    p = QPainter(img)
    p.setPen(QPen(QColor(94, 223, 255), 2))
    for n, v in enumerate(voci, 1):
        vl, vt, vr, vb = v.rect
        p.drawRect(vl - l, vt - t, vr - vl, vb - vt)
        p.drawText(vl - l + 2, vt - t + 12, str(n))
    p.end()
    CATTURE.mkdir(parents=True, exist_ok=True)
    out = CATTURE / f"{nome}_{datetime.now():%Y%m%d_%H%M%S}.png"
    img.save(str(out))
    del app
    return out


def spike_uia(pezzo: str, giri: int, confronta: bool, cattura: bool) -> dict:
    i = _trova_finestra(pezzo)
    print(f"{i.titolo[:70]}  ({i.processo}, {i.rect[2] - i.rect[0]}x{i.rect[3] - i.rect[1]})")

    misure = []
    voci: list[Voce] = []
    for g in range(giri):
        voci, m = leggi(i.hwnd, i.rect)
        misure.append(m)
        print(f"  giro {g + 1}: {m['totale_ms']:7.1f} ms  "
              f"(findall {m['findall_ms']:.1f})  restituiti {m['restituiti']:4d}  "
              f"visibili {m['visibili']:4d}")
        time.sleep(0.3)

    caldi = [m["totale_ms"] for m in misure[1:]] or [misure[0]["totale_ms"]]
    per_tipo = Counter(v.tipo for v in voci)
    senza_nome = sum(1 for v in voci if not v.nome.strip())
    esito = {
        "finestra": i.titolo[:120], "processo": i.processo,
        "dimensioni": [i.rect[2] - i.rect[0], i.rect[3] - i.rect[1]],
        "giri": misure,
        "primo_ms": misure[0]["totale_ms"],
        "caldo_mediana_ms": round(statistics.median(caldi), 1),
        "caldo_max_ms": max(caldi),
        "visibili": len(voci), "per_tipo": dict(per_tipo), "senza_nome": senza_nome,
        "sotto_soglia": max(m["totale_ms"] for m in misure) < SOGLIA_MS,
        "esempi": [asdict(v) for v in voci[:15]],
    }
    print(f"  primo {esito['primo_ms']} ms, a caldo mediana {esito['caldo_mediana_ms']} "
          f"ms, max {esito['caldo_max_ms']} ms  ->  "
          f"{'SOTTO' if esito['sotto_soglia'] else 'SOPRA'} 1 s")
    print(f"  per tipo: {dict(per_tipo)}; senza nome: {senza_nome}")
    for v in voci[:8]:
        print(f"     {v.tipo:8s} {v.rect}  {v.nome[:50]!r}")

    if confronta:
        esito["visitatore_vecchio"] = _visitatore_vecchio(i.hwnd)
        print(f"  visitatore di uia.py: {esito['visitatore_vecchio']}")
    if cattura:
        out = _cattura(i, voci, i.processo.split(".")[0])
        esito["cattura"] = str(out)
        print(f"  cattura: {out}")
    return esito


# --- main ------------------------------------------------------------------------

def _salva(tipo: str, dati: dict) -> Path:
    RISULTATI.mkdir(exist_ok=True)
    out = RISULTATI / f"spike_navigazione_{tipo}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cosa", required=True)
    c = sub.add_parser("cdp")
    c.add_argument("--profilo-predefinito", action="store_true")
    u = sub.add_parser("uia")
    u.add_argument("--finestra", required=True, help="pezzo del titolo")
    u.add_argument("--giri", type=int, default=5)
    u.add_argument("--confronta", action="store_true")
    u.add_argument("--cattura", action="store_true")
    a = ap.parse_args()

    if a.cosa == "cdp":
        dati = spike_cdp(a.profilo_predefinito)
    else:
        dati = spike_uia(a.finestra, a.giri, a.confronta, a.cattura)
    print(f"-> {_salva(a.cosa, dati)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
