"""Interfaccia grafica di Metis — PySide6 (LGPL).

LA REGOLA CHE REGGE TUTTO IL PACCHETTO
I widget si toccano **solo dal thread principale**. Ogni comunicazione da un
thread secondario passa per un `Signal`. Non esistono eccezioni, nemmeno
"solo per questa etichetta".

Violarla non produce un errore subito: produce crash sporadici settimane
dopo, in situazioni non riproducibili, di solito sulla macchina di qualcun
altro. `tests/test_gui_thread.py` lo verifica leggendo il sorgente dei
worker, perche' una regola che si controlla a occhio dura fino al giorno
dopo.
"""
