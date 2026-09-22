"""Trovare un elemento dentro una pagina web, via Playwright su CDP.

CI SI COLLEGA A CHROME, NON SE NE LANCIA UNO
Playwright sa avviare un browser suo, pulito e isolato. Sarebbe inutile:
quel profilo non ha i login, non ha le schede aperte, non ha la sessione su
cui l'utente sta effettivamente lavorando. "Clicca sul link Contatti"
riguarda la pagina che ha davanti adesso. Quindi CDP, sulla porta che
`config/apps.toml` passa a Chrome all'avvio.

Il prezzo e' che il flag deve esserci. Se Chrome era gia' aperto senza,
Windows riusa il processo esistente e la porta non si apre mai — e il
sintomo sarebbe "Metis non trova mai niente sul web". Per questo
`diagnosi()` distingue i due casi e lo dice con parole diverse.

DA COORDINATE DELLA PAGINA A COORDINATE DELLO SCHERMO
Playwright da' il rettangolo di un elemento in pixel CSS relativi al
viewport. Il clic invece parte da `SendInput` in pixel fisici del desktop.
La conversione e' questa, e ogni pezzo c'e' per un motivo:

    schermo = (screenX + bordo) * dpr + css * dpr

`screenX`/`screenY` sono l'angolo della *finestra*, non del viewport;
`outerHeight - innerHeight` e' tutto cio' che sta sopra la pagina — barra
del titolo, barra degli indirizzi, schede — e va aggiunto; `devicePixelRatio`
converte i pixel CSS in pixel fisici, ed e' il punto in cui il monitor al
150% smette di essere un problema.

PERCHE' NON SI USA `locator.click()`, CHE SAREBBE PIU' SEMPLICE
Playwright sa cliccare da solo, in modo piu' affidabile di qualunque
conversione di coordinate. Non lo si fa per una ragione di sicurezza, non di
stile: un clic sintetizzato dentro il browser **non passa dal desktop**, e
quindi non e' soggetto alla guardia che verifica quale finestra sia in primo
piano. Esisterebbero due modi di cliccare, di cui uno solo controllato. Con
la conversione, ogni clic di Metis — nativo o web — e' lo stesso evento del
sistema operativo, sottoposto agli stessi controlli, rivalutati un
millisecondo prima di partire.

Lo scotto e' che se Chrome non e' in primo piano il clic finisce altrove.
Per questo `trova()` si rifiuta di lavorare su una finestra che non sia
quella davanti: e' la stessa cautela, dall'altro lato.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from dataclasses import dataclass

from metis.tools.registry import Rifiuto
from metis.tools.uia import Elemento, _piatto

PORTA_CDP = 9222
TIMEOUT_MS = 2500

# Dal `Literal` TipoElemento ai ruoli ARIA. Il ruolo e' l'equivalente web
# del ControlType di UIA: e' semantica dichiarata dalla pagina, non una
# somiglianza indovinata su un `div`.
RUOLI = {
    "pulsante": ("button",),
    "link": ("link",),
    "casella_di_testo": ("textbox", "searchbox", "combobox"),
    "voce_di_menu": ("menuitem",),
    "casella_di_spunta": ("checkbox", "radio"),
    "scheda": ("tab",),
    "elemento_lista": ("listitem", "option"),
    "qualsiasi": ("link", "button", "menuitem", "tab", "checkbox", "textbox"),
}


@dataclass(frozen=True)
class Riquadro:
    """La geometria della finestra del browser, letta dalla pagina stessa."""

    screen_x: float
    screen_y: float
    bordo_x: float
    bordo_y: float
    dpr: float

    def a_schermo(self, x: float, y: float) -> tuple[int, int]:
        return (round((self.screen_x + self.bordo_x + x) * self.dpr),
                round((self.screen_y + self.bordo_y + y) * self.dpr))


def porta_aperta(porta: int = PORTA_CDP) -> bool:
    """Un connect secco, senza Playwright: costa un millisecondo.

    Serve perche' avviare Playwright e scoprire solo dopo che non c'e'
    nessuno costa mezzo secondo, e quel mezzo secondo si paga a ogni frase
    in cui il modello ha creduto di dover cliccare qualcosa.
    """
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.15):
            return True
    except OSError:
        return False


def diagnosi() -> str:
    """Una frase su perche' il browser non e' raggiungibile. Vuota se lo e'."""
    if porta_aperta():
        return ""
    import psutil

    acceso = any(p.info["name"] and p.info["name"].lower() == "chrome.exe"
                 for p in psutil.process_iter(["name"]))
    if acceso:
        return ("Chrome e' aperto ma senza la porta di debug: era gia' in "
                "esecuzione quando l'ho trovato. Chiudilo del tutto e "
                "riaprilo da me")
    return "Chrome non e' aperto"


@contextmanager
def pagina_attiva():
    """La scheda in primo piano del Chrome dell'utente.

    Si apre e si chiude a ogni chiamata invece di tenere la connessione in
    caldo. L'API sincrona di Playwright e' legata al thread che l'ha creata,
    e ogni turno di Metis gira su un thread nuovo: una connessione riusata
    fra turni esploderebbe al secondo, in un modo poco leggibile. Costa
    ~300 ms e li paga solo chi clicca sul web.
    """
    from playwright.sync_api import sync_playwright

    if not porta_aperta():
        raise Rifiuto(diagnosi())

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTA_CDP}",
                                               timeout=TIMEOUT_MS)
        try:
            contesti = browser.contexts
            pagine = [p for c in contesti for p in c.pages]
            if not pagine:
                raise Rifiuto("Chrome e' collegato ma non ha schede aperte")
            # `bring_to_front` NON viene chiamato: cambierebbe la scheda
            # sotto le mani dell'utente. Si lavora su quella che sta
            # guardando, e se non e' quella giusta lo dira'.
            attiva = next((p for p in pagine if p.evaluate(
                "() => document.visibilityState === 'visible'")), pagine[0])
            yield attiva
        finally:
            browser.close()
    finally:
        pw.stop()


def _riquadro(pagina) -> Riquadro:
    d = pagina.evaluate("""() => ({
        sx: window.screenX, sy: window.screenY,
        ow: window.outerWidth, oh: window.outerHeight,
        iw: window.innerWidth, ih: window.innerHeight,
        dpr: window.devicePixelRatio || 1
    })""")
    return Riquadro(
        screen_x=d["sx"], screen_y=d["sy"],
        # Il bordo laterale e' meta' della differenza fra finestra e
        # viewport; quello superiore e' tutta la differenza verticale, perche'
        # sotto la pagina non c'e' niente.
        bordo_x=max(0.0, (d["ow"] - d["iw"]) / 2),
        bordo_y=max(0.0, d["oh"] - d["ih"]),
        dpr=d["dpr"] or 1.0,
    )


def candidati(pagina, nome: str, tipo: str = "qualsiasi") -> list[Elemento]:
    """Elementi della pagina con quel nome accessibile, in coordinate schermo."""
    riq = _riquadro(pagina)
    cercato = _piatto(nome)
    fuori: list[Elemento] = []
    visti: set[tuple] = set()

    for ruolo in RUOLI.get(tipo, RUOLI["qualsiasi"]):
        try:
            loc = pagina.get_by_role(ruolo)
            n = min(loc.count(), 60)
        except Exception:                      # noqa: BLE001
            continue
        for i in range(n):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                etichetta = (el.inner_text(timeout=300) or "").strip()
                if not etichetta:
                    etichetta = (el.get_attribute("aria-label") or "").strip()
                if not etichetta or cercato not in _piatto(etichetta):
                    continue
                box = el.bounding_box(timeout=300)
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue
            except Exception:                  # noqa: BLE001
                continue
            l, t = riq.a_schermo(box["x"], box["y"])
            r, b = riq.a_schermo(box["x"] + box["width"], box["y"] + box["height"])
            chiave = (etichetta[:60], l, t)
            if chiave in visti:
                continue
            visti.add(chiave)
            fuori.append(Elemento(etichetta[:120], ruolo, (l, t, r, b)))
    return fuori


def trova(nome: str, tipo: str = "qualsiasi") -> Elemento:
    """Cerca nella scheda attiva. Rifiuta se non trova, o se trova troppo."""
    from metis.tools.uia import scegli

    with pagina_attiva() as pagina:
        return scegli(candidati(pagina, nome, tipo), nome)
