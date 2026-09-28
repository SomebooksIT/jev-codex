# Jev for Codex Desktop

Plugin locale che aggiunge a Codex Desktop review deterministica, checkpoint preventivi e routing Jev indipendente per ogni subagente. Usa solo Python 3 e libreria standard.

## Installazione

Dalla radice di questa repository:

```powershell
codex plugin marketplace add .
codex plugin add jev-codex@personal --json
codex plugin list
```

Riavvia Codex Desktop o apri un nuovo task perché manifest, skill e hook vengano riscoperti. Apri `/hooks` e autorizza gli hook del plugin quando Codex chiede la trust esplicita. Installazione e attivazione degli hook sono due verifiche distinte.

Configura la chiave TypeSafe solo nell'ambiente del processo che avvia Codex:

```powershell
$env:TYPESAFE_API_KEY = "<chiave>"
```

Per renderla persistente nell'ambiente utente Windows, quindi riavviare completamente Codex Desktop:

```powershell
[Environment]::SetEnvironmentVariable("TYPESAFE_API_KEY", "<chiave>", "User")
```

Non incollare la chiave in chat e non salvarla nella repository. Per disattivare il routing automatico e la policy delegation-first:

```powershell
$env:JEV_ROUTER_DISABLED = "1"
```

## Routing dei subagenti

Il primo `UserPromptSubmit` riuscito della sessione inserisce la policy; un errore transitorio non consuma l'attivazione e i prompt successivi non la reinseriscono. Per ogni richiesta non banale che contiene lavoro descrivibile come subtask indipendente, Codex deve creare almeno un subagente instradato. Implementazione, debugging, code review, ricerca nel repository e analisi multi-step sono considerate non banali. Risposte brevi, chiarimenti, coordinamento, lavoro intrinsecamente indivisibile, runtime senza subagenti o istruzioni di priorità superiore restano nel thread principale, che mantiene coordinamento, verifica e risposta finale.

Immediatamente prima di ogni `spawn_agent`, anche annidato, Codex classifica il solo subtask corrente con `jev_route.py`. Le istruzioni degli hook usano lo stesso interprete Python con cui l'hook e' stato avviato, con quoting adatto alla piattaforma:

Il router interroga localmente `codex app-server --stdio` e usa soltanto modelli generali visibili e reasoning effort realmente supportati dall'app. Considera automaticamente le due famiglie GPT numeriche più recenti disponibili; oggi sono GPT-6 e GPT-5.6. La famiglia precedente viene scelta solo quando Jev assegna probabilità `<= 0,30` che sia insufficiente:

| Tier | Famiglia precedente, se sufficiente | Famiglia corrente, se necessaria | Effort predefinito |
|---|---|---|---|
| fast | Luna | Luna | `low` |
| balanced | Terra, altrimenti Sol | Sol | `medium` |
| deep | Sol | Sol | `high` |

Gli effort selezionabili sono `low`, `medium`, `high`, `xhigh` e `max`; `ultra` è escluso per evitare delegazione automatica e consumo non necessario. Se un livello non è supportato dal modello scelto, il router usa il successivo livello disponibile, oppure il più alto inferiore quando non ne esiste uno superiore.

Ogni subtask riceve una decisione nuova; una scelta non viene riutilizzata. Astra viene scelto soltanto per un task `deep` quando Jev assegna probabilità `> 0,70` al fatto che il Sol della famiglia corrente, anche con effort `high`, `xhigh` o `max`, non possa completarlo in modo affidabile. Il solo rischio alto aumenta l'effort almeno a `high`, senza cambiare modello o famiglia. Se la discovery locale fallisce, Jev non è disponibile, la chiave manca, l'input è sensibile o troppo grande, oppure la confidenza è insufficiente, l'output è `route=inherit` e Codex omette modello ed effort. Se Codex rifiuta un modello selezionato, il subtask viene ritentato una sola volta per ereditarietà, senza una seconda chiamata Jev.

Questa è una policy euristica orientata al risparmio di token: privilegia la coppia più leggera giudicata affidabile, ma non promette un risparmio numerico per singola richiesta perché il catalogo dell'app non espone il consumo token previsto.

Gli hook non possono cambiare il modello del thread principale. La selezione vale solo per i nuovi subagenti. `JEV_ROUTER_DISABLED=1` salta l'intera policy prima di consumare l'attivazione, quindi rimuovendo l'opt-out durante la sessione il prompt successivo può attivarla.

## Code review

La skill `jev-review` è esplicita e read-only. Esempi diretti:

```powershell
py -3 "<plugin-root>\scripts\jev_review.py" --working --json
py -3 "<plugin-root>\scripts\jev_review.py" --git main --json
py -3 "<plugin-root>\scripts\jev_review.py" --diff change.diff --title "Titolo" --description "Descrizione" --json
```

`--working` include solo file tracked staged e unstaged tramite `git diff --no-ext-diff HEAD`; gli untracked non sono aggiunti implicitamente. `--git` accetta solo riferimenti che Git risolve a un commit e rifiuta valori simili a opzioni. Una sola richiesta contiene tutti i 14 check. Il verdetto `BLOCK`, `SECURITY REVIEW`, `NITS` o `MERGE` viene calcolato localmente da `policy.json`; `merge_ready` è solo informativo. Diff vuoto produce `NO_DIFF`. Chiave assente, input sensibile, input oltre 250.000 caratteri, rete non disponibile o risposta incompleta producono `UNAVAILABLE`, mai `MERGE`.

## Checkpoint e compattazione

La skill `jev-checkpoint` mantiene:

```text
.codex/jev-checkpoints/<session-id>.md
```

Il file viene validato, confinato nel workspace anche in presenza di symlink o junction, scritto nello stesso filesystem e sostituito atomicamente. Va aggiornato dopo avanzamenti materiali, prima di comandi lunghi e prima di chiudere un turno che ha modificato file. Su `SessionStart` con sorgente `compact`, l'hook ricarica una copia limitata solo dopo averla rivalidata; checkpoint malformati o sensibili vengono ignorati.

Codex non consente a questo plugin di sostituire la compattazione nativa o di conservare verbatim l'intera trascrizione. Il checkpoint è il meccanismo di recupero supportato.

## Confine di privacy

Il router invia solo la descrizione autonoma del subtask; la review invia il diff, titolo, descrizione e lista dei file modificati. Una guard locale blocca marker ad alta confidenza come chiavi private, header `Authorization: Bearer ...` e assegnazioni di credenziali, inclusi i bearer token. È una barriera prudenziale, non uno scanner completo di segreti: controlla comunque il contenuto prima di una review esterna.

Il plugin non registra chiave, task, diff, request body o response body. I test unitari non usano rete né richiedono la chiave.
