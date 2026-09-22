"""Risoluzione delle finestre e dei monitor nominati a voce.

LA PROPRIETA' CHE SI VERIFICA QUI E' IL RIFIUTO
Quasi tutti i test di questo file controllano che Metis NON agisca: due
finestre che corrispondono, uno schermo che non esiste, un riferimento
scaduto. E' l'inverso di come si scrivono di solito i test di una funzione
di ricerca, ed e' voluto — l'esito pericoloso di M4 non e' "non ho trovato",
e' "ho trovato la cosa sbagliata e l'ho spostata".

Le funzioni di ricerca prendono l'elenco delle finestre dal sistema, quindi
qui `elenca` viene sostituita: descrivere la situazione e' l'unico modo di
provare "due finestre con lo stesso pezzo di titolo" senza aprirne davvero
due e sperare che i titoli siano quelli previsti.
"""
import pytest

from metis.tools import finestre
from metis.tools.display import Monitor
from metis.tools.finestre import Info, rect_disposizione, risolvi, risolvi_monitor
from metis.tools.registry import Rifiuto


def info(titolo, processo="app.exe", hwnd=None, stato="normale"):
    return Info(hwnd=hwnd if hwnd is not None else abs(hash(titolo)) % 100000,
                titolo=titolo, processo=processo, classe="C",
                rect=(0, 0, 800, 600), stato=stato)


@pytest.fixture
def desktop(monkeypatch):
    """Descrive le finestre aperte invece di aprirle."""
    aperte: list[Info] = []
    monkeypatch.setattr(finestre, "elenca", lambda *a, **k: list(aperte))
    monkeypatch.setattr(finestre, "info",
                        lambda h: next((i for i in aperte if i.hwnd == h), None))
    finestre.imposta_riferimento(None)
    yield aperte
    finestre.imposta_riferimento(None)


def mon(indice, left, dpi=96, primario=False):
    return Monitor(indice, f"D{indice}", (left, 0, left + 1920, 1080),
                   (left, 0, left + 1920, 1040), dpi, primario)


DUE = [mon(0, 0, primario=True), mon(1, 1920)]
TRE = [mon(0, -1920), mon(1, 0, primario=True), mon(2, 1920)]


# --- "questa finestra" -------------------------------------------------------

def test_senza_riferimento_si_rifiuta_invece_di_indovinare(desktop):
    desktop.append(info("Un documento"))
    with pytest.raises(Rifiuto) as e:
        risolvi("")
    assert "quale finestra" in str(e.value)


def test_il_riferimento_catturato_vale_per_tutto_il_turno(desktop):
    prima = info("Editor")
    desktop.append(prima)
    finestre.imposta_riferimento(prima.hwnd)
    # Nel frattempo l'utente ha cambiato finestra: non deve cambiare nulla.
    desktop.insert(0, info("Chrome"))
    assert risolvi("").titolo == "Editor"


def test_un_riferimento_a_una_finestra_chiusa_e_un_rifiuto(desktop):
    finestre.imposta_riferimento(999999)
    with pytest.raises(Rifiuto) as e:
        risolvi("")
    assert "non c'e' piu'" in str(e.value)


# --- risoluzione per titolo --------------------------------------------------

def test_titolo_esatto(desktop):
    desktop += [info("Posta"), info("Posta in arrivo")]
    assert risolvi("Posta").titolo == "Posta"


def test_sottostringa_quando_e_una_sola(desktop):
    desktop += [info("progetto - Visual Studio Code"), info("Posta")]
    assert risolvi("visual studio").titolo.endswith("Code")


def test_due_candidati_producono_un_rifiuto_che_li_elenca(desktop):
    """Il cuore di M4: scegliere a caso fra due sarebbe agire sulla finestra
    sbagliata una volta su due."""
    desktop += [info("relazione - Word"), info("bilancio - Word")]
    with pytest.raises(Rifiuto) as e:
        risolvi("Word")
    testo = str(e.value)
    assert "2 finestre" in testo and "relazione" in testo and "bilancio" in testo


def test_ripiego_sul_nome_del_processo(desktop):
    """"massimizza chrome" quando il titolo e' quello della pagina."""
    desktop.append(info("Il Post - Notizie", processo="chrome.exe"))
    assert risolvi("chrome").processo == "chrome.exe"


def test_il_titolo_vince_sul_processo(desktop):
    """Se una finestra si chiama davvero cosi', e' quella: il ripiego sul
    processo serve solo quando nessun titolo corrisponde."""
    desktop += [info("Chrome Canary - guida"), info("pagina", processo="chrome.exe")]
    assert risolvi("chrome").titolo == "Chrome Canary - guida"


def test_titolo_inesistente_e_un_rifiuto(desktop):
    desktop.append(info("Posta"))
    with pytest.raises(Rifiuto) as e:
        risolvi("photoshop")
    assert "non trovo" in str(e.value)


def test_un_titolo_inventato_non_puo_colpire_nulla(desktop):
    """La ragione per cui le finestre si indicano per titolo e non per
    handle: un intero allucinato sarebbe quasi sempre una finestra vera."""
    desktop += [info("A"), info("B"), info("C")]
    for allucinazione in ("853420", "window 3", "la finestra di prima"):
        with pytest.raises(Rifiuto):
            risolvi(allucinazione)


# --- risoluzione dei monitor -------------------------------------------------

def test_destra_e_sinistra_sono_relative_a_dove_si_trova():
    assert risolvi_monitor("destra", DUE[0], DUE).indice == 1
    assert risolvi_monitor("sinistra", DUE[1], DUE).indice == 0


def test_non_esiste_uno_schermo_oltre_il_bordo():
    with pytest.raises(Rifiuto) as e:
        risolvi_monitor("destra", DUE[1], DUE)
    assert "a destra" in str(e.value)


def test_altro_con_due_schermi_e_univoco():
    assert risolvi_monitor("altro", DUE[0], DUE).indice == 1
    assert risolvi_monitor("altro", DUE[1], DUE).indice == 0


def test_altro_con_un_solo_schermo_e_un_rifiuto():
    uno = [mon(0, 0, primario=True)]
    with pytest.raises(Rifiuto) as e:
        risolvi_monitor("altro", uno[0], uno)
    assert "un monitor solo" in str(e.value)


def test_altro_con_tre_schermi_e_il_successivo_ciclico():
    assert risolvi_monitor("altro", TRE[2], TRE).indice == 0


def test_indice_assoluto():
    assert risolvi_monitor("1", DUE[0], DUE).indice == 1


def test_indice_oltre_il_numero_di_schermi():
    with pytest.raises(Rifiuto) as e:
        risolvi_monitor("3", DUE[0], DUE)
    assert "ne vedo 2" in str(e.value)


def test_primario_su_un_impianto_con_coordinate_negative():
    """Il primario non e' il primo da sinistra quando c'e' uno schermo a
    sinistra di lui."""
    assert risolvi_monitor("primario", TRE[0], TRE).indice == 1


# --- disposizioni ------------------------------------------------------------

def test_le_meta_coprono_l_area_di_lavoro_senza_buchi():
    m = mon(0, 0, primario=True)
    sx = rect_disposizione("meta_sinistra", m)
    dx = rect_disposizione("meta_destra", m)
    assert sx[2] == dx[0], "fra le due meta' resterebbe una striscia"
    assert sx[0] == m.lavoro[0] and dx[2] == m.lavoro[2]


def test_piena_non_copre_la_barra_delle_applicazioni():
    m = mon(0, 0, primario=True)
    assert rect_disposizione("piena", m) == m.lavoro
    assert rect_disposizione("piena", m)[3] < m.rect[3]


def test_centrata_e_davvero_centrata():
    m = mon(0, 0, primario=True)
    l, t, r, b = rect_disposizione("centrata", m)
    wl, wt, wr, wb = m.lavoro
    assert abs((l - wl) - (wr - r)) <= 1
    assert abs((t - wt) - (wb - b)) <= 1


def test_le_disposizioni_su_uno_schermo_a_coordinate_negative():
    m = mon(0, -1920)
    for nome in ("meta_sinistra", "meta_destra", "centrata", "piena"):
        l, t, r, b = rect_disposizione(nome, m)
        assert l >= m.lavoro[0] and r <= m.lavoro[2], nome
        assert l < 0, f"{nome}: la coordinata negativa e' sparita"
