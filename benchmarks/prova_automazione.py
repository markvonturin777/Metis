"""L'automazione di M4, verificata contro il sistema vero.

    python benchmarks/prova_automazione.py              # tutto
    python benchmarks/prova_automazione.py finestre
    python benchmarks/prova_automazione.py input
    python benchmarks/prova_automazione.py browser

COSA VERIFICA, CHE NON E' QUELLO CHE VERIFICA LA SUITE
`pytest` copre la matematica: il trasferimento di un rettangolo fra monitor
a DPI diversi, la scelta fra due elementi omonimi, il rifiuto quando non si
trova niente. Sono funzioni pure, e le si verifica con monitor e finestre
inventati.

Quello che nessun test in memoria puo' dire e' se **Windows si comporta
come crediamo**: se una finestra massimizzata si sposta davvero, se un
carattere accentato arriva davvero nella casella, se il clic calcolato sul
rettangolo di un link atterra davvero su quel link. Qui si apre una cavia
vera e le si fanno cose vere, controllando l'effetto dall'altra parte.

NON TOCCA NIENTE DI TUO
La cavia e' una finestra creata da questo banco. Il Chrome della prova web
e' una seconda istanza con un profilo temporaneo e la porta di debug: le
tue schede, i tuoi login e le tue finestre restano dove sono. Quando la
prova finisce, chiude solo cio' che ha aperto — riconoscendolo dal profilo,
non dal nome del processo.

TUTTO PASSA DAL BROKER
Nessun gesto di questo banco chiama un handler direttamente. Se lo facesse,
verificherebbe che `SendInput` funziona, che non e' la domanda: la domanda
e' se l'automazione di Metis funziona, e l'automazione di Metis e' il
broker piu' gli handler.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from metis.tools.display import set_dpi_awareness

# Prima di tutto, come in `metis/gui/app.py`: senza, le coordinate dei clic
# sarebbero virtualizzate e questo banco misurerebbe la cosa sbagliata.
set_dpi_awareness()

from metis.security.audit import AuditLog          # noqa: E402
from metis.security.broker import Broker           # noqa: E402
from metis.security.guards import ALLOWLIST_APP    # noqa: E402
from metis.security.policies import Context        # noqa: E402
from metis.tools import browser, finestre          # noqa: E402
from metis.tools.display import monitor_di_rect, monitors, tabella  # noqa: E402
from metis.tools.registry import carica_tutti      # noqa: E402

TITOLO = "CAVIA-METIS-M4"
CAVIA = Path(__file__).with_name("cavia.py")
PORTA = 9222

PAGINA = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>BERSAGLIO-M4</title>
<style>
 body { font: 16px sans-serif; margin: 0; padding: 40px; }
 a, button { display: block; margin: 26px 0; font-size: 20px; }
 h1 { margin-top: 0 }
</style></head><body>
<h1>Bersaglio M4</h1>
<a href="#" onclick="segna('contatti');return false">Contatti</a>
<a href="#" onclick="segna('chi siamo');return false">Chi siamo</a>
<button onclick="segna('invia')">Invia</button>
<a href="#" onclick="segna('doppio-a');return false">Ambiguo</a>
<a href="#" onclick="segna('doppio-b');return false">Ambiguo</a>
<p id="esito">niente</p>
<script>
 window.premuti = [];
 function segna(n) { window.premuti.push(n);
   document.getElementById('esito').textContent = window.premuti.join(','); }
</script></body></html>"""


class Conteggio:
    def __init__(self):
        self.ok = 0
        self.totale = 0

    def segna(self, riuscito: bool, nome: str, dettaglio: str = "") -> bool:
        self.totale += 1
        self.ok += bool(riuscito)
        print(f"  {'OK  ' if riuscito else 'NO  '} {nome:<34} {dettaglio}")
        return bool(riuscito)


def _broker(tmp: Path) -> Broker:
    return Broker(registry=carica_tutti(), audit=AuditLog(tmp / "audit.db"))


def _apri_cavia(con_stdout: bool = False):
    proc = subprocess.Popen(
        [sys.executable, str(CAVIA), TITOLO],
        stdout=subprocess.PIPE if con_stdout else None, text=True, bufsize=1)
    righe: queue.Queue = queue.Queue()
    if con_stdout:
        threading.Thread(
            target=lambda: [righe.put(r.strip()) for r in proc.stdout],
            daemon=True).start()
    for _ in range(30):
        time.sleep(0.2)
        try:
            finestre.risolvi(TITOLO)
            time.sleep(0.5)
            return proc, righe
        except Exception:                        # noqa: BLE001
            continue
    raise SystemExit("la cavia non e' comparsa")


# --- finestre ----------------------------------------------------------------

def prova_finestre(tmp: Path) -> Conteggio:
    print(tabella())
    c = Conteggio()
    proc, _ = _apri_cavia()
    b = _broker(tmp)
    ctx = Context(origine="banco")
    i = finestre.risolvi(TITOLO)
    print(f"\ncavia: hwnd={i.hwnd} monitor={monitor_di_rect(i.rect).indice} "
          f"rect={i.rect}\n")

    def passo(nome, call, controllo):
        time.sleep(0.35)
        r = b.execute(call, ctx)
        dopo = finestre.info(i.hwnd)
        c.segna(bool(r.ok and dopo and controllo(dopo, r)), nome,
                f"{r.outcome.value:<7} rect={dopo.rect if dopo else '?'}")

    passo("sposta sull altro schermo",
          {"tool": "move_window_to_monitor", "window": TITOLO, "monitor": "altro"},
          lambda d, r: monitor_di_rect(d.rect).indice != 0)
    passo("riportala sul primario",
          {"tool": "move_window_to_monitor", "window": TITOLO, "monitor": "primario"},
          lambda d, r: monitor_di_rect(d.rect).indice == 0)
    passo("meta destra",
          {"tool": "resize_window", "window": TITOLO, "disposizione": "meta_destra"},
          lambda d, r: d.rect[0] >= monitors()[0].lavoro[2] // 2 - 4)
    passo("meta sinistra",
          {"tool": "resize_window", "window": TITOLO, "disposizione": "meta_sinistra"},
          lambda d, r: d.rect[0] <= monitors()[0].lavoro[0] + 4)
    passo("massimizza",
          {"tool": "maximize_window", "window": TITOLO},
          lambda d, r: d.stato == "massimizzata")
    # Il caso che il piano chiama "in questo ordine": una finestra
    # massimizzata e' agganciata al suo schermo e non si sposta finche' non
    # la si ripristina.
    passo("sposta MASSIMIZZATA sull altro",
          {"tool": "move_window_to_monitor", "window": TITOLO, "monitor": "altro"},
          lambda d, r: d.stato == "massimizzata" and monitor_di_rect(d.rect).indice != 0)
    passo("ripristina",
          {"tool": "restore_window", "window": TITOLO},
          lambda d, r: d.stato == "normale")
    passo("riduci a icona",
          {"tool": "minimize_window", "window": TITOLO},
          lambda d, r: d.stato == "ridotta")
    passo("porta davanti",
          {"tool": "focus_window", "window": TITOLO},
          lambda d, r: r.value.get("in_primo_piano"))

    print("\n  rifiuti attesi:")
    for nome, call, pezzo in [
        ("titolo che non esiste",
         {"tool": "maximize_window", "window": "photoshop-inesistente"}, "non trovo"),
        ("schermo che non c'e'",
         {"tool": "move_window_to_monitor", "window": TITOLO, "monitor": "3"}, "ne vedo"),
    ]:
        r = b.execute(call, ctx)
        c.segna(r.denied and r.stage == "strumento" and pezzo in r.detail,
                nome, f"{r.outcome.value:<7} {r.detail[:52]}")

    proc.terminate()
    time.sleep(0.3)
    return c


# --- input sintetico ---------------------------------------------------------

def prova_input(tmp: Path) -> Conteggio:
    c = Conteggio()
    proc, righe = _apri_cavia(con_stdout=True)
    b = _broker(tmp)
    ctx = Context(origine="banco")

    def sentito(prefisso: str, entro: float = 2.0) -> str | None:
        """L'ULTIMA riga con quel prefisso. La cavia riporta la casella a
        ogni carattere: la prima riga sarebbe "p", non la frase."""
        fine = time.perf_counter() + entro
        ultima = None
        while time.perf_counter() < fine:
            try:
                r = righe.get(timeout=0.1)
            except queue.Empty:
                continue
            if r.startswith(prefisso):
                ultima = r
                fine = min(fine, time.perf_counter() + 0.4)
        return ultima

    def davanti() -> bool:
        r = b.execute({"tool": "focus_window", "window": TITOLO}, ctx)
        time.sleep(0.4)
        return bool(r.ok and r.value.get("in_primo_piano"))

    def gesto(nome, call, verifica):
        if not davanti():
            c.segna(False, nome, "la cavia non e' venuta davanti")
            return
        r = b.execute(call, ctx)
        c.segna(bool(r.ok and verifica()), nome,
                f"{r.outcome.value:<7} {str(r.value)[:60] if r.ok else r.detail[:60]}")

    # Gli accenti sono il motivo per cui si usa KEYEVENTF_UNICODE invece
    # dei codici virtuali: con quelli, "però" dipende dal layout.
    gesto("scrivi, accenti compresi",
          {"tool": "type_text", "text": "citta, perché, però"},
          lambda: (sentito("TESTO") or "").endswith("però"))
    gesto("premi ctrl+a",
          {"tool": "press_hotkey", "keys": ["ctrl", "a"]}, lambda: True)
    b.execute({"tool": "press_hotkey", "keys": ["backspace"]}, ctx)
    gesto("clicca il pulsante per nome",
          {"tool": "click_element", "elemento": "Bersaglio", "tipo": "pulsante"},
          lambda: sentito("CLIC") is not None)
    gesto("scorri", {"tool": "scroll", "verso": "giu", "quantita": 2},
          lambda: True)

    print("\n  rifiuti attesi:")
    for nome, call, stadio, pezzo in [
        ("shift+canc, in ogni caso",
         {"tool": "press_hotkey", "keys": ["shift", "delete"]},
         "guardie", "non consentita"),
        ("win+r, in ogni caso",
         {"tool": "press_hotkey", "keys": ["win", "r"]},
         "guardie", "non consentita"),
        ("clic su cio' che non esiste",
         {"tool": "click_element", "elemento": "Zqxwv non esiste"},
         "strumento", "non trovo"),
    ]:
        davanti()
        r = b.execute(call, ctx)
        c.segna(r.denied and r.stage == stadio and pezzo in r.detail, nome,
                f"{r.outcome.value:<7} {r.stage:<12} {r.detail[:44]}")

    proc.terminate()
    time.sleep(0.3)
    return c


# --- browser -----------------------------------------------------------------

def chiudi_chrome_di_prova() -> int:
    """Chiude SOLO i Chrome di questo banco, riconosciuti dalla porta di
    debug o dal profilo temporaneo.

    Serve perche' Chrome sopravvive a `terminate()` sul processo che l'ha
    lanciato: i figli restano, e alla prova successiva ci si ritrova due
    finestre con lo stesso titolo. Il rifiuto per ambiguita' che ne segue e'
    corretto, ma qui e' rumore.
    """
    import psutil

    n = 0
    for pr in psutil.process_iter(["name", "cmdline"]):
        if not pr.info["name"] or pr.info["name"].lower() != "chrome.exe":
            continue
        riga = " ".join(pr.info["cmdline"] or [])
        if f"remote-debugging-port={PORTA}" in riga:
            try:
                pr.kill()
                n += 1
            except Exception:                    # noqa: BLE001
                pass
    if n:
        time.sleep(1.2)
    return n


def prova_browser(tmp: Path) -> Conteggio:
    c = Conteggio()
    voce = ALLOWLIST_APP.get("chrome")
    if voce is None or not voce.percorso.exists():
        print("  chrome non e' nell'allowlist: prova saltata")
        return c

    rimasti = chiudi_chrome_di_prova()
    if rimasti:
        print(f"  chiusi {rimasti} chrome di prova rimasti da prima")

    html = tmp / "bersaglio.html"
    html.write_text(PAGINA, encoding="utf-8")
    proc = subprocess.Popen([
        str(voce.percorso), f"--remote-debugging-port={PORTA}",
        f"--user-data-dir={tmp / 'profilo'}",     # non tocca il profilo vero
        "--no-first-run", "--no-default-browser-check",
        "--new-window", html.as_uri()])

    for _ in range(60):
        time.sleep(0.5)
        if browser.porta_aperta(PORTA):
            break
    else:
        print("  la porta di debug non si e' aperta")
        proc.terminate()
        return c
    time.sleep(2.0)

    b = _broker(tmp)
    ctx = Context(origine="banco")

    with browser.pagina_attiva() as pag:
        riq = browser._riquadro(pag)
        print(f"  riquadro: finestra=({riq.screen_x},{riq.screen_y}) "
              f"bordo=({riq.bordo_x},{riq.bordo_y}) dpr={riq.dpr}")

    def premuti() -> list:
        with browser.pagina_attiva() as p:
            return p.evaluate("() => window.premuti || []")

    def davanti() -> bool:
        r = b.execute({"tool": "focus_window", "window": "BERSAGLIO-M4"}, ctx)
        time.sleep(0.5)
        return bool(r.ok and r.value.get("in_primo_piano"))

    def clic(nome, elemento, tipo, atteso):
        if not davanti():
            c.segna(False, nome, "Chrome non e' venuto davanti")
            return
        r = b.execute({"tool": "click_element", "elemento": elemento,
                       "tipo": tipo}, ctx)
        time.sleep(0.6)
        ora = premuti()
        c.segna(bool(r.ok and ora and ora[-1] == atteso), nome,
                f"{r.outcome.value:<7} pagina={ora}")

    clic("link Contatti", "Contatti", "link", "contatti")
    clic("link Chi siamo", "Chi siamo", "link", "chi siamo")
    clic("pulsante Invia", "Invia", "pulsante", "invia")

    print("\n  rifiuti attesi:")
    for nome, elemento, tipo, pezzo in [
        ("link che non esiste", "Iscriviti alla newsletter", "qualsiasi", "non trovo"),
        ("due link identici", "Ambiguo", "link", "2 elementi"),
    ]:
        davanti()
        prima = premuti()
        r = b.execute({"tool": "click_element", "elemento": elemento,
                       "tipo": tipo}, ctx)
        time.sleep(0.4)
        # Che non abbia cliccato niente conta quanto il rifiuto: un clic a
        # caso seguito da un messaggio di rifiuto sarebbe il peggio.
        c.segna(r.denied and r.stage == "strumento" and pezzo in r.detail
                and premuti() == prima, nome,
                f"{r.outcome.value:<7} {r.detail[:52]}")

    proc.terminate()
    time.sleep(0.5)
    chiudi_chrome_di_prova()
    return c


# --- ingresso -----------------------------------------------------------------

PROVE = {"finestre": prova_finestre, "input": prova_input,
         "browser": prova_browser}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("prova", nargs="?", default="tutto", choices=[*PROVE, "tutto"])
    args = ap.parse_args()

    scelte = list(PROVE) if args.prova == "tutto" else [args.prova]
    tmp = Path(tempfile.mkdtemp(prefix="metis-m4-"))
    totale = Conteggio()
    for nome in scelte:
        print(f"\n{'=' * 66}\n{nome.upper()}\n{'=' * 66}")
        c = PROVE[nome](tmp)
        totale.ok += c.ok
        totale.totale += c.totale
        print(f"\n  {c.ok}/{c.totale}")

    print(f"\n{'=' * 66}\n{totale.ok}/{totale.totale} verificati")
    return 0 if totale.ok == totale.totale else 1


if __name__ == "__main__":
    sys.exit(main())
