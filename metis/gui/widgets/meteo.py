"""Il pannello del meteo nella colonna sinistra dell'Hub. PHASE1, D-UI 5.

Disegna quello che manda `metis/gui/workers/meteo.py`, e nient'altro: la
rete sta su quel thread. Quattro stati, dal dizionario:

    ok            temperatura, citta', cielo, tre tessere; "aggiornato alle 14:30"
    vecchio       lo stesso, con "dato delle 14:30 · la rete non risponde"
    assente       nessun dato recente: la frase in persona, al posto dei numeri
    da_impostare  nessuna citta': come dirlo
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from metis.gui import tema
from metis.gui.componenti import Pannello, Tessera

ICONA_VUOTA = "cloud-sun"


def gradi(valore: float) -> str:
    """"18,3°C": la virgola italiana, come nel resto dell'Hub. Senza spazio:
    in un carattere a larghezza fissa sembrava un buco."""
    return f"{valore:.1f}°C".replace(".", ",")


class PannelloMeteo(Pannello):
    def __init__(self, parent=None):
        super().__init__("Meteo", "cloud", parent)
        self.stato = "da_impostare"
        self.icona_nome = ""

        # -- i dati ------------------------------------------------------------
        self.box_dati = QWidget()
        self.box_dati.setObjectName("meteoDati")
        # Trasparenti: altrimenti prendono il fondo della finestra, piu' scuro
        # di quello del pannello.
        self.box_dati.setStyleSheet("#meteoDati { background: transparent; }")
        colonna = QVBoxLayout(self.box_dati)
        colonna.setContentsMargins(0, 0, 0, 0)
        colonna.setSpacing(10)

        riga = QHBoxLayout()
        testi = QVBoxLayout()
        testi.setSpacing(2)
        self.temperatura = QLabel("—")
        self.temperatura.setFont(tema.font(tema.FONT_NUMERI, 26))
        self.temperatura.setStyleSheet(f"color: {tema.TESTO};")
        self.citta = QLabel("")
        self.citta.setFont(tema.font(tema.FONT_TESTO, 13))
        self.citta.setStyleSheet(f"color: {tema.ACCENTO};")
        self.descrizione = QLabel("")
        self.descrizione.setFont(tema.font(tema.FONT_TESTO, 12))
        self.descrizione.setStyleSheet(f"color: {tema.TESTO_SECONDARIO};")
        for w in (self.temperatura, self.citta, self.descrizione):
            testi.addWidget(w)
        riga.addLayout(testi, 1)
        self.icona = QLabel()
        self.icona.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        riga.addWidget(self.icona)
        colonna.addLayout(riga)

        tessere = QGridLayout()
        tessere.setSpacing(8)
        self.umidita = Tessera("Umidità")
        self.vento = Tessera("Vento")
        self.percepita = Tessera("Percepita")
        for i, t in enumerate((self.umidita, self.vento, self.percepita)):
            tessere.addWidget(t, 0, i)
        colonna.addLayout(tessere)

        self.piede = QLabel("")
        self.piede.setFont(tema.font(tema.FONT_TESTO, 11))
        self.piede.setStyleSheet(f"color: {tema.TESTO_TENUE};")
        colonna.addWidget(self.piede)
        self.corpo.addWidget(self.box_dati)

        # -- l'avviso, al posto dei dati ----------------------------------------------
        self.box_avviso = QWidget()
        self.box_avviso.setObjectName("meteoAvviso")
        self.box_avviso.setStyleSheet("#meteoAvviso { background: transparent; }")
        avviso = QVBoxLayout(self.box_avviso)
        avviso.setContentsMargins(12, 12, 12, 12)
        avviso.setSpacing(6)
        self.icona_avviso = QLabel()
        self.icona_avviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icona_avviso.setPixmap(tema.pixmap_icona(ICONA_VUOTA, tema.SEGNAPOSTO, 34,
                                                      self.devicePixelRatioF()))
        self.avviso = QLabel("")
        self.avviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avviso.setWordWrap(True)
        self.avviso.setStyleSheet(f"color: {tema.TESTO_SECONDARIO};")
        avviso.addWidget(self.icona_avviso)
        avviso.addWidget(self.avviso)
        self.corpo.addWidget(self.box_avviso)

        self.aggiorna({"stato": "da_impostare", "messaggio": "Meteo in arrivo…"})

    def aggiorna(self, d: dict) -> None:
        self.stato = d.get("stato", "assente")
        con_dati = self.stato in ("ok", "vecchio") and "temperatura" in d
        self.box_dati.setVisible(con_dati)
        self.box_avviso.setVisible(not con_dati)
        if not con_dati:
            self.avviso.setText(d.get("messaggio") or "")
            return

        self.temperatura.setText(gradi(d["temperatura"]))
        self.citta.setText(d.get("citta", ""))
        self.citta.setVisible(bool(d.get("citta")))
        self.descrizione.setText((d.get("descrizione") or "").capitalize())
        nome = d.get("icona") or "cloud"
        if nome != self.icona_nome:
            self.icona_nome = nome
            self.icona.setPixmap(tema.pixmap_icona(nome, tema.ACCENTO, 52,
                                                   self.devicePixelRatioF()))
        self.umidita.imposta(f"{d.get('umidita', 0)}%")
        self.vento.imposta(f"{d.get('vento_kmh', 0):.0f} km/h")
        self.percepita.imposta(gradi(d.get("percepita", d["temperatura"])))
        ora = d.get("ora", "")
        if self.stato == "vecchio":
            self.piede.setText(f"dato delle {ora} · la rete non risponde")
            self.piede.setStyleSheet(f"color: {tema.ATTENZIONE};")
        else:
            self.piede.setText(f"aggiornato alle {ora}" if ora else "")
            self.piede.setStyleSheet(f"color: {tema.TESTO_TENUE};")

    def breve(self) -> str:
        """Per l'intestazione dell'Hub: "18° Milano", vuoto senza dati."""
        if self.stato not in ("ok", "vecchio") or self.temperatura.text() == "—":
            return ""
        numero = self.temperatura.text().split(",")[0]
        return f"{numero}°  {self.citta.text()}".strip()
