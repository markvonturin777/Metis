"""PHASE2 — la sorgente degli elementi cliccabili.

Qui si verificano la geometria e il comportamento del lettore senza UIA: il
filtro, l'ordine, il tetto dei 99, la rilettura delle finestre fredde, e il
rifiuto quando la finestra non risponde. La lettura vera sta nello spike
(`benchmarks/spike_navigazione.py`) e nella prova su finestra vera in fondo.
"""
import threading
import time

import pytest

from metis.tools import cliccabili
from metis.tools.cliccabili import Lettore, _stabile, filtra, interseca, ordina
from metis.tools.registry import Rifiuto
from metis.tools.uia import Elemento

CORNICE = (0, 0, 1000, 800)


def el(l, t, r, b, nome="x", tipo="link"):
    return Elemento(nome, tipo, (l, t, r, b))


def test_interseca():
    assert interseca((0, 0, 10, 10), (5, 5, 20, 20)) == (5, 5, 10, 10)
    assert interseca((0, 0, 10, 10), (10, 0, 20, 10)) is None


def test_fuori_dalla_cornice_o_troppo_piccoli_si_scartano():
    tenuti = filtra([el(-50, 10, -10, 30), el(10, 10, 12, 30), el(10, 900, 50, 950),
                     el(10, 10, 60, 30, "buono")], CORNICE)
    assert [e.nome for e in tenuti] == ["buono"]


def test_tagliati_dal_bordo_resta_la_parte_visibile():
    (e,) = filtra([el(900, 780, 1100, 900)], CORNICE)
    assert e.rect == (900, 780, 1000, 800)
    assert e.centro == (950, 790)


def test_i_doppioni_sullo_stesso_rettangolo_prendono_un_numero_solo():
    assert len(filtra([el(10, 10, 60, 30, "a"), el(10, 10, 60, 30, "b")], CORNICE)) == 1


def test_ordine_di_lettura_con_tolleranza_sulle_righe():
    a, b, c = el(300, 12, 350, 30, "c"), el(10, 10, 60, 30, "a"), el(100, 14, 150, 30, "b")
    d = el(10, 100, 60, 130, "d")
    assert [e.nome for e in ordina([d, a, c, b])] == ["a", "b", "c", "d"]


def test_al_massimo_99():
    tanti = [el(10 + (i % 20) * 45, 10 + (i // 20) * 40, 50 + (i % 20) * 45,
                40 + (i // 20) * 40, str(i)) for i in range(150)]
    assert len(filtra(tanti, (0, 0, 2000, 2000))) == cliccabili.MAX_NUMERI == 99


# --- finestre fredde ---------------------------------------------------------------

def test_una_finestra_fredda_si_rilegge_finche_il_conteggio_cresce():
    letture = iter([[1] * 3, [1] * 40, [1] * 78, [1] * 78, [1] * 99])
    assert len(_stabile(lambda: next(letture), dormi=lambda s: None)) == 78


def test_si_tiene_sempre_la_lettura_piu_recente():
    letture = iter([[1] * 10, ["nuova"] * 8])
    assert _stabile(lambda: next(letture), dormi=lambda s: None) == ["nuova"] * 8


def test_le_riletture_hanno_un_tetto():
    n = {"letture": 0}

    def cresce():
        n["letture"] += 1
        return [1] * n["letture"]
    _stabile(cresce, letture=4, dormi=lambda s: None)
    assert n["letture"] == 4


# --- il thread ---------------------------------------------------------------------

def test_una_finestra_che_non_risponde_e_un_rifiuto_entro_il_tempo():
    lett = Lettore(timeout_s=0.2)
    blocco = threading.Event()
    t0 = time.perf_counter()
    with pytest.raises(Rifiuto, match="non risponde"):
        lett.esegui(lambda uia: blocco.wait(5))
    assert time.perf_counter() - t0 < 1.0
    # La richiesta dopo ha un thread nuovo, e funziona.
    assert lett.esegui(lambda uia: "ok") == "ok"
    blocco.set()


def test_un_errore_nella_lettura_e_un_rifiuto_non_un_crash():
    lett = Lettore(timeout_s=2)
    with pytest.raises(Rifiuto, match="non riesco"):
        lett.esegui(lambda uia: 1 / 0)
    with pytest.raises(Rifiuto, match="mio motivo"):
        lett.esegui(lambda uia: (_ for _ in ()).throw(Rifiuto("mio motivo")))


def test_la_lettura_non_gira_sul_thread_di_chi_chiede():
    lett = Lettore(timeout_s=5)
    nome = lett.esegui(lambda uia: threading.current_thread().name)
    assert nome == "metis-cliccabili" != threading.current_thread().name


# --- una finestra vera --------------------------------------------------------------

def test_su_una_finestra_vera_esce_un_elenco_coerente():
    """Qualunque finestra visibile che non sia di questo processo: si legge e
    basta. Serve a sapere che la condizione e la cache funzionano sul COM vero."""
    pytest.importorskip("uiautomation")
    from metis.tools import finestre

    candidate = [w for w in finestre.elenca() if w.stato != "ridotta"
                 and (w.rect[2] - w.rect[0]) > 200 and w.processo != "explorer.exe"]
    if not candidate:
        pytest.skip("nessuna finestra visibile su cui provare")
    trovati = cliccabili.elementi(candidate[0].hwnd)
    assert len(trovati) <= 99
    cornice = cliccabili.cornice_visibile(candidate[0].rect)
    for e in trovati:
        assert interseca(e.rect, cornice) == e.rect
        assert e.tipo in cliccabili.TIPI.values()
