"""Worker: `QObject` spostati su un `QThread`, mai sottoclassi di `QThread`.

Sottoclassando `QThread`, i metodi dell'oggetto restano affiliati al thread
che lo ha CREATO, non a quello nuovo: si crede di aver spostato il lavoro e
lo si e' lasciato dov'era. E' l'errore piu' comune con Qt e produce
esattamente i bug che si voleva evitare, con l'aggravante che l'interfaccia
sembra funzionare finche' il carico e' leggero.

    worker = Nucleo(...)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.avvia)
    thread.start()

Nessun worker di questo pacchetto importa `QtWidgets`. Non e' una
convenzione: `tests/test_gui_thread.py` lo verifica leggendo il sorgente.
"""
