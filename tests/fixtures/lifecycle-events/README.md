# Journaux d'événements de cycle de vie synthétiques

Statut : **PROVISOIRE**, comme la relecture `lifecycle-event-replay-v1` qu'ils illustrent (`docs/data/lifecycle-events.md`). Aucun journal réel n'existe ; ces fichiers sont inventés.

- Chaque fichier est un journal JSONL : un événement par ligne, dans l'ordre d'ajout.
- `valid-*.jsonl` se rejoue entièrement ; `expected.json` donne le nombre d'événements appliqués, les doublons identiques ignorés et l'état final de chaque sujet.
- `invalid-*.jsonl` est refusé au premier événement fautif ; `expected.json` donne ses codes et l'indice de cet événement. Un même fichier peut servir à plusieurs cas, par exemple avec une borne `max_events` plus basse.
- Identifiants : UUID de compteur, empreintes SHA-256 d'étiquettes fixes, acteurs désignés par un rôle technique (`collector-ingress`, `quarantine-validator`, `owner-review`).

`tests/test_contract_fixtures.py` vérifie chaque cas et que chaque règle d'événement ou de relecture a au moins un journal invalide ; `tests/test_fixture_hygiene.py` vérifie l'absence de secret et de valeur non réservée.

Les événements d'un sujet sont chaînés par empreinte RFC 8785 : modifier un événement oblige à recalculer `previous_event_sha256` des événements suivants du même sujet (`lifecycle.event_sha256`). Relecture locale :

```text
python -B services/quarantine/lifecycle.py fichier.jsonl
```
