# Mémoire conversationnelle privée

`MemoryStore` conserve localement les conversations après masquage des secrets
probables. Chaque message reçoit un SHA-256 et un ordinal stable. L'export
retourne le contenu privé authentifié ; la suppression efface les messages et
ne conserve qu'un reçu d'audit sans contenu.

Le chemin SQLite est fixé par l'opérateur et n'est jamais fourni par une
requête. Cette mémoire n'est ni un corpus d'entraînement ni une connaissance
validée. Aucune opération ne promeut une conversation vers `VALIDATED`.

## Sauvegarde durable

`tools/backup_conversation_memory.py` est un outil opérateur, jamais exposé
par HTTP ou MCP. Il réalise une copie SQLite cohérente malgré le journal WAL,
génère un manifeste sans contenu (nom d'artefact, taille et SHA-256), vérifie
l'artefact puis restaure uniquement après cette vérification. Les destinations
restent des chemins fixés par l'opérateur ; une restauration vers une base en
service doit être précédée d'un arrêt contrôlé du service concerné.

```bash
python3 -B tools/backup_conversation_memory.py backup \
  --source /var/lib/sovereign-gateway/memory.sqlite3 \
  --destination-directory /mnt/sovereign-memory/backups
```

Le montage durable de la passerelle et son ordonnanceur restent une opération
de déploiement distincte. Une conversation ne devient jamais un corpus
d'entraînement par cette sauvegarde.

La primitive de copie SQLite accepte aussi un préfixe et un schéma de manifeste
spécifiques pour un autre artefact local, afin de ne jamais confondre une
sauvegarde de mémoire et une sauvegarde de catalogue RAG. Le seul consommateur
actuel est l'outil opérateur `backup_knowledge_index.py` ; aucun de ces outils
n'est exposé par HTTP ou MCP.
