"""Metis — assistente personale vocale locale.

La registrazione delle DLL CUDA avviene qui, all'import del pacchetto, perche'
deve precedere qualunque import di CTranslate2. Vedi metis/core/cuda_libs.py.
"""
from metis.core.cuda_libs import register_cuda_dll_dirs

register_cuda_dll_dirs()
