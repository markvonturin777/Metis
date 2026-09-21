"""NFR-7 — zero auto-inneschi con Metis che parla e il microfono aperto.

IL RISCHIO CHE QUESTA PROVA MISURA
Il rilevatore di wake word resta acceso anche mentre Metis parla: e' il
livello L2 della strategia anti-eco, quello che rende possibile il barge-in.
Il prezzo e' che gli altoparlanti suonano dentro il microfono. Se la voce di
Piper riuscisse a far scattare il rilevatore, Metis si interromperebbe da
solo a meta' frase, in modo apparentemente casuale — il difetto peggiore di
tutta questa fase, perche' dal vivo sembra un capriccio.

LA PROVA DEVE POTER FALLIRE
Un banco con gli altoparlanti a zero passerebbe sempre e non direbbe niente.
Prima di cominciare si misura quindi quanto il microfono senta davvero la
voce: se la differenza fra silenzio e parlato e' sotto i 6 dB, il banco si
rifiuta di partire. Una verifica che non puo' fallire non e' una verifica.

DUE FASI, CONTATE SEPARATAMENTE
  A. parlato normale — e' NFR-7: il criterio e' ZERO scatti.
  B. Metis pronuncia il proprio nome, "Hey Metis" compreso. Qui uno scatto
     non e' propriamente un difetto: il rilevatore sta facendo il suo lavoro
     su un suono che e' davvero la wake word. Si misura perche' e' il caso
     peggiore e conviene sapere quanto e' vicino, ma non entra nel verdetto.

    python wakeword/nfr7_test.py --minutes 120
    python wakeword/nfr7_test.py --minutes 5 --nome-minutes 2     # prova rapida
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import warnings
from collections import deque
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from metis.audio.capture import TARGET_SR, VAD_BLOCK, AudioCapture  # noqa: E402
from metis.audio.wakeword import Confirmer, WakeWordConfig, WakeWordDetector  # noqa: E402
from metis.tts import create_engine  # noqa: E402
from metis.tts.kokoro_engine import Player  # noqa: E402

OUT = Path("wakeword/nfr7")
BLOCK_S = VAD_BLOCK / TARGET_SR
CONTESTO_S = 3.0
CODA_S = 1.5

# Frasi normali. Varie di proposito: lunghezze diverse, punteggiatura diversa,
# e diverse vocali accentate, perche' e' la prosodia a contare, non il senso.
CORPUS = [
    "La riunione di domani e' stata spostata alle quattordici e trenta.",
    "Ho trovato tre articoli sull'argomento, il piu' recente e' di marzo.",
    "Il file si trova nella cartella dei documenti condivisi.",
    "Non ho capito bene, puoi ripetere la seconda parte?",
    "Il meteo per il fine settimana prevede pioggia e sedici gradi.",
    "Ti ricordo che alle diciotto hai una chiamata con il fornitore.",
    "Ho messo da parte gli appunti, sono nella stessa cartella di prima.",
    "La batteria del portatile e' al ventidue per cento.",
    "Mi sembra che manchi ancora la firma sull'ultimo documento.",
    "Secondo i dati, il consumo e' calato del sette per cento.",
    "Metti pure quel foglio dove preferisci, tanto lo rivedo domani.",
    "Mettiamoci d'accordo su un orario che vada bene a tutti.",
    "Mattia ha scritto poco fa, chiede conferma per giovedi'.",
    "Ehi, mi senti bene adesso o c'e' ancora un'eco?",
    "Smettila di preoccuparti, il backup e' andato a buon fine.",
    "La mattina presto il traffico e' molto piu' scorrevole.",
    "Ammettiamo per un attimo che l'ipotesi sia corretta.",
    "Il documento conta quarantadue pagine, indice escluso.",
    "Ho aggiornato il foglio di calcolo con i numeri di ieri sera.",
    "Direi che possiamo chiudere qui e riprendere lunedi'.",
    "L'aggiornamento richiedera' circa dieci minuti, poi si riavvia.",
    "Purtroppo quel collegamento non funziona piu', e' scaduto.",
    "Preferisci che te lo riassuma o che te lo legga per intero?",
    "Nel frattempo ho preparato una bozza, la trovi in allegato.",
    "Quel progetto e' fermo da settimane per mancanza di tempo.",
    "Se serve posso cercare qualcosa di piu' aggiornato in rete.",
    "La stampante segnala carta esaurita nel cassetto inferiore.",
    "Non sono sicuro di aver capito la domanda, la riformulo.",
    "Ho notato che il grafico non include gli ultimi due mesi.",
    "Sono le undici e dodici, ti restano venti minuti.",
]

# Caso peggiore: Metis dice il proprio nome. Fase B, conteggio separato.
CORPUS_NOME = [
    "Mi chiamo Metis e sono il tuo assistente su questo computer.",
    "Puoi chiamarmi dicendo Hey Metis, oppure con la scorciatoia da tastiera.",
    "Metis e' pronto, dimmi pure cosa ti serve.",
    "Se dici Hey Metis mentre sto parlando, mi interrompo.",
    "Il nome Metis viene dalla mitologia greca, significa saggezza astuta.",
    "Hey Metis, hey Metis: sto pronunciando la mia stessa parola di attivazione.",
]


class Parlatore(threading.Thread):
    """Tiene la coda di riproduzione sempre piena.

    Sta su un thread suo perche' la sintesi costa un centinaio di millisecondi:
    farla nel ciclo di lettura lascerebbe buchi nel flusso che arriva al
    rilevatore, ed e' proprio il flusso continuo la cosa da misurare.
    """

    def __init__(self, tts, player: Player, frasi: list[str]):
        super().__init__(daemon=True, name="nfr7-parlatore")
        self.tts, self.player = tts, player
        self.frasi = list(frasi)
        self.attivo = threading.Event()
        self.attivo.set()
        self._stop = threading.Event()
        self.dette = 0
        self.secondi_audio = 0.0

    def cambia_corpus(self, frasi: list[str]) -> None:
        self.frasi = list(frasi)

    def run(self) -> None:
        rng = random.Random(0)
        while not self._stop.is_set():
            if not self.attivo.is_set() or self.player.pending() >= 2:
                time.sleep(0.05)
                continue
            frase = rng.choice(self.frasi)
            syn = self.tts.synth(frase)
            # L'etichetta viaggia con l'audio: il Player dira' quale frase sta
            # suonando davvero. Attribuire l'ultima SINTETIZZATA e' sbagliato,
            # perche' la coda ne tiene due di anticipo — errore che ha reso
            # inutilizzabili le attribuzioni della seduta del 21 settembre.
            self.player.enqueue(syn.pcm, frase)
            self.dette += 1
            self.secondi_audio += syn.audio_s

    def chiudi(self) -> None:
        self._stop.set()


def livello_medio(cap: AudioCapture, secondi: float) -> float:
    """RMS medio in dBFS su una finestra. Serve alla verifica di validita'."""
    cap.drain()          # la coda contiene audio di prima: non e' questo il momento
    valori = []
    t_fine = time.perf_counter() + secondi
    while time.perf_counter() < t_fine:
        b = cap.read(timeout=0.5)
        if b is not None:
            valori.append(b.rms_dbfs)
    return float(np.mean(valori)) if valori else -120.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=120.0, help="fase A, NFR-7")
    ap.add_argument("--nome-minutes", type=float, default=5.0, help="fase B, il nome")
    ap.add_argument("--peak", type=float, default=0.5)
    ap.add_argument("--min-delta-db", type=float, default=6.0,
                    help="quanto il microfono deve sentire gli altoparlanti")
    ap.add_argument("--no-full-audio", dest="full_audio", action="store_false",
                    help="non salvare l'audio integrale della seduta")
    args = ap.parse_args()

    sess = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT / sess
    out.mkdir(parents=True, exist_ok=True)

    cfg = WakeWordConfig.load()
    det = WakeWordDetector(cfg)
    tts = create_engine()
    player = Player(sample_rate=tts.sample_rate)

    print("=" * 66)
    print(f"  NFR-7 — auto-inneschi con Metis che parla   ({args.minutes:.0f} min"
          f" + {args.nome_minutes:.0f} min sul nome)")
    print("=" * 66)
    print(f"  modello : {cfg.model_path.name}  soglia {cfg.threshold} "
          f"x{cfg.consecutive} blocchi")
    print(f"  voce    : {getattr(tts, 'voice_name', '?')}   {tts.warmup():.0f} ms")
    for _ in range(8):
        det.feed(np.zeros(VAD_BLOCK, dtype=np.float32))
    det.reset()
    det.scores.clear()

    cap = AudioCapture()
    with cap:
        # --- verifica di validita' ------------------------------------
        print("\n  Alza gli altoparlanti al volume a cui useresti Metis davvero.")
        input("  INVIO quando sei pronto...")
        print("\n  silenzio, 3 secondi...")
        db_silenzio = livello_medio(cap, 3.0)

        player.start()
        parlatore = Parlatore(tts, player, CORPUS)
        parlatore.start()
        time.sleep(1.0)
        print("  parlato, 6 secondi...")
        db_voce = livello_medio(cap, 6.0)
        delta = db_voce - db_silenzio

        print(f"\n  silenzio {db_silenzio:6.1f} dBFS")
        print(f"  con voce {db_voce:6.1f} dBFS      differenza {delta:+.1f} dB")
        if delta < args.min_delta_db:
            parlatore.chiudi()
            player.close()
            print(f"\n  FERMO — il microfono non sente gli altoparlanti ({delta:.1f} dB).")
            print("  Cosi' la prova passerebbe da sola senza dimostrare niente.")
            print("  Alza il volume, o avvicina il microfono, e rilancia.")
            return
        print("  Il microfono sente: la prova puo' fallire, quindi ha senso.\n")

        # --- fasi ------------------------------------------------------
        contesto: deque[np.ndarray] = deque(maxlen=int(CONTESTO_S / BLOCK_S))
        coda_blocchi = int(CODA_S / BLOCK_S)
        in_cattura: list[np.ndarray] | None = None
        cattura_resta = 0
        info: dict = {}

        eventi: list[dict] = []
        punteggi = {"A": [], "B": []}
        scatti = {"A": 0, "B": 0}
        # Stessa audio, regola alternativa: confronto appaiato gratuito.
        conf_dual = Confirmer(cfg.threshold, cfg.consecutive, cfg.refractory_s)
        scatti_dual = {"A": 0, "B": 0}
        livelli: list[float] = []

        # AUDIO INTEGRALE — e' quello che rende questa seduta l'ULTIMA.
        # Due ore a 16 kHz mono int16 sono ~230 MB: da qui in poi qualunque
        # modello riaddestrato si rivaluta su queste stesse due ore con
        # `rescore_session.py`, offline, senza altoparlanti e senza che
        # nessuno debba risentire la voce di Piper.
        sessione_wav = None
        if args.full_audio:
            sessione_wav = sf.SoundFile(out / "sessione.wav", "w",
                                        samplerate=TARGET_SR, channels=1,
                                        subtype="PCM_16")
            mb = (args.minutes + args.nome_minutes) * 60 * TARGET_SR * 2 / 1024**2
            print(f"  audio integrale -> {out / 'sessione.wav'}  (~{mb:.0f} MB)\n")

        cap.drain()
        t0 = time.perf_counter()
        fase_a_fine = args.minutes * 60
        fine = fase_a_fine + args.nome_minutes * 60
        fase = "A"
        ultimo = 0.0

        try:
            while True:
                b = cap.read(timeout=0.5)
                ora = time.perf_counter()
                trascorso = ora - t0
                if trascorso > fine:
                    break
                if fase == "A" and trascorso > fase_a_fine:
                    fase = "B"
                    parlatore.cambia_corpus(CORPUS_NOME)
                    print("\n\n  --- FASE B: Metis pronuncia il proprio nome ---\n")
                if b is None:
                    continue

                scattato = det.feed(b.pcm)
                s = det.last_score
                if conf_dual.feed(min(det.last_score_a, det.last_score_b), ora):
                    scatti_dual[fase] += 1
                punteggi[fase].append(s)
                livelli.append(b.rms_dbfs)
                contesto.append(b.pcm)
                if sessione_wav is not None:
                    sessione_wav.write(b.pcm)

                if in_cattura is None and (s >= args.peak or scattato):
                    in_cattura = list(contesto)
                    cattura_resta = coda_blocchi
                    info = {"fase": fase, "t_s": round(trascorso, 1), "picco": float(s),
                            "scatto": bool(scattato),
                            "frase": player.now_playing or ""}
                elif in_cattura is not None:
                    in_cattura.append(b.pcm)
                    info["picco"] = max(info["picco"], float(s))
                    info["scatto"] = info["scatto"] or bool(scattato)
                    cattura_resta -= 1
                    if cattura_resta <= 0:
                        nome = (f"{fase}_{'SCATTO' if info['scatto'] else 'picco'}"
                                f"_{info['t_s']:07.1f}s_{info['picco']:.3f}.wav")
                        sf.write(out / nome, np.concatenate(in_cattura), TARGET_SR)
                        info["wav"] = nome
                        eventi.append(info)
                        in_cattura, info = None, {}

                if scattato:
                    scatti[fase] += 1
                    print(f"\n  !! AUTO-INNESCO fase {fase} a {trascorso / 60:.1f} min "
                          f"(punteggio {s:.3f}) mentre diceva: {player.now_playing!r}")

                if ora - ultimo > 1.0:
                    p = punteggi[fase]
                    print(f"\r  fase {fase}  {trascorso / 60:6.1f} / {fine / 60:.1f} min   "
                          f"frasi {parlatore.dette:5d}   picco {max(p) if p else 0:.3f}   "
                          f"scatti A={scatti['A']} B={scatti['B']}   "
                          f"mic {b.rms_dbfs:6.1f} dBFS", end="")
                    ultimo = ora
        except KeyboardInterrupt:
            print("\n  interrotto")
        finally:
            parlatore.chiudi()
            player.close()
            if sessione_wav is not None:
                sessione_wav.close()

    # --- esito ----------------------------------------------------------
    durata = time.perf_counter() - t0
    a = np.array(punteggi["A"]) if punteggi["A"] else np.zeros(1)
    bb = np.array(punteggi["B"]) if punteggi["B"] else np.zeros(1)

    report = {
        "sessione": sess,
        "minuti": round(durata / 60, 1),
        "soglia": cfg.threshold,
        "consecutive": cfg.consecutive,
        "db_silenzio": round(db_silenzio, 1),
        "db_voce": round(db_voce, 1),
        "delta_db": round(delta, 1),
        "audio_integrale": str(out / "sessione.wav") if args.full_audio else None,
        "frasi_pronunciate": parlatore.dette,
        "secondi_di_voce": round(parlatore.secondi_audio, 1),
        "fase_A": {"blocchi": len(punteggi["A"]), "scatti": scatti["A"],
                   "scatti_doppia_fase": scatti_dual["A"],
                   "p99": float(np.percentile(a, 99)), "max": float(a.max())},
        "fase_B": {"blocchi": len(punteggi["B"]), "scatti": scatti["B"],
                   "scatti_doppia_fase": scatti_dual["B"],
                   "p99": float(np.percentile(bb, 99)), "max": float(bb.max())},
        "eventi": eventi,
    }
    (OUT / f"{sess}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print("\n\n" + "=" * 66)
    print(f"  RISULTATO — {durata / 60:.1f} minuti, {parlatore.dette} frasi, "
          f"{parlatore.secondi_audio / 60:.0f} min di voce")
    print("=" * 66)
    print(f"  microfono sentiva gli altoparlanti: {delta:+.1f} dB sopra il silenzio")
    print("\n  FASE A (parlato normale) — e' NFR-7")
    print(f"    blocchi valutati : {len(punteggi['A']):,}")
    print(f"    auto-inneschi    : {scatti['A']}        (NFR-7 chiede 0)")
    print(f"    con doppia fase  : {scatti_dual['A']}")
    print(f"    punteggi         : p99 {np.percentile(a, 99):.4f}   max {a.max():.4f}")
    print("\n  FASE B (Metis dice il proprio nome) — informativa")
    print(f"    blocchi valutati : {len(punteggi['B']):,}")
    print(f"    scatti           : {scatti['B']}   (doppia fase: {scatti_dual['B']})")
    print(f"    punteggi         : p99 {np.percentile(bb, 99):.4f}   max {bb.max():.4f}")

    print("\n" + "=" * 66)
    if scatti["A"] == 0:
        print(f"  NFR-7 SUPERATO — zero auto-inneschi in {durata / 60:.1f} minuti")
        margine = cfg.threshold - a.max()
        print(f"  margine sulla soglia: {margine:+.3f} "
              f"(max raggiunto {a.max():.3f} contro soglia {cfg.threshold})")
        if margine < 0.1:
            print("  Stretto: e' passato, ma non di molto. Vale la pena aggiungere")
            print("  i picchi salvati ai negativi duri prima di considerarlo chiuso.")
    else:
        print(f"  NFR-7 FALLITO — {scatti['A']} auto-inneschi")
        print(f"  I WAV in {out} mostrano cosa stava dicendo. Sono anche i")
        print("  negativi duri piu' preziosi che si possano avere: copiali in")
        print("  wakeword/data/hard/ e riaddestra.")
    if scatti["B"]:
        print(f"\n  Nota: in fase B Metis si e' interrotto {scatti['B']} volte dicendo")
        print("  il proprio nome. Non e' un difetto del rilevatore — sta")
        print("  riconoscendo la wake word vera — ma in M3 conviene non far")
        print("  pronunciare 'Hey Metis' alle risposte.")
    print("=" * 66)
    print(f"\n  dettaglio: {OUT / (sess + '.json')}")


if __name__ == "__main__":
    main()
