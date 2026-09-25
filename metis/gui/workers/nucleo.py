"""Il nucleo di Metis su un thread suo: audio, macchina a stati, broker.

PERCHE' IL SISTEMA SI COSTRUISCE DENTRO `avvia()` E NON NEL COSTRUTTORE
Caricare Whisper, Qwen e Piper costa una decina di secondi. Farlo nel
costruttore significa farlo sul thread che costruisce l'oggetto, cioe'
quello della GUI, cioe' una finestra congelata per dieci secondi prima
ancora di comparire. Il costruttore qui non fa nulla di pesante: prende le
opzioni e basta.

I COMANDI NON SONO SLOT, ED E' VOLUTO
`ptt()` e `kill_switch()` sono metodi normali, chiamati **direttamente** dal
thread della GUI. Con Qt verrebbe naturale farne degli slot e invocarli in
coda, ma non funzionerebbe: mentre il ciclo audio gira, questo thread non
sta processando eventi, quindi uno slot in coda non verrebbe mai eseguito —
e il pulsante non risponderebbe proprio quando serve, cioe' mentre Metis
parla.

Chiamarli direttamente e' sicuro perche' l'orchestratore e' pensato per
essere toccato da piu' thread fin da M1: la macchina a stati ha un lock, il
token di annullamento e' un `Event`, la coda del player e' una `Queue`. Nel
percorso da console e' gia' cosi', con il thread delle scorciatoie globali.

Il verso opposto — un widget toccato da qui — resta vietato senza eccezioni.
Questo modulo non importa `QtWidgets`, e un test lo verifica.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal, Slot

from metis.core.avvio import CicloAudio, Opzioni, costruisci_sistema
from metis.core.logging import get_logger
from metis.security.killswitch import KILL_SWITCH

CONTATORI_HZ = 2.0          # ogni quanto si spedisce lo stato dei contatori


class Nucleo(QObject):
    """Tutto cio' che non e' interfaccia. Emette, non disegna."""

    avvio = Signal(str)                 # riga di avanzamento all'avvio
    pronto = Signal(float)              # secondi impiegati
    stato = Signal(str, str, str)       # da, evento, a
    trascritto = Signal(str, bool)      # testo, sospetto
    dice = Signal(str)                  # frase che sta per pronunciare
    turno = Signal(dict)                # metriche del turno concluso
    livello = Signal(float, float)      # rms, picco in dBFS
    contatori = Signal(dict)
    contesto = Signal(dict)             # M5: budget, slot, fonti dell'ultimo turno
    errore = Signal(str)
    finito = Signal()

    def __init__(self, opzioni: Opzioni, ponte_conferma=None, parent=None):
        super().__init__(parent)
        self.opzioni = opzioni
        self.ponte = ponte_conferma
        self.sistema = None
        self.ciclo: CicloAudio | None = None
        self._log = get_logger()
        self._ultimo_contatori = 0.0

    # -- sul thread del nucleo ---------------------------------------------

    @Slot()
    def avvia(self) -> None:
        try:
            self.sistema = costruisci_sistema(
                self.opzioni, self._log,
                riporta=self.avvio.emit,
                chiedi_conferma=(self.ponte.chiedi if self.ponte else None),
                on_transition=lambda tr: self.stato.emit(
                    tr.frm.name, tr.event.name, tr.to.name),
                on_trascritto=lambda tr: self.trascritto.emit(
                    tr.text, bool(getattr(tr, "suspect", False))),
                on_dice=self.dice.emit,
                on_turno=lambda m: self.turno.emit(self._metriche(m)),
            )
            self.pronto.emit(self.sistema.avvio_s)
        except Exception as exc:              # noqa: BLE001
            # Microfono assente, Ollama giu', voce non scaricata: l'utente
            # deve leggerlo in finestra, non in un traceback su un terminale
            # che con la GUI potrebbe non esserci nemmeno.
            # M7: la frase in persona nella finestra, il testo tecnico nel
            # log. Prima si mostrava "ConnectionError: ..." — un traceback
            # abbreviato, ma sempre un traceback.
            from metis.core.errors import messaggio, tecnico

            self._log.error("avvio fallito", errore=tecnico(exc))
            self.errore.emit(messaggio(exc))
            self.finito.emit()
            return

        self.ciclo = CicloAudio(self.sistema.orchestrator,
                                on_blocco=self._su_blocco,
                                on_microfono=self._microfono)
        try:
            self.ciclo.esegui(
                limite_s=self.opzioni.minutes * 60 if self.opzioni.minutes else None)
        except Exception as exc:              # noqa: BLE001
            from metis.core.errors import messaggio, tecnico

            self._log.error("ciclo audio fallito", errore=tecnico(exc))
            self.errore.emit(messaggio(exc))
        finally:
            self.finito.emit()

    def _microfono(self, ok: bool) -> None:
        """M7 — il microfono c'e' o non c'e'. Una riga in conversazione e una
        notifica: la voce di Metis funziona, ma senza microfono l'utente non
        potrebbe rispondere, e il messaggio deve restare leggibile anche se
        nessuno era li' ad ascoltare."""
        from metis.core.errors import Categoria, messaggio
        from metis.tools import notify

        if ok:
            self.errore.emit("Il microfono e' di nuovo disponibile.")
            return
        frase = messaggio(Categoria.AUDIO_INGRESSO)
        self.errore.emit(frase)
        notify.mostra("Metis", frase)

    def _su_blocco(self, blocco) -> None:
        """~31 volte al secondo: deve costare quasi niente.

        Il diradamento del VU meter lo fa chi riceve, non qui: questo e'
        l'unico punto in cui si vede il livello istantaneo, e filtrarlo
        adesso vorrebbe dire buttare via informazione che l'interfaccia
        potrebbe voler usare diversamente.
        """
        self.livello.emit(blocco.rms_dbfs, blocco.peak_dbfs)
        ora = time.perf_counter()
        if ora - self._ultimo_contatori >= 1.0 / CONTATORI_HZ:
            self._ultimo_contatori = ora
            self.contatori.emit(self._stato_contatori())
            self.contesto.emit(self._stato_contesto())

    def _stato_contatori(self) -> dict:
        c = self.sistema.orchestrator.counters
        return {
            "turni": c.turns, "strumenti_ok": c.tools_ok,
            "strumenti_negati": c.tools_denied, "errori": c.errors,
            "barge_in": c.barge_ins, "scartati": c.discarded,
            "kill_switch": KILL_SWITCH.attivo,
        }

    def _stato_contesto(self) -> dict:
        """Cosa c'e' nel prompt adesso, in forma di dizionario.

        Due volte al secondo, come i contatori: e' un conteggio di caratteri
        su una finestra di 16 messaggi, cioe' microsecondi. Se un giorno
        diventasse un tokenizzatore vero andrebbe diradato, perche' questa
        funzione gira sul thread del nucleo e NFR-8 si misura anche qui.

        Escono dati, mai oggetti: `Memoria` e `Slots` hanno un lock e
        reggerebbero la lettura dal thread della GUI, ma la regola di M3
        resta — fra i due thread passano dizionari.
        """
        from metis.memory.slots import SLOTS

        mem = getattr(self.sistema, "memoria", None)
        if mem is None:
            return {}
        slot = SLOTS.blocco()
        consulente = getattr(self.sistema, "consulente", None)
        ultimo = getattr(consulente, "ultimo", None)
        fonti = ultimo.citazioni() if ultimo is not None else []
        return {"conteggio": mem.conteggio(slot, fonti=(ultimo.blocco()
                                                        if ultimo else "")
                                           ).come_dizionario(),
                "slot": slot,
                "riassunti": mem.riassunti_fatti,
                "fonti": fonti}

    @staticmethod
    def _metriche(m) -> dict:
        b = m.breakdown()
        return {"turn_id": m.turn_id, "totale_ms": b["totale"],
                "stt_ms": b["stt"], "ttft_ms": b["ttft"], "tts_ms": b["tts"],
                "tokens": m.tokens, "tok_per_s": m.tok_per_s,
                "testo": m.transcript, "risposta": m.reply,
                "strumento": m.extra.get("tool")}

    # -- chiamabili dal thread della GUI (vedi la nota in testa) -----------

    def ptt(self) -> None:
        if self.sistema is not None:
            self.sistema.orchestrator.on_ptt()

    def kill_switch(self) -> bool:
        """Zittisce e sospende T2/T3. Ritorna lo stato risultante."""
        if self.sistema is not None:
            self.sistema.orchestrator.panic()
        sospeso = KILL_SWITCH.commuta()
        self._log.warning("kill switch",
                          capacita="SOSPESE" if sospeso else "ripristinate")
        return sospeso

    def pausa(self) -> bool:
        """M7 — commuta la pausa dell'ascolto. Ritorna lo stato risultante.

        Prima che il sistema sia pronto non c'e' niente da mettere in pausa,
        e si risponde False: la tray non deve mostrare una spunta che non
        corrisponde a nulla.
        """
        if self.sistema is None:
            return False
        orch = self.sistema.orchestrator
        orch.pausa(not orch.in_pausa)
        self._log.warning("ascolto", stato="IN PAUSA" if orch.in_pausa else "ripreso")
        return orch.in_pausa

    def ferma(self) -> None:
        """Esce dal ciclo al giro successivo, entro ~250 ms."""
        if self.ponte is not None:
            self.ponte.annulla()          # chi aspetta una conferma non resti appeso
        if self.ciclo is not None:
            self.ciclo.ferma()

    def chiudi(self) -> None:
        if self.sistema is not None:
            self.sistema.orchestrator.panic()
            self.sistema.player.close()
            # M6: scheduler e Home Assistant girano su thread propri.
            self.sistema.chiudi()
