"""Le Impostazioni dell'Hub (⚙). PHASE1, giorni 11-12.

    citta' del meteo      [meteo] citta
    riduci animazioni     [interfaccia] riduci_animazioni
    vista all'avvio       [interfaccia] vista_avvio      minimal | hub | diagnostica
    muto all'avvio        [interfaccia] muto_avvio

TUTTO IN `config/gui.local.toml`
Ignorato da git: la citta' e' un dato personale, come gli indirizzi di
`email.local.toml`. Il file del repository, `gui.toml`, resta con i valori
vuoti; qui si scrive solo il locale, e le chiavi che questo modulo non
conosce restano dove sono.

LA RETE NON PASSA DI QUI
Il dialogo salva il NOME della citta'. Le coordinate le trova il worker del
meteo, sul suo thread, alla prossima `ricarica()`: una geocodifica fatta dal
dialogo sarebbe una richiesta di rete sul thread della GUI, cioe' un blocco
di NFR-8 ogni volta che qualcuno cambia citta'. Cambiando citta' le vecchie
coordinate si cancellano: altrimenti vincerebbero loro, e il meteo
resterebbe quello di prima con il nome nuovo.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from metis.gui import tema

CONFIG = Path("config/gui.toml")
VISTE = {"minimal": "Minimal (in un angolo)", "hub": "Hub", "diagnostica": "Diagnostica"}
INTESTAZIONE = ("# Impostazioni locali dell'interfaccia: scritte dalle Impostazioni dell'Hub,\n"
                "# ignorate da git. Il formato e' quello di config/gui.toml.\n")


@dataclass
class Preferenze:
    citta: str = ""
    riduci_animazioni: bool = False
    vista_avvio: str = "minimal"
    muto_avvio: bool = False


def locale(path: Path = CONFIG) -> Path:
    return path.with_name(f"{path.stem}.local{path.suffix}")


def _carica(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def leggi(path: Path = CONFIG) -> Preferenze:
    """Il repository, sovrascritto dal locale. Valori strani: quelli di prima."""
    dati: dict = {}
    for sorgente in (_carica(path), _carica(locale(path))):
        for sezione, valori in sorgente.items():
            if isinstance(valori, dict):
                dati.setdefault(sezione, {}).update(valori)
    meteo, ui = dati.get("meteo", {}), dati.get("interfaccia", {})
    vista = str(ui.get("vista_avvio", "minimal"))
    return Preferenze(citta=str(meteo.get("citta", "") or "").strip(),
                      riduci_animazioni=bool(ui.get("riduci_animazioni", False)),
                      vista_avvio=vista if vista in VISTE else "minimal",
                      muto_avvio=bool(ui.get("muto_avvio", False)))


def salva(pref: Preferenze, path: Path = CONFIG) -> bool:
    """Scrive il locale. Ritorna True se la citta' e' cambiata: e' il segnale
    per chiedere al meteo un giro subito."""
    file = locale(path)
    dati = _carica(file)
    meteo = dict(dati.get("meteo", {}))
    prima = str(meteo.get("citta", "") or leggi(path).citta).strip()
    cambiata = pref.citta.strip().casefold() != prima.casefold()
    meteo["citta"] = pref.citta.strip()
    if cambiata:
        meteo.pop("latitudine", None)
        meteo.pop("longitudine", None)
    dati["meteo"] = meteo
    dati["interfaccia"] = {**dati.get("interfaccia", {}),
                           "riduci_animazioni": pref.riduci_animazioni,
                           "vista_avvio": pref.vista_avvio,
                           "muto_avvio": pref.muto_avvio}
    file.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = file.with_suffix(".tmp")
    provvisorio.write_text(INTESTAZIONE + "\n" + in_toml(dati), encoding="utf-8")
    provvisorio.replace(file)
    return cambiata


def in_toml(dati: dict) -> str:
    """TOML per quello che serve qui: sezioni di valori semplici."""
    righe = []
    for sezione, valori in dati.items():
        if not isinstance(valori, dict):
            continue
        righe.append(f"[{sezione}]")
        for chiave, v in valori.items():
            righe.append(f"{chiave} = {_valore(v)}")
        righe.append("")
    return "\n".join(righe)


def _valore(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    testo = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{testo}"'


class DialogoImpostazioni(QDialog):
    def __init__(self, pref: Preferenze, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — impostazioni")
        self.setMinimumWidth(460)
        radice = QVBoxLayout(self)
        radice.setContentsMargins(20, 18, 20, 16)
        radice.setSpacing(14)

        titolo = QLabel("Impostazioni")
        titolo.setFont(tema.font(tema.FONT_TITOLI, 15))
        titolo.setStyleSheet(f"color: {tema.ACCENTO};")
        radice.addWidget(titolo)

        modulo = QFormLayout()
        modulo.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        modulo.setHorizontalSpacing(14)
        modulo.setVerticalSpacing(10)

        self.citta = QLineEdit(pref.citta)
        self.citta.setPlaceholderText("per esempio Milano")
        modulo.addRow("Città del meteo", self.citta)
        nota = QLabel("Dal PC escono solo le coordinate, verso Open-Meteo.")
        nota.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px;")
        modulo.addRow("", nota)

        self.vista = QComboBox()
        for chiave, nome in VISTE.items():
            self.vista.addItem(nome, chiave)
        self.vista.setCurrentIndex(list(VISTE).index(pref.vista_avvio))
        modulo.addRow("Vista all'avvio", self.vista)

        self.animazioni = QCheckBox("Riduci animazioni (il nucleo resta fermo)")
        self.animazioni.setChecked(pref.riduci_animazioni)
        modulo.addRow("", self.animazioni)
        self.muto = QCheckBox("Voce di Metis spenta all'avvio")
        self.muto.setChecked(pref.muto_avvio)
        modulo.addRow("", self.muto)
        radice.addLayout(modulo)

        pulsanti = QHBoxLayout()
        pulsanti.addStretch(1)
        self.annulla = QPushButton("Annulla")
        self.annulla.clicked.connect(self.reject)
        self.salva = QPushButton("Salva")
        self.salva.clicked.connect(self.accept)
        for b in (self.annulla, self.salva):
            b.setAutoDefault(False)
        pulsanti.addWidget(self.annulla)
        pulsanti.addWidget(self.salva)
        radice.addLayout(pulsanti)

    def preferenze(self) -> Preferenze:
        return Preferenze(citta=self.citta.text().strip(),
                          riduci_animazioni=self.animazioni.isChecked(),
                          vista_avvio=self.vista.currentData(),
                          muto_avvio=self.muto.isChecked())
