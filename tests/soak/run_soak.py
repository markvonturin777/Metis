"""Soak test: Metis vivo per ore, con interazioni sintetiche e guasti veri.

    python tests/soak/run_soak.py --ore 72                  # il soak del piano
    python tests/soak/run_soak.py --ore 0.25 --intervallo-min 1 --scala 0.005
                                                           # prova breve: ~15 min
    python tests/soak/run_soak.py --analizza data/soak/soak_20261001_0900

COSA E' VERO E COSA NO
Tutto e' quello di esercizio — `costruisci_sistema`, cioe' Whisper, Qwen,
Piper, broker, audit, scheduler, salute — tranne il microfono. Al suo posto
una `SorgenteSintetica` che consegna blocchi da 32 ms A VELOCITA' REALE:
rumore di fondo quando nessuno parla, e una frase sintetizzata da Piper
quando e' ora di un'interazione. Il piano parlava di "audio riprodotto su
loopback"; qui non c'e' un device loopback, e sostituire la cattura prova la
stessa catena (VAD, endpointing, STT) senza dipendere da un driver in piu'.
E' lo stesso principio di `benchmarks/e2e_replay.py`, applicato al sistema
intero invece che all'orchestratore nudo.

La voce di Metis esce davvero dagli altoparlanti: e' condizione realistica,
e il player e' uno dei pezzi che il soak deve far girare per 72 ore.

IL MIX DEL PIANO: 40 / 30 / 20 / 10
    conversazione   domande di chiacchiera, nessuno strumento
    T1              promemoria (e la loro cancellazione), telemetria
    web             ricerche: rete, estrazione, fonti
    T3              invio email con conferma AUTOMATICA (sì). Se la posta
                    non e' configurata finisce in un rifiuto — ed e' giusto:
                    si prova il percorso della conferma, non si spediscono
                    430 email in tre giorni. Con la posta configurata,
                    `--senza-t3` le toglie.

LE INIEZIONI
    ora 6    Ollama fermo 5 min        automatica con --ollama-auto, se no guidata
    ora 18   rete assente 30 min       guidata (servirebbero privilegi di admin)
    ora 30   microfono scollegato 10'  automatica: la sorgente smette di consegnare
    ora 42   Home Assistant fermo      guidata
    ora 54   VRAM saturata             guidata

"Guidata" vuol dire: l'harness avvisa (console e notifica), registra
l'inizio e la fine, e giudica dall'esterno se Metis ha retto. Non finge di
aver fatto un'iniezione che non ha fatto.

COSA SI SCRIVE, IN data/soak/soak_<data>/
    campioni.jsonl      ogni 60 s: RSS, VRAM (picco sul minuto, a 1 Hz),
                        handle, thread, code, salute
    interazioni.jsonl   ogni interazione: categoria, frase, esito, tempi
    iniezioni.jsonl     inizio, fine, esito di ogni iniezione
    metis.jsonl         il log di Metis per questa prova, separato da quello
                        dell'uso reale: NFR-1 si misura sulle interazioni
                        vere, e mescolarle con le sintetiche lo falserebbe
    rapporto.md         la tabella §3 del tracking, pronta
    grafico.svg         le curve, per guardarne la pendenza
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

RADICE = Path(__file__).resolve().parents[2]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

SR = 16_000
BLOCCO = 512
BLOCCO_S = BLOCCO / SR
CARTELLA = Path("data/soak")

# --- il mix ------------------------------------------------------------------

MIX: dict[str, tuple[float, tuple[str, ...]]] = {
    "conversazione": (0.40, (
        "Che differenza c'e' fra un lago e uno stagno?",
        "Dimmi una curiosita' sui gatti.",
        "Come si prepara un buon caffe' con la moka?",
        "Perche' il cielo e' azzurro?",
        "Qual e' la capitale dell'Australia?",
    )),
    "T1": (0.30, (
        "Ricordami fra due minuti di bere un bicchiere d'acqua.",
        "Quali promemoria ho?",
        "Quanta memoria sta usando il computer?",
        "Annulla il promemoria dell'acqua.",
    )),
    "web": (0.20, (
        "Cerca in rete le ultime notizie sull'esplorazione di Marte.",
        "Cerca online che tempo fa oggi a Milano.",
        "Cerca in rete chi ha vinto l'ultimo Giro d'Italia.",
    )),
    "T3": (0.10, (
        "Mandami una mail con oggetto prova soak e testo tutto bene.",
    )),
}


def sequenza(n: int, seme: int = 7, senza_t3: bool = False) -> list[tuple[str, str]]:
    """Le prime `n` interazioni: (categoria, frase). Deterministica.

    Non si estrae a caso a ogni giro: con 430 estrazioni il 10% di T3 puo'
    uscire 30 volte come 55, e il mix del piano diventerebbe un'intenzione.
    Si costruisce un mazzo con le proporzioni esatte e lo si mescola.
    """
    rng = random.Random(seme)
    categorie = [c for c in MIX if not (senza_t3 and c == "T3")]
    pesi = {c: MIX[c][0] for c in categorie}
    totale = sum(pesi.values())
    mazzo: list[str] = []
    for c in categorie:
        mazzo += [c] * round(n * pesi[c] / totale)
    while len(mazzo) < n:
        mazzo.append(max(pesi, key=pesi.get))
    mazzo = mazzo[:n]
    rng.shuffle(mazzo)
    indici = {c: 0 for c in categorie}
    fuori = []
    for c in mazzo:
        frasi = MIX[c][1]
        fuori.append((c, frasi[indici[c] % len(frasi)]))
        indici[c] += 1
    return fuori


# --- la sorgente audio -------------------------------------------------------

class SorgenteSintetica:
    """Al posto di `AudioCapture`: stessa interfaccia, stesso ritmo.

    Il ritmo e' la cosa importante. Consegnare i blocchi a raffica sarebbe
    piu' veloce e renderebbe la prova inutile: VAD ed endpointing contano
    il silenzio in blocchi, i timeout della macchina a stati contano secondi.
    """

    def __init__(self, rumore: float = 1e-4, seme: int = 0):
        self._rng = np.random.default_rng(seme)
        self._rumore = rumore
        self._coda: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._prossimo = 0.0
        self.scollegata = False
        self.consegnati = 0

    # interfaccia di AudioCapture
    def start(self) -> None:
        if self.scollegata:
            raise RuntimeError("nessun device di ingresso (iniezione del soak)")
        self._prossimo = time.perf_counter()

    def stop(self) -> None:
        pass

    def read(self, timeout: float = 0.25):
        from metis.audio.capture import Block, _dbfs

        if self.scollegata:
            time.sleep(min(timeout, 0.05))
            return None
        ora = time.perf_counter()
        if self._prossimo - ora > 0:
            time.sleep(self._prossimo - ora)
        # In ritardo di oltre un secondo (il thread del ciclo era occupato):
        # si riallinea invece di recuperare a raffica.
        self._prossimo = max(self._prossimo + BLOCCO_S, time.perf_counter() - 1.0)
        with self._lock:
            pcm = self._coda.popleft() if self._coda else None
        if pcm is None:
            pcm = (self._rng.standard_normal(BLOCCO) * self._rumore).astype(np.float32)
        self.consegnati += 1
        rms, picco = _dbfs(pcm)
        return Block(pcm, rms, picco)

    # comandi dell'harness
    def pronuncia(self, pcm: np.ndarray, coda_s: float = 1.2) -> None:
        """Accoda la frase, seguita da silenzio perche' l'endpointing chiuda."""
        rumore = (self._rng.standard_normal(int(coda_s * SR)) * self._rumore).astype(np.float32)
        tutto = np.concatenate([pcm.astype(np.float32), rumore])
        n = tutto.size // BLOCCO
        with self._lock:
            for i in range(n):
                self._coda.append(tutto[i * BLOCCO:(i + 1) * BLOCCO].copy())

    def in_coda(self) -> int:
        with self._lock:
            return len(self._coda)

    def scollega(self) -> None:
        self.scollegata = True

    def ricollega(self) -> None:
        self.scollegata = False


# --- campionamento -----------------------------------------------------------

def leggi_vram_gb() -> float | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml.nvmlDeviceGetMemoryInfo(h).used / 1024**3
    except Exception:                          # noqa: BLE001
        return None


class Campionatore:
    """VRAM a 1 Hz (NFR-4 e' un picco), tutto il resto a 60 s."""

    def __init__(self, uscita: Path, periodo_s: float, sonde: dict,
                 leggi_vram=leggi_vram_gb):
        import psutil

        self.proc = psutil.Process()
        self.uscita = uscita
        self.periodo_s = periodo_s
        self.sonde = sonde
        self.leggi_vram = leggi_vram
        self.fermo = threading.Event()
        self._picco = 0.0
        self.t0 = time.time()
        self.thread = threading.Thread(target=self._ciclo, daemon=True,
                                       name="soak-campionatore")

    def avvia(self) -> None:
        self.thread.start()

    def ferma(self) -> None:
        self.fermo.set()
        self.thread.join(5)

    def campione(self) -> dict:
        m = self.proc.memory_info()
        riga = {
            "t": round(time.time() - self.t0, 1),
            "ts": datetime.now().isoformat(timespec="seconds"),
            "rss_mb": round(m.rss / 1024**2, 1),
            "vram_gb": None,
            "vram_picco_gb": round(self._picco, 3) if self._picco else None,
            "handle": getattr(self.proc, "num_handles", lambda: None)(),
            "thread_os": self.proc.num_threads(),
            "thread_py": threading.active_count(),
        }
        v = self.leggi_vram()
        riga["vram_gb"] = round(v, 3) if v is not None else None
        for nome, sonda in self.sonde.items():
            try:
                riga[nome] = sonda()
            except Exception as exc:           # noqa: BLE001
                riga[nome] = f"errore: {type(exc).__name__}"
        return riga

    def _ciclo(self) -> None:
        prossimo = time.monotonic() + self.periodo_s
        with self.uscita.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.campione()) + "\n")
            while not self.fermo.wait(1.0):
                v = self.leggi_vram()
                if v is not None:
                    self._picco = max(self._picco, v)
                if time.monotonic() >= prossimo:
                    f.write(json.dumps(self.campione()) + "\n")
                    f.flush()
                    self._picco = 0.0
                    prossimo += self.periodo_s


# --- iniezioni ---------------------------------------------------------------

@dataclass
class Iniezione:
    ora: float                  # ore dall'inizio, prima della scala
    tipo: str
    durata_min: float
    istruzioni: str
    automatica: bool = False
    inizio: float | None = None
    fine: float | None = None
    osservato: dict = field(default_factory=dict)


def piano_iniezioni(ollama_auto: bool) -> list[Iniezione]:
    return [
        Iniezione(6, "ollama", 5,
                  "Fermare Ollama (icona nella tray > Quit Ollama) per 5 minuti, "
                  "poi riavviarlo.", automatica=ollama_auto),
        Iniezione(18, "rete", 30,
                  "Scollegare la rete (cavo o Wi-Fi) per 30 minuti."),
        Iniezione(30, "microfono", 10,
                  "Automatica: la sorgente sintetica smette di consegnare blocchi.",
                  automatica=True),
        Iniezione(42, "casa", 10,
                  "Fermare Home Assistant per 10 minuti (se configurato)."),
        Iniezione(54, "vram", 10,
                  "Saturare la VRAM con un altro processo per 10 minuti "
                  "(es. `ollama run` di un secondo modello)."),
    ]


def _ollama(ferma: bool) -> None:
    """Solo con --ollama-auto. Ferma il server e l'app della tray; lo
    riavvia con `ollama serve`, staccato."""
    import subprocess

    if ferma:
        for nome in ("ollama app.exe", "ollama.exe"):
            subprocess.run(["taskkill", "/F", "/IM", nome], capture_output=True)
    else:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["ollama", "serve"], creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- analisi -----------------------------------------------------------------

def retta(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Minimi quadrati: (pendenza, intercetta). Pendenza 0 con meno di 2 punti."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my
    pend = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return pend, my - pend * mx


def percentile(valori: list[float], p: float) -> float | None:
    if not valori:
        return None
    v = sorted(valori)
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _al(campioni: list[dict], chiave: str, ora_h: float) -> float | None:
    """Il valore del campione piu' vicino a `ora_h`, se la prova ci e' arrivata."""
    validi = [c for c in campioni if isinstance(c.get(chiave), (int, float))]
    if not validi or validi[-1]["t"] < ora_h * 3600 - 120:
        return None
    return min(validi, key=lambda c: abs(c["t"] - ora_h * 3600))[chiave]


def analizza(campioni: list[dict], interazioni: list[dict],
             riscaldamento_h: float = 1.0) -> dict:
    """La tabella §3 del tracking, piu' le pendenze.

    La crescita si giudica sulla RETTA dopo il riscaldamento, non sul valore
    finale contro quello iniziale: la prima ora carica cache (dizionari del
    tokenizzatore, pool di connessioni) e un soak che la includesse
    segnalerebbe un "leak" che si ferma da solo. E' la regola del piano:
    si guarda la pendenza.
    """
    durata_h = campioni[-1]["t"] / 3600 if campioni else 0.0
    dopo = [c for c in campioni if c["t"] >= riscaldamento_h * 3600] or campioni
    righe = {}
    for chiave, nome in (("rss_mb", "RSS (MB)"), ("vram_gb", "VRAM (GB)"),
                         ("handle", "Handle"), ("thread_os", "Thread")):
        pts = [(c["t"] / 3600, c[chiave]) for c in dopo
               if isinstance(c.get(chiave), (int, float))]
        if not pts:
            continue
        pend, inter = retta([p[0] for p in pts], [p[1] for p in pts])
        base = inter + pend * pts[0][0]
        fine = inter + pend * pts[-1][0]
        crescita = (fine - base) / base * 100 if base else 0.0
        righe[chiave] = {
            "nome": nome,
            "inizio": _al(campioni, chiave, 0) if campioni else None,
            "24h": _al(campioni, chiave, 24), "48h": _al(campioni, chiave, 48),
            "72h": _al(campioni, chiave, 72),
            "fine": pts[-1][1], "pendenza_h": pend, "crescita_pct": crescita,
        }
    picco_vram = max((c.get("vram_picco_gb") or c.get("vram_gb") or 0.0
                      for c in campioni), default=None)
    code = [c.get("coda_player", 0) or 0 for c in campioni]

    tot = [i["totale_ms"] for i in interazioni if i.get("totale_ms")]
    per_blocco = {}
    for i in interazioni:
        if i.get("totale_ms"):
            per_blocco.setdefault(int(i["t"] // (24 * 3600)), []).append(i["totale_ms"])
    esiti: dict[str, int] = {}
    for i in interazioni:
        esiti[i["esito"]] = esiti.get(i["esito"], 0) + 1
    return {
        "durata_h": durata_h,
        "metriche": righe,
        "vram_picco_gb": picco_vram,
        "coda_player_max": max(code, default=0),
        "latenza_p50_ms": percentile(tot, 50),
        "latenza_p95_ms": percentile(tot, 95),
        "latenza_p95_per_giorno": {g: percentile(v, 95) for g, v in sorted(per_blocco.items())},
        "interazioni": len(interazioni),
        "esiti": esiti,
    }


def verdetto_rss(a: dict, soglia_pct: float = 10.0, minimo_h: float = 3.0) -> str:
    """Sotto le 3 ore non c'e' verdetto: la retta si calcola DOPO la prima
    ora, e con meno di due ore di dati una cache che si scalda e un leak
    sono indistinguibili. La prima prova breve (9 minuti) diceva ❌ per il
    caricamento dei modelli."""
    r = a["metriche"].get("rss_mb")
    if r is None or a["durata_h"] < minimo_h:
        return "—"
    return "✅" if r["crescita_pct"] < soglia_pct else "❌"


def rapporto(a: dict, iniezioni: list[dict]) -> str:
    def f(v, dec=1):
        return "—" if v is None else f"{v:.{dec}f}"

    out = [f"# Soak — {a['durata_h']:.1f} h, {a['interazioni']} interazioni", "",
           "| Metrica | Inizio | 24 h | 48 h | 72 h | Fine | Pendenza / h | Crescita (retta) |",
           "| :-- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in a["metriche"].values():
        out.append(f"| {r['nome']} | {f(r['inizio'])} | {f(r['24h'])} | {f(r['48h'])} "
                   f"| {f(r['72h'])} | {f(r['fine'])} | {r['pendenza_h']:+.3f} "
                   f"| {r['crescita_pct']:+.1f}% |")
    p95g = ", ".join(f"g{g + 1}: {f(v, 0)}" for g, v in a["latenza_p95_per_giorno"].items())
    out += ["",
            f"- **Latenza** p50 {f(a['latenza_p50_ms'], 0)} ms · p95 "
            f"{f(a['latenza_p95_ms'], 0)} ms (per giorno: {p95g or '—'})",
            f"- **Picco VRAM** {f(a['vram_picco_gb'], 2)} GB (NFR-4: ≤ 7,2)",
            f"- **Coda del player** massima {a['coda_player_max']}",
            f"- **Esiti** {a['esiti']}",
            f"- **RSS** {verdetto_rss(a)} (NFR-10: crescita < 10% sulla retta dopo "
            "la prima ora)", "",
            "## Iniezioni", "",
            "| Tipo | Inizio (h) | Fine (h) | Modo | Osservato |",
            "| :-- | ---: | ---: | :-- | :-- |"]
    for i in iniezioni:
        out.append(f"| {i['tipo']} | {f(i.get('inizio_h'), 2)} | {f(i.get('fine_h'), 2)} "
                   f"| {'automatica' if i.get('automatica') else 'guidata'} "
                   f"| {json.dumps(i.get('osservato', {}), ensure_ascii=False)} |")
    return "\n".join(out) + "\n"


def grafico_svg(campioni: list[dict], chiavi=("rss_mb", "vram_gb", "handle", "thread_os"),
                larghezza: int = 900, alto: int = 160) -> str:
    """Un pannello per metrica, con la retta dei minimi quadrati sovrapposta.
    SVG scritto a mano: il soak non deve portarsi dietro matplotlib."""
    pannelli = []
    for n, chiave in enumerate(chiavi):
        pts = [(c["t"] / 3600, c[chiave]) for c in campioni
               if isinstance(c.get(chiave), (int, float))]
        y0 = n * (alto + 30) + 20
        pannelli.append(f'<text x="10" y="{y0 - 5}" font-size="13" '
                        f'font-family="sans-serif">{chiave}</text>')
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        xmax = max(xs) or 1.0
        ymin, ymax = min(ys), max(ys)
        if ymax == ymin:
            ymax = ymin + 1.0

        def px(x, y):
            return (60 + (x / xmax) * (larghezza - 80),
                    y0 + alto - (y - ymin) / (ymax - ymin) * alto)

        linea = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(x, y) for x, y in pts))
        pend, inter = retta(xs, ys)
        (ax, ay), (bx, by) = px(xs[0], inter + pend * xs[0]), px(xs[-1], inter + pend * xs[-1])
        pannelli.append(
            f'<rect x="60" y="{y0}" width="{larghezza - 80}" height="{alto}" '
            f'fill="none" stroke="#ccc"/>'
            f'<polyline points="{linea}" fill="none" stroke="#3b82f6" stroke-width="1.2"/>'
            f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="#ef4444" stroke-dasharray="4 3"/>'
            f'<text x="55" y="{y0 + 10}" font-size="10" text-anchor="end" '
            f'font-family="sans-serif">{ymax:.1f}</text>'
            f'<text x="55" y="{y0 + alto}" font-size="10" text-anchor="end" '
            f'font-family="sans-serif">{ymin:.1f}</text>'
            f'<text x="{larghezza - 20}" y="{y0 + alto + 14}" font-size="10" '
            f'text-anchor="end" font-family="sans-serif">{xmax:.1f} h · '
            f'pendenza {pend:+.3f}/h</text>')
    h = len(chiavi) * (alto + 30) + 20
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{larghezza}" height="{h}" '
            f'style="background:#fff">{"".join(pannelli)}</svg>\n')


def leggi_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(r) for r in path.read_text(encoding="utf-8").splitlines() if r.strip()]


def scrivi_rapporto(cartella: Path) -> dict:
    campioni = leggi_jsonl(cartella / "campioni.jsonl")
    interazioni = leggi_jsonl(cartella / "interazioni.jsonl")
    iniezioni = leggi_jsonl(cartella / "iniezioni.jsonl")
    a = analizza(campioni, interazioni)
    (cartella / "rapporto.md").write_text(rapporto(a, iniezioni), encoding="utf-8")
    (cartella / "grafico.svg").write_text(grafico_svg(campioni), encoding="utf-8")
    return a


# --- la prova ----------------------------------------------------------------

def sintetizza_frasi(frasi: set[str]) -> dict[str, np.ndarray]:
    """Tutte le frasi del mix, una volta, a 16 kHz. Con Piper: la voce e'
    diversa da quella dell'utente, ma e' italiana e pulita, e il soak misura
    la tenuta nel tempo, non il WER (quello e' NFR-5, con la voce vera)."""
    import soxr

    from metis.tts import create_engine

    tts = create_engine("piper")
    fuori = {}
    for frase in frasi:
        s = tts.synth(frase)
        pcm = soxr.resample(np.asarray(s.pcm, dtype=np.float32), s.sample_rate, SR)
        fuori[frase] = (pcm * 0.5).astype(np.float32)     # ~ livello di un microfono
    return fuori


def esegui(args) -> Path:
    from metis.core import logging as mlog

    cartella = CARTELLA / f"soak_{datetime.now():%Y%m%d_%H%M}"
    cartella.mkdir(parents=True, exist_ok=True)
    # Il log di Metis per questa prova va nella sua cartella: vedi la nota in
    # testa. Va fissato PRIMA di `configure`.
    mlog.JSONL = cartella / "metis.jsonl"
    mlog.configure(level="INFO")
    log = mlog.get_logger()

    from metis.core.avvio import CicloAudio, Opzioni, costruisci_sistema
    from metis.core.errors import SALUTE
    from metis.core.state_machine import State

    durata_s = args.ore * 3600
    intervallo_s = args.intervallo_min * 60
    n = max(1, int(durata_s // intervallo_s))
    mix = sequenza(n, senza_t3=args.senza_t3)
    print(f"  soak: {args.ore} h, {n} interazioni ogni {args.intervallo_min} min -> {cartella}")

    print("  sintesi delle frasi...")
    audio = sintetizza_frasi({f for _, f in mix})

    fine_turno = threading.Event()
    ultimo: dict = {}

    def al_turno(m) -> None:
        b = m.breakdown()
        ultimo.clear()
        ultimo.update(totale_ms=round(b["totale"]), stt_ms=round(b["stt"]),
                      ttft_ms=round(b["ttft"]), tokens=m.tokens,
                      tok_s=round(m.tok_per_s, 1), trascritto=m.transcript,
                      strumento=m.extra.get("tool"))
        fine_turno.set()

    microfono: list[tuple[float, bool]] = []
    t0 = time.time()
    sistema = costruisci_sistema(
        Opzioni(wakeword=False, tools=True, whisper=args.whisper, saluto=False),
        log, riporta=lambda r: print("  " + r),
        chiedi_conferma=lambda spec, call: True,       # "T3 auto-confermate"
        on_turno=al_turno)
    orch = sistema.orchestrator
    sorgente = SorgenteSintetica()
    ciclo = CicloAudio(orch, apri_cattura=lambda: sorgente,
                       on_microfono=lambda ok: microfono.append((time.time() - t0, ok)))
    thread_ciclo = threading.Thread(target=ciclo.esegui, daemon=True, name="soak-ciclo")
    thread_ciclo.start()

    campionatore = Campionatore(
        cartella / "campioni.jsonl", args.campione_s,
        sonde={
            "coda_player": lambda: sistema.player._q.qsize(),
            "annunci": lambda: len(orch._annunci),
            "coda_sorgente": sorgente.in_coda,
            "stato": lambda: orch.sm.state.name,
            "turni": lambda: orch.counters.turns,
            "errori": lambda: orch.counters.errors,
            "salute_giu": lambda: SALUTE.stato(),
            "microfono_perdite": lambda: ciclo.perdite,
        })
    campionatore.avvia()

    iniezioni = piano_iniezioni(args.ollama_auto)
    f_int = (cartella / "interazioni.jsonl").open("a", encoding="utf-8")
    f_inj = (cartella / "iniezioni.jsonl").open("a", encoding="utf-8")

    def gestisci_iniezioni(t: float) -> None:
        from metis.tools import notify

        for inj in iniezioni:
            inizio_s = inj.ora * 3600 * args.scala
            fine_s = inizio_s + inj.durata_min * 60 * max(args.scala, 0.02)
            if inj.inizio is None and t >= inizio_s and inizio_s < durata_s:
                inj.inizio = t
                testo = f"Iniezione '{inj.tipo}': {inj.istruzioni}"
                print(f"\n  >>> {testo}\n")
                notify.mostra("Metis soak", testo)
                if inj.automatica and inj.tipo == "microfono":
                    sorgente.scollega()
                elif inj.automatica and inj.tipo == "ollama":
                    _ollama(ferma=True)
            elif inj.inizio is not None and inj.fine is None and t >= fine_s:
                inj.fine = t
                if inj.automatica and inj.tipo == "microfono":
                    sorgente.ricollega()
                elif inj.automatica and inj.tipo == "ollama":
                    _ollama(ferma=False)
                print(f"\n  <<< fine iniezione '{inj.tipo}'\n")
            elif inj.inizio is not None and inj.fine is None:
                # Cosa vede Metis durante l'iniezione: e' la prova che se
                # n'e' accorto, non solo che e' sopravvissuto.
                o = inj.osservato
                giu = o.setdefault("giu", [])
                for k in SALUTE.stato():
                    if k not in giu:
                        giu.append(k)
                o["microfono_perso"] = o.get("microfono_perso") or any(
                    not ok for tt, ok in microfono if tt >= inj.inizio)

    def chiudi_iniezioni_scritte() -> None:
        for inj in iniezioni:
            if inj.inizio is None:
                continue
            o = inj.osservato
            if inj.tipo == "microfono":
                o["ripreso"] = any(ok for tt, ok in microfono if inj.fine and tt >= inj.fine)
            f_inj.write(json.dumps({
                "tipo": inj.tipo, "automatica": inj.automatica,
                "inizio_h": inj.inizio / 3600, "fine_h": (inj.fine or 0) / 3600,
                "osservato": o}, ensure_ascii=False) + "\n")

    try:
        for i, (cat, frase) in enumerate(mix):
            obiettivo = (i + 1) * intervallo_s
            while time.time() - t0 < obiettivo:
                gestisci_iniezioni(time.time() - t0)
                time.sleep(1.0)
            t = time.time() - t0
            riga = {"t": round(t, 1), "i": i, "categoria": cat, "frase": frase}
            if orch.sm.state is not State.DORMIENTE:
                riga["esito"] = f"saltata: {orch.sm.state.name}"
            elif sorgente.scollegata:
                riga["esito"] = "saltata: microfono scollegato"
            else:
                fine_turno.clear()
                orch.on_ptt()
                sorgente.pronuncia(audio[frase])
                if fine_turno.wait(args.attesa_turno_s):
                    riga.update(ultimo)
                    riga["esito"] = "ok"
                else:
                    riga["esito"] = "senza turno"     # STT vuoto, timeout, guasto
                    riga["stato_finale"] = orch.sm.state.name
            f_int.write(json.dumps(riga, ensure_ascii=False) + "\n")
            f_int.flush()
            print(f"  [{t / 3600:6.2f} h] {cat:<13} {riga['esito']:<12} "
                  f"{riga.get('totale_ms', '')}")
    except KeyboardInterrupt:
        print("\n  interrotto: si chiude e si scrive il rapporto su cio' che c'e'.")
    finally:
        chiudi_iniezioni_scritte()
        f_int.close()
        f_inj.close()
        campionatore.ferma()
        ciclo.ferma()
        thread_ciclo.join(5)
        orch.panic()
        sistema.player.close()
        sistema.chiudi()
    a = scrivi_rapporto(cartella)
    print(f"\n  RSS {verdetto_rss(a)} · rapporto: {cartella / 'rapporto.md'}")
    return cartella


def main() -> int:
    # La console di Windows e' cp1252: il primo ❌ del rapporto la faceva
    # cadere, dopo nove minuti di prova, sull'ultima riga.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Soak test di Metis")
    ap.add_argument("--ore", type=float, default=72.0)
    ap.add_argument("--intervallo-min", type=float, default=10.0)
    ap.add_argument("--campione-s", type=float, default=60.0)
    ap.add_argument("--scala", type=float, default=1.0,
                    help="moltiplica gli orari delle iniezioni (0.005 = ora 6 a ~2 min)")
    ap.add_argument("--attesa-turno-s", type=float, default=120.0)
    ap.add_argument("--whisper", default="small")
    ap.add_argument("--senza-t3", action="store_true")
    ap.add_argument("--ollama-auto", action="store_true",
                    help="ferma e riavvia Ollama da solo all'ora 6")
    ap.add_argument("--analizza", type=Path,
                    help="rifa' rapporto e grafico di una cartella esistente")
    args = ap.parse_args()
    if args.analizza:
        a = scrivi_rapporto(args.analizza)
        print((args.analizza / "rapporto.md").read_text(encoding="utf-8"))
        return 0 if verdetto_rss(a) != "❌" else 1
    esegui(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
