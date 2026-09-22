"""La memoria conversazionale: finestra, riassunto, budget.

Nessun test chiama Ollama. `Memoria` riceve il riassuntore iniettato proprio
per questo: la correttezza di "cosa si riassume e cosa no" e' una proprieta'
del codice, e verificarla contro un modello vero la renderebbe una proprieta'
della giornata.

Quanto e' BUONO il riassunto e' un'altra domanda, si misura in
`benchmarks/prova_memoria.py` e finisce nel tracking come numero.
"""
from __future__ import annotations

from metis.llm.grounding import BUDGET, CONTESTO_MAX, conta_token
from metis.memory.conversation import INTESTAZIONE_RIASSUNTO, Memoria

SYS = "Sei Metis."


def riempi(m: Memoria, n: int, lunghezza: int = 20) -> None:
    for i in range(n):
        m.aggiungi("user", f"domanda {i} " + "x" * lunghezza)
        m.aggiungi("assistant", f"risposta {i} " + "y" * lunghezza)


# --- finestra scorrevole ------------------------------------------------------

def test_la_finestra_tiene_gli_ultimi_otto_turni():
    m = Memoria(system=SYS)
    riempi(m, 20)
    utenti = [x for x in m.messaggi() if x["role"] == "user"]
    assert len(utenti) == 8
    assert "domanda 19" in utenti[-1]["content"]


def test_il_system_prompt_c_e_sempre():
    m = Memoria(system=SYS)
    riempi(m, 50)
    assert m.messaggi()[0] == {"role": "system", "content": SYS}


def test_gli_slot_stanno_attaccati_al_system_prompt():
    """Qwen 3 tratta un secondo messaggio `system` come testo qualunque, e un
    blocco di contesto declassato a testo qualunque e' un blocco che il
    modello contraddice."""
    m = Memoria(system=SYS)
    msgs = m.messaggi(slot="[CONTESTO CORRENTE]\nFinestra: Code")
    assert msgs[0]["role"] == "system" and "Finestra: Code" in msgs[0]["content"]
    assert sum(1 for x in msgs if x["role"] == "system") == 1


# --- il turno con le fonti ----------------------------------------------------

def test_la_domanda_sostituisce_l_ultimo_messaggio_utente():
    """Le fonti si iniettano NEL turno che le ha recuperate: se si
    aggiungessero, il modello vedrebbe la domanda due volte."""
    m = Memoria(system=SYS)
    m.aggiungi("user", "quanto rende il btp?")
    msgs = m.messaggi(domanda="FONTI... quanto rende il btp?")
    utenti = [x for x in msgs if x["role"] == "user"]
    assert len(utenti) == 1 and utenti[0]["content"].startswith("FONTI")


def test_le_fonti_non_restano_in_memoria():
    """Un testo ostile che restasse in cronologia continuerebbe a insistere
    per tutti i turni successivi, e quelli non sarebbero piu' marcati come
    contaminati."""
    m = Memoria(system=SYS)
    m.aggiungi("user", "quanto rende il btp?")
    m.messaggi(domanda="<<<FONTE_ESTERNA_NON_FIDATA...>>> quanto rende?")
    m.aggiungi("assistant", "Il tre e settantacinque.")
    assert all("FONTE_ESTERNA" not in x["content"] for x in m.messaggi())


# --- budget -------------------------------------------------------------------

def test_il_conteggio_divide_le_voci():
    m = Memoria(system=SYS)
    riempi(m, 4)
    c = m.conteggio(slot="[CONTESTO CORRENTE]\nx")
    assert c.system > 0 and c.slot > 0 and c.turni > 0
    assert c.totale == c.system + c.slot + c.riassunto + c.turni + c.web


def test_l_occupazione_esclude_il_margine_di_risposta():
    """Il margine per generare non e' spazio libero: e' gia' prenotato.
    Contarlo come disponibile farebbe scattare il riassunto troppo tardi."""
    m = Memoria(system="x" * 100)
    c = m.conteggio()
    assert c.occupazione == c.totale / (CONTESTO_MAX - BUDGET["risposta"])


def test_la_finestra_piena_piu_le_fonti_stanno_nel_contesto():
    """Il criterio di uscita "il contesto non supera mai gli 8k", nella
    forma che si puo' verificare senza un modello: il caso peggiore
    costruito a mano."""
    m = Memoria(system="s" * 1800)        # ~600 token
    riempi(m, 30, lunghezza=400)
    c = m.conteggio(slot="l" * 400, fonti="f" * int(3500 * 3.1))
    assert c.totale + BUDGET["risposta"] <= CONTESTO_MAX, c.come_dizionario()


# --- riassunto ----------------------------------------------------------------

def test_non_si_riassume_finche_la_finestra_contiene_tutto():
    """Finche' nessun turno e' uscito dalla finestra non c'e' niente da
    salvare, e riassumere costerebbe 2-3 secondi per niente."""
    m = Memoria(system=SYS, riassumi=lambda p: "riassunto")
    riempi(m, 3)
    assert not m.serve_riassunto()


def test_si_riassume_cio_che_esce_dalla_finestra():
    """La condizione che scatta davvero in una conversazione parlata. Vedi
    la nota su `da_condensare`: con la sola soglia del 70% questi turni
    sarebbero spariti senza che nessuno li riassumesse."""
    m = Memoria(system=SYS, riassumi=lambda p: "riassunto")
    riempi(m, 12)
    assert m.occupazione() < 0.70, "il caso in prova non e' quello di pressione"
    assert m.serve_riassunto()
    assert m.da_condensare() == 24 - m.finestra


def test_sotto_pressione_si_scende_fino_agli_intoccabili():
    """La soglia del piano. Con messaggi lunghi non basta salvare cio' che e'
    uscito: bisogna fare posto dentro la finestra."""
    m = Memoria(system=SYS, riassumi=lambda p: "riassunto")
    riempi(m, 40, lunghezza=2200)
    assert m.occupazione() >= 0.70
    assert m.da_condensare() == 80 - m.intoccabili


def test_non_si_riassume_se_non_c_e_niente_da_condensare():
    """Una singola domanda lunghissima riempie il contesto e non ha niente
    di vecchio da condensare: senza questa condizione il riassunto
    ripartirebbe a ogni tick."""
    m = Memoria(system=SYS, riassumi=lambda p: "r")
    m.aggiungi("user", "x" * 30000)
    assert m.occupazione() >= 0.70
    assert not m.serve_riassunto()


def test_gli_ultimi_quattro_turni_non_si_riassumono_mai():
    """Sono esattamente quelli a cui si riferiscono i pronomi della frase che
    l'utente sta per dire. Vale anche sotto pressione, che e' il caso in cui
    verrebbe la tentazione di tagliare piu' a fondo."""
    m = Memoria(system=SYS, riassumi=lambda p: "condensato")
    riempi(m, 40, lunghezza=2200)
    m.compatta()
    coda = [x["content"] for x in m.messaggi() if x["role"] != "system"]
    assert len(coda) == m.intoccabili
    assert "domanda 36" in coda[0]


def test_in_condizioni_normali_la_finestra_resta_intera():
    """Condensare cio' che e' gia' caduto non deve accorciare la finestra: i
    turni recenti vanno letti per intero, non riassunti."""
    m = Memoria(system=SYS, riassumi=lambda p: "condensato")
    riempi(m, 12)
    m.compatta()
    coda = [x for x in m.messaggi() if x["role"] != "system"]
    assert len(coda) == m.finestra
    assert "domanda 23" not in coda[0]["content"]


def test_caso_anaforico_4_l_argomento_sopravvive_a_tre_turni():
    """§4.4 numero 4: "Cerca X" -> tre turni di altro -> "torna su
    quell'argomento". La parte che spetta alla memoria e' che X finisca nel
    riassunto invece di sparire quando esce dalla finestra."""
    condensati = []
    m = Memoria(system=SYS,
                riassumi=lambda p: condensati.append(p) or "L'utente ha cercato "
                                                          "l'andamento del BTP decennale.")
    m.aggiungi("user", "cerca l'andamento del BTP decennale")
    m.aggiungi("assistant", "Il rendimento e' al tre e settantacinque.")
    riempi(m, 10)
    assert m.compatta()
    assert "BTP decennale" in condensati[0], "il turno da salvare non e' stato passato"
    assert "BTP decennale" in "".join(x["content"] for x in m.messaggi())


def test_il_riassunto_entra_come_messaggio_di_sistema():
    m = Memoria(system=SYS, riassumi=lambda p: "l'utente ha aperto Chrome")
    riempi(m, 10)
    m.compatta()
    sistemi = [x["content"] for x in m.messaggi() if x["role"] == "system"]
    assert any(INTESTAZIONE_RIASSUNTO in x and "Chrome" in x for x in sistemi)


def test_il_riassunto_precedente_entra_in_quello_nuovo():
    """Riassumere il riassunto: senza, la memoria piu' vecchia sparisce al
    secondo giro invece di condensarsi ancora."""
    visti = []
    m = Memoria(system=SYS, riassumi=lambda p: visti.append(p) or "nuovo")
    riempi(m, 10)
    m.compatta()
    riempi(m, 10)
    m.compatta()
    assert INTESTAZIONE_RIASSUNTO in visti[1]


def test_il_riassunto_non_puo_crescere_oltre_il_tetto():
    """Un riassunto che cresce a ogni giro ricrea, un turno alla volta, il
    problema che doveva risolvere."""
    m = Memoria(system=SYS, riassumi=lambda p: "parola. " * 2000)
    riempi(m, 10)
    m.compatta()
    assert conta_token(m.riassunto) <= 300


def test_un_riassuntore_che_esplode_non_perde_la_memoria():
    def rotto(p):
        raise RuntimeError("ollama giu'")

    m = Memoria(system=SYS, riassumi=rotto)
    riempi(m, 10)
    assert m.compatta() is False
    assert len(m.turni) == 20


def test_un_riassunto_vuoto_non_cancella_i_turni():
    m = Memoria(system=SYS, riassumi=lambda p: "   ")
    riempi(m, 10)
    assert m.compatta() is False
    assert len(m.turni) == 20


def test_senza_riassuntore_non_si_riassume():
    m = Memoria(system=SYS)
    riempi(m, 10)
    assert m.compatta() is False


def test_cio_che_arriva_durante_il_riassunto_non_si_perde():
    """Fra l'inizio del riassunto e la sua fine passano 2-3 secondi, e
    l'utente puo' aver parlato. Si tagliano i messaggi che c'erano allora,
    non gli ultimi N."""
    m = Memoria(system=SYS)
    riempi(m, 10)

    def lento(prompt):
        m.aggiungi("user", "arrivata durante il riassunto")
        return "condensato"

    m.riassumi = lento
    m.compatta()
    assert m.messaggi()[-1]["content"] == "arrivata durante il riassunto"


def test_le_statistiche_dicono_cosa_e_successo():
    m = Memoria(system=SYS, riassumi=lambda p: "r")
    riempi(m, 10)
    m.compatta()
    s = m.stats()
    assert s["riassunti"] == 1 and s["condensati"] == 20 - m.finestra
