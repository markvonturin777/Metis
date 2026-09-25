<#
.SYNOPSIS
    Avvio automatico di Metis all'accesso, tramite l'Utilita' di pianificazione.

.DESCRIPTION
    Registra (o toglie) l'attivita' "Metis" per l'utente corrente:

        trigger        all'accesso di QUESTO utente, con 60 s di ritardo
        riavvio        3 volte, a 1 minuto di distanza, se l'avvio fallisce
        privilegi      RunLevel Limited: MAI amministratore
        durata         nessun limite (il default di Windows e' 72 ore)

    Perche' non la chiave di registro Run: parte troppo presto. Al login
    Ollama e la rete possono non essere pronti, e i device USB — il Yeti —
    possono non essere ancora enumerati. Il ritardo di 60 s copre il caso
    tipico; per il resto c'e' l'avvio robusto di M7 (attende Ollama fino a
    120 s, aspetta il microfono senza uscire).

    PERCHE' "LIMITED" NON E' NEGOZIABILE
    Metis esegue azioni sul PC per conto di chi parla. Un Metis elevato
    renderebbe ogni falla del broker una falla da amministratore. Lo script
    rifiuta di girare da una console elevata: registrerebbe l'attivita' come
    amministratore, contro l'intenzione.

    LIMITE NOTO DI RestartCount
    L'Utilita' di pianificazione riavvia un'attivita' che non riesce a
    PARTIRE, non un processo che esce con errore dopo essere partito. Un
    crash a meta' giornata non viene coperto da qui: lo copre il fatto che
    Metis non esce per gli errori previsti (matrice di M7). Scritto qui per
    non farlo scoprire dopo.

.PARAMETER Disinstalla
    Toglie l'attivita'. Non tocca nient'altro.

.PARAMETER Anteprima
    Mostra cosa verrebbe registrato, senza registrare. Serve anche ai test.

.PARAMETER Eseguibile
    Il programma da avviare. Default: il bundle `dist\Metis\Metis.exe` se
    esiste, altrimenti `pythonw.exe` del venv con `-m metis.gui.app`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Anteprima
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Disinstalla
#>

[CmdletBinding()]
param(
    [switch]$Disinstalla,
    [switch]$Anteprima,
    [string]$Eseguibile = ""
)

$ErrorActionPreference = "Stop"
$NomeAttivita = "Metis"
$Radice = Split-Path -Parent $PSScriptRoot

function Test-Elevato {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Disinstalla) {
    if ($Anteprima) {
        Write-Output "anteprima: toglierei l'attivita' '$NomeAttivita'"
        exit 0
    }
    $c = Get-ScheduledTask -TaskName $NomeAttivita -ErrorAction SilentlyContinue
    if ($null -eq $c) {
        Write-Output "Nessuna attivita' '$NomeAttivita' da togliere."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $NomeAttivita -Confirm:$false
    Write-Output "Attivita' '$NomeAttivita' tolta. Metis non partira' piu' all'accesso."
    exit 0
}

if ((Test-Elevato) -and -not $Anteprima) {
    Write-Error ("Console da amministratore: l'attivita' verrebbe registrata con " +
                 "privilegi elevati. Riaprire PowerShell come utente normale.")
    exit 1
}

# --- cosa avviare -------------------------------------------------------------
# pythonw e non python: nessuna finestra di console. Il log va comunque in
# data\logs, che e' il posto dove guardare se qualcosa non parte.
$Argomenti = ""
if ($Eseguibile -eq "") {
    $Bundle = Join-Path $Radice "dist\Metis\Metis.exe"
    if (Test-Path $Bundle) {
        $Eseguibile = $Bundle
    } else {
        $Eseguibile = Join-Path $Radice ".venv\Scripts\pythonw.exe"
        $Argomenti = "-m metis.gui.app"
    }
}
if (-not (Test-Path $Eseguibile)) {
    Write-Error "Non trovo '$Eseguibile'. Installare prima Metis (docs\INSTALL.md)."
    exit 1
}

# La cartella di lavoro e' la radice del progetto: config\ e data\ sono
# percorsi relativi, e da C:\Windows\System32 — il default dell'Utilita' di
# pianificazione — Metis non troverebbe niente.
if ($Argomenti -eq "") {
    $Azione = New-ScheduledTaskAction -Execute $Eseguibile -WorkingDirectory $Radice
} else {
    $Azione = New-ScheduledTaskAction -Execute $Eseguibile -Argument $Argomenti `
                                      -WorkingDirectory $Radice
}

$Utente = "$env:USERDOMAIN\$env:USERNAME"
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Utente
$Trigger.Delay = "PT60S"

$Principale = New-ScheduledTaskPrincipal -UserId $Utente -LogonType Interactive `
                                         -RunLevel Limited

$Impostazioni = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$Attivita = New-ScheduledTask -Action $Azione -Trigger $Trigger `
    -Principal $Principale -Settings $Impostazioni `
    -Description "Metis: assistente vocale locale. Avvio all'accesso, non elevato."

if ($Anteprima) {
    # Righe chiave=valore: le legge anche `tests/test_autostart.py`.
    Write-Output "anteprima: nessuna attivita' registrata"
    Write-Output "Nome=$NomeAttivita"
    Write-Output "Esegui=$($Azione.Execute)"
    Write-Output "Argomenti=$($Azione.Arguments)"
    Write-Output "Cartella=$($Azione.WorkingDirectory)"
    Write-Output "Utente=$($Principale.UserId)"
    Write-Output "RunLevel=$($Principale.RunLevel)"
    Write-Output "Ritardo=$($Trigger.Delay)"
    Write-Output "RestartCount=$($Impostazioni.RestartCount)"
    Write-Output "RestartInterval=$($Impostazioni.RestartInterval)"
    Write-Output "ExecutionTimeLimit=$($Impostazioni.ExecutionTimeLimit)"
    Write-Output "MultipleInstances=$($Impostazioni.MultipleInstances)"
    exit 0
}

Register-ScheduledTask -TaskName $NomeAttivita -InputObject $Attivita -Force | Out-Null

# Si rilegge quello che Windows ha registrato davvero, non quello che si e'
# chiesto: e' la verifica di "Metis NON gira come amministratore".
$Registrata = Get-ScheduledTask -TaskName $NomeAttivita
if ($Registrata.Principal.RunLevel -ne "Limited") {
    Unregister-ScheduledTask -TaskName $NomeAttivita -Confirm:$false
    Write-Error "RunLevel registrato: $($Registrata.Principal.RunLevel). Attivita' tolta."
    exit 1
}
Write-Output "Attivita' '$NomeAttivita' registrata: partira' 60 s dopo il prossimo accesso."
Write-Output "  esegue:    $Eseguibile $Argomenti"
Write-Output "  privilegi: $($Registrata.Principal.RunLevel)"
Write-Output "Per toglierla: scripts\install_autostart.ps1 -Disinstalla"
