"""La matrice degli errori: cosa si dice quando qualcosa si rompe.

IL PRINCIPIO
Nessun traceback raggiunge l'utente. Ogni modalita' di errore produce una
frase in persona. "L'infrastruttura di inferenza non risponde" e' un
assistente; `ConnectionRefusedError` in un overlay e' un prototipo.

Fino a M6 c'erano tre punti in cui il testo grezzo di un'eccezione arrivava
all'utente, trovati cercandoli prima di scrivere questo file:

    la GUI                 "errore: ConnectionError: ..." nella conversazione
    risposte.descrivi      "Non ci sono riuscito: ConnectionError: ..." a voce
    il turno               Ollama giu' a meta' turno: ERRORE, e Metis TACEVA

L'ultimo non e' un traceback ma e' peggio: un assistente che smette di
rispondere senza dire perche' sembra rotto anche quando si riprendera' da
solo fra dieci secondi.

LA CLASSIFICAZIONE SI FA SUL TIPO, E SUL TIPO VERO
Misurato prima di scriverla: il client di Ollama solleva `ConnectionError`
nelle chiamate normali, ma `httpx.ConnectError` in STREAMING — cioe' nel
percorso che Metis usa sempre. Una classificazione scritta leggendo la
documentazione avrebbe mancato il caso principale.

TRE STRATEGIE, DAL PIANO

    riprova    silenziosa se costa meno di due secondi, poi degrada
    degrada    si fa meno, e lo si dice
    dichiara   non si puo' fare niente: lo si dice, e si aspetta

Il messaggio non contiene MAI il testo dell'eccezione. Il testo va nel log,
dove serve a chi ripara; la frase va all'utente, dove serve a chi usa.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Categoria(Enum):
    INFERENZA = "inferenza"              # Ollama non raggiungibile
    INFERENZA_OOM = "inferenza_oom"      # Ollama senza memoria grafica
    MODELLO_MANCANTE = "modello_mancante"
    AUDIO_INGRESSO = "audio_ingresso"    # microfono scollegato
    RETE = "rete"                        # internet assente
    CASA = "casa"                        # Home Assistant
    POSTA = "posta"                      # SMTP
    STRUMENTO = "strumento"              # uno strumento in eccezione
    SINTESI = "sintesi"                  # TTS
    VRAM = "vram"                        # memoria grafica oltre soglia
    SCONOSCIUTO = "sconosciuto"


class Strategia(Enum):
    RIPROVA = "riprova"
    DEGRADA = "degrada"
    DICHIARA = "dichiara"
    SILENZIO = "silenzio"                # STT vuoto: commentarlo e' peggio


@dataclass(frozen=True)
class Voce:
    """Una riga della matrice."""

    strategia: Strategia
    messaggio: str
    tentativi: int = 0
    backoff_s: tuple[float, ...] = ()


# La matrice del piano, §1.2. I messaggi sono frasi da pronunciare: brevi, in
# persona, senza un solo termine tecnico che l'utente debba decifrare.
MATRICE: dict[Categoria, Voce] = {
    Categoria.INFERENZA: Voce(
        Strategia.RIPROVA,
        "L'infrastruttura di inferenza non risponde. Provo a ristabilire il "
        "collegamento.",
        # UN tentativo in piu', non tre. Misurato: su Windows una connessione
        # rifiutata costa 2,26 s da sola (4,3 s con "localhost"), perche' lo
        # stack TCP riprova il SYN. I tre tentativi del piano facevano 8
        # secondi di silenzio. Il resto del recupero lo fa `SALUTE`, in
        # sottofondo, senza far aspettare nessuno: vedi sotto.
        tentativi=1, backoff_s=(0.5,)),
    Categoria.INFERENZA_OOM: Voce(
        Strategia.DEGRADA,
        "Memoria grafica al limite. Riorganizzo le risorse.",
        tentativi=1),
    Categoria.MODELLO_MANCANTE: Voce(
        Strategia.DICHIARA,
        "Il modello linguistico non e' installato. Serve un intervento "
        "sull'installazione."),
    Categoria.AUDIO_INGRESSO: Voce(
        Strategia.DICHIARA,
        "Il microfono non risponde. Resto in attesa che torni."),
    Categoria.RETE: Voce(
        Strategia.DEGRADA,
        "Le fonti non sono raggiungibili. Posso pero' ancora occuparmi del "
        "sistema."),
    Categoria.CASA: Voce(
        Strategia.RIPROVA,
        "L'hub domotico non risponde."),
    Categoria.POSTA: Voce(
        Strategia.RIPROVA,
        "L'invio non e' riuscito. Ho rimandato di dieci minuti."),
    Categoria.STRUMENTO: Voce(
        Strategia.DICHIARA,
        "Quell'operazione non e' andata a buon fine."),
    Categoria.SINTESI: Voce(
        Strategia.DEGRADA,
        ""),                             # non si puo' dire: la voce e' il guasto
    Categoria.VRAM: Voce(
        Strategia.DEGRADA,
        "Memoria grafica al limite. Sposto il riconoscimento vocale sul "
        "processore."),
    Categoria.SCONOSCIUTO: Voce(
        Strategia.DICHIARA,
        "Qualcosa non ha funzionato. Riprovi fra un momento."),
}


# --- classificazione ---------------------------------------------------------------

# Pezzi di messaggio con cui Ollama e CUDA dicono "memoria finita". Non c'e'
# un tipo d'eccezione dedicato: arriva come `ResponseError` con un testo.
_OOM = ("out of memory", "cudamalloc", "cuda error", "insufficient memory",
        "failed to allocate", "memory allocation")


def classifica(exc: BaseException) -> Categoria:
    """La categoria di un'eccezione. Non solleva, non importa librerie pesanti.

    Si guarda il TIPO, risalendo la gerarchia per nome invece che con
    `isinstance`: cosi' questo modulo non importa `httpx`, `ollama` o
    `sounddevice` solo per poterli riconoscere, e si puo' usare anche dove
    quelle librerie non ci sono.
    """
    nomi = {f"{t.__module__}.{t.__name__}" for t in type(exc).__mro__}
    testo = str(exc).casefold()

    if any(n.startswith("ollama.") for n in nomi):
        if getattr(exc, "status_code", None) == 404 and "not found" in testo:
            return Categoria.MODELLO_MANCANTE
        if any(p in testo for p in _OOM):
            return Categoria.INFERENZA_OOM
        return Categoria.INFERENZA
    if any(p in testo for p in _OOM):
        return Categoria.INFERENZA_OOM
    if "Failed to connect to Ollama".casefold() in testo:
        return Categoria.INFERENZA
    # httpx in streaming: vedi la nota in testa. Per l'orchestratore l'unico
    # client HTTP che parla in streaming e' quello di Ollama.
    if any(n.startswith("httpx.") for n in nomi):
        return Categoria.INFERENZA
    if any(n.startswith("sounddevice.") for n in nomi) or "portaudio" in testo:
        return Categoria.AUDIO_INGRESSO
    if any(n.startswith("smtplib.") for n in nomi):
        return Categoria.POSTA
    if "builtins.ConnectionError" in nomi or "builtins.TimeoutError" in nomi:
        return Categoria.INFERENZA
    return Categoria.SCONOSCIUTO


def messaggio(exc_o_categoria: BaseException | Categoria) -> str:
    """La frase per l'utente. MAI il testo dell'eccezione."""
    if isinstance(exc_o_categoria, Categoria):
        cat = exc_o_categoria
    else:
        # `Esaurito` e `Indisponibile` portano gia' la categoria: riclassificare
        # il loro testo darebbe SCONOSCIUTO.
        cat = getattr(exc_o_categoria, "categoria", None) or classifica(exc_o_categoria)
    return MATRICE[cat].messaggio


def tecnico(exc: BaseException) -> str:
    """La riga per il log: tipo e testo, tagliati. E' l'opposto di
    `messaggio`, e va dove va il log."""
    return f"{type(exc).__name__}: {exc}"[:300]


# --- salute: cosa e' giu' adesso -------------------------------------------------

class Indisponibile(Exception):
    """Il servizio e' noto come giu': non lo si prova nemmeno."""

    def __init__(self, categoria: Categoria):
        self.categoria = categoria
        super().__init__(f"{categoria.value}: noto come non disponibile")


class Salute:
    """Quali servizi sono giu', e chi li sorveglia per sapere quando tornano.

    PERCHE' ESISTE (misurato in M7)
    Una connessione rifiutata costa 2,26 s su Windows. Senza memoria di cosa
    e' giu', ogni turno con Ollama spento pagherebbe quei secondi due volte —
    il router e poi la generazione — prima di dire che non va. Con questa
    classe il primo turno li paga una volta, e i successivi rispondono
    subito, mentre un thread in sottofondo ricontrolla ogni cinque secondi e
    rimette le cose a posto quando il servizio torna.

    I comandi rapidi non ne risentono: non passano dal modello, quindi "apri
    VS Code" funziona anche con Ollama spento.
    """

    def __init__(self):

        self._giu: dict[Categoria, float] = {}
        self._lock = threading.Lock()
        self._sonde: dict[Categoria, Callable[[], bool]] = {}
        self._ferma = threading.Event()
        self._thread = None
        self.cadute = 0
        self.riprese = 0

    def giu(self, categoria: Categoria) -> None:
        with self._lock:
            if categoria not in self._giu:
                self._giu[categoria] = time.monotonic()
                self.cadute += 1

    def su(self, categoria: Categoria) -> None:
        with self._lock:
            if self._giu.pop(categoria, None) is not None:
                self.riprese += 1

    def e_giu(self, categoria: Categoria) -> bool:
        with self._lock:
            return categoria in self._giu

    def stato(self) -> dict[str, float]:
        """{categoria: secondi da quando e' giu'}. Per la GUI e il soak."""
        with self._lock:
            ora = time.monotonic()
            return {c.value: round(ora - t, 1) for c, t in self._giu.items()}

    def richiedi(self, categoria: Categoria) -> None:
        """Solleva `Indisponibile` se il servizio e' giu'. Costa un dizionario."""
        if self.e_giu(categoria):
            raise Indisponibile(categoria)

    def sorveglia(self, categoria: Categoria, sonda: Callable[[], bool],
                  periodo_s: float = 5.0) -> None:
        """Registra una sonda e, al primo uso, avvia il thread che la chiama
        mentre il servizio e' giu'. La sonda gira SOLO in quel caso: da
        servizio vivo non costa niente."""

        self._sonde[categoria] = sonda
        if self._thread is not None:
            return
        self._ferma.clear()

        def ciclo() -> None:
            while not self._ferma.wait(periodo_s):
                for cat, s in list(self._sonde.items()):
                    if not self.e_giu(cat):
                        continue
                    try:
                        if s():
                            self.su(cat)
                    except Exception:             # noqa: BLE001
                        pass

        self._thread = threading.Thread(target=ciclo, daemon=True,
                                        name="metis-salute")
        self._thread.start()

    def ferma(self, attesa_s: float = 1.0) -> None:
        # Si aspetta il thread, con un limite: una sonda in corso puo' durare
        # un paio di secondi (connessione rifiutata su Windows), e l'uscita
        # non deve restare appesa a lei. Oltre il limite il thread e' demone
        # e muore col processo.
        t, self._thread = self._thread, None
        self._ferma.set()
        if t is not None and t is not threading.current_thread():
            t.join(attesa_s)


SALUTE = Salute()


# --- riprova ---------------------------------------------------------------------

class Esaurito(Exception):
    """I tentativi sono finiti. Porta l'ultima eccezione vera."""

    def __init__(self, categoria: Categoria, ultima: BaseException):
        self.categoria = categoria
        self.ultima = ultima
        super().__init__(f"{categoria.value}: {tecnico(ultima)}")


def riprova(fn: Callable[[], object], categoria: Categoria,
            attendi: Callable[[float], None] = time.sleep,
            ritentabile: Callable[[BaseException], bool] | None = None):
    """Esegue `fn` con i tentativi e il backoff della matrice.

    Riprova solo le eccezioni della stessa categoria (o quelle che
    `ritentabile` accetta): un errore di programmazione non guarisce
    aspettando un secondo, e riprovarlo tre volte triplica solo il tempo
    prima di dirlo.
    """
    voce = MATRICE[categoria]
    ok = ritentabile or (lambda e: classifica(e) is categoria)
    ultima: BaseException | None = None
    for i in range(voce.tentativi + 1):
        try:
            return fn()
        except Exception as exc:                  # noqa: BLE001
            if not ok(exc):
                raise
            ultima = exc
            if i < voce.tentativi:
                attendi(voce.backoff_s[min(i, len(voce.backoff_s) - 1)]
                        if voce.backoff_s else 0)
    raise Esaurito(categoria, ultima)            # type: ignore[arg-type]
