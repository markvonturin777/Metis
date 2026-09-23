"""Un Home Assistant finto che parla il protocollo WebSocket vero.

Implementa i quattro messaggi che il client usa — autenticazione,
`get_states`, `subscribe_events`, `call_service` — e spinge gli eventi
`state_changed` come fa quello vero. Soprattutto, si puo' **spegnere e
riaccendere**: il comportamento che conta di piu' in `home_assistant.py` e'
cosa succede quando la connessione cade, e un finto che non cade non lo
proverebbe mai.

Gira su un thread con il suo loop, come il client: i test restano sincroni.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone

TOKEN = "token-di-prova"

STATI_INIZIALI = {
    "switch.friggitrice_aria": "off",
    "switch.distributore_crocchette": "off",
    "camera.xiaomi_salotto": "idle",
    # Un'entita' che Home Assistant ha e che il file di configurazione NON
    # nomina: il client la vede, gli strumenti non devono poterla toccare.
    "lock.porta_ingresso": "locked",
}


def _stato(eid: str, valore: str) -> dict:
    ora = datetime.now(timezone.utc).isoformat()
    return {"entity_id": eid, "state": valore, "attributes": {},
            "last_changed": ora, "last_updated": ora}


class FintoHA:
    def __init__(self, token: str = TOKEN, porta: int = 0):
        self.token = token
        self.porta = porta
        self.stati = {e: _stato(e, v) for e, v in STATI_INIZIALI.items()}
        self.servizi: list[tuple[str, str, str]] = []   # (dominio, servizio, entita')
        self.rifiuta_servizi = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._client = set()
        self._pronto = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.porta}/api/websocket"

    # -- ciclo di vita, dal thread del test --

    def avvia(self) -> "FintoHA":
        self._pronto.clear()
        self._thread = threading.Thread(target=self._esegui, daemon=True,
                                        name="finto-ha")
        self._thread.start()
        assert self._pronto.wait(5), "il finto Home Assistant non parte"
        return self

    def ferma(self) -> None:
        """Chiude il server E le connessioni aperte: e' un Home Assistant
        che si riavvia, non uno che smette di accettarne di nuove."""
        if self._loop is None:
            return
        fut = asyncio.run_coroutine_threadsafe(self._chiudi(), self._loop)
        fut.result(5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        self._loop = None

    def __enter__(self) -> "FintoHA":
        return self.avvia()

    def __exit__(self, *_):
        self.ferma()

    def cambia(self, eid: str, valore: str) -> None:
        """Qualcuno ha acceso la friggitrice dall'app del telefono."""
        asyncio.run_coroutine_threadsafe(self._cambia(eid, valore), self._loop).result(5)

    # -- dentro il thread --

    def _esegui(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._apri())
        self._pronto.set()
        self._loop.run_forever()

    async def _apri(self) -> None:
        import websockets

        self._server = await websockets.serve(self._gestisci, "127.0.0.1", self.porta)
        # La porta si fissa alla prima accensione: le riaccensioni devono
        # tornare sulla STESSA, come un Home Assistant riavviato.
        self.porta = self._server.sockets[0].getsockname()[1]

    async def _chiudi(self) -> None:
        for ws in list(self._client):
            await ws.close()
        self._server.close()
        await self._server.wait_closed()

    async def _cambia(self, eid: str, valore: str) -> None:
        vecchio = self.stati.get(eid)
        nuovo = _stato(eid, valore)
        self.stati[eid] = nuovo
        evento = {"type": "event", "event": {
            "event_type": "state_changed",
            "data": {"entity_id": eid, "old_state": vecchio, "new_state": nuovo}}}
        for ws in list(self._client):
            await ws.send(json.dumps({"id": ws.id_sottoscrizione, **evento})
                          if getattr(ws, "id_sottoscrizione", None) else json.dumps(evento))

    async def _gestisci(self, ws) -> None:
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "finto"}))
        auth = json.loads(await ws.recv())
        if auth.get("access_token") != self.token:
            await ws.send(json.dumps({"type": "auth_invalid", "message": "no"}))
            await ws.close()
            return
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "finto"}))
        self._client.add(ws)
        try:
            async for grezzo in ws:
                m = json.loads(grezzo)
                mid, tipo = m.get("id"), m.get("type")
                if tipo == "get_states":
                    await ws.send(json.dumps({"id": mid, "type": "result",
                                              "success": True,
                                              "result": list(self.stati.values())}))
                elif tipo == "subscribe_events":
                    ws.id_sottoscrizione = mid
                    await ws.send(json.dumps({"id": mid, "type": "result",
                                              "success": True, "result": None}))
                elif tipo == "call_service":
                    eid = m["target"]["entity_id"]
                    self.servizi.append((m["domain"], m["service"], eid))
                    if self.rifiuta_servizi or eid not in self.stati:
                        await ws.send(json.dumps({
                            "id": mid, "type": "result", "success": False,
                            "error": {"code": "not_found", "message": "entita' sconosciuta"}}))
                        continue
                    await ws.send(json.dumps({"id": mid, "type": "result",
                                              "success": True, "result": {}}))
                    await self._cambia(eid, "on" if m["service"] == "turn_on" else "off")
        except Exception:                          # noqa: BLE001
            pass
        finally:
            self._client.discard(ws)
