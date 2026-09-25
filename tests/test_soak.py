"""Le parti del soak che si possono provare senza aspettare 72 ore.

Il soak vero dura tre giorni e produce un solo verdetto. Se l'analisi
sbagliasse — una pendenza calcolata male, un mix che non rispetta le
proporzioni — lo si scoprirebbe dopo tre giorni, o mai. Qui si prova
l'harness con numeri noti.
"""
import time

import numpy as np
import pytest

from tests.soak.run_soak import (
    BLOCCO,
    BLOCCO_S,
    MIX,
    SorgenteSintetica,
    analizza,
    grafico_svg,
    percentile,
    rapporto,
    retta,
    sequenza,
)


# --- mix -----------------------------------------------------------------------

def test_il_mix_ha_le_proporzioni_esatte_del_piano():
    s = sequenza(430)
    conta = {c: sum(1 for x, _ in s if x == c) for c in MIX}
    assert conta == {"conversazione": 172, "T1": 129, "web": 86, "T3": 43}


def test_il_mix_e_deterministico_e_mescolato():
    a, b = sequenza(50), sequenza(50)
    assert a == b
    assert [c for c, _ in a[:10]] != sorted(c for c, _ in a[:10])


def test_senza_t3_non_ci_sono_email():
    assert all(c != "T3" for c, _ in sequenza(100, senza_t3=True))
    assert len(sequenza(100, senza_t3=True)) == 100


def test_le_frasi_ruotano():
    frasi = [f for c, f in sequenza(200) if c == "conversazione"]
    assert set(frasi) == set(MIX["conversazione"][1])


# --- sorgente ------------------------------------------------------------------

def test_la_sorgente_va_a_velocita_reale():
    s = SorgenteSintetica()
    s.start()
    t0 = time.perf_counter()
    for _ in range(20):
        b = s.read()
        assert b.pcm.shape == (BLOCCO,)
    trascorso = time.perf_counter() - t0
    assert trascorso >= 19 * BLOCCO_S * 0.9          # non a raffica


def test_la_frase_arriva_intera_e_poi_torna_il_rumore():
    s = SorgenteSintetica()
    s.start()
    frase = np.full(BLOCCO * 3, 0.3, dtype=np.float32)
    s.pronuncia(frase, coda_s=0.0)
    livelli = [s.read().rms_dbfs for _ in range(5)]
    assert all(v > -15 for v in livelli[:3])
    assert all(v < -60 for v in livelli[3:])


def test_il_rumore_non_e_silenzio_digitale():
    """Zeri esatti sono un ingresso che dal microfono non arriva mai: vedi
    `benchmarks/e2e_replay.py`."""
    s = SorgenteSintetica()
    s.start()
    b = s.read()
    assert -100 < b.rms_dbfs < -60


def test_scollegata_non_consegna_e_non_si_riapre():
    s = SorgenteSintetica()
    s.scollega()
    assert s.read(timeout=0.01) is None
    with pytest.raises(RuntimeError):
        s.start()
    s.ricollega()
    s.start()
    assert s.read() is not None


def test_il_ciclo_audio_vero_vede_la_perdita_e_la_ripresa():
    """L'iniezione del microfono, con il `CicloAudio` di esercizio."""
    import threading

    from metis.core.avvio import CicloAudio

    class Orch:
        def on_audio(self, b):
            pass

        def tick(self):
            pass

    s = SorgenteSintetica()
    eventi = []
    c = CicloAudio(Orch(), apri_cattura=lambda: s, on_microfono=eventi.append,
                   silenzio_device_s=0.2, riapertura_s=0.05)
    t = threading.Thread(target=c.esegui, daemon=True)
    t.start()
    time.sleep(0.1)
    s.scollega()
    time.sleep(0.5)
    s.ricollega()
    time.sleep(0.3)
    c.ferma()
    t.join(2)
    assert eventi[:3] == [True, False, True]


# --- analisi -------------------------------------------------------------------

def test_retta_su_numeri_noti():
    pend, inter = retta([0, 1, 2, 3], [10, 12, 14, 16])
    assert pend == pytest.approx(2.0) and inter == pytest.approx(10.0)
    assert retta([1], [5]) == (0.0, 5)


def test_percentile():
    assert percentile(list(range(1, 101)), 50) == pytest.approx(50.5)
    assert percentile([], 95) is None


def _campioni(ore: float, rss, passo_min: float = 10):
    n = int(ore * 60 / passo_min) + 1
    return [{"t": i * passo_min * 60, "rss_mb": rss(i * passo_min / 60),
             "vram_gb": 6.0, "vram_picco_gb": 6.5, "handle": 900,
             "thread_os": 40, "coda_player": 0} for i in range(n)]


def test_un_leak_lineare_viene_bocciato():
    a = analizza(_campioni(72, lambda h: 800 + 2 * h), [])
    r = a["metriche"]["rss_mb"]
    assert r["pendenza_h"] == pytest.approx(2.0)
    assert r["crescita_pct"] > 10                   # 142 MB su ~802: ~17,7%
    assert "❌" in rapporto(a, [])


def test_una_cache_che_si_stabilizza_non_e_un_leak():
    """+150 MB nella prima ora, poi piatto: la regola del piano, "si guarda
    la pendenza". Confrontare fine e inizio direbbe +19%, cioe' un falso
    leak."""
    a = analizza(_campioni(72, lambda h: 800 + 150 * min(h, 1.0)), [])
    r = a["metriche"]["rss_mb"]
    assert abs(r["crescita_pct"]) < 1
    assert r["fine"] / r["inizio"] > 1.15           # il confronto ingenuo sbaglierebbe


def test_le_colonne_24_48_72_sono_vuote_se_la_prova_non_ci_arriva():
    a = analizza(_campioni(30, lambda h: 800), [])
    r = a["metriche"]["rss_mb"]
    assert r["24h"] == 800 and r["48h"] is None and r["72h"] is None


def test_latenza_e_esiti():
    inter = [{"t": 60 * i, "esito": "ok", "totale_ms": 1000 + i} for i in range(100)]
    inter.append({"t": 7000, "esito": "senza turno"})
    a = analizza(_campioni(2, lambda h: 800), inter)
    assert a["latenza_p50_ms"] == pytest.approx(1049.5)
    assert a["esiti"] == {"ok": 100, "senza turno": 1}
    assert a["vram_picco_gb"] == 6.5


def test_il_grafico_e_un_svg_con_la_retta():
    svg = grafico_svg(_campioni(5, lambda h: 800 + h))
    assert svg.startswith("<svg") and svg.count("<polyline") == 4
    assert "pendenza +1.000/h" in svg


def test_una_prova_breve_non_ha_verdetto_rss():
    from tests.soak.run_soak import verdetto_rss

    breve = analizza(_campioni(0.15, lambda h: 800 + 1000 * h, passo_min=1), [])
    assert verdetto_rss(breve) == "—"
    lunga = analizza(_campioni(6, lambda h: 800 + 50 * h), [])
    assert verdetto_rss(lunga) == "❌"
