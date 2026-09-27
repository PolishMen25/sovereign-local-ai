# Artefacts dérivés et lignée

> Statut : **PROVISOIRE**. Contrat candidat pour l'issue #6 (schéma `derived-artifact` 0.1.0, contrôle `derived-artifact-lineage-v1`), rédigé avant l'ADR du Research Gateway. Il n'est câblé à aucune route, aucun service et aucun port ; aucun enregistrement réel n'est produit. Sa publication comme contrat attend une décision du propriétaire. Le registre `docs/project/decisions.md` n'est pas modifié.

`docs/data/provenance-and-lifecycle.md` exige qu'une transformation produise « un nouvel artefact avec les identifiants et empreintes des parents, le type et la version de la transformation, l'identité du service ou de l'opérateur, les horodatages, les paramètres non secrets et l'empreinte du résultat », et que les artefacts dérivés disposent d'un schéma append-only séparé. Ce document spécifie ce schéma : `schemas/derived-artifact.schema.json` (Draft 2020-12, fermé partout par `additionalProperties: false`), implémenté sans dépendance tierce par `services/quarantine/lineage.py` et vérifié par `tests/test_derived_artifacts.py`. Les changements d'état restent dans le journal de cycle de vie (`docs/data/lifecycle-events.md`).

## Principes

- **Un dérivé est un nouvel artefact.** Masquer, nettoyer, résumer, traduire, découper, calculer des embeddings ou indexer ne modifie jamais un parent. Le RAW reste identique aux octets reçus.
- **Aucun contenu.** Un enregistrement ne porte que des identifiants, des empreintes, un type de transformation, des paramètres non secrets et des horodatages : ni texte, ni extrait, ni URL, ni chemin. Les octets du résultat sont stockés à part, sous leur empreinte.
- **Remontée jusqu'au RAW.** Tout dérivé cohérent se remonte, de parent en parent, jusqu'aux empreintes RAW dont il provient.
- **Refus sûrs.** Chaque refus est un couple (code, pointeur JSON). Le pointeur n'est construit qu'avec l'indice de l'enregistrement, des noms du schéma et des indices de tableau ; aucune valeur n'est recopiée dans un résultat, une exception ou la sortie de la ligne de commande.
- **Aucun réseau, aucune écriture.** Le module n'ouvre aucune socket, n'écrit aucun fichier et ne lit jamais les octets d'un artefact ; des tests le vérifient.

## Champs

| Champ | Contenu |
|---|---|
| `schema_version` | `0.1.0`. |
| `artifact_id` | Identifiant stable du dérivé, motif `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. |
| `parents` | 1 à 4 096 références `{artifact_kind, artifact_id, sha256, role}`. |
| `transformation` | `{type, version, parameters}` ; au plus 64 paramètres `{name, value}`. |
| `actor` | `{kind, id}` : `internal_service` ou `operator`, identifiant technique non nominatif. |
| `started_at`, `completed_at` | RFC 3339 avec décalage ; `started_at` ≤ `completed_at`. |
| `result` | `{content_sha256, byte_size, media_type}` : empreinte et taille (1 octet à 1 Tio) des octets produits. |
| `replaces` | Facultatif : `{artifact_kind, artifact_id, sha256}` de l'artefact que ce dérivé corrige. |

Le Collector et les producteurs externes ne dérivent jamais : le type d'acteur `collector` n'est pas admis et `producer` n'existe pas. Les bornes de 4 096 parents, 64 paramètres et 1 024 caractères par valeur sont des HYPOTHÈSES à confirmer sur des volumes réels.

### Parents

Un parent est désigné comme un sujet du journal de cycle de vie :

- un artefact RAW d'ingress (`research_package`, `conversation`, `conversation_revision`), dont `sha256` est le `subject_sha256` du journal (octets reçus) ;
- un autre dérivé (`derived_artifact`), dont `sha256` est le `result.content_sha256` de son enregistrement.

`role` vaut `primary` pour le contenu transformé, `supporting` pour une entrée auxiliaire qui influence le résultat sans être transformée (liste de masquage, glossaire…). Au moins un parent est `primary`. La distinction des rôles est une proposition (PROPOSÉ).

### Transformations

| `type` | Sens |
|---|---|
| `redact` | Masquage de données personnelles ou sensibles. |
| `clean` | Nettoyage ou normalisation (Unicode, balisage, doublons). |
| `summarize` | Résumé d'un ou plusieurs parents. |
| `translate` | Traduction. |
| `chunk` | Découpage en fragments pour l'indexation. |
| `embed` | Calcul d'embeddings sur des fragments. |
| `index` | Construction d'un index à partir d'embeddings ou de fragments. |

`version` identifie l'implémentation (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`). Ajouter un type exige une nouvelle version du schéma. L'extraction de texte d'une pièce jointe binaire (PDF, image) n'a pas encore de type (OUVERT).

### Paramètres non secrets

- Le nom suit exactement le motif de `generationParameter` du paquet de recherche : minuscules, 64 caractères au plus, et refus de tout nom contenant `api_key`, `access_token`, `refresh_token`, `auth`/`authorization`, `password`, `passwd`, `secret`, `credential`, `cookie` ou `private_key` (séparateurs `_` ou `-`). Le filtre est volontairement large : `author` est refusé aussi. Un test garde les deux motifs identiques.
- La valeur est un scalaire JSON (chaîne de 1 024 caractères au plus, nombre fini, booléen ou `null`).
- Chaque valeur texte passe par `secret_scan` (`collector-secret-scan-v1`). Toute catégorie détectée refuse l'enregistrement, sauf `SECRET_MIXED_TOKEN`, heuristique de faible précision qui se déclenche aussi sur des noms de modèle ordinaires. Ce choix ne concerne que les métadonnées internes de lignée ; il ne préjuge pas de la politique refus/signalement à l'ingress, qui reste une décision du propriétaire (PROPOSÉ).

### Remplacement

`replaces` documente qu'un dérivé corrige un autre artefact, dérivé ou RAW : un résumé corrigé remplace l'ancien résumé, un paquet nettoyé peut remplacer le paquet d'origine pour les usages courants. Le changement d'état lui-même reste un événement `STATE_TRANSITION` vers `SUPERSEDED` du journal, avec `superseded_by` égal au sujet du nouveau dérivé. La cohérence entre ce lien et l'événement n'est pas vérifiée ici (OUVERT, à traiter avec l'écrivain du journal).

Un remplaçant est toujours plus récent que ce qu'il remplace, comme un dérivé l'est de ses parents. Les liens `replaces` entrent donc dans la détection de cycles, mais pas dans la remontée vers le RAW : remplacer n'est pas dériver.

## Lien avec le journal de cycle de vie

- Le sujet d'un dérivé dans le journal est `(derived_artifact, artifact_id, result.content_sha256)` (`subject_key`). Il est enregistré par un événement `DERIVED_RECORDED` émis par un service interne ou un opérateur.
- Les racines RAW connues se déduisent d'un journal rejoué (`roots_from_replay`) : tout sujet d'ingress accepté compte, quel que soit son état ultérieur, car `REJECTED`, `SUPERSEDED` et `ARCHIVED` ne suppriment pas le RAW. Un sujet `REJECTED_AT_INGRESS` n'a jamais été stocké : il ne peut pas être parent.
- Le contrôle ne vérifie pas encore que chaque enregistrement de lignée a son événement `DERIVED_RECORDED` (OUVERT, à traiter avec l'écrivain du journal).

## Correspondance avec le manifeste de corpus

Le manifeste `training-corpus-manifest` 0.2.0 porte, pour chaque entrée de `source_packages[]`, un `package_id`, un `provenance_id` et un `content_sha256`. Correspondance proposée (PROPOSÉ) :

| Manifeste | Lignée |
|---|---|
| `provenance_id` | `artifact_id` du nœud de lignée dont le contenu entre dans le corpus : un dérivé (typiquement `redact` ou `clean`) ou, sans transformation, l'artefact RAW lui-même. Le motif d'identifiant est le même ; un test garde les deux motifs identiques. |
| `content_sha256` | `result.content_sha256` de ce dérivé, ou `subject_sha256` du RAW. |
| `package_id` | Identifiant d'une racine RAW atteinte par `raw_roots(provenance_id)`. |
| `review_state` | Ne se déduit pas de la lignée : il relève d'une décision journalisée (`VALIDATED`) et de l'approbation du corpus. |

Constat, sans décision : `tools/materialize_training_corpus.py` reçoit aujourd'hui `provenance_id` de sa spécification sans contrôle de lignée et calcule `content_sha256` sur les octets de l'archive source ; `tools/validate_training_corpus_manifest.py` ne contrôle que le motif de `provenance_id`. Les archives de corpus ne sont pas un type d'artefact du journal (seuls `research_package`, `conversation`, `conversation_revision` et `derived_artifact` existent). Les rattacher demanderait un nouveau type et une nouvelle version des deux schémas (OUVERT). Aucun outil n'est modifié ici. Les `provenance_id` de l'index de connaissances (`upload:…`, `manifest-sha256:…`) forment un autre espace de noms, hors de ce contrat.

## Codes de refus

Codes propres à un enregistrement isolé (pointeur relatif à l'enregistrement) :

| Code | Refus |
|---|---|
| `LINEAGE_TIME_ORDER` | `completed_at` antérieur à `started_at` (comparaison en UTC). |
| `LINEAGE_SELF_PARENT` | Un parent `derived_artifact` porte l'`artifact_id` de l'enregistrement lui-même. |
| `LINEAGE_DUPLICATE_PARENT` | Même parent (type, identifiant, empreinte) cité deux fois. |
| `LINEAGE_NO_PRIMARY_PARENT` | Aucun parent de rôle `primary`. |
| `LINEAGE_PARAMETER_NAME_SECRET` | Nom de paramètre évoquant un secret, quelle que soit la casse (s'ajoute à `LINEAGE_PATTERN_MISMATCH`). |
| `LINEAGE_PARAMETER_VALUE_SECRET` | Valeur de paramètre où `secret_scan` détecte une catégorie autre que `SECRET_MIXED_TOKEN`. |
| `LINEAGE_DUPLICATE_PARAMETER` | Nom de paramètre répété. |
| `LINEAGE_REPLACES_SELF` | `replaces` désigne l'enregistrement lui-même. |

S'y ajoutent les codes structurels génériques de l'interpréteur partagé (`LINEAGE_FIELD_UNKNOWN`, `LINEAGE_FIELD_MISSING`, `LINEAGE_TYPE_MISMATCH`, `LINEAGE_CONST_MISMATCH`, `LINEAGE_ENUM_MISMATCH`, `LINEAGE_PATTERN_MISMATCH`, `LINEAGE_TIMESTAMP_INVALID`, `LINEAGE_ARRAY_TOO_SHORT`, `LINEAGE_ARRAY_TOO_LONG`, `LINEAGE_ONE_OF_MISMATCH`, etc., décrits avec le préfixe `PKG_` dans `docs/data/research-package-validation.md`) et les codes `JSON_*` du profil strict.

Codes d'un ensemble d'enregistrements (pointeur préfixé par l'indice de l'enregistrement, par exemple `/3/parents/0/sha256`) :

| Code | Refus |
|---|---|
| `LINEAGE_ARTIFACT_ID_CONFLICT` | Même `artifact_id` avec un contenu différent ; un doublon identique est ignoré (reprise idempotente). |
| `LINEAGE_PARENT_UNKNOWN` | Parent absent des racines RAW connues ou des enregistrements valides. |
| `LINEAGE_PARENT_HASH_MISMATCH` | Parent connu dont l'empreinte déclarée diffère. |
| `LINEAGE_REPLACES_UNKNOWN` | Cible de `replaces` inconnue. |
| `LINEAGE_REPLACES_HASH_MISMATCH` | Cible de `replaces` connue dont l'empreinte diffère. |
| `LINEAGE_CYCLE` | Enregistrement pris dans un cycle de parents ou de remplacements. |
| `LINEAGE_ARTIFACT_UNKNOWN` | Remontée demandée pour un dérivé absent d'une lignée cohérente. |
| `LINEAGE_LIMIT_EXCEEDED` | Plus de 1 000 000 d'enregistrements ou de 4 000 000 de références de parents (bornes HYPOTHÈSE). |

Un enregistrement refusé pour lui-même est exclu du graphe : ses enfants signalent alors `LINEAGE_PARENT_UNKNOWN`. Au plus 100 refus sont rendus ; au-delà, le dernier est `LINEAGE_TOO_MANY_FINDINGS`. Seul un ensemble sans aucun refus donne un graphe que l'on peut remonter.

## Hors périmètre

- **Écriture.** Aucun enregistrement n'est produit ni stocké ; le module ne sait que vérifier et remonter.
- **Contenu.** Le contrôle ne relit pas les octets des parents ou du résultat et ne recalcule donc aucune empreinte : il vérifie la cohérence des empreintes déclarées entre elles et avec le journal.
- **Chemins existants.** Les outils de corpus, d'arène et d'index écrivent déjà des artefacts sans enregistrement de lignée ; leur raccordement n'est pas traité ici.
- **Retrait d'une source.** La lignée permettra de retrouver tous les dérivés d'un RAW retiré, mais la procédure de retrait reste à écrire.

## Utilisation locale

```text
python -B services/quarantine/lineage.py derives.jsonl --journal journal.jsonl
python -B services/quarantine/lineage.py derives.jsonl --journal journal.jsonl --walk drv-index-0001
```

Les deux fichiers sont lus avec le profil JSON strict, un objet par ligne. Le journal est d'abord rejoué ; ses racines RAW servent au contrôle. Sans `--walk`, la sortie est `{"duplicates_ignored", "findings", "policy_id", "records_checked", "schema_version", "valid"}`. Avec `--walk`, une lignée cohérente donne `{"artifact_id", "policy_id", "raw_roots"}` ; une lignée incohérente donne ses refus. Un journal ou un fichier refusé donne `{"refused": "journal" | "records" | "walk", "reasons", …}`. Code de sortie : 0 si tout est cohérent, 1 en cas de refus, 2 si un fichier est illisible.
