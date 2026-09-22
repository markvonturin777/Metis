"""Il perimetro d'azione di Metis, verificato sul codice invece che a occhio.

Il piano di M2 chiedeva due controlli "per ispezione": nessuno strumento
accetta un percorso, nessun handler e' chiamabile fuori dal broker. Una lista
di controllo che si spunta una volta protegge fino al giorno dopo. Qui sono
test, e girano a ogni esecuzione della suite.

Il terzo controllo non era nel piano ed e' emerso scrivendolo: un T2 senza la
guardia della finestra sarebbe un buco silenzioso, e in M4 gli strumenti T2
si scriveranno di fretta.
"""
import ast
import tomllib
from pathlib import Path

import pytest

from metis.llm.schemas import SCHEMI, AppKey, nome_strumento
from metis.security.audit import Tier
from metis.security.guards import DENY_CLASSI, DENY_PROCESSI
from metis.tools.registry import carica_tutti

REG = carica_tutti()


# --- nessuno strumento nomina un percorso ------------------------------------

# Parole che in un nome di campo tradiscono un percorso. Non e' un elenco
# esaustivo di tutto il male possibile: e' una rete che prende la
# distrazione, che e' il modo in cui un campo del genere entrerebbe davvero.
SOSPETTE = ("path", "percorso", "file", "dir", "folder", "cartella",
            "filename", "filepath", "location", "destinazione", "src", "dst")


def test_nessuno_schema_accetta_un_percorso():
    """IL vincolo di sicurezza del progetto, in forma eseguibile.

    "Metis non tocca i file personali" non si ottiene bloccando `os`: l'LLM
    non esegue mai Python. Si ottiene non esistendo alcun campo in cui un
    percorso possa entrare. Se questo test fallisce, il vincolo e' saltato,
    e nessun controllo a valle lo rimette in piedi.
    """
    colpevoli = []
    for schema in SCHEMI:
        for nome, campo in schema.model_fields.items():
            if any(s in nome.lower() for s in SOSPETTE):
                colpevoli.append(f"{schema.__name__}.{nome} (nome sospetto)")
            if campo.annotation in (Path,) or "Path" in str(campo.annotation):
                colpevoli.append(f"{schema.__name__}.{nome} (tipo Path)")
    assert not colpevoli, "campi che possono contenere un percorso: " + ", ".join(colpevoli)


def test_il_controllo_sui_percorsi_riconosce_una_violazione():
    """Meta-test: una verifica che non sa vedere il difetto passa sempre."""
    from typing import Literal

    from pydantic import BaseModel

    class Cattivo(BaseModel):
        tool: Literal["cattivo"]
        file_path: str

    trovati = [n for n in Cattivo.model_fields
               if any(s in n.lower() for s in SOSPETTE)]
    assert trovati == ["file_path"]


# --- allowlist: due barriere che devono dire la stessa cosa ------------------

def test_allowlist_schema_e_config_coincidono():
    """Il Literal e il TOML sono due barriere separate, e va bene: ma se
    divergono, una delle due rifiuta qualcosa che l'altra permette e il
    risultato e' uno strumento che non funziona mai, oppure una voce di
    configurazione che nessuno puo' usare."""
    config = tomllib.loads(Path("config/apps.toml").read_text(encoding="utf-8"))
    chiavi_config = set(config.get("apps", {}))
    chiavi_schema = set(AppKey.__args__)
    assert chiavi_schema == chiavi_config, (
        f"solo nello schema: {chiavi_schema - chiavi_config} · "
        f"solo in config: {chiavi_config - chiavi_schema}"
    )


# --- nessun handler raggiungibile fuori dal broker ---------------------------

def _chiamate_per_nome(path: Path) -> set[str]:
    """Nomi di funzione effettivamente CHIAMATI nel file.

    Un decoratore applicato a una funzione non e' una chiamata a quella
    funzione, quindi `@REGISTRY.strumento(...)` sopra `_apri` non conta.
    """
    albero = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for n in ast.walk(albero):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.add(n.func.attr)
    return out


def test_nessun_handler_chiamato_fuori_dal_broker():
    """Durante lo sviluppo la tentazione di chiamare l'handler direttamente
    per provare e' fortissima, e ogni chiamata diretta e' un percorso che
    salta validazione, guardie, conferma e log."""
    handler = {s.handler.__name__ for s in REG}
    assert handler, "nessun handler registrato: il test non verifica nulla"

    colpevoli = []
    for f in Path("metis").rglob("*.py"):
        for nome in _chiamate_per_nome(f) & handler:
            colpevoli.append(f"{f.as_posix()} chiama {nome}()")
    assert not colpevoli, "handler chiamati fuori dal broker: " + "; ".join(colpevoli)


def test_gli_handler_sono_privati():
    """Un nome pubblico e' un invito a importarlo."""
    pubblici = [s.name for s in REG if not s.handler.__name__.startswith("_")]
    assert not pubblici, f"handler con nome pubblico: {pubblici}"


# --- invarianti del registro -------------------------------------------------

def test_ogni_t2_ha_la_guardia_della_finestra():
    """In M4 gli strumenti T2 si scriveranno in fretta, ed e' li' che una
    guardia dimenticata diventa un testo sintetico dentro Esplora risorse."""
    senza = [s.name for s in REG
             if s.tier is Tier.T2 and not any(g.nome == "finestra" for g in s.guards)]
    assert not senza, f"strumenti T2 senza guardia della finestra: {senza}"


def test_la_guardia_della_finestra_e_sempre_immediata():
    """Verificarla una volta per turno lascia aperta la finestra di corsa
    fra l'autorizzazione e l'evento di tastiera."""
    pigre = [f"{s.name}" for s in REG for g in s.guards
             if g.nome == "finestra" and not g.immediato]
    assert not pigre, f"guardia della finestra non immediata in: {pigre}"


def test_ogni_strumento_registrato_ha_uno_schema_coerente():
    for s in REG:
        assert nome_strumento(s.schema) == s.name
        assert s.schema.model_config.get("extra") == "forbid", (
            f"{s.name}: senza extra='forbid' un campo inventato passerebbe inosservato"
        )


def test_solo_gli_strumenti_eseguibili_sono_offerti_al_modello():
    """Offrire uno strumento che non puo' funzionare significa provocare
    fallimenti e insegnare al modello a insistere."""
    offerti = {s.name for s in REG.disponibili()}
    non_implementati = {s.name for s in REG if not s.implemented}
    assert offerti & non_implementati == set()
    assert offerti, "nessuno strumento disponibile"


def test_lo_schema_json_per_ollama_si_genera():
    """Nello schema offerto al modello ci sono tutti e soli gli implementati.

    In M2 questo test elencava `type_text` e `press_hotkey` fra i vietati,
    perche' allora erano perimetro senza capacita'. In M4 la capacita' e'
    arrivata e l'elenco si e' accorciato: l'unico ancora fuori e'
    `send_email`, che aspetta M6. La riga che conta non e' l'elenco — che
    per costruzione cambia a ogni iterazione — ma il legame con
    `implemented`, verificato qui sopra.
    """
    schema = REG.json_schema()
    assert schema, "schema vuoto"
    testo = str(schema)
    for nome in {s.name for s in REG if not s.implemented}:
        assert nome not in testo, f"{nome} non ha un corpo e non va offerto"
    assert "send_email" not in testo, "T3 senza capacita': arriva in M6"
    assert "click_element" in testo


@pytest.mark.parametrize("processo", ["explorer.exe", "cmd.exe", "powershell.exe",
                                      "regedit.exe", "consent.exe"])
def test_i_processi_piu_pericolosi_sono_in_denylist(processo):
    """Non e' un test del codice, e' un test della LISTA: e' la lista la cosa
    che si dimentica di aggiornare."""
    assert processo in DENY_PROCESSI


def test_i_dialoghi_di_file_sono_in_denylist():
    """#32770 e' la classe di 'Apri', 'Salva con nome' ed 'Elimina': un testo
    sintetico li' dentro agisce sul filesystem senza che nessuno strumento
    abbia mai accettato un percorso."""
    assert "#32770" in DENY_CLASSI


# --- casi avversariali sugli strumenti VERI ----------------------------------

def _broker_reale(tmp_path):
    from metis.security.audit import AuditLog
    from metis.security.broker import Broker
    return Broker(registry=REG, audit=AuditLog(tmp_path / "a.db"))


def test_type_text_vero_rifiutato_con_esplora_davanti(tmp_path, monkeypatch):
    """Il caso avversariale del piano, sullo strumento registrato davvero e
    non su un finto: e' l'unico modo di sapere che la guardia e' montata."""
    from metis.security import guards
    from metis.security.policies import Context

    monkeypatch.setattr(guards, "finestra_in_primo_piano",
                        lambda: guards.Finestra("Documenti", "explorer.exe", "CabinetWClass"))
    r = _broker_reale(tmp_path).execute(
        {"tool": "type_text", "text": "ciao"}, Context())
    assert r.denied and r.stage == "guardie" and "explorer.exe" in r.detail


def test_press_hotkey_vero_rifiuta_shift_canc(tmp_path):
    from metis.security.policies import Context

    r = _broker_reale(tmp_path).execute(
        {"tool": "press_hotkey", "keys": ["shift", "delete"]}, Context())
    assert r.denied and r.stage == "guardie"


@pytest.mark.parametrize("inventato", [
    {"tool": "delete_file", "path": "C:/Users/Marco/Documenti"},
    {"tool": "run_command", "cmd": "format c:"},
    {"tool": "read_file", "path": "C:/Users/Marco/.ssh/id_rsa"},
    {"tool": "execute_python", "code": "import os; os.remove('x')"},
    {"tool": "move_file", "src": "a", "dst": "b"},
])
def test_strumenti_inventati_dal_modello(tmp_path, inventato):
    """Non esistono, quindi non c'e' niente da bloccare: e' il punto."""
    from metis.security.policies import Context

    r = _broker_reale(tmp_path).execute(inventato, Context())
    assert r.denied and r.stage == "registro"


def test_send_email_vero_senza_conferma_non_parte(tmp_path):
    from metis.security.policies import Context

    b = _broker_reale(tmp_path)
    r = b.execute({"tool": "send_email", "to": "a@b.it", "subject": "s",
                   "body": "b"}, Context())
    assert r.denied and r.stage == "conferma"
    assert b.audit.unconfirmed_t3() == 0


# --- M4: nessuna coordinata come parametro ----------------------------------

COORDINATE = ("x", "y", "left", "top", "right", "bottom", "pixel",
              "coord", "coords", "pos", "posizione", "punto", "cx", "cy")


def test_nessuno_schema_accetta_delle_coordinate():
    """La decisione centrale di M4, in forma eseguibile.

    Se un campo `x` esistesse, il modello dovrebbe inventarsi un numero —
    non ha modo di sapere dov'e' il pulsante Salva — e il clic partirebbe
    comunque, in un punto che nessuno ha verificato. Le coordinate le
    calcola il risolutore guardando l'albero di UI Automation o il DOM,
    oppure non si clicca.
    """
    colpevoli = [f"{s.__name__}.{n}" for s in SCHEMI for n in s.model_fields
                 if n.lower() in COORDINATE]
    assert not colpevoli, ("campi con coordinate grezze: " + ", ".join(colpevoli))


def test_gli_strumenti_che_cliccano_nominano_l_elemento():
    """Il verso positivo del test qui sopra: non basta che le coordinate
    manchino, deve esserci un modo semantico di dire cosa premere."""
    for nome, campo in (("click_element", "elemento"), ("drag", "da")):
        spec = REG.get(nome)
        assert spec is not None and campo in spec.schema.model_fields


def test_il_livello_che_preme_i_tasti_non_registra_strumenti():
    """`sendinput.py` e' una libreria muta: se registrasse uno strumento,
    esisterebbe una via per premere tasti senza passare dalle guardie."""
    sorgente = Path("metis/tools/sendinput.py").read_text(encoding="utf-8")
    assert "REGISTRY" not in sorgente


# --- M4: il DPI si dichiara prima di Qt --------------------------------------

def test_il_dpi_si_dichiara_prima_di_qt():
    """Criterio di uscita di M4, che il piano chiedeva "per ispezione".

    Il contesto DPI si fissa al primo uso: se `QApplication` nasce prima,
    la chiamata non ha piu' effetto e non lo dice. Si legge l'ORDINE
    nell'AST e non il testo, perche' una ricerca testuale troverebbe anche
    questa docstring — e' gia' successo tre volte in questo progetto.
    """
    albero = ast.parse(Path("metis/gui/app.py").read_text(encoding="utf-8"))
    riga_dpi = None
    riga_qt = None
    for n in ast.walk(albero):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("PySide6"):
            riga_qt = min(riga_qt or n.lineno, n.lineno)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "set_dpi_awareness":
            riga_dpi = min(riga_dpi or n.lineno, n.lineno)
    assert riga_dpi is not None, "metis/gui/app.py non dichiara il DPI"
    assert riga_qt is not None, "il test non ha trovato gli import di Qt"
    assert riga_dpi < riga_qt, (
        f"set_dpi_awareness() alla riga {riga_dpi}, PySide6 alla {riga_qt}: "
        "Qt fissa il contesto DPI per primo e la chiamata non ha effetto")


def test_anche_la_console_dichiara_il_dpi():
    """Senza GUI non c'e' Qt a rovinare le cose, ma i clic sintetici si
    calcolano lo stesso sul desktop virtuale."""
    sorgente = Path("metis/core/app.py").read_text(encoding="utf-8")
    albero = ast.parse(sorgente)
    chiamate = {n.func.id for n in ast.walk(albero)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "set_dpi_awareness" in chiamate
