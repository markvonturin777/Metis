"""Vista dell'audit log. Serve all'utente e servira' soprattutto a M4.

PERCHE' E' PIU' UNO STRUMENTO DI SVILUPPO CHE UN CRUSCOTTO
Durante M4 la domanda ricorrente sara' "perche' non l'ha fatto?". La
risposta e' sempre nell'audit log — quale stadio ha negato, con quali
argomenti, con quale finestra davanti — e leggerla in una tabella filtrabile
invece che in un file SQLite cambia il tempo di diagnosi da minuti a
secondi.

LA LETTURA DAL THREAD DELLA GUI E' AMMESSA
`AuditLog` e' esplicitamente thread-safe: lock interno e connessione aperta
con `check_same_thread=False`, fin da M1. E' l'unico oggetto del nucleo che
la GUI tocca direttamente, ed e' cosi' perche' e' stato progettato per
questo. Una copia dei dati spedita via segnale non aggiungerebbe sicurezza
e aggiungerebbe una seconda verita'.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

COLORI_ESITO = {"ok": "#22c55e", "denied": "#ef4444", "error": "#f59e0b"}
COLONNE = ("ora", "tier", "strumento", "esito", "stadio", "motivo")


class VistaAudit(QWidget):
    def __init__(self, audit=None, righe: int = 200, parent=None):
        super().__init__(parent)
        self.audit = audit
        self.max_righe = righe
        # Ultimo stato disegnato: id della riga piu' recente, quante righe, e
        # i due filtri. Se non e' cambiato niente non si ridisegna. Vedi la
        # nota su M5 in testa al modulo.
        self._ultimo_id: tuple = ()
        self.ridisegni = 0

        radice = QVBoxLayout(self)
        radice.setContentsMargins(4, 4, 4, 4)

        filtri = QHBoxLayout()
        filtri.addWidget(QLabel("AUDIT"))
        self.filtro_tier = QComboBox()
        self.filtro_tier.addItems(["tutti", "T0", "T1", "T2", "T3"])
        self.filtro_esito = QComboBox()
        self.filtro_esito.addItems(["tutti", "ok", "denied", "error"])
        for c in (self.filtro_tier, self.filtro_esito):
            c.currentTextChanged.connect(self.ricarica)
            filtri.addWidget(c)
        filtri.addStretch(1)
        self.riassunto = QLabel("—")
        self.riassunto.setStyleSheet("color: #94a3b8; font-size: 11px;")
        filtri.addWidget(self.riassunto)
        radice.addLayout(filtri)

        self.tabella = QTableWidget(0, len(COLONNE))
        self.tabella.setHorizontalHeaderLabels(
            ["ora", "tier", "strumento", "esito", "stadio", "motivo"])
        self.tabella.verticalHeader().setVisible(False)
        self.tabella.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabella.setSelectionBehavior(QTableWidget.SelectRows)
        intestazione = self.tabella.horizontalHeader()
        # `Interactive`, non `ResizeToContents`. La differenza e' il motivo per
        # cui la GUI si bloccava: con ResizeToContents **ogni** `setItem`
        # invalida la geometria dell'intestazione e Qt rimisura tutte le
        # righe della colonna. Riempire 164 righe per 6 colonne diventa
        # centomila calcoli di dimensione, sotto un foglio di stile che li
        # rende tutti costosi. Misurato: **5,1 secondi**.
        #
        # Il lavoro e' DIFFERITO all'event loop, quindi cronometrare
        # `ricarica()` dava 3 ms e non si vedeva niente. Si vedeva solo dal
        # vivo, come 2,6 s di interfaccia ferma ogni 3.
        #
        # Adesso le colonne si adattano una volta sola, a riempimento finito.
        for i in range(len(COLONNE) - 1):
            intestazione.setSectionResizeMode(i, QHeaderView.Interactive)
        intestazione.setSectionResizeMode(len(COLONNE) - 1, QHeaderView.Stretch)
        radice.addWidget(self.tabella)

        # Un secondo: l'audit log cresce di qualche riga al minuto, non
        # serve di piu' e interrogare SQLite a ogni fotogramma sarebbe
        # sprecato.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.ricarica)
        self._timer.start(1000)

    @Slot()
    def ricarica(self) -> None:
        if self.audit is None:
            return
        try:
            righe = self.audit.recent(limit=self.max_righe)
            stat = self.audit.stats()
        except Exception:                     # noqa: BLE001
            # Il database e' chiuso, o e' in scrittura: si riprova fra un
            # secondo. Un cruscotto non deve mai far cadere l'applicazione.
            return

        tier = self.filtro_tier.currentText()
        esito = self.filtro_esito.currentText()
        if tier != "tutti":
            righe = [r for r in righe if r["tier"] == tier]
        if esito != "tutti":
            righe = [r for r in righe if r["outcome"] == esito]

        # Se non e' cambiato niente non si ridisegna. E' il caso NORMALE: il
        # timer batte una volta al secondo e l'audit log cresce di qualche
        # riga al minuto, quindi 59 battiti su 60 non hanno niente da fare.
        #
        # `self._ultimo_id` esisteva dal primo giorno di questo widget ed era
        # dichiarato e mai letto: la guardia era prevista e non cablata.
        firma = (righe[0]["id"] if righe else -1, len(righe), tier, esito)
        if firma == self._ultimo_id:
            return
        self._ultimo_id = firma
        self.ridisegni += 1

        # Aggiornamenti sospesi durante il riempimento: senza, la tabella si
        # ridisegna a ogni cella.
        self.tabella.setUpdatesEnabled(False)
        try:
            self.tabella.setRowCount(len(righe))
            for i, r in enumerate(righe):
                valori = [
                    str(r["ts"])[11:19], r["tier"], r["tool"], r["outcome"],
                    r["stage"] or "", (r["detail"] or "")[:120],
                ]
                for j, v in enumerate(valori):
                    cella = QTableWidgetItem(v)
                    if j == 3:
                        cella.setForeground(Qt.GlobalColor.white)
                        colore = COLORI_ESITO.get(r["outcome"])
                        if colore:
                            cella.setToolTip(r["detail"] or "")
                    self.tabella.setItem(i, j, cella)
        finally:
            self.tabella.setUpdatesEnabled(True)
        # Una volta sola, a riempimento finito: e' la riga che ResizeToContents
        # faceva mille volte.
        self.tabella.resizeColumnsToContents()

        non_confermate = stat.get("t3_non_confermate", 0)
        avviso = "" if non_confermate == 0 else f"  ⚠ T3 NON CONFERMATE: {non_confermate}"
        self.riassunto.setText(
            f"{stat['totale']} azioni · " +
            " ".join(f"{k}:{v}" for k, v in sorted(stat["per_esito"].items())) +
            avviso)
        self.riassunto.setStyleSheet(
            "color: #ef4444; font-size: 11px;" if non_confermate
            else "color: #94a3b8; font-size: 11px;")

    def collega(self, audit) -> None:
        self.audit = audit
        self.ricarica()
