# Arène des agents

Service `sovereign-arena` dans le sas (CT 101). Les profils d'agents (auteurs et
relecteurs) s'affrontent sur les tâches de `configs/evaluation/core-python-e2.candidate.json`.
**Seuls les tests de la tâche, exécutés dans le sandbox bwrap hors réseau, décident** ;
aucun modèle ne note sa propre réponse.

## Ce que fait l'arène

- Match : deux auteurs résolvent la même tâche ; un échec passe par un relecteur,
  puis l'auteur tente une seule correction. 1 point du premier coup, 0,6 après
  correction, 0 sinon ; Elo en tête-à-tête.
- Évolution : tous les 12 matchs, le meilleur auteur (au moins 4 matchs) engendre
  une variante dont les instructions sont réécrites à partir de ses échecs ; au-delà
  de 6 auteurs, le plus faible vétéran (au moins 8 matchs) prend sa retraite.
- Paquets : toutes les 50 solutions validées, un paquet `arena-*` est écrit dans
  `/var/lib/sovereign-arena/packets/` avec manifeste et SHA-256. Il reste
  `awaiting_owner_approval` (ou `flagged` si unicité < 80 % ou répétition > 5 %).
  **Aucun paquet n'est promu ni utilisé pour l'entraînement sans approbation.**
- Pause automatique quand un moteur sert déjà une requête (`/slots` de llama.cpp),
  budget de 12 matchs par heure par défaut.

## Séparation des droits

| Élément | Propriétaire | Accès |
|---|---|---|
| `/var/lib/sovereign-arena` (base, paquets) | `sovereign-arena:sovereign`, 2750 | la passerelle lit (groupe), n'écrit jamais |
| `/var/lib/sovereign-arena/inbox` | `sovereign-arena:sovereign`, 2770 | la passerelle y dépose les approbations (0640) |
| `/var/lib/sovereign-gateway` | `sovereign`, 0700 | l'arène n'y a pas accès |

Le code candidat s'exécute sous `sovereign-arena` dans bwrap (`--unshare-all
--unshare-net`, seul le dossier de travail monté), avec les limites de
`tools/run_code_evaluation.py` (10 s CPU, 512 Mio, 64 Mio de sortie).

## Configuration

`/opt/sovereign/credentials/arena.env` (0640 `root:sovereign`, hors Git) :

```
SOVEREIGN_QWEN_TOKEN=<clé acceptée par CT 103>
SOVEREIGN_QWEN_ENDPOINT=http://192.168.0.144:8790
SOVEREIGN_BOOTSTRAP_ENDPOINT=http://127.0.0.1:8080
SOVEREIGN_ARENA_MAX_MATCHES_PER_HOUR=12
```

Sans jeton Qwen, l'arène tourne avec les seuls profils BOOTSTRAP.

## Page

`https://<sas>/arena` (session du chat requise) : classement Elo avec évolution,
fil des matchs en direct (code, sorties de tests, conseils), lignée des agents,
paquets et boutons d'approbation.
