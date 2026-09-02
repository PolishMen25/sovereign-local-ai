# Mémoire conversationnelle privée

`MemoryStore` conserve localement les conversations après masquage des secrets
probables. Chaque message reçoit un SHA-256 et un ordinal stable. L'export
retourne le contenu privé authentifié ; la suppression efface les messages et
ne conserve qu'un reçu d'audit sans contenu.

Le chemin SQLite est fixé par l'opérateur et n'est jamais fourni par une
requête. Cette mémoire n'est ni un corpus d'entraînement ni une connaissance
validée. Aucune opération ne promeut une conversation vers `VALIDATED`.

