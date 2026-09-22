"""Geometria dei monitor e trasferimento di un rettangolo.

PERCHE' QUASI TUTTO QUI USA MONITOR INVENTATI
Questa macchina ha due schermi identici, 1920x1080 al 100%, affiancati a
partire da (0,0). Sono la configurazione piu' comune e la meno interessante:
non hanno scaling misto e non hanno coordinate negative, cioe' non hanno
nessuno dei due casi che il piano di M4 indica come quelli che rompono
tutto.

Il codice pero' li gestisce, e la matematica che li gestisce e' una funzione
pura. Costruire dei `Monitor` a mano e' l'unico modo di verificarla senza
comprare un 4K, ed e' anche il motivo per cui `rect_trasferito` e'
deliberatamente separata dalle chiamate a Windows invece di essere dentro
`sposta_su_monitor`.

Resta un limite dichiarato: il comportamento *di Windows* a DPI misti — il
riaggancio del DPI quando una finestra attraversa il confine — non e'
verificato qui e non lo e' da nessuna parte. E' scritto nel tracking.
"""
from metis.tools.display import (
    DPI_BASE,
    Monitor,
    dpi_consapevole,
    monitor_di_punto,
    monitor_di_rect,
    monitors,
    origine_desktop,
    rect_trasferito,
    set_dpi_awareness,
)


def mon(indice, left, top, w=1920, h=1080, dpi=96, primario=False, barra=40):
    return Monitor(indice=indice, nome=f"\\\\.\\DISPLAY{indice + 1}",
                   rect=(left, top, left + w, top + h),
                   lavoro=(left, top, left + w, top + h - barra),
                   dpi=dpi, primario=primario)


# --- la macchina vera --------------------------------------------------------

def test_il_processo_si_dichiara_consapevole_del_dpi():
    """Idempotente: la seconda chiamata puo' fallire perche' il contesto e'
    gia' fissato, ma lo stato finale deve essere quello giusto."""
    set_dpi_awareness()
    assert dpi_consapevole(), "coordinate virtualizzate: tutto M4 sbaglia"


def test_i_monitor_veri_si_enumerano():
    ms = monitors()
    assert ms, "nessun monitor: impossibile"
    assert [m.indice for m in ms] == list(range(len(ms)))
    assert sum(m.primario for m in ms) == 1, "deve esserci un solo primario"
    for m in ms:
        assert m.larghezza > 0 and m.altezza > 0
        assert m.dpi >= DPI_BASE


def test_i_monitor_sono_ordinati_da_sinistra_a_destra():
    """L'ordine di Windows non ha un criterio stabile, e "lo schermo a
    destra" e' l'unica cosa che l'utente puo' dire a voce."""
    sinistri = [m.rect[0] for m in monitors()]
    assert sinistri == sorted(sinistri)


def test_i_monitor_veri_non_si_sovrappongono():
    ms = monitors()
    for a in ms:
        for b in ms:
            if a.indice >= b.indice:
                continue
            dx = min(a.rect[2], b.rect[2]) - max(a.rect[0], b.rect[0])
            dy = min(a.rect[3], b.rect[3]) - max(a.rect[1], b.rect[1])
            assert dx <= 0 or dy <= 0, f"{a.nome} e {b.nome} si sovrappongono"


# --- appartenenza ------------------------------------------------------------

def test_origine_del_desktop_con_un_monitor_a_sinistra():
    """Il caso che questa macchina non ha: left negativo."""
    ms = [mon(0, -1920, 0), mon(1, 0, 0, primario=True)]
    assert origine_desktop(ms) == (-1920, 0)


def test_punto_su_monitor_a_coordinate_negative():
    ms = [mon(0, -1920, -200), mon(1, 0, 0, primario=True)]
    assert monitor_di_punto(-500, -100, ms).indice == 0
    assert monitor_di_punto(500, 100, ms).indice == 1


def test_una_finestra_a_cavallo_appartiene_a_dove_sta_di_piu():
    """Non al monitor dell'angolo in alto a sinistra: quello, per una
    finestra trascinata oltre il confine, e' spesso quello sbagliato."""
    ms = [mon(0, 0, 0, primario=True), mon(1, 1920, 0)]
    # 300 px sul primo, 700 sul secondo.
    assert monitor_di_rect((1620, 100, 2620, 700), ms).indice == 1


def test_una_finestra_fuori_da_ogni_schermo_non_fa_esplodere_niente():
    """Una finestra ridotta a icona ha rect a -32000: capita davvero."""
    ms = [mon(0, 0, 0, primario=True)]
    assert monitor_di_rect((-32000, -32000, -31900, -31900), ms) is not None


# --- il trasferimento --------------------------------------------------------

def test_a_pari_dpi_la_finestra_non_cambia_dimensione():
    """Il caso di questa macchina. Se il codice riscalasse comunque, si
    vedrebbe subito ed e' il difetto piu' probabile."""
    a, b = mon(0, 0, 0, primario=True), mon(1, 1920, 0)
    r = rect_trasferito((100, 100, 900, 700), a, b)
    assert (r[2] - r[0], r[3] - r[1]) == (800, 600)
    assert r[0] == 2020 and r[1] == 100


def test_la_posizione_relativa_si_conserva():
    """Una finestra a meta' schermo resta a meta' schermo, anche se lo
    schermo di arrivo e' piu' grande."""
    a = mon(0, 0, 0, 1920, 1080, primario=True)
    b = mon(1, 1920, 0, 3840, 2160)
    r = rect_trasferito((960, 500, 1160, 700), a, b)
    # Meta' larghezza dell'area di lavoro di partenza -> meta' di quella
    # di arrivo, che comincia a 1920.
    assert r[0] == 1920 + 1920


def test_da_150_a_100_la_finestra_si_rimpicciolisce():
    """Il caso che il piano indica come quello che rompe tutto. 1200 pixel
    fisici al 150% sono 800 pixel logici: sull'altro schermo devono restare
    800, altrimenti il contenuto — che Windows ridisegna alla nuova scala —
    balla dentro una finestra rimasta grande."""
    a = mon(0, 0, 0, 3840, 2160, dpi=144, primario=True)
    b = mon(1, 3840, 0, 1920, 1080, dpi=96)
    r = rect_trasferito((0, 0, 1200, 900), a, b)
    assert (r[2] - r[0], r[3] - r[1]) == (800, 600)


def test_da_100_a_150_la_finestra_si_ingrandisce():
    a = mon(0, 0, 0, 1920, 1080, dpi=96, primario=True)
    b = mon(1, 1920, 0, 3840, 2160, dpi=144)
    r = rect_trasferito((0, 0, 800, 600), a, b)
    assert (r[2] - r[0], r[3] - r[1]) == (1200, 900)


def test_una_finestra_piu_grande_dello_schermo_di_arrivo_viene_contenuta():
    """Sbordare oltre il bordo destro significa una finestra che l'utente
    non riesce piu' a prendere per la barra del titolo."""
    a = mon(0, 0, 0, 3840, 2160, primario=True)
    b = mon(1, 3840, 0, 1280, 720)
    r = rect_trasferito((0, 0, 3000, 1800), a, b)
    assert r[0] >= b.lavoro[0] and r[1] >= b.lavoro[1]
    assert r[2] <= b.lavoro[2] and r[3] <= b.lavoro[3]


def test_il_trasferimento_verso_coordinate_negative():
    """Verso il monitor a sinistra del primario: il risultato ha left
    negativo, e non deve essere stato riportato a zero da nessuna parte."""
    a = mon(0, 0, 0, primario=True)
    b = mon(1, -1920, 0)
    r = rect_trasferito((100, 100, 900, 700), a, b)
    assert r[0] == -1820, r
    assert r[2] - r[0] == 800


def test_il_rettangolo_resta_dentro_l_area_di_lavoro():
    """La barra delle applicazioni non e' area utile: una finestra
    posizionata sotto di lei ha il bordo inferiore irraggiungibile."""
    a = mon(0, 0, 0, primario=True)
    b = mon(1, 1920, 0, barra=40)
    r = rect_trasferito((0, 1000, 800, 1070), a, b)
    assert r[3] <= b.lavoro[3]


def test_il_trasferimento_e_una_funzione_pura():
    """Nessuna chiamata a Windows: e' quello che la rende verificabile con
    configurazioni che questa macchina non ha."""
    a, b = mon(0, 0, 0, primario=True), mon(1, 1920, 0)
    r1 = rect_trasferito((10, 20, 310, 220), a, b)
    r2 = rect_trasferito((10, 20, 310, 220), a, b)
    assert r1 == r2
