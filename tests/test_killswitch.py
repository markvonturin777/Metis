"""Il kill switch. Piccolo, e per questo facile da sbagliare senza accorgersene.

Le due proprieta' che contano: sospende T2 e T3 **e nient'altro**, e resta
sospeso finche' non lo si rimette a posto. Un ripristino automatico dopo N
secondi sembrerebbe comodo: chi lo ha premuto lo ha fatto perche' stava
succedendo qualcosa che non voleva, e decidere per lui quando e' passata non
spetta al programma.
"""
import time

import pytest

from metis.security.audit import Tier
from metis.security.killswitch import TIER_SOSPESI, KillSwitch


def test_nasce_disattivato():
    assert KillSwitch().attivo is False


def test_sospende_t2_e_t3():
    k = KillSwitch()
    k.sospendi()
    assert k.blocca(Tier.T2) is not None
    assert k.blocca(Tier.T3) is not None


def test_non_tocca_t0_e_t1():
    """Se spegnesse tutto, Metis diventerebbe inerte e lo si userebbe di
    meno — e un interruttore che si evita di usare non e' un interruttore."""
    k = KillSwitch()
    k.sospendi()
    assert k.blocca(Tier.T0) is None
    assert k.blocca(Tier.T1) is None


def test_da_spento_non_blocca_niente():
    k = KillSwitch()
    for t in Tier:
        assert k.blocca(t) is None


def test_il_motivo_dice_quale_livello():
    k = KillSwitch()
    k.sospendi()
    assert "T3" in k.blocca(Tier.T3)


def test_resta_sospeso_nel_tempo():
    k = KillSwitch()
    k.sospendi()
    time.sleep(0.15)
    assert k.attivo, "si e' ripristinato da solo"


def test_sospendere_due_volte_non_cambia_nulla():
    k = KillSwitch()
    k.sospendi()
    primo = k.attivato_a
    k.sospendi()
    assert k.attivazioni == 1 and k.attivato_a == primo


def test_ripristinare_da_spento_non_fa_nulla():
    k = KillSwitch()
    k.ripristina()
    assert k.attivo is False and k.attivazioni == 0


def test_commuta_avanti_e_indietro():
    k = KillSwitch()
    assert k.commuta() is True
    assert k.commuta() is False
    assert k.attivazioni == 1


def test_avvisa_chi_deve_mostrarlo():
    """In M3 diventa un indicatore in GUI: senza notifica, l'utente non
    saprebbe di avere le capacita' sospese e crederebbe Metis rotto."""
    visti = []
    k = KillSwitch(on_change=visti.append)
    k.sospendi()
    k.ripristina()
    assert visti == [True, False]


def test_il_ripristino_azzera_l_istante():
    k = KillSwitch()
    k.sospendi()
    assert k.attivato_a is not None
    k.ripristina()
    assert k.attivato_a is None


def test_l_insieme_sospeso_e_esattamente_t2_e_t3():
    assert TIER_SOSPESI == frozenset({Tier.T2, Tier.T3})


@pytest.mark.parametrize("n", [1, 5, 20])
def test_conta_le_attivazioni(n):
    k = KillSwitch()
    for _ in range(n):
        k.sospendi()
        k.ripristina()
    assert k.attivazioni == n


def test_sospende_entro_cento_millisecondi():
    """Criterio di uscita di M2. E' un `threading.Event`, quindi la misura
    e' quasi una formalita': serve a impedire che un domani qualcuno ci
    metta in mezzo un'operazione lenta."""
    k = KillSwitch()
    t0 = time.perf_counter()
    k.sospendi()
    bloccato = k.blocca(Tier.T2) is not None
    ms = (time.perf_counter() - t0) * 1000
    assert bloccato and ms < 100, f"{ms:.1f} ms"
