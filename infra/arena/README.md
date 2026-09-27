# Arène des agents

Service `sovereign-arena` dans le conteneur du sas. Les profils d'agents (auteurs et
relecteurs) s'affrontent sur les tâches de la suite désignée par
`SOVEREIGN_ARENA_SUITE` ; sans cette variable, la suite d'entraînement
`configs/arena/practice-suite.v1.json` (voir
[Suite de tâches et jeu scellé](#suite-de-tâches-et-jeu-scellé)).
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

## Suite de tâches et jeu scellé

Le runner lit la suite désignée par `SOVEREIGN_ARENA_SUITE`, un chemin relatif
au répertoire de travail du service. Sans cette variable, il charge la suite
d'entraînement `configs/arena/practice-suite.v1.json`. Le jeu d'évaluation E2
`configs/evaluation/core-python-e2.candidate.json` est un benchmark scellé : il
n'est jamais un défaut et ne se joue que par un choix explicite.

Jusqu'au commit `db9414d` inclus, le runner et
`tools/build_core_increment_from_arena.py` prenaient E2 par défaut, et ni
l'unité `sovereign-arena.service` ni l'exemple `arena.env` ci-dessous ne fixent
cette variable. L'arène n'est attestée en service que par `AGENTS.md` (composant
sans décision au registre, D-038) et par des messages de commit ; rien n'a été
revérifié. La suite qu'elle joue ne se déduit pas du dépôt : elle doit être
relevée sur l'hôte avant toute conclusion.

Le passage d'un paquet au corpus garde une seconde barrière.
`tools/build_core_increment_from_arena.py` refuse une suite de schéma
`core-code-evaluation-suite.v1`, une suite contenant un identifiant de tâche
`python-NN-` et un paquet contenant une solution pour une telle tâche ; il
inscrit l'empreinte SHA-256 de la suite utilisée dans le manifeste d'incrément
(`task_suite_sha256`). 14 tâches de la suite d'entraînement reprennent le nom de
fonction d'une tâche E2, avec un énoncé reformulé ; elles sont listées dans
`tests/test_arena_practice_suite.py`. D-040 n'admet les données de l'arène que
sans recouvrement avec les jeux d'évaluation : le constructeur refuse donc tout
paquet contenant une solution pour l'une d'elles, en lisant les noms de fonction
dans la suite E2 versionnée (illisible ⇒ refus). Le traitement d'E2 lui-même
reste une décision ouverte du propriétaire, décrite dans la
[grille d'évaluation V1 proposée](../../docs/model/v1-evaluation-grid.md#séparation-évaluation--entraînement).
Une paraphrase sous un autre nom de fonction échappe à ces contrôles ;
`tools/check_evaluation_contamination.py` l'approche.

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
SOVEREIGN_QWEN_TOKEN=<clé acceptée par le conteneur Qwen>
SOVEREIGN_BOOTSTRAP_ENDPOINT=http://127.0.0.1:8080
SOVEREIGN_ARENA_MAX_MATCHES_PER_HOUR=12
```

Sans jeton Qwen, l'arène tourne avec les seuls profils BOOTSTRAP. Avec un jeton,
l'adresse du moteur Qwen vient uniquement du fichier privé
`/etc/sovereign-endpoints/private-endpoints.json` (D-036, contrat
`schemas/private-endpoints.schema.json`, nom `qwen_coder`), désigné par
`SOVEREIGN_PRIVATE_ENDPOINTS_FILE` dans l'unité. Sans fichier valide, l'arène
refuse de démarrer et affiche `engine_configuration_refused`. L'ancienne
variable `SOVEREIGN_QWEN_ENDPOINT` est facultative ; si elle reste présente, elle
doit être strictement identique à l'adresse épinglée. Les moteurs BOOTSTRAP et
14B restent sur la boucle locale. Voir
`docs/operations/private-endpoints-migration.md`.

Variables lues par `services/arena/runner.py` (et `services/arena/status.py`
pour la dernière) :

| Variable | Défaut | Rôle |
|---|---|---|
| `SOVEREIGN_ARENA_STATE` | répertoire d'état du code, fixé aussi par l'unité | base SQLite, paquets et boîte d'approbations |
| `SOVEREIGN_ARENA_INBOX` | `inbox/` sous le répertoire d'état | approbations déposées par la passerelle |
| `SOVEREIGN_ARENA_SUITE` | `configs/arena/practice-suite.v1.json` | suite de tâches jouée ; E2 seulement par choix explicite |
| `SOVEREIGN_ARENA_PACKET_SIZE` | `50` | solutions validées par paquet |
| `SOVEREIGN_ARENA_EVOLVE_EVERY` | `12` | matchs entre deux évolutions |
| `SOVEREIGN_ARENA_MAX_MATCHES_PER_HOUR` | `12` | budget horaire de matchs |
| `SOVEREIGN_BOOTSTRAP_ENDPOINT` | boucle locale, port 8080 | moteur BOOTSTRAP |
| `SOVEREIGN_QWEN_TOKEN` | vide | active QWEN-CODER à partir de 32 caractères |
| `SOVEREIGN_PRIVATE_ENDPOINTS_FILE` | aucun : requis dès qu'un jeton Qwen est fourni | fichier privé hors Git qui épingle le moteur QWEN-CODER (D-036) |
| `SOVEREIGN_QWEN_ENDPOINT` | adresse épinglée du fichier privé | facultative ; si présente, strictement identique à l'épingle |
| `SOVEREIGN_CHAT14B_ENDPOINT` | vide : relecteur CHAT-14B absent | moteur CHAT-14B |
| `SOVEREIGN_ARENA_DB` | `arena.sqlite3` sous le répertoire d'état par défaut, sans suivre `SOVEREIGN_ARENA_STATE` | base lue en lecture seule par l'outil d'état |

## Page

`https://<sas>/arena` (session du chat requise) : classement Elo avec évolution,
fil des matchs en direct (code, sorties de tests, conseils), lignée des agents,
paquets et boutons d'approbation.
