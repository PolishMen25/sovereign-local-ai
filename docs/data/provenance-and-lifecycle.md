# Provenance et cycle de vie des données

## Objectif

Chaque élément de connaissance doit rester attribuable, vérifiable et reproductible autant que les sources le permettent. L’archive originale est conservée sans modification ; les corrections, validations, enrichissements et changements de statut sont de nouveaux événements ou de nouveaux artefacts liés à l’original.

Le format d’échange initial est défini par `schemas/research-package.schema.json`, version `0.1.0`. Sur la frontière externe, ce schéma impose `lifecycle_state: RAW` ; les autres états appartiennent au journal d'événements interne et ne peuvent pas être déclarés par le producteur.

## Principes

- **RAW immuable** : les octets reçus, leur empreinte et leur date de réception ne sont jamais réécrits.
- **Provenance de bout en bout** : fournisseur, modèle, question, éventuel prompt système contrôlé, réponse, sources, citations, métadonnées des pièces jointes, paramètres, métriques de tokens, coût et erreurs sont conservés lorsqu’ils sont disponibles.
- **Aucun secret** : clés d’API, jetons, cookies, mots de passe, en-têtes d’autorisation, URL signées, identifiants de session et autres justificatifs d’accès sont retirés avant la soumission.
- **Séparation données/contrôle** : les contenus externes ne sont jamais interprétés comme des instructions système ou des autorisations d’outil.
- **Traçabilité append-only** : toute décision ajoute un événement daté, signé ou authentifié ; elle ne remplace pas l’historique.
- **Dérivations explicites** : un résumé, un nettoyage, une traduction, un découpage ou un nouvel index référence toujours son ou ses parents.

## États du cycle de vie

| État | Signification | Effet sur l’utilisation |
|---|---|---|
| `RAW` | Paquet reçu et archivé à l’identique. | Non consultable par les usages de connaissance. |
| `PENDING` | Contrôles de structure, sécurité, provenance et qualité en cours. | En quarantaine ; non indexé dans le corpus actif. |
| `VALIDATED` | Politique de validation satisfaite et décision journalisée. | Peut être dérivé et indexé pour le MCP Knowledge. |
| `REJECTED` | Paquet refusé, avec codes de motif non sensibles. | Conservé selon la politique, jamais servi comme connaissance fiable. |
| `SUPERSEDED` | Une version plus récente ou une correction remplace cet artefact pour les usages courants. | Encore traçable et consultable pour audit, mais exclu par défaut. |
| `ARCHIVED` | Retiré des index actifs et placé en conservation longue durée. | Accessible uniquement par un processus d’archive autorisé. |

Transitions ordinaires :

```text
RAW -> PENDING -> VALIDATED -> SUPERSEDED -> ARCHIVED
                 |                 |
                 +---------------> ARCHIVED

RAW -> PENDING -> REJECTED -> ARCHIVED
```

Une panne avant validation laisse l’artefact en `RAW` ou `PENDING` ; elle ne le promeut jamais implicitement. `REJECTED`, `SUPERSEDED` et `ARCHIVED` ne signifient pas suppression du RAW. Un effacement imposé par une obligation légale suit une procédure exceptionnelle, autorisée et auditée, avec conservation d’une preuve non réversible lorsque la loi le permet.

L’état courant est obtenu en rejouant le journal d’événements. Changer l’état n’altère ni les octets RAW ni leur empreinte. Une vue ou un manifeste matérialisé peut être régénéré à partir de ce journal.

## Enveloppe de provenance

Un paquet porte au minimum :

- un identifiant global et la version de schéma ;
- l’état déclaré au moment du manifeste ;
- le fournisseur et le modèle, avec un identifiant de requête fournisseur seulement s’il n’est pas sensible ;
- les horodatages de début, fin, collecte et création ;
- la question d’origine et, uniquement lorsqu’il est maîtrisé par le Gateway ou l’opérateur local, le prompt système contrôlé ;
- la réponse brute utile, sans secret ;
- les sources et citations avec leurs identifiants stables ;
- les seules métadonnées des pièces jointes, jamais leurs octets dans l’enveloppe ;
- les tokens, le coût et la devise lorsqu’ils sont connus ;
- les paramètres de génération non secrets ;
- les erreurs assainies, sans pile d’exécution ni en-tête ;
- une déclaration de contrôle des secrets et des empreintes SHA-256.

Les champs inconnus sont refusés. Une valeur indisponible doit être omise lorsque le schéma la rend facultative, et non inventée. Un montant nul signifie réellement zéro ; il ne remplace pas un coût inconnu.

## Empreintes et canonicalisation

SHA-256 est l’algorithme initial obligatoire. Il sert à détecter les altérations et les doublons, pas à prouver seul l’identité de l’émetteur.

Trois empreintes de portée différente peuvent coexister :

1. **empreinte d'ingress** : SHA-256 calculé par le Collector sur les octets exactement reçus ; elle réside dans le reçu ou journal append-only, hors du paquet afin d'éviter toute référence circulaire ;
2. **empreinte canonique du paquet** : SHA-256 du JSON canonique selon RFC 8785, en excluant l’objet `integrity` afin d'éviter une référence circulaire ;
3. **empreinte de réponse fournisseur** : facultative, elle porte sur les octets bruts d'une réponse conservée comme objet séparé et ne désigne jamais le paquet JSON qui contient la référence.

La valeur est encodée par 64 caractères hexadécimaux minuscules. À la réception, le service interne recalcule les empreintes avant tout traitement. Une divergence produit un événement de sécurité, bloque la promotion vers `VALIDATED` et conserve les preuves nécessaires à l’enquête.

Chaque pièce jointe est référencée par une empreinte de contenu SHA-256 et des métadonnées bornées. Les URL doivent être HTTPS, publiques et canoniques, sans paramètres d’accès. Les contenus binaires sont transférés et stockés par un canal d’objets séparé, soumis aux mêmes règles d’immutabilité.

Le schéma structure les champs mais ne remplace pas la validation sémantique. Le Collector doit activer l'assertion des formats et vérifier côté application : UUID et horodatages, ordre temporel, unicité des identifiants, existence des sources citées, bornes et ordre des offsets, cohérence des tokens, empreintes et URLs. Une URL `https://` reste non fiable : identifiants intégrés, hôtes privés, résolutions DNS, redirections et changements d'adresse doivent être contrôlés contre la SSRF.

## Sources, citations et dérivations

Une source possède un identifiant local stable. Une citation référence cet identifiant et, lorsque possible, une plage dans la réponse ainsi qu’une empreinte de l’extrait cité. Une citation prouve l’attribution déclarée, pas la véracité de la source.

Toute transformation produit un nouvel artefact avec :

- les identifiants et empreintes des parents ;
- le type et la version de la transformation ;
- l’identité du service ou de l’opérateur ;
- les horodatages ;
- les paramètres non secrets ;
- l’empreinte du résultat.

Le schéma `research-package` v0.1.0 ne représente que le paquet d'ingress. Les événements d'état, relations `SUPERSEDED` et artefacts dérivés devront disposer de schémas append-only séparés avant l'implémentation ; tant qu'ils n'existent pas, aucune lignée interne ne doit être considérée comme entièrement représentée.

Une correction n’écrase donc jamais la réponse initiale. Elle peut devenir la version active et placer l’ancienne en `SUPERSEDED`.

## Contenu externe non fiable

Le Web, les réponses de modèles, les documents importés et les métadonnées tierces sont des entrées hostiles par défaut. Ils peuvent contenir du prompt injection, des instructions déguisées, des liens d’exfiltration, du code, des charges malveillantes ou de fausses citations.

La chaîne de validation doit au minimum :

- étiqueter clairement l’origine non fiable ;
- empêcher le contenu de modifier les instructions système ou les règles d’accès ;
- désactiver l’exécution active des documents et isoler leur analyse ;
- normaliser les URL et retirer les paramètres sensibles ;
- vérifier les correspondances citation/source et signaler les références inaccessibles ;
- rechercher les secrets et données personnelles selon une politique versionnée ;
- conserver les résultats des contrôles comme événements séparés ;
- demander une approbation avant toute action ayant un effet externe.

Un détecteur de prompt injection constitue une défense supplémentaire, jamais une autorisation automatique. Aucun texte collecté ne peut accorder de privilège, déclencher un outil ou demander au Collector de lire le corpus interne.

## Contrôles d’accès et conservation

- Le MCP Collector peut ajouter une soumission mais ne peut lire aucune donnée interne.
- Les validateurs lisent la quarantaine et écrivent des décisions ; ils n’altèrent pas le RAW.
- Les indexeurs lisent seulement les artefacts `VALIDATED` autorisés.
- Le MCP Knowledge lit les index internes selon l’identité du client ; il n’est pas accessible depuis Internet.
- Les administrateurs d’archive sont séparés des identités applicatives ordinaires.

Les durées de conservation, la réplication, les sauvegardes, la localisation des données et les procédures d’effacement exceptionnel seront fixées après l’audit et documentées dans une politique versionnée. Tout changement de politique doit être applicable prospectivement sans effacer silencieusement l’historique.

