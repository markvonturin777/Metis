"""T1 — musica e volume (PHASE2, dopo le prove dell'utente, 2026-09-28).

    "pausa", "riprendi", "brano successivo"   ->  tasto_multimediale
    "alza il volume", "abbassa di 20"         ->  cambia_volume
    "volume al 30"                            ->  set_volume   (specifica §9.2, mai fatto prima)
    "muto", "togli il muto"                   ->  imposta_muto

PERCHE' T1 E NON T2 (D-NAV 8)
T2 e' "input nella finestra in primo piano", con la sua guardia: il testo non
deve finire in Esplora risorse o in un terminale. I tasti multimediali non
vanno a nessuna finestra: li riceve Windows, che li gira al lettore che sta
suonando (YouTube in Chrome, Spotify, …), anche se e' dietro. E il volume non
e' un tasto: e' una proprieta' del dispositivo audio. Niente dei due scrive,
cancella o esegue qualcosa, e tutto si annulla con il comando opposto.

IL VOLUME E' QUELLO DI SISTEMA
Anche la voce di Metis passa di li': "abbassa il volume" abbassa anche lei, e
"muto" la zittisce. E' il comportamento di un telecomando, ed e' quello che ci
si aspetta; le risposte restano scritte nell'Hub.

PLAY/PAUSA E' UN TASTO SOLO
Il tasto multimediale inverte lo stato: "pausa" su un video gia' in pausa lo
fa ripartire. Windows non dice a chi lo manda in che stato fosse. Per questo la
frase detta dopo e' "Fatto.", non "In pausa.": non si afferma cio' che non si
sa.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_float, c_uint, c_void_p

from metis.llm.schemas import (
    CambiaVolume,
    ImpostaMuto,
    LeggiVolume,
    SetVolume,
    TastoMultimediale,
)
from metis.security.audit import Tier
from metis.tools.registry import REGISTRY, Rifiuto

# --- Core Audio, con comtypes ------------------------------------------------------
#
# Le interfacce si dichiarano qui, nell'ordine esatto dei metodi della vtable
# (Mmdeviceapi.h, Endpointvolume.h): un metodo spostato chiama il metodo
# sbagliato. `test_media.py` legge e riscrive il volume attuale sul
# dispositivo vero, senza cambiarlo.


def _interfacce():
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _methods_ = [
            COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], c_void_p)),
            COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], c_void_p)),
            COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint))),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevel",
                      (["in"], c_float), (["in"], POINTER(GUID))),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar",
                      (["in"], c_float), (["in"], POINTER(GUID))),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float))),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float))),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevel",
                      (["in"], c_uint), (["in"], c_float), (["in"], POINTER(GUID))),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar",
                      (["in"], c_uint), (["in"], c_float), (["in"], POINTER(GUID))),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevel",
                      (["in"], c_uint), (["out"], POINTER(c_float))),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar",
                      (["in"], c_uint), (["out"], POINTER(c_float))),
            COMMETHOD([], HRESULT, "SetMute", (["in"], ctypes.c_int), (["in"], POINTER(GUID))),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(ctypes.c_int))),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Activate",
                      (["in"], POINTER(GUID)), (["in"], ctypes.c_ulong),
                      (["in"], c_void_p), (["out"], POINTER(POINTER(IUnknown)))),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                      (["in"], ctypes.c_int), (["in"], ctypes.c_ulong),
                      (["out"], POINTER(c_void_p))),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                      (["in"], ctypes.c_int), (["in"], ctypes.c_int),
                      (["out"], POINTER(POINTER(IMMDevice)))),
        ]

    return IAudioEndpointVolume, IMMDevice, IMMDeviceEnumerator


_CLSID_ENUMERATORE = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_RENDER, _CONSOLE = 0, 0
_CLSCTX_ALL = 23


def _volume():
    """L'interfaccia del volume dell'uscita predefinita. Una per chiamata: e'
    economica, e un oggetto COM tenuto fra un turno e l'altro vive sul thread
    sbagliato (ogni turno di Metis ha il suo)."""
    import comtypes
    from comtypes import GUID
    from comtypes.client import CreateObject

    comtypes.CoInitialize()
    vol_t, _, enum_t = _interfacce()
    enum = CreateObject(GUID(_CLSID_ENUMERATORE), interface=enum_t)
    dispositivo = enum.GetDefaultAudioEndpoint(_RENDER, _CONSOLE)
    grezzo = dispositivo.Activate(ctypes.byref(vol_t._iid_), _CLSCTX_ALL, None)
    return grezzo.QueryInterface(vol_t)


def livello() -> int:
    return round(_volume().GetMasterVolumeLevelScalar() * 100)


def imposta_livello(percento: int) -> int:
    v = _volume()
    p = max(0, min(100, int(percento)))
    v.SetMasterVolumeLevelScalar(p / 100.0, None)
    if p > 0 and v.GetMute():
        v.SetMute(0, None)          # "volume al 30" con il muto attivo: si sente
    return p


def muto() -> bool:
    return bool(_volume().GetMute())


def imposta_muto_audio(attivo: bool) -> None:
    _volume().SetMute(1 if attivo else 0, None)


def _senza_audio(exc: BaseException) -> Rifiuto:
    return Rifiuto("non trovo un'uscita audio a cui cambiare il volume")


# --- gli strumenti -----------------------------------------------------------------

@REGISTRY.strumento(Tier.T1, TastoMultimediale, al_modello=False)
def _tasto_multimediale(call: TastoMultimediale) -> dict:
    """Pausa o riprendi, brano successivo o precedente, per il lettore che suona."""
    from metis.tools import sendinput

    sendinput.multimediale(call.tasto)
    return {"tasto": call.tasto}


@REGISTRY.strumento(Tier.T0, LeggiVolume, al_modello=False)
def _leggi_volume(call: LeggiVolume) -> dict:
    """Dice a che livello e' il volume di sistema, e se e' muto."""
    try:
        return {"livello": livello(), "muto": muto()}
    except Exception as exc:                  # noqa: BLE001 - OSError, COMError
        raise _senza_audio(exc) from exc


@REGISTRY.strumento(Tier.T1, SetVolume, al_modello=False)
def _set_volume(call: SetVolume) -> dict:
    """Porta il volume di sistema a un livello da 0 a 100."""
    try:
        prima = livello()
        dopo = imposta_livello(call.livello)
    except Exception as exc:                  # noqa: BLE001 - OSError, COMError
        raise _senza_audio(exc) from exc
    return {"prima": prima, "livello": dopo}


@REGISTRY.strumento(Tier.T1, CambiaVolume, al_modello=False)
def _cambia_volume(call: CambiaVolume) -> dict:
    """Alza o abbassa il volume di sistema di qualche punto."""
    try:
        prima = livello()
        delta = call.passo if call.verso == "su" else -call.passo
        dopo = imposta_livello(prima + delta)
    except Exception as exc:                  # noqa: BLE001 - OSError, COMError
        raise _senza_audio(exc) from exc
    return {"prima": prima, "livello": dopo, "verso": call.verso}


@REGISTRY.strumento(Tier.T1, ImpostaMuto, al_modello=False)
def _imposta_muto(call: ImpostaMuto) -> dict:
    """Toglie o rimette l'audio di sistema."""
    try:
        imposta_muto_audio(call.muto)
    except Exception as exc:                  # noqa: BLE001 - OSError, COMError
        raise _senza_audio(exc) from exc
    return {"muto": call.muto}
