"""Verifica formale dei 10 NFR: cio' che si misura dai dati, misurato.

    python tests/nfr/verifica_nfr.py
    python tests/nfr/verifica_nfr.py --soak data/soak/soak_20261001_0900 --md rapporto.md

"NESSUNA CASELLA SI SPUNTA PER CONVINZIONE"
E' la regola del piano, e questo script la applica in due modi. Ogni NFR
che si ricava dai dati si ricava da QUI, con la query o il calcolo scritti
in chiaro. E ogni NFR per cui i dati non bastano risulta "dati insufficienti",
non verde: NFR-1 chiede 100 interazioni reali, e 17 turni di prova danno un
p95 che non vuol dire niente.

DA DOVE VENGONO I NUMERI

    NFR-1, 2, 3   data/logs/metis.jsonl, eventi "turno" — l'uso REALE. Il
                  soak scrive in un log suo proprio per non finire qui.
    NFR-4, 10     l'ultimo soak in data/soak/ (o quello indicato)
    NFR-8         eventi "freeze interfaccia" con fase "esercizio"
    NFR-9         data/audit.db, la query del piano

    NFR-5, 6, 7   procedure manuali (voce registrata, 8 h di ambiente, 2 h di
                  TTS): lo script dice quali sono, non le inventa.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from tests.soak.run_soak import analizza, leggi_jsonl, percentile  # noqa: E402

LOG = Path("data/logs/metis.jsonl")
AUDIT = Path("data/audit.db")
SOAK = Path("data/soak")

MIN_INTERAZIONI = 100          # NFR-1: "100 interazioni reali"
MIN_SOAK_H = 72.0

# La query del piano (§3), senza riscriverla: e' lei l'evidenza.
QUERY_NFR9 = ("SELECT COUNT(*) FROM audit WHERE tier='T3' "
              "AND (confirmed IS NULL OR confirmed != 1) AND outcome='ok'")


@dataclass
class Esito:
    nfr: int
    metrica: str
    target: str
    misurato: str
    evidenza: str
    stato: str                 # "verde" | "rosso" | "insufficiente" | "manuale"

    @property
    def icona(self) -> str:
        return {"verde": "✅", "rosso": "❌", "insufficiente": "⏳",
                "manuale": "✋"}[self.stato]


def _fmt(v, dec=0, unita=""):
    return "—" if v is None else f"{v:.{dec}f}{unita}"


def nfr_turni(eventi: list[dict]) -> list[Esito]:
    """NFR-1, 2, 3 dagli eventi "turno" del log d'uso."""
    turni = [e for e in eventi if e.get("event") == "turno"]
    tot = [e["totale_ms"] for e in turni if e.get("totale_ms")]
    ttft = [e["ttft_ms"] for e in turni if e.get("ttft_ms")]
    toks = [e["tok_s"] for e in turni if e.get("tok_s")]
    n = len(tot)
    basta = n >= MIN_INTERAZIONI
    p50, p95 = percentile(tot, 50), percentile(tot, 95)
    ev = f"{n} turni reali in {LOG}"

    def stato(ok: bool, campioni: int) -> str:
        if campioni < MIN_INTERAZIONI:
            return "insufficiente"
        return "verde" if ok else "rosso"

    t_ttft = percentile(ttft, 50)
    media_tok = sum(toks) / len(toks) if toks else None
    return [
        Esito(1, "Latenza e2e p50 / p95", "< 1200 / < 1800 ms",
              f"{_fmt(p50)} / {_fmt(p95)} ms", ev,
              stato(basta and p50 < 1200 and p95 < 1800, n)),
        Esito(2, "TTFT (mediana)", "< 400 ms", f"{_fmt(t_ttft)} ms",
              f"{len(ttft)} turni", stato(t_ttft is not None and t_ttft < 400, len(ttft))),
        Esito(3, "Throughput (media)", ">= 45 tok/s", f"{_fmt(media_tok, 1)} tok/s",
              f"{len(toks)} turni con tok_s (loggato da M7)",
              stato(media_tok is not None and media_tok >= 45, len(toks))),
    ]


def nfr_soak(cartella: Path | None) -> list[Esito]:
    """NFR-4 e NFR-10 dal soak."""
    if cartella is None:
        return [Esito(4, "Picco VRAM", "<= 7,2 GB", "—", "nessun soak in data/soak",
                      "insufficiente"),
                Esito(10, "Stabilita' RSS", "> 72 h, < +10%", "—",
                      "nessun soak in data/soak", "insufficiente")]
    a = analizza(leggi_jsonl(cartella / "campioni.jsonl"),
                 leggi_jsonl(cartella / "interazioni.jsonl"))
    durata = a["durata_h"]
    completo = durata >= MIN_SOAK_H
    picco = a["vram_picco_gb"]
    rss = a["metriche"].get("rss_mb")
    crescita = rss["crescita_pct"] if rss else None
    ev = f"{cartella.name}, {durata:.1f} h"
    return [
        Esito(4, "Picco VRAM", "<= 7,2 GB", f"{_fmt(picco, 2)} GB", ev + " (1 Hz)",
              "insufficiente" if not completo or picco is None
              else ("verde" if picco <= 7.2 else "rosso")),
        Esito(10, "Stabilita' RSS", "> 72 h, < +10%",
              f"{_fmt(crescita, 1, '%')} in {durata:.1f} h", ev + " (retta dopo 1 h)",
              "insufficiente" if not completo or crescita is None
              else ("verde" if crescita < 10 else "rosso")),
    ]


def nfr8(eventi: list[dict]) -> Esito:
    """NFR-8: blocchi dell'interfaccia oltre 100 ms IN ESERCIZIO.

    Solo gli eventi con `fase` — loggata da M7 in poi. Quelli prima non
    dicono se erano all'avvio (ammessi) o in uso (no), e contarli
    mescolerebbe le due cose.
    """
    con_fase = [e for e in eventi if e.get("event") == "freeze interfaccia" and "fase" in e]
    in_uso = [e for e in con_fase if e["fase"] == "esercizio" and e.get("ms", 0) > 100]
    if not con_fase:
        return Esito(8, "Reattivita' GUI", "nessun freeze > 100 ms", "—",
                     "nessun evento con fase: usare la GUI da M7 in poi", "insufficiente")
    peggiore = max((e["ms"] for e in in_uso), default=None)
    return Esito(8, "Reattivita' GUI", "nessun freeze > 100 ms",
                 f"{len(in_uso)} freeze in esercizio" +
                 (f", peggiore {peggiore} ms" if peggiore else ""),
                 f"{len(con_fase)} eventi con fase in {LOG}",
                 "verde" if not in_uso else "rosso")


def nfr9(db: Path) -> Esito:
    if not db.exists():
        return Esito(9, "T3 non confermate", "0", "—", f"{db} assente", "insufficiente")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        n = con.execute(QUERY_NFR9).fetchone()[0]
        t3 = con.execute("SELECT COUNT(*) FROM audit WHERE tier='T3'").fetchone()[0]
    finally:
        con.close()
    return Esito(9, "T3 non confermate", "0", str(n),
                 f"query su {db}: {t3} righe T3 totali", "verde" if n == 0 else "rosso")


MANUALI = [
    Esito(5, "WER italiano", "< 12%", "—",
          "50 frasi registrate con la propria voce, riferimento trascritto a mano "
          "(benchmarks/stt_check.py)", "manuale"),
    Esito(6, "Falsi risvegli", "< 1 / 8 h", "—",
          "wake word spenta in V1.0 (D1): si misura quando si riaccende, 8 h di "
          "ambiente (wakeword/ambient)", "manuale"),
    Esito(7, "Auto-inneschi da eco", "0", "—",
          "2 h di TTS continuo a microfono aperto (wakeword/nfr7)", "manuale"),
]


def ultimo_soak(cartella: Path = SOAK) -> Path | None:
    if not cartella.exists():
        return None
    prove = sorted(p for p in cartella.iterdir()
                   if p.is_dir() and (p / "campioni.jsonl").exists())
    return prove[-1] if prove else None


def verifica(log: Path = LOG, db: Path = AUDIT, soak: Path | None = None) -> list[Esito]:
    eventi = leggi_jsonl(log)
    esiti = nfr_turni(eventi) + nfr_soak(soak) + [nfr8(eventi), nfr9(db)] + MANUALI
    return sorted(esiti, key=lambda e: e.nfr)


def tabella(esiti: list[Esito]) -> str:
    righe = ["| NFR | Metrica | Target | Misurato | Evidenza | Esito |",
             "| :-- | :-- | :-- | :-- | :-- | :-: |"]
    righe += [f"| {e.nfr} | {e.metrica} | {e.target} | {e.misurato} | {e.evidenza} "
              f"| {e.icona} |" for e in esiti]
    return "\n".join(righe) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica formale dei 10 NFR")
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--audit", type=Path, default=AUDIT)
    ap.add_argument("--soak", type=Path, default=None,
                    help="cartella del soak (default: l'ultima in data/soak)")
    ap.add_argument("--md", type=Path, help="scrive anche la tabella su file")
    args = ap.parse_args()

    esiti = verifica(args.log, args.audit, args.soak or ultimo_soak())
    testo = tabella(esiti)
    sys.stdout.reconfigure(encoding="utf-8")
    print(testo)
    conta = {s: sum(1 for e in esiti if e.stato == s)
             for s in ("verde", "rosso", "insufficiente", "manuale")}
    print(f"verdi {conta['verde']} · rossi {conta['rosso']} · dati insufficienti "
          f"{conta['insufficiente']} · manuali {conta['manuale']}")
    if args.md:
        args.md.write_text(testo, encoding="utf-8")
    # Un rosso e' un difetto; NFR-9 rosso e' bloccante per definizione.
    return 1 if conta["rosso"] else 0


if __name__ == "__main__":
    sys.exit(main())
