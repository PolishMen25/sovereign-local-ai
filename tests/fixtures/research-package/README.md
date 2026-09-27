# Paquets `research-package` synthétiques

Statut : **PROVISOIRE**, comme le contrat `research-package-contract-v1` qu'ils illustrent (`docs/data/research-package-validation.md`). Tous les paquets sont inventés ; aucun ne provient d'un fournisseur réel.

| Fichiers | Rôle |
|---|---|
| `valid-*.json` | Paquets acceptés par le contrat. |
| `invalid-*.json` | Un défaut par fichier. Un défaut peut produire deux codes, par exemple `lifecycle_state` = `VALIDATED` donne `PKG_CONST_MISMATCH` et `PKG_LIFECYCLE_STATE_NOT_RAW`. |
| `flagged-*.json` | Paquets acceptés par le contrat mais signalés par `secret_scan`. Le choix entre refus à l'ingress et signalement en `PENDING` reste une décision du propriétaire. |
| `*.template.json` | Contiennent un espace réservé `{{…}}`, remplacé à l'exécution par `tests/test_contract_fixtures.py`. Les fragments en forme de secret (paramètre d'URL signée, jeton) ne sont jamais écrits dans le dépôt public. L'empreinte `integrity.package_sha256` porte sur la version développée. |
| `expected.json` | Pour chaque cas, les refus exacts attendus (code et pointeur) et, si besoin, une limite de taille `max_bytes` plus basse que la limite ordinaire. |

`tests/test_contract_fixtures.py` vérifie que chaque fichier est listé, que chaque cas donne exactement ses refus, et que chaque règle sémantique et chaque code structurel atteignable a au moins une fixture invalide. `tests/test_fixture_hygiene.py` vérifie que tout `tests/fixtures` ne contient aucun secret détectable et que les noms, adresses e-mail et adresses IP sont réservés à la documentation (RFC 2606, RFC 6761, RFC 5737, RFC 3849).

Conséquence : aucune adresse privée RFC 1918 ne peut figurer ici. Le cas « IP littérale » utilise une adresse de documentation, refusée avec `URL_IP_RESERVED` ; `URL_IP_PRIVATE` reste couvert par le test tabulaire de `tests/test_url_policy.py`, hors de `tests/fixtures`.

Pour modifier une fixture, recalculer l'empreinte canonique puis la reporter dans `integrity.package_sha256` (sur la version développée pour un gabarit) et mettre à jour `expected.json` :

```text
python -B services/quarantine/canonical_json.py --scope package fichier.json
python -B services/quarantine/research_package.py fichier.json
```
