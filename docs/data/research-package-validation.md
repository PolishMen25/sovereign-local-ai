# Validation d'un paquet `research-package` 0.1.0

> Statut : **PROVISOIRE**. Contrat candidat `research-package-contract-v1` pour l'issue #6, rédigé avant l'ADR du Research Gateway. Il n'est câblé à aucune route, aucun service et aucun port ; aucun gestionnaire HTTP ne l'importe. Sa publication comme contrat attend une décision du propriétaire. Le registre `docs/project/decisions.md` n'est pas modifié.

Ce document précise la phrase de `docs/data/provenance-and-lifecycle.md` : « le Collector doit […] vérifier côté application : UUID et horodatages, ordre temporel, unicité des identifiants, existence des sources citées, bornes et ordre des offsets, cohérence des tokens, empreintes et URLs ». Il est implémenté, sans dépendance tierce, par `services/quarantine/research_package.py` et vérifié par `tests/test_research_package_contract.py`.

## Principes

- **Refuser, jamais corriger.** Le validateur ne modifie pas le paquet. Le RAW reste identique aux octets reçus.
- **Codes seulement.** Chaque refus est un couple (code, pointeur JSON RFC 6901). Le pointeur n'est construit qu'avec des noms du schéma et des indices de tableau : un membre inconnu est signalé sur son objet parent, sans recopier son nom. Aucune valeur, URL ou partie de texte n'apparaît dans un résultat, une exception ou la sortie de la ligne de commande.
- **Deux couches.** Une couche structurelle reproduit le schéma ; une couche sémantique applique les règles que le schéma ne peut pas exprimer.
- **Bornes.** Un tableau qui dépasse son `maxItems` est signalé et n'est pas parcouru. Au plus 100 refus sont rendus : jusqu'à 100 refus distincts, tous figurent ; au-delà, 99 sont gardés et le dernier est `PKG_TOO_MANY_FINDINGS`.
- **Aucun réseau.** Le module n'ouvre aucune socket et ne résout aucun nom ; un test le vérifie.

## Couche structurelle : miroir du schéma

`services/quarantine/research_package.py` embarque un miroir littéral de `schemas/research-package.schema.json`. L'interpréteur partagé `services/quarantine/closed_schema.py` n'accepte qu'un sous-ensemble fermé de mots-clés Draft 2020-12 (`type`, `const`, `enum`, `pattern`, `format`, bornes de longueur, de valeur et de taille, `uniqueItems`, `items`, `properties`, `additionalProperties: false`, `required`, `dependentRequired`, `oneOf`, `allOf`, `if`/`then`/`else`, `$ref` local). Un miroir qui utiliserait un autre mot-clé est refusé au chargement.

Le test de parité compare le miroir au fichier de schéma, annotations (`title`, `description`, `$id`, `$schema`) retirées : toute divergence de `required`, `const`, `enum`, `maxItems` ou de toute autre contrainte fait échouer la suite. Le miroir évite de lire et d'interpréter un fichier au démarrage du service.

Écarts délibérés avec Draft 2020-12, tous plus stricts :

| Point | Draft 2020-12 | Validateur |
|---|---|---|
| `integer` | accepte `1.0` | exige un entier JSON sans partie décimale |
| `number` | — | refuse NaN et les infinis (entrée déjà analysée) |
| `format` | annotation par défaut | assertion (`uuid`, `date-time`) ; `uri` est délégué à la politique URL |
| `date-time` | RFC 3339 | RFC 3339 avec `T` et `Z` majuscules, décalage obligatoire, 1 à 9 décimales, seconde intercalaire `:60` refusée (HYPOTHÈSE de simplicité) |
| `pattern` | ECMA-262 | `$` ne correspond qu'à la fin exacte, comme en ECMA-262 (le `$` de Python accepterait un saut de ligne final) |

Le choix entre ce validateur stdlib et une dépendance `jsonschema` de test reste ouvert (OUVERT, décision du propriétaire).

### Codes structurels

| Code | Refus |
|---|---|
| `PKG_FIELD_UNKNOWN` | Membre absent du schéma (signalé sur l'objet parent). |
| `PKG_FIELD_MISSING` | Membre requis absent. |
| `PKG_FIELD_FORBIDDEN` | Membre interdit par un sous-schéma `false` (inutilisé par ce schéma, commun aux contrats). |
| `PKG_FIELD_DEPENDENCY_MISSING` | `dependentRequired` : `amount`, `currency` et `estimated` vont ensemble ; `response_start` et `response_end` aussi. |
| `PKG_TYPE_MISMATCH` | Type JSON inattendu, dont un booléen à la place d'un entier. |
| `PKG_CONST_MISMATCH` | Valeur différente d'un `const` (`schema_version`, `lifecycle_state`, `integrity.*`, `producer_secret_scan_status`). |
| `PKG_ENUM_MISMATCH` | Valeur hors énumération. |
| `PKG_STRING_TOO_SHORT`, `PKG_STRING_TOO_LONG` | Longueur hors bornes, comptée en points de code. |
| `PKG_PATTERN_MISMATCH` | Motif non respecté : empreinte en majuscules, nom de fichier avec `/`, nom de paramètre évoquant un secret, URL non `https://`… |
| `PKG_UUID_INVALID` | `package_id` hors forme 8-4-4-4-12 hexadécimale. |
| `PKG_TIMESTAMP_INVALID` | Horodatage hors profil RFC 3339 ci-dessus. |
| `PKG_NUMBER_NOT_FINITE` | NaN ou infini dans un document déjà analysé. |
| `PKG_NUMBER_BELOW_MINIMUM`, `PKG_NUMBER_ABOVE_MAXIMUM` | Nombre hors bornes. |
| `PKG_ARRAY_TOO_SHORT`, `PKG_ARRAY_TOO_LONG` | Taille de tableau hors bornes ; un tableau trop long n'est pas parcouru. |
| `PKG_ARRAY_DUPLICATE_ITEM` | Doublon dans `redacted_categories`. |
| `PKG_ONE_OF_MISMATCH` | Valeur de paramètre de génération qui n'est ni un scalaire ni une liste de scalaires. |
| `PKG_TOO_MANY_FINDINGS` | Plafond de 100 refus dépassé (plus de 100 refus distincts). |

## Couche sémantique

| Code | Règle | Pointeur |
|---|---|---|
| `PKG_LIFECYCLE_STATE_NOT_RAW` | Un producteur ne déclare que `RAW`. `PENDING`, `VALIDATED` ou toute autre valeur est refusée, en plus de `PKG_CONST_MISMATCH`. Les états suivants n'existent que dans le journal d'événements (`docs/data/lifecycle-events.md`). | `/lifecycle_state` |
| `PKG_TIMESTAMP_ORDER` | Ordre candidat : `request_started_at` ≤ `response_completed_at` ≤ `collected_at` ≤ `created_at`, comparés en UTC à la nanoseconde. L'égalité est admise. | le second horodatage de la paire fautive |
| `PKG_DUPLICATE_ID` | Unicité de `sources[].source_id`, `citations[].citation_id`, `attachments[].attachment_id` et `generation_parameters[].name`. | la deuxième occurrence |
| `PKG_CITATION_SOURCE_UNKNOWN` | Chaque `citations[].source_id` désigne une source déclarée. | `/citations/i/source_id` |
| `PKG_CITATION_OFFSET_ORDER` | `response_start` ≤ `response_end`. | `/citations/i/response_start` |
| `PKG_CITATION_OFFSET_RANGE` | `response_end` ≤ longueur de `response.text` en **points de code** (et non en unités UTF-16 ni en octets). | `/citations/i/response_end` |
| `PKG_USAGE_CACHED_EXCEEDS_INPUT` | `cached_input_tokens` ≤ `input_tokens`. | `/usage/cached_input_tokens` |
| `PKG_USAGE_REASONING_EXCEEDS_OUTPUT` | `reasoning_tokens` ≤ `output_tokens`. | `/usage/reasoning_tokens` |
| `PKG_USAGE_TOTAL_BELOW_SUM` | `total_tokens` ≥ `input_tokens` + `output_tokens`. | `/usage/total_tokens` |
| `PKG_SYSTEM_PROMPT_SHA256_MISMATCH` | `controlled_system_prompt.sha256` = SHA-256 des octets UTF-8 de son `text`. | `/request/controlled_system_prompt/sha256` |
| `PKG_INTEGRITY_MISMATCH` | `integrity.package_sha256` = empreinte RFC 8785 du paquet hors `integrity` (portée `canonical-package-excluding-integrity`, `docs/data/canonical-hashing.md`). | `/integrity/package_sha256` |

Les règles d'usage ne comparent que les compteurs présents. Elles supposent une convention de normalisation (HYPOTHÈSE, PROPOSÉ) : `input_tokens` inclut les tokens servis depuis un cache et `output_tokens` inclut les tokens de raisonnement. Certains fournisseurs les comptent à part ; le producteur doit alors les additionner avant soumission. Cette convention doit être confirmée par le propriétaire avec l'ADR du Research Gateway.

L'ordre des horodatages est lui aussi une proposition : il suppose que le paquet est créé après la collecte. `published_at`, `retrieved_at`, `scanned_at` et `occurred_at` ne sont contrôlés que dans leur format. `quoted_text_sha256` n'est pas recalculé, car l'extrait cité appartient à la source et non à la réponse (OUVERT).

### Empreintes et octets

- `evaluate_bytes` analyse d'abord le corps avec le profil strict de `canonical_json.loads_strict`. Un refus y rend un seul code `JSON_*` (`JSON_DUPLICATE_KEY`, `JSON_NON_FINITE_NUMBER`, `JSON_BOM_REFUSED`, `JSON_SIZE_EXCEEDED`, etc.) et arrête la validation.
- Sur un document déjà analysé, une valeur que la RFC 8785 ne peut pas représenter (entier hors ±(2⁵³ − 1), substitut isolé, NaN) empêche le calcul de l'empreinte et produit le code `JSON_*` correspondant au pointeur racine.
- L'empreinte d'ingress (octets reçus) n'est pas vérifiable ici : elle appartient au reçu du Collector.

### URL déclarées

Chaque `sources[].url` et `attachments[].source_url` passe par `url_policy.evaluate_url` (`docs/security/url-ssrf-policy.md`). Les codes `URL_*` sont rendus tels quels au pointeur de l'URL. Le motif `^https://` du schéma produit en outre `PKG_PATTERN_MISMATCH` pour une URL non HTTPS. Les contrôles DNS, redirections et rebinding restent au composant qui déréférence les URL.

## Hors périmètre

- **Analyse de secrets.** `secret_scan` (`collector-secret-scan-v1`) n'est pas appliqué ici : le choix entre refus à l'ingress et signalement en `PENDING`, par catégorie, est une décision du propriétaire. Le composant désigné par l'ADR du Research Gateway (OUVERT) devra combiner les deux résultats selon la politique refus/signalement du propriétaire (OUVERT).
- **Câblage.** Aucune route `submit_research_package` n'existe ; elle dépend de l'ADR du Research Gateway.
- **Horloge.** Aucune comparaison avec l'heure de réception : `received_at` appartient au reçu et au journal.

## Exemples synthétiques

`tests/fixtures/research-package/` contient des paquets synthétiques valides et au moins un paquet invalide par règle sémantique et par code structurel atteignable, avec les refus exacts attendus dans `expected.json`. Les fragments en forme de secret n'y figurent que comme espaces réservés, développés à l'exécution par `tests/test_contract_fixtures.py`.

## Utilisation locale

```text
python -B services/quarantine/research_package.py paquet.json
```

La sortie est un objet JSON canonique `{"findings", "policy_id", "schema_version", "valid"}` où chaque refus est `{"code", "pointer"}`. Code de sortie : 0 si le paquet est valide, 1 s'il est refusé, 2 si le fichier est illisible.
