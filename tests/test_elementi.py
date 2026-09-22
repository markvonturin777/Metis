"""La scelta dell'elemento da cliccare, e le coordinate del clic.

Non si verifica qui che UI Automation e Playwright trovino le cose: quello
dipende dall'applicazione che si ha davanti e si misura a mano (§3.3 del
tracking di M4). Si verifica la REGOLA che governa cosa fare dei candidati
trovati, che e' logica pura ed e' la parte che decide se un clic sbagliato
puo' partire.

La regola, in una riga: esatto, poi sottostringa, e in caso di parita' si
rifiuta.
"""
import ctypes

import pytest

from metis.tools.registry import Rifiuto
from metis.tools.sendinput import VK, _normalizza, _vk_di
from metis.tools.uia import Elemento, _piatto, scegli


def el(nome, l=0, t=0, r=100, b=40, tipo="ButtonControl"):
    return Elemento(nome, tipo, (l, t, r, b))


# --- normalizzazione dei nomi ------------------------------------------------

@pytest.mark.parametrize("dato,atteso", [
    ("Salva", "salva"),
    ("&Salva", "salva"),                 # acceleratore del menu
    ("  Città  ", "citta"),
    ("Perché", "perche"),
    ("", ""),
])
def test_piatto(dato, atteso):
    assert _piatto(dato) == atteso


# --- la scelta ---------------------------------------------------------------

def test_nessun_candidato_e_un_rifiuto_esplicito():
    """Criterio di uscita: elemento non individuabile -> rifiuto, mai un
    clic a caso."""
    with pytest.raises(Rifiuto) as e:
        scegli([], "Contatti")
    assert "non trovo" in str(e.value) and "Contatti" in str(e.value)


def test_un_candidato_solo():
    assert scegli([el("Contatti")], "contatti").nome == "Contatti"


def test_l_esatto_vince_sul_parziale():
    """"Salva" e "Salva con nome" sono due pulsanti diversi, e premere il
    secondo al posto del primo apre un dialogo sul filesystem."""
    trovati = [el("Salva con nome"), el("Salva"), el("Salvaschermo")]
    assert scegli(trovati, "Salva").nome == "Salva"


def test_due_esatti_producono_un_rifiuto():
    """Due pulsanti con lo stesso nome in due pannelli diversi: non c'e'
    modo di sapere quale, e sbagliare costa piu' che chiedere."""
    with pytest.raises(Rifiuto) as e:
        scegli([el("Apri", l=0), el("Apri", l=500)], "Apri")
    assert "2 elementi" in str(e.value)


def test_due_parziali_producono_un_rifiuto_che_li_nomina():
    with pytest.raises(Rifiuto) as e:
        scegli([el("Elimina definitivamente"), el("Elimina tutto")], "Elimina")
    testo = str(e.value)
    assert "definitivamente" in testo and "tutto" in testo


def test_il_rifiuto_non_elenca_piu_di_quattro_candidati():
    """Il motivo finisce in una frase pronunciata: venti nomi sono
    inascoltabili."""
    with pytest.raises(Rifiuto) as e:
        scegli([el(f"voce {i}") for i in range(20)], "voce")
    assert str(e.value).count('"') <= 8


def test_accenti_e_maiuscole_non_impediscono_la_corrispondenza_esatta():
    assert scegli([el("Città"), el("Città vecchia")], "citta").nome == "Città"


def test_il_clic_va_al_centro_del_rettangolo():
    assert el("x", 100, 200, 300, 260).centro == (200, 230)


def test_il_centro_funziona_a_coordinate_negative():
    """Un elemento sul monitor a sinistra del primario."""
    assert el("x", -1900, 100, -1700, 200).centro == (-1800, 150)


# --- tastiera ----------------------------------------------------------------

def test_ogni_tasto_nominabile_ha_un_codice():
    """Lo schema permette al modello di nominare certi tasti; se uno di
    quelli non avesse un codice, la guardia lo lascerebbe passare e
    l'esecuzione esploderebbe dopo l'autorizzazione."""
    from metis.llm.schemas import KeyName

    for nome in KeyName.__args__:
        assert _vk_di(nome) > 0, nome


def test_i_modificatori_hanno_i_codici_giusti():
    assert (VK["ctrl"], VK["alt"], VK["shift"], VK["win"]) == (0x11, 0x12, 0x10, 0x5B)
    assert _vk_di("f1") == 0x70 and _vk_di("f12") == 0x7B
    assert _vk_di("a") == 0x41 and _vk_di("0") == 0x30


def test_un_tasto_non_mappato_solleva():
    with pytest.raises(KeyError):
        _vk_di("scroll_lock")


# --- coordinate assolute -----------------------------------------------------

def test_la_normalizzazione_copre_gli_estremi_del_desktop_virtuale():
    """`MOUSEEVENTF_ABSOLUTE` vuole 0..65535 sul desktop virtuale. Gli
    estremi devono mappare sugli estremi: se l'origine fosse assunta a
    (0,0), su un impianto con uno schermo a sinistra il puntatore
    finirebbe fuori."""
    gsm = ctypes.windll.user32.GetSystemMetrics
    ox, oy = gsm(76), gsm(77)
    w, h = gsm(78), gsm(79)
    assert _normalizza(ox, oy) == (0, 0)
    assert _normalizza(ox + w - 1, oy + h - 1) == (65535, 65535)


def test_i_punti_fuori_schermo_vengono_riportati_dentro():
    gsm = ctypes.windll.user32.GetSystemMetrics
    ox, oy = gsm(76), gsm(77)
    assert _normalizza(ox - 10_000, oy - 10_000) == (0, 0)
    assert _normalizza(ox + 10 ** 6, oy + 10 ** 6) == (65535, 65535)
