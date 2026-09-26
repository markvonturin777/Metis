"""La verifica degli NFR, su dati noti.

Lo script decide se una casella diventa verde: se sbagliasse, sbaglierebbe
nel verso peggiore — un verde non meritato. Qui si prova soprattutto che
con pochi dati NON dica verde.
"""
import json
import sqlite3

from tests.nfr.verifica_nfr import (
    QUERY_NFR9,
    nfr8,
    nfr9,
    nfr_soak,
    nfr_turni,
    tabella,
    verifica,
)


def _turni(n, totale=900, ttft=250, tok=55.0):
    return [{"event": "turno", "totale_ms": totale, "ttft_ms": ttft, "tok_s": tok}
            for _ in range(n)]


def test_con_meno_di_100_turni_non_e_verde_anche_se_veloce():
    e1, e2, e3 = nfr_turni(_turni(17))
    assert {e1.stato, e2.stato, e3.stato} == {"insufficiente"}


def test_cento_turni_veloci_sono_verdi():
    e1, e2, e3 = nfr_turni(_turni(100))
    assert (e1.stato, e2.stato, e3.stato) == ("verde", "verde", "verde")


def test_un_p95_lento_e_rosso():
    eventi = _turni(90) + _turni(10, totale=2500)
    assert nfr_turni(eventi)[0].stato == "rosso"


def test_i_turni_senza_audio_non_contano():
    """Un turno senza primo audio ha totale 0: contarlo abbasserebbe il p50."""
    e1 = nfr_turni(_turni(100) + _turni(50, totale=0))[0]
    assert "100 turni" in e1.evidenza


def test_nfr9_usa_la_query_del_piano(tmp_path):
    db = tmp_path / "audit.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE audit (tier TEXT, confirmed INTEGER, outcome TEXT)")
    con.executemany("INSERT INTO audit VALUES (?,?,?)", [
        ("T3", 1, "ok"), ("T3", 0, "denied"), ("T3", None, "denied"), ("T1", None, "ok")])
    con.commit()
    assert nfr9(db).stato == "verde"
    con.execute("INSERT INTO audit VALUES ('T3', NULL, 'ok')")
    con.commit()
    con.close()
    e = nfr9(db)
    assert e.stato == "rosso" and e.misurato == "1"
    assert "confirmed IS NULL" in QUERY_NFR9


def test_nfr8_conta_solo_l_esercizio():
    eventi = [{"event": "freeze interfaccia", "ms": 2065, "fase": "avvio"},
              {"event": "freeze interfaccia", "ms": 90, "fase": "esercizio"}]
    assert nfr8(eventi).stato == "verde"
    eventi.append({"event": "freeze interfaccia", "ms": 180, "fase": "esercizio"})
    e = nfr8(eventi)
    assert e.stato == "rosso" and "180" in e.misurato


def test_nfr8_senza_fase_non_decide():
    assert nfr8([{"event": "freeze interfaccia", "ms": 2065}]).stato == "insufficiente"


def _soak(tmp_path, ore, rss_per_h=0.0, vram=6.5):
    c = tmp_path / "soak_x"
    c.mkdir()
    righe = [{"t": i * 600, "rss_mb": 800 + rss_per_h * i / 6, "vram_gb": 6.0,
              "vram_picco_gb": vram, "handle": 900, "thread_os": 40}
             for i in range(int(ore * 6) + 1)]
    (c / "campioni.jsonl").write_text("\n".join(json.dumps(r) for r in righe),
                                      encoding="utf-8")
    return c


def test_un_soak_breve_non_basta(tmp_path):
    e4, e10 = nfr_soak(_soak(tmp_path, 5))
    assert e4.stato == e10.stato == "insufficiente"


def test_soak_completo_e_stabile(tmp_path):
    e4, e10 = nfr_soak(_soak(tmp_path, 72))
    assert e4.stato == e10.stato == "verde"


def test_soak_completo_con_leak(tmp_path):
    _, e10 = nfr_soak(_soak(tmp_path, 72, rss_per_h=2.0))
    assert e10.stato == "rosso"


def test_la_tabella_ha_tutti_e_dieci(tmp_path):
    esiti = verifica(tmp_path / "nessun.jsonl", tmp_path / "nessun.db", None)
    assert [e.nfr for e in esiti] == list(range(1, 11))
    assert tabella(esiti).count("\n") == 12
    assert all(e.stato != "verde" for e in esiti)     # senza dati, niente verde


def test_la_suite_non_scrive_nel_log_di_metis():
    """PHASE1 — la suite scriveva kill switch e pause finte nel file da cui
    `verifica_nfr.py` certifica l'uso reale. Vedi `tests/conftest.py`."""
    from pathlib import Path

    import metis.core.logging as mlog

    vero = Path("data/logs/metis.jsonl")
    prima = vero.stat().st_size if vero.exists() else 0
    mlog.get_logger().info("prova della suite", test="log separato")
    assert mlog.JSONL != vero and mlog.JSONL.exists()
    assert "prova della suite" in mlog.JSONL.read_text(encoding="utf-8")
    assert (vero.stat().st_size if vero.exists() else 0) == prima


def test_nfr8_dice_quanto_e_durato_l_uso():
    """PHASE1: "0 blocchi in 30 minuti" chiede anche i 30 minuti."""
    eventi = [{"event": "sessione interfaccia", "esercizio_s": 1200},
              {"event": "sessione interfaccia", "esercizio_s": 900},
              {"event": "freeze interfaccia", "ms": 2000, "fase": "avvio"}]
    e = nfr8(eventi)
    assert e.stato == "verde" and "35 min di esercizio in 2 sessioni" in e.misurato


def test_verifica_dal_conta_solo_la_prova(tmp_path):
    from tests.nfr.verifica_nfr import verifica

    log = tmp_path / "metis.jsonl"
    righe = [{"timestamp": "2026-09-25T16:57:01", "event": "freeze interfaccia",
              "ms": 186, "fase": "esercizio"},
             {"timestamp": "2026-09-26T10:30:00", "event": "sessione interfaccia",
              "esercizio_s": 1860}]
    log.write_text("\n".join(json.dumps(r) for r in righe), encoding="utf-8")
    tutto = {e.nfr: e for e in verifica(log, tmp_path / "nessuno.db", None)}
    assert tutto[8].stato == "rosso"
    prova = {e.nfr: e for e in verifica(log, tmp_path / "nessuno.db", None,
                                        dal="2026-09-26T10:00")}
    assert prova[8].stato == "verde" and "31 min" in prova[8].misurato
