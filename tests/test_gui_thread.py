"""La regola dei thread, verificata sul sorgente.

Il piano di M3 chiedeva un controllo "per ispezione": nessun accesso ai
widget dai thread secondari. Un controllo per ispezione dura fino al giorno
dopo, e il difetto che previene non si manifesta subito — produce crash
sporadici, settimane dopo, di solito su un'altra macchina.

Qui e' un test. Legge i moduli dei worker con l'AST e cerca qualunque
traccia di Qt grafico: import di `QtWidgets`, `QtGui`, nomi che cominciano
per `Q` e finiscono in `Widget`, `Dialog`, `Window`, `Label`.
"""
import ast
from pathlib import Path

import pytest

WORKER = sorted(Path("metis/gui/workers").rglob("*.py"))
NON_GRAFICI = [Path("metis/gui/conferma.py"), Path("metis/gui/lag.py")]

MODULI_GRAFICI = {"PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtQuick"}
SOSPETTI = ("Widget", "Dialog", "Window", "Label", "Button", "Layout", "Painter")


def _import_di(path: Path) -> set[str]:
    albero = ast.parse(path.read_text(encoding="utf-8"))
    fuori: set[str] = set()
    for n in ast.walk(albero):
        if isinstance(n, ast.Import):
            fuori.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            fuori.add(n.module)
            fuori.update(f"{n.module}.{a.name}" for a in n.names)
    return fuori


def _nomi_usati(path: Path) -> set[str]:
    albero = ast.parse(path.read_text(encoding="utf-8"))
    return {n.id for n in ast.walk(albero) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(albero) if isinstance(n, ast.Attribute)}


def test_ci_sono_worker_da_controllare():
    """Senza questo, il giorno in cui la cartella si svuota il test passerebbe
    dicendo che va tutto bene."""
    assert WORKER, "nessun worker trovato"


@pytest.mark.parametrize("path", WORKER, ids=lambda p: p.name)
def test_nessun_worker_importa_qt_grafico(path):
    trovati = _import_di(path) & MODULI_GRAFICI
    assert not trovati, f"{path} importa {trovati}: i widget si toccano solo dal main"


@pytest.mark.parametrize("path", WORKER + NON_GRAFICI, ids=lambda p: p.name)
def test_nessun_nome_di_widget_nei_worker(path):
    """Cattura anche l'import fatto dentro una funzione, che sfuggirebbe al
    controllo sugli import di modulo."""
    colpevoli = [n for n in _nomi_usati(path)
                 if n.startswith("Q") and any(s in n for s in SOSPETTI)]
    assert not colpevoli, f"{path} nomina widget: {colpevoli}"


def test_i_worker_non_sono_sottoclassi_di_qthread():
    """Sottoclassando QThread i metodi restano affiliati al thread che ha
    creato l'oggetto: si crede di aver spostato il lavoro e lo si e'
    lasciato dov'era. E' l'errore piu' comune con Qt."""
    for path in WORKER:
        albero = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(albero):
            if isinstance(n, ast.ClassDef):
                basi = [b.id for b in n.bases if isinstance(b, ast.Name)]
                assert "QThread" not in basi, f"{path}: {n.name} sottoclassa QThread"


def test_il_controllo_riconosce_una_violazione(tmp_path):
    """Meta-test: una verifica che non sa vedere il difetto passa sempre."""
    cattivo = tmp_path / "cattivo.py"
    cattivo.write_text(
        "from PySide6.QtWidgets import QLabel\n"
        "def f(): QLabel('tocco un widget dal thread sbagliato')\n",
        encoding="utf-8")
    assert _import_di(cattivo) & MODULI_GRAFICI
    assert [n for n in _nomi_usati(cattivo)
            if n.startswith("Q") and any(s in n for s in SOSPETTI)]


def test_l_app_e_l_unica_a_montare_i_thread():
    """Se i thread si montassero in piu' punti, chiuderli in ordine
    diventerebbe una questione di fortuna.

    Il controllo guarda le CHIAMATE, non il testo. La prima versione cercava
    la parola nel sorgente e inciampava nella docstring che spiega il
    pattern: lo stesso errore commesso a M1 sul test dell'audit log, dove
    la verifica falliva sulla frase che descriveva la regola. Contano le
    chiamate eseguite, non le parole scritte.
    """
    montaggi = []
    for path in Path("metis").rglob("*.py"):
        albero = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(albero):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "moveToThread"):
                montaggi.append(path.as_posix())
    assert sorted(set(montaggi)) == ["metis/gui/app.py"], montaggi


# --- dove atterrano davvero gli slot ----------------------------------------

def test_i_segnali_del_nucleo_atterrano_sul_thread_principale(app_qt):
    """Il test che avrebbe preso subito il difetto delle lambda.

    `signal.connect(lambda: ...)` non ha un oggetto ricevente: Qt non sa a
    chi consegnare e la esegue nel thread che emette. Con i segnali del
    nucleo significa toccare i widget dal thread sbagliato — il difetto che
    non si manifesta subito e che poi non si riproduce.

    Qui si emette da un QThread vero e si guarda su quale thread e' finito
    lo slot. E' l'unica verifica che non si puo' aggirare scrivendo codice
    che sembra giusto.
    """
    import threading

    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from metis.core.avvio import Opzioni
    from metis.gui.app import Applicazione

    principale = threading.get_ident()
    app = Applicazione(Opzioni(tools=False, wakeword=False))
    atterrati: list[int] = []

    vero_stato = app._stato

    def spia(da, ev, a):
        atterrati.append(threading.get_ident())
        vero_stato(da, ev, a)

    app.nucleo.stato.disconnect(app._stato)
    app.nucleo.stato.connect(app._stato)     # riconnessione pulita

    class Emettitore(QThread):
        def run(self):
            app.nucleo.stato.emit("IN_ASCOLTO", "PTT", "PARLATO")

    app.conversazione.destroyed.connect(lambda: None)
    t = Emettitore()
    t.start()
    t.wait(2000)

    # Lo slot e' in coda: arriva quando il thread principale gira.
    for _ in range(200):
        QApplication.processEvents()
        if app.minimal.indicatore.stato == "PARLATO":
            break
    app.hotkeys.stop()

    assert app.minimal.indicatore.stato == "PARLATO", (
        "lo slot non e' mai arrivato al thread principale")
    assert app.fullscreen.indicatore.stato == "PARLATO"


def test_nessuna_lambda_sui_segnali_dei_worker():
    """Il controllo strutturale, per non dover rifare la scoperta.

    Cerca `qualcosa.connect(lambda ...)` dove il segnale viene da un worker:
    sono le connessioni che girerebbero sul thread sbagliato.
    """
    sorgente = Path("metis/gui/app.py").read_text(encoding="utf-8")
    albero = ast.parse(sorgente)
    colpevoli = []
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "connect"):
            continue
        if not any(isinstance(a, ast.Lambda) for a in n.args):
            continue
        # Il segnale e' `<qualcosa>.<nome>`: si guarda da dove arriva.
        emittente = n.func.value
        if isinstance(emittente, ast.Attribute) and isinstance(emittente.value, ast.Attribute):
            radice = emittente.value.attr
            if radice in ("nucleo", "worker_telemetria", "ponte"):
                colpevoli.append(f"riga {n.lineno}: {radice}.{emittente.attr}")
    assert not colpevoli, (
        "lambda su segnali di worker (girerebbero sul thread sbagliato): "
        + "; ".join(colpevoli))
