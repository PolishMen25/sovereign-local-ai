# Événements de cycle de vie

> Statut : **PROVISOIRE**. Contrat candidat pour l'issue #6 (schéma `lifecycle-event` 0.1.0, relecture `lifecycle-event-replay-v1`), rédigé avant l'ADR du Research Gateway. Il n'est câblé à aucune route, aucun service et aucun port ; aucun journal réel n'est tenu. Sa publication comme contrat attend une décision du propriétaire. Le registre `docs/project/decisions.md` n'est pas modifié.

`docs/data/provenance-and-lifecycle.md` exige que « les événements d'état, relations `SUPERSEDED` et artefacts dérivés » disposent de schémas append-only avant toute implémentation. Ce document spécifie le premier : `schemas/lifecycle-event.schema.json` (Draft 2020-12, fermé partout par `additionalProperties: false`), implémenté sans dépendance tierce par `services/quarantine/lifecycle.py` et vérifié par `tests/test_lifecycle_events.py`. Les artefacts dérivés relèvent d'un schéma de lignée distinct, spécifié dans `docs/data/derived-artifacts.md`.

## Principes

- **Le journal fait foi.** L'état courant d'un artefact s'obtient en rejouant ses événements dans l'ordre d'ajout. Une vue matérialisée peut être régénérée à tout moment.
- **RAW intact.** Un événement ne contient aucun octet RAW, aucun extrait, aucune URL, aucun chemin : seulement des identifiants, des empreintes, des états et des codes de motif. La relecture ne lit jamais le RAW et n'écrit aucun fichier ; un test vérifie que les octets, l'empreinte et la date de modification d'un RAW synthétique sont inchangés.
- **Append-only vérifiable.** Les événements d'un même sujet sont numérotés sans trou et chaînés par empreinte RFC 8785. Toute réécriture, suppression ou insertion est détectée à la relecture.
- **Refus sûrs.** Une relecture s'arrête au premier événement fautif et rend ses codes et son indice, jamais son contenu. Un journal est accepté entièrement ou refusé ; il n'est jamais appliqué à moitié.

## États et transitions

Les états reprennent le tableau de `provenance-and-lifecycle.md`, plus `REJECTED_AT_INGRESS` pour un refus à l'ingress :

| État | Sens |
|---|---|
| `RAW` | Déposé à l'identique (ingress accepté ou dérivé enregistré). |
| `PENDING` | Contrôles en cours. |
| `VALIDATED` | Politique satisfaite, décision journalisée. |
| `REJECTED` | Refusé après contrôle, avec au moins un code de motif. |
| `SUPERSEDED` | Remplacé pour les usages courants par un autre sujet validé. |
| `ARCHIVED` | Retiré des index actifs ; état terminal. |
| `REJECTED_AT_INGRESS` | Refusé par le Collector avant tout stockage durable ; état terminal. |

Transitions ordinaires, seules admises par `STATE_TRANSITION` :

```text
RAW -> PENDING
PENDING -> VALIDATED | REJECTED
VALIDATED -> SUPERSEDED | ARCHIVED
SUPERSEDED -> ARCHIVED
REJECTED -> ARCHIVED
```

La table `TRANSITIONS` du module est l'unique source de ces règles : les clauses conditionnelles du schéma en sont générées, et le test de parité compare le miroir au fichier de schéma. Aucune transition ne ramène un artefact vers `RAW` ou `PENDING`, et aucun retour depuis un état terminal n'existe. Une réouverture après changement de politique reste à décider (OUVERT).

## Types d'événements

| `event_type` | Transition | Acteur autorisé | Sujets admis |
|---|---|---|---|
| `INGRESS_ACCEPTED` | ∅ → `RAW` | `collector` | `research_package`, `conversation`, `conversation_revision` |
| `INGRESS_REJECTED` | ∅ → `REJECTED_AT_INGRESS` | `collector` | `research_package`, `conversation` |
| `DERIVED_RECORDED` | ∅ → `RAW` | `internal_service`, `operator` | `derived_artifact` |
| `STATE_TRANSITION` | table ci-dessus | `internal_service`, `operator` | tous |

Les trois premiers sont des **événements d'enregistrement** : `sequence` = 0, `previous_event_sha256` = `null`, `from_state` = `null`. Un `STATE_TRANSITION` a `sequence` ≥ 1 et une empreinte précédente.

Conséquences sur les acteurs :

- aucun producteur externe n'écrit dans le journal : le type d'acteur `producer` n'existe pas ;
- le Collector n'émet que les événements d'ingress ; il ne peut jamais produire `PENDING`, `VALIDATED` ni aucune autre transition ;
- `actor.id` est un identifiant technique non nominatif (`quarantine-validator`, `owner-review`), jamais un nom de personne ni un compte.

## Champs

| Champ | Contenu |
|---|---|
| `schema_version` | `0.1.0`. |
| `event_id` | UUID de l'événement ; clé d'idempotence. |
| `subject` | `{artifact_kind, artifact_id, subject_sha256}`, clé du sujet. |
| `sequence` | Rang dans la chaîne du sujet, de 0 à 1 000 000. |
| `previous_event_sha256` | Empreinte de l'événement précédent du sujet, ou `null`. |
| `from_state`, `to_state` | États avant et après. |
| `actor` | `{kind, id}`. |
| `decision` | `{policy_id, policy_version, reason_codes, confirmation_ref?}`. |
| `superseded_by` | Présent si et seulement si `to_state` = `SUPERSEDED`. |
| `revision_of` | Présent si et seulement si l'événement dépose une révision de conversation. |
| `occurred_at`, `recorded_at` | RFC 3339 avec décalage ; `occurred_at` ≤ `recorded_at`. |
| `auth_tag` | Emplacement réservé, facultatif (voir plus bas). |

### Identité du sujet (HYPOTHÈSE)

Le sujet est identifié par le triplet `(artifact_kind, artifact_id, subject_sha256)`. `subject_sha256` est l'empreinte des octets conservés, identique dans tous les événements du sujet :

- `research_package` : `artifact_id` = `package_id` ; empreinte de portée `ingress-payload-bytes` (`docs/data/canonical-hashing.md`), car le RAW conserve les octets reçus ;
- `conversation` : `artifact_id` = `conversation_id` ; empreinte `sha256` du reçu que produit aujourd'hui le code du collecteur de conversations sur `main` (contrat distinct, voir `canonical-hashing.md`). **OUVERT** : la portée de cette empreinte dépend de la décision du propriétaire sur le contrat de conversation (empreinte actuelle documentée comme contrat propre, ou passage aux octets d'ingress et à RFC 8785) et de la fusion de la PR #17. Le schéma et la relecture ne traitent `subject_sha256` que comme une empreinte SHA-256 opaque et ne tranchent donc pas ce choix ;
- `conversation_revision` : même `artifact_id` que l'original, empreinte de la révision ;
- refus à l'ingress : `artifact_id` = `submission_id` attribué par le Collector, car un corps refusé peut ne contenir aucun identifiant fiable ; empreinte des octets reçus puis écartés ;
- `derived_artifact` : `artifact_id` et `result.content_sha256` de l'enregistrement de lignée.

Hors révisions de conversation, un couple `(artifact_kind, artifact_id)` ne peut être enregistré qu'une fois.

### Décision

`policy_id` et `policy_version` désignent la politique appliquée, par exemple `research-package-contract-v1`, `collector-secret-scan-v1` ou `url-ssrf-policy-v1`. `reason_codes` contient au plus 32 codes distincts de forme `^[A-Z][A-Z0-9_]{0,63}$`, jamais un extrait ; au moins un code est exigé vers `REJECTED` et `REJECTED_AT_INGRESS`. Les codes des validateurs candidats respectent déjà cette forme.

`confirmation_ref` = `{capability: "knowledge.promote_approved", proposal_id}` renvoie à une proposition du registre de confirmations de l'orchestrateur (`proposal_id` en 32 caractères hexadécimaux). Il n'est admis que vers `VALIDATED`. Savoir quelles validations exigent une confirmation humaine relève de la matrice de promotion du propriétaire (OUVERT) ; le schéma ne l'impose pas.

### Révision RAW d'une conversation

La PR #17, encore ouverte, conserve un premier instantané dans `raw/conversations/<id>.json` et chaque contenu différent sous `raw/conversations/versions/<id>/<sha256>.json`. Le lien entre une révision et son original n'est aujourd'hui qu'implicite dans l'arborescence. Ici, l'événement `INGRESS_ACCEPTED` d'un sujet `conversation_revision` porte `revision_of`, qui doit désigner une `conversation` déjà acceptée avec le même `artifact_id` et une empreinte différente. Une révision ne remplace jamais l'original : les deux restent en `RAW`. **Ces sémantiques devront être revérifiées après la fusion de la PR #17.**

### `superseded_by`

La cible doit être un autre sujet connu et, au moment de l'événement dans l'ordre du journal, en `VALIDATED`. Ce qui remplace un artefact devient donc la version active. Deux sujets ne peuvent pas se remplacer mutuellement, puisqu'un sujet `SUPERSEDED` n'est plus `VALIDATED`. La cible peut être d'un autre type, par exemple un dérivé corrigé qui remplace un paquet.

## Chaîne d'empreintes et idempotence

- `event_sha256(event)` = SHA-256 de la forme RFC 8785 de l'événement privé de son seul membre `auth_tag`. `previous_event_sha256` d'un événement doit égaler l'empreinte de l'événement précédent du même sujet.
- Un événement dont l'`event_id` a déjà été vu et dont la forme canonique est identique est ignoré (reprise idempotente). La même clé avec un contenu différent, y compris un `auth_tag` différent, est refusée.
- `recorded_at` ne recule jamais pour un même sujet. La source de temps reste à désigner (OUVERT).

## Authentification (OUVERT)

`auth_tag` = `{scheme, key_id, value}` réserve la place d'une authentification des événements. Le choix du mécanisme (HMAC-SHA256 par service, Ed25519 qui demanderait une dépendance), la gestion des clés, le stockage du journal (SQLite chaîné ou segments JSONL avec instantanés) et la source de temps sont des décisions du propriétaire. En attendant :

- la relecture **ne vérifie pas** `auth_tag` : un journal relu est cohérent, pas authentifié ;
- `auth_tag` est exclu de l'empreinte de chaîne, afin que le mécanisme retenu puisse signer cette empreinte sans la modifier.

## Codes de refus

Codes propres aux règles d'un événement isolé :

| Code | Refus |
|---|---|
| `EVENT_TRANSITION_NOT_ALLOWED` | Couple (`from_state`, `to_state`) hors table pour ce type d'événement. |
| `EVENT_ACTOR_NOT_ALLOWED` | Acteur interdit pour ce type : Collector hors ingress, service ou opérateur à l'ingress. |
| `EVENT_SUBJECT_KIND_NOT_ALLOWED` | Type de sujet interdit pour ce type d'événement. |
| `EVENT_TIME_ORDER` | `occurred_at` postérieur à `recorded_at`. |

S'y ajoutent les codes structurels génériques de l'interpréteur (`EVENT_FIELD_UNKNOWN`, `EVENT_FIELD_MISSING`, `EVENT_FIELD_FORBIDDEN`, `EVENT_CONST_MISMATCH`, `EVENT_ENUM_MISMATCH`, `EVENT_PATTERN_MISMATCH`, `EVENT_ARRAY_TOO_SHORT`, etc., décrits dans `docs/data/research-package-validation.md` avec le préfixe `PKG_`) et les codes `JSON_*` du profil strict.

Codes de relecture :

| Code | Refus |
|---|---|
| `EVENT_ID_CONFLICT` | `event_id` déjà vu avec un contenu différent. |
| `EVENT_FORK` | Deux événements différents au même rang d'un sujet, ou second enregistrement d'un sujet. |
| `EVENT_SEQUENCE_GAP` | Rang qui saute au moins une valeur. |
| `EVENT_SUBJECT_UNKNOWN` | Transition sur un sujet jamais enregistré. |
| `EVENT_CHAIN_MISMATCH` | `previous_event_sha256` différent de l'empreinte de l'événement précédent. |
| `EVENT_STATE_MISMATCH` | `from_state` différent de l'état courant rejoué. |
| `EVENT_RECORDED_AT_REGRESSION` | `recorded_at` antérieur à celui de l'événement précédent du sujet. |
| `EVENT_ARTIFACT_ID_CONFLICT` | Même `(artifact_kind, artifact_id)` enregistré deux fois avec des octets différents, hors révision. |
| `EVENT_REVISION_ORIGINAL_UNKNOWN` | Révision dont l'original n'a pas été accepté auparavant. |
| `EVENT_REVISION_LINK_INVALID` | Révision liée à un autre `artifact_id` ou aux mêmes octets que l'original. |
| `EVENT_SUPERSEDED_BY_UNKNOWN` | Cible de remplacement inconnue. |
| `EVENT_SUPERSEDED_BY_SELF` | Sujet qui se remplace lui-même. |
| `EVENT_SUPERSEDED_BY_NOT_VALIDATED` | Cible de remplacement pas en `VALIDATED`. |
| `EVENT_LIMIT_EXCEEDED` | Plus de 1 000 000 d'événements dans une relecture (borne HYPOTHÈSE). |

## Hors périmètre

- **Stockage et écriture.** Aucun journal n'est créé ; le module ne sait que relire.
- **Chemins de promotion existants.** `tools/promote_arena_increment.py` et `tools/materialize_training_corpus.py` écrivent déjà `VALIDATED` dans des manifestes sans journal. Le schéma pourra les couvrir, mais leur raccordement n'est pas traité ici.
- **Politiques.** La politique de refus ou de signalement par catégorie de secret et la matrice de promotion automatique ou humaine restent des décisions du propriétaire.

## Exemples synthétiques

`tests/fixtures/lifecycle-events/` contient des journaux JSONL synthétiques : des journaux cohérents avec leur état final attendu, et au moins un journal invalide par code de règle ou de relecture, avec ses codes et l'indice de l'événement fautif dans `expected.json`.

## Utilisation locale

```text
python -B services/quarantine/lifecycle.py journal.jsonl
```

Le journal contient un événement JSON par ligne, dans l'ordre d'ajout ; chaque ligne est lue avec le profil strict (clés dupliquées, NaN refusés). La sortie donne, par sujet, son type, son identifiant, son empreinte, son état et son rang, ou bien `{"refused": true, "reasons", "event_index"}`. Code de sortie : 0 si le journal est cohérent, 1 s'il est refusé, 2 s'il est illisible.
