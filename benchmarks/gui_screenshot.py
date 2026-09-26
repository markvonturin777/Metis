"""Catture delle viste di PHASE1 con dati finti, per la revisione visiva.

    python benchmarks/gui_screenshot.py                    # tutte, in data/catture/
    python benchmarks/gui_screenshot.py --stati PARLATO    # solo alcuni stati
    python benchmarks/gui_screenshot.py --larghezza 1280 --altezza 720
    python benchmarks/gui_screenshot.py --nucleo           # il nucleo in ogni stato, un foglio
    python benchmarks/gui_screenshot.py --viste            # Minimal, Diagnostica, T3, impostazioni
    python benchmarks/gui_screenshot.py --evidenza         # PHASE2: la bolla, ogni stile

Il criterio estetico dell'Hub lo chiude l'utente guardando queste immagini:
per un'interfaccia non esiste un test che dica "e' bella". Esiste pero' un
modo di guardarla sempre nelle stesse condizioni — stessi dati, stessi
stati, stesse dimensioni — ed e' questo script.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from metis.core.palette import significato  # noqa: E402
from metis.gui import tema  # noqa: E402
from metis.gui.hub_view import HubView  # noqa: E402
from metis.gui.modello_conversazione import ModelloConversazione  # noqa: E402

CARTELLA = Path("data/catture")
LINK = "https://www.bing.com/aclick?ld=e8" + "7G1qS5Cs3bZcU-1FQBLKqTVUCUwj8UNEw" * 40


def conversazione_finta() -> ModelloConversazione:
    m = ModelloConversazione()
    m.metis("Buongiorno. Sono operativo.")
    m.chiudi_turno()
    m.utente("Che tempo fa oggi a Milano?")
    m.metis("Secondo MeteoAM, oggi a Milano cielo coperto e 18 gradi.")
    m.metis("In serata possibili piogge deboli.")
    m.chiudi_turno()
    m.sistema("strumento: web_search")
    m.utente("apri visual studio code", scritto=True)
    m.metis("Fatto.")
    m.chiudi_turno()
    m.utente("cercami annunci di lavoro in Svizzera", sospetto=True)
    m.metis(f"Ho trovato alcune fonti, per esempio {LINK}")
    m.chiudi_turno()
    for i, msg in enumerate(m.messaggi):          # orari plausibili, non tutti uguali
        msg.ora = datetime.now().replace(second=0) - timedelta(minutes=2 * (len(m) - i))
    return m


# Il meteo finto: la citta' della conversazione finta, non quella dell'utente.
METEO = {"stato": "ok", "messaggio": "", "citta": "Milano", "temperatura": 18.3,
         "percepita": 17.9, "umidita": 70, "vento_kmh": 7.2, "codice": 3, "giorno": True,
         "descrizione": "coperto", "icona": "cloud", "ora": "14:30"}

TELEMETRIA = {"cpu": 8.0, "ram_percento": 44.0, "ram_gb": 7.0, "ram_totale_gb": 16.0,
              "vram_gb": 6.12, "vram_totale_gb": 8.0, "gpu": 23, "gpu_c": 54,
              "disco_usato_gb": 218, "disco_totale_gb": 232}


# Livelli finti: il microfono di chi parla, la voce di Metis a meta' frase.
MICROFONO_DB, VOCE_DB = -22.0, -16.0
STATI_NUCLEO = ("DORMIENTE", "IN_ASCOLTO", "ELABORAZIONE", "RICERCA_WEB", "ATTESA_CONFERMA",
                "PARLATO", "INTERROTTO")


def aspetta(app: QApplication, secondi: float) -> None:
    """Il nucleo si anima: sfumatura del colore e livelli smussati chiedono
    qualche fotogramma prima di arrivare dove devono."""
    fine = time.perf_counter() + secondi
    while time.perf_counter() < fine:
        app.processEvents()
        time.sleep(0.005)


def porta_in(app: QApplication, hub: HubView, stato: str) -> None:
    hub.imposta_stato(stato)
    hub.nucleo.campiona_microfono(MICROFONO_DB)
    hub.nucleo.campiona_voce(VOCE_DB)
    # Il lampo di INTERROTTO si fotografa a meta', non finito.
    aspetta(app, 0.25 if stato in ("INTERROTTO", "ERRORE") else 0.45)


def foglio_nucleo(app: QApplication, hub: HubView, cartella: Path) -> Path:
    lato = hub.nucleo.width()
    colonne = 4
    righe = (len(STATI_NUCLEO) + 1 + colonne - 1) // colonne
    foglio = QPixmap(colonne * lato, righe * (lato + 30))
    foglio.fill(QColor(tema.SFONDO))
    p = QPainter(foglio)
    p.setFont(tema.font(tema.FONT_TESTO, 14))
    casi = [(s, False) for s in STATI_NUCLEO] + [("DORMIENTE", True)]
    for k, (stato, pausa) in enumerate(casi):
        hub.imposta_pausa(pausa)
        porta_in(app, hub, stato)
        x, y = (k % colonne) * lato, (k // colonne) * (lato + 30)
        p.drawPixmap(QPoint(x, y), hub.nucleo.grab())
        p.setPen(QColor(tema.TESTO_SECONDARIO))
        p.drawText(x, y + lato, lato, 26, Qt.AlignmentFlag.AlignCenter,
                   "in pausa" if pausa else significato(stato))
    p.end()
    hub.imposta_pausa(False)
    percorso = cartella / "nucleo_stati.png"
    foglio.save(str(percorso))
    return percorso


def foglio_evidenza(cartella: Path) -> Path:
    """PHASE2, giorni 11-12: la bolla fotogramma per fotogramma, su una pagina
    chiara e su una scura. La forma e' decisa (D-NAV 6); qui si rivedono
    colori, spessori e tempi."""
    from PySide6.QtCore import QRectF

    from metis.gui import evidenza
    from metis.gui.evidenza import Stile
    from metis.gui.numeri import OverlayNumeri, _Bolla

    casi = [
        ("clic: entra (0 ms)", Stile.CLIC, 0, None, True),
        ("clic: si stringe (110 ms)", Stile.CLIC, 110, None, True),
        ("clic: ferma (250 ms)", Stile.CLIC, 250, None, True),
        ("clic: l'onda (+120 ms)", Stile.CLIC, 370, 250, True),
        ("clic: sfuma (+300 ms)", Stile.CLIC, 550, 250, True),
        ("conferma: respira", Stile.ATTESA, 600, None, True),
        ("conferma: respira", Stile.ATTESA, 950, None, True),
        ("rifiuto: lampo (100 ms)", Stile.RIFIUTO, 100, None, True),
        ("rifiuto: sfuma (350 ms)", Stile.RIFIUTO, 350, None, True),
        ("riduci animazioni", Stile.CLIC, 50, None, False),
    ]
    lato_w, lato_h, colonne = 300, 170, 5
    righe_per_sfondo = (len(casi) + colonne - 1) // colonne
    foglio = QPixmap(colonne * lato_w, 2 * righe_per_sfondo * lato_h)
    foglio.fill(QColor(tema.SFONDO))
    p = QPainter(foglio)
    p.setRenderHint(QPainter.Antialiasing)
    for s_idx, (fondo, testo) in enumerate(((Qt.GlobalColor.white, Qt.GlobalColor.darkGray),
                                            (QColor(tema.SFONDO), QColor(tema.TESTO_SECONDARIO)))):
        for k, (titolo, stile, t, t_clic, animato) in enumerate(casi):
            x = (k % colonne) * lato_w
            y = (s_idx * righe_per_sfondo + k // colonne) * lato_h
            p.fillRect(x, y, lato_w, lato_h, fondo)
            p.setPen(testo)
            p.setFont(tema.font(tema.FONT_TESTO, 13))
            # Una riga di "pagina": un link fra due righe di testo.
            p.drawText(x + 20, y + 52, "Notizie di oggi dal mondo e dall'Italia")
            p.drawText(x + 20, y + 118, "Commenti dei lettori (12)   Condividi")
            p.setPen(QColor(tema.ACCENTO_SCURO))
            p.drawText(x + 20, y + 85, "Leggi l'articolo sul terremoto")
            rect = (x + 18.0, y + 70.0, x + 230.0, y + 92.0)
            f = evidenza.fotogramma(stile, t, evidenza.raggio_per(rect), t_clic, None, animato)
            OverlayNumeri._disegna_bolla(p, _Bolla(stile, rect, 0.0, t_clic), f)
            p.setPen(testo)
            p.setFont(tema.font(tema.FONT_TESTO, 11))
            p.drawText(QRectF(x, y + lato_h - 26, lato_w, 20), Qt.AlignmentFlag.AlignCenter,
                       titolo)
    p.end()
    percorso = cartella / "evidenza_bolla.png"
    foglio.save(str(percorso))
    return percorso


def catture_viste(app: QApplication, modello, cartella: Path) -> list[Path]:
    """Le viste di PHASE0 restilizzate (giorni 11-12), con gli stessi dati finti."""
    from metis.gui.fullscreen_view import FullscreenView
    from metis.gui.minimal_view import MinimalView
    from metis.gui.widgets.conferma import DialogoConferma
    from metis.gui.widgets.conversazione import Conversazione
    from metis.gui.widgets.telemetria import Telemetria

    fatte = []
    mini = MinimalView()
    mini.show()
    mini.imposta_stato("PARLATO")
    mini.imposta_ultima("Secondo MeteoAM, oggi a Milano cielo coperto e 18 gradi.")
    for _ in range(20):
        mini.nucleo.campiona_voce(VOCE_DB)
        mini.vu.campiona(MICROFONO_DB, MICROFONO_DB + 8)
        aspetta(app, 0.03)
    fatte.append(cartella / "minimal_parlato.png")
    mini.grab().save(str(fatte[-1]))
    mini.imposta_kill(True)
    aspetta(app, 0.1)
    fatte.append(cartella / "minimal_kill.png")
    mini.grab().save(str(fatte[-1]))
    mini.hide()

    tel = Telemetria()
    tel.aggiorna_risorse(TELEMETRIA)
    for ms in (900, 1100, 1300, 1000):
        tel.aggiorna_turno({"totale_ms": ms, "ttft_ms": 150, "tok_per_s": 54})
    diag = FullscreenView(Conversazione(modello), tel)
    diag.resize(1600, 900)
    diag.show()
    diag.imposta_stato("ELABORAZIONE")
    diag.imposta_corrente("Secondo MeteoAM, oggi a Milano cielo coperto e 18 gradi.")
    diag.imposta_contesto({"conteggio": {"system": 900, "slot": 60, "riassunto": 0,
                                         "turni": 1400, "web": 2100, "totale": 4460},
                           "slot": "[CONTESTO CORRENTE]\nUltimo argomento cercato: meteo Milano",
                           "fonti": ["https://www.meteoam.it/it/meteo-citta/milano"]})
    aspetta(app, 0.3)
    fatte.append(cartella / "diagnostica_1600x900.png")
    diag.grab().save(str(fatte[-1]))
    diag.hide()

    dlg = DialogoConferma("send_email", "T3",
                          {"to": "mario.rossi@example.com", "subject": "Riunione di domani",
                           "body": "Buongiorno,\nconfermo la riunione di domani alle 10.\n"
                                   "A presto."}, timeout_s=30)
    dlg.show()
    aspetta(app, 0.3)
    fatte.append(cartella / "conferma_t3.png")
    dlg.grab().save(str(fatte[-1]))
    dlg._timer.stop()
    dlg.hide()

    from metis.gui.impostazioni import DialogoImpostazioni, Preferenze

    imp = DialogoImpostazioni(Preferenze(citta="Milano", vista_avvio="hub", muto_avvio=True))
    imp.show()
    aspetta(app, 0.2)
    fatte.append(cartella / "impostazioni.png")
    imp.grab().save(str(fatte[-1]))
    imp.hide()
    return fatte


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stati", nargs="*",
                    default=["DORMIENTE", "IN_ASCOLTO", "ELABORAZIONE", "PARLATO",
                             "ATTESA_CONFERMA"])
    ap.add_argument("--larghezza", type=int, default=1600)
    ap.add_argument("--altezza", type=int, default=900)
    ap.add_argument("--cartella", type=Path, default=CARTELLA)
    ap.add_argument("--nucleo", action="store_true", help="solo il foglio degli stati del nucleo")
    ap.add_argument("--viste", action="store_true", help="Minimal, Diagnostica, dialogo T3")
    ap.add_argument("--evidenza", action="store_true", help="PHASE2: la bolla, ogni stile")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    print("font:", tema.applica(app))
    args.cartella.mkdir(parents=True, exist_ok=True)
    if args.evidenza:
        print(foglio_evidenza(args.cartella))
        return 0

    hub = HubView(conversazione_finta())
    hub.resize(args.larghezza, args.altezza)
    hub.imposta_pronto()
    for _ in range(3):
        hub.sistema.aggiorna(TELEMETRIA)
        hub.sessione.aggiorna_risorse(TELEMETRIA)
    hub.sessione.aggiorna_contatori({"turni": 12, "strumenti_ok": 4, "strumenti_negati": 1})
    hub.imposta_meteo(METEO)
    hub.show()
    if args.viste:
        for f in catture_viste(app, hub.modello, args.cartella):
            print(f)
        return 0
    if args.nucleo:
        aspetta(app, 0.3)
        print(foglio_nucleo(app, hub, args.cartella))
        return 0
    for stato in args.stati:
        porta_in(app, hub, stato)
        percorso = args.cartella / f"hub_{args.larghezza}x{args.altezza}_{stato.lower()}.png"
        hub.grab().save(str(percorso))
        print(percorso)
    hub.imposta_kill(True)
    hub.imposta_pausa(True)
    app.processEvents()
    percorso = args.cartella / f"hub_{args.larghezza}x{args.altezza}_kill_pausa.png"
    hub.grab().save(str(percorso))
    print(percorso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
