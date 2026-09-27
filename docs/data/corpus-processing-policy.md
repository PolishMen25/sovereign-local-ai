# Politique de traitement du corpus CORE — état implémenté et lacunes

- Statut : **PROVISOIRE** (politique candidate, non approuvée par le
  propriétaire, sans entrée au registre)
- Date : 2026-09-26
- Base examinée : `main` au commit `db9414d`
- Issue : #7 (gate G3)
- Documents liés : [inventaire des sources d'entraînement](training-sources-inventory.md),
  [gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md),
  [provenance et cycle de vie](provenance-and-lifecycle.md)

Ce document décrit ce que le code du dépôt fait réellement aux textes destinés
à l'entraînement de CORE, puis ce qu'il ne fait pas. Il ne modifie aucun outil,
n'approuve aucune source et ne tranche aucune des questions posées en fin de
document. Il ne couvre ni l'index RAG ni l'ingress `research-package`.

## Étiquettes employées

- **CONFIRMÉ** : vérifiable par lecture du code ou d'un document versionné à
  `db9414d`.
- **PROVISOIRE** : proposition sans validation du propriétaire.
- **OUVERT** : question sans réponse qui conditionne la politique.
- **HYPOTHÈSE** : conséquence déduite par l'auteur, non mesurée.

Aucun état de déploiement n'a été revérifié en direct à la date de rédaction
(2026-09-26). Les volumes cités proviennent de documents ou de messages de
commit datés, jamais d'une observation récente.

## 1. Chaîne de traitement actuelle

**CONFIRMÉ** — Quatre chemins distincts produisent aujourd'hui des textes
candidats à l'entraînement. Aucun ne partage l'intégralité des règles des
autres.

| Étape | Outil | Sortie |
| --- | --- | --- |
| Acquisition du catalogue | [`acquire_corpus_v1.py`](../../tools/acquire_corpus_v1.py) | archives RAW et mesures de texte ; aucune promotion |
| Matérialisation d'un corpus approuvé | [`materialize_training_corpus.py`](../../tools/materialize_training_corpus.py) | splits JSONL et manifeste `0.2.0` |
| Validation du manifeste | [`validate_training_corpus_manifest.py`](../../tools/validate_training_corpus_manifest.py) | refus ou acceptation structurelle |
| Tokenizer et préflight | [`train_byte_bpe.py`](../../tools/train_byte_bpe.py), [`preflight_core_700m_tokenizer.py`](../../tools/preflight_core_700m_tokenizer.py) | artefact tokenizer lié au split `train` |
| Dérivé étendu | [`build_extended_corpus_splits.py`](../../tools/build_extended_corpus_splits.py) | splits candidats `RAW_DERIVED_PENDING_REVIEW` |
| Incréments de l'arène | [`build_core_increment_from_arena.py`](../../tools/build_core_increment_from_arena.py), [`promote_arena_increment.py`](../../tools/promote_arena_increment.py) | incrément RAW puis copie VALIDATED |
| Candidats conversationnels | [`export_conversation_learning_candidates.py`](../../tools/export_conversation_learning_candidates.py) | paquet candidat `pending_owner_approval` |

## 2. Ce qui est implémenté

### 2.1 Normalisation Unicode

- **CONFIRMÉ** — La politique `unicode-nfc-v1` applique la forme NFC dans le
  tokenizer, à l'apprentissage comme à l'encodage
  ([`services/inference/tokenizer.py`](../../services/inference/tokenizer.py)).
  `train_byte_bpe.py` refuse un manifeste qui déclare une autre politique.
- **CONFIRMÉ** — Les octets des splits JSONL ne sont pas normalisés à la
  matérialisation : ils sont écrits tels que décodés depuis l'archive. Les
  empreintes des splits portent donc sur le texte non normalisé ; la
  normalisation n'intervient qu'à la tokenisation.
- **OUVERT** — Aucune autre normalisation n'est définie : fins de ligne,
  espaces, caractères de contrôle autres que NUL, BOM.

### 2.2 Sélection des fichiers : deux listes qui divergent

**CONFIRMÉ** — L'outil d'acquisition, qui produit les mesures publiées du
catalogue, et le matérialiseur, qui produit les splits d'entraînement,
n'appliquent pas les mêmes règles.

| Règle | Acquisition (mesure) | Matérialisation (splits) |
| --- | --- | --- |
| Suffixes admis | 27 : `.bash .c .cc .cpp .cs .css .go .h .html .java .js .json .md .mdx .ps1 .psm1 .py .rst .sh .sql .toml .ts .tsx .txt .yaml .yml .zsh` | 14 : `.go .json .md .ps1 .psd1 .psm1 .py .pyi .rst .sh .toml .txt .yaml .yml` |
| Répertoires exclus | `.git`, `coverage`, `dist`, `node_modules`, `vendor` (casse exacte) | `.github`, `example`, `examples`, `test`, `tests`, `vendor` (casse ignorée) |
| Taille maximale d'un fichier | 2 000 000 octets | 256 Kio ; fichier vide refusé |
| Octet NUL, UTF-8 invalide | fichier exclu | fichier exclu |
| Marqueurs de secrets | non appliqués | 5 marqueurs (voir 2.3) |
| Borne globale | aucune | archive 128 Mio ; split 16 Mio |

- **CONFIRMÉ** — Aucune des deux listes de suffixes ne contient l'autre :
  `.psd1` et `.pyi` ne sont admis qu'à la matérialisation. Leur intersection
  compte 12 suffixes : `.go .json .md .ps1 .psm1 .py .rst .sh .toml .txt
  .yaml .yml`.
- **HYPOTHÈSE** — Les mesures d'acquisition ne prédisent pas le volume
  matérialisable. Les suffixes `.ts`, `.tsx`, `.js`, `.html` et `.css` sont
  comptés à l'acquisition mais écartés à la matérialisation : l'essentiel du
  code de TypeScript, Vite, Nuxt et Docusaurus serait perdu. À l'inverse, les
  répertoires de tests et d'exemples sont comptés puis écartés. Aucun écart n'a
  été mesuré.

### 2.3 Filtrage des secrets

- **CONFIRMÉ** — Le matérialiseur écarte un fichier entier dès qu'il contient,
  sans tenir compte de la casse, l'un de cinq marqueurs. Ce sont deux en-têtes
  de clé privée PEM (générique et OpenSSH) et trois affectations collées :
  `password=`, `api_key=` et `access_token=`.
- **CONFIRMÉ** — Aucun compteur de fichiers écartés n'est inscrit dans le
  manifeste ; l'effet du filtre n'est pas auditable après coup.
- **CONFIRMÉ** (lecture du code) — Les marqueurs sont des sous-chaînes
  exactes, à la casse près. L'en-tête PEM générique ne correspond donc pas aux
  en-têtes PEM `RSA`, `EC` ni `ENCRYPTED`, dont le mot-clé s'intercale avant
  `PRIVATE KEY`. Les affectations avec espaces (`password = …`) ou en syntaxe
  YAML ou JSON (`password: …`, `"password": …`) ne sont pas reconnues non
  plus.
- **HYPOTHÈSE** — Aucune règle ne vise les préfixes de jetons de fournisseurs
  ni les chaînes à forte entropie : ils ne seraient écartés que s'ils suivent
  l'une des trois affectations collées. Leur présence dans les archives n'est
  pas mesurée.
- **CONFIRMÉ** — Les conversations suivent un autre filtre : la mémoire privée
  masque les secrets probables avant stockage (lignes et affectations
  sensibles, en-têtes `Bearer`, préfixes de jetons connus, paramètres d'URL,
  jetons mixtes longs). Ce masquage ne vise pas les données personnelles.

### 2.4 Déduplication exacte

**CONFIRMÉ** — La déduplication exacte n'existe que par morceaux.

- Le matérialiseur ne déduplique pas : deux fichiers identiques d'une même
  archive produisent deux enregistrements.
- Le dérivé étendu calcule l'identité d'un document par SHA-256 de son texte et
  **refuse** toute l'opération si un doublon apparaît ; il ne le retire pas.
- Un incrément de l'arène retient un enregistrement par couple (tâche,
  empreinte de la solution) à l'intérieur d'un paquet.
- La [spécification d'auto-entraînement](../model/self-training-loop-spec.md)
  exige en plus la suppression des doublons normalisés et des plafonds de
  répétition, remesurés par `recheck_packet_health.py`.
- Aucune déduplication ne traverse les familles de sources ; voir
  l'[inventaire](training-sources-inventory.md) pour les recouvrements connus.

### 2.5 Découpage en train, validation et test

- **CONFIRMÉ** (lecture du code et reproduction sur des archives
  synthétiques) — Le matérialiseur vérifie seulement que l'ensemble des
  valeurs `split` de la spécification vaut exactement `train`, `validation`
  et `test`. Son message d'erreur annonce une source par split, mais rien
  n'interdit deux sources pour le même split. Dans ce cas, les enregistrements
  de la dernière source traitée écrasent ceux des autres, et
  `splits.<split>.package_ids` nomme la première source de la spécification.
  `source_packages` liste pourtant toutes les sources, et l'outil annonce une
  matérialisation réussie. Le validateur `0.2.0` refuse ensuite ce manifeste,
  puisqu'un paquet n'y est rattaché à aucun split, mais seulement s'il est
  lancé.
- **CONFIRMÉ** — Chaque source reste entière dans un seul split : le
  découpage du matérialiseur est au niveau du paquet, mais il ne sait pas
  placer plusieurs paquets dans un même split. Le corpus initial approuvé le
  2026-09-07 compte trois archives pour trois splits ; il n'est pas touché par
  ce défaut.
- **CONFIRMÉ** — Le validateur du manifeste `0.2.0` refuse qu'un paquet
  appartienne à plus d'un split, exige que chaque paquet soit rattaché à un
  split et exige trois empreintes de split distinctes.
- **CONFIRMÉ** — Le dérivé étendu découpe **par document** : les huit premiers
  caractères hexadécimaux du SHA-256 du texte, modulo 100, envoient le reste 0
  en test, le reste 1 en validation et le reste en entraînement (98/1/1). Un
  même paquet se retrouve donc dans plusieurs splits.
- **HYPOTHÈSE** — Tel quel, ce dérivé ne peut pas être décrit par un manifeste
  `0.2.0` valide, puisque ses paquets sont partagés entre splits. Des fichiers
  voisins d'un même dépôt peuvent en outre fuiter entre entraînement et test.
  Le point de reprise public exige déjà une reconstruction au niveau des
  paquets.

### 2.6 Exclusion des holdouts

**CONFIRMÉ** — Le dérivé étendu retire tout document dont le SHA-256 du texte
figure dans les splits `validation` ou `test` de pilote-v3. Il vérifie que
l'identifiant de chaque enregistrement de holdout est bien l'empreinte de son
texte. Le point de reprise rapporte 1 531 documents retirés ; ce compte vient
d'un document daté du 2026-09-09 et n'a pas été revérifié.

La correspondance est exacte : une variante d'un document de holdout (espaces,
en-tête de licence, autre version) n'est pas détectée.

### 2.7 Bornes et troncature

- **CONFIRMÉ** — Le matérialiseur parcourt l'archive dans l'ordre alphabétique
  des chemins et **s'arrête** dès que le split atteindrait 16 Mio.
- **HYPOTHÈSE** — Cette troncature déterministe est biaisée : les fichiers
  situés en fin d'ordre alphabétique ne sont jamais retenus, quel que soit
  leur intérêt.
- **CONFIRMÉ** — L'apprentissage du tokenizer est borné à 512 Mio par
  lancement, 1 Mio par enregistrement et un million d'enregistrements, selon la
  [note pilote-v3](../model/pilote-v3-tokenizer-adoption.md).

### 2.8 Langue et estimation des volumes

- **CONFIRMÉ** — L'acquisition n'identifie pas la langue par le contenu. Une
  source déclarée `fr` est comptée entièrement en français ; une source
  `mixte` ne compte en français que son répertoire de traduction déclaré.
- **CONFIRMÉ** — Les « tokens » des mesures d'acquisition sont des mots ou des
  signes de ponctuation isolés par une expression régulière, pas des tokens du
  Byte-BPE. Ils ne sont pas comparables aux budgets de tokens d'entraînement.
- **HYPOTHÈSE** — Le taux de français publié (0,42 %) inclut tout le code de
  DSFR, compté comme français. La part de prose française est donc plus faible
  que ce chiffre.

### 2.9 Licences admises

**CONFIRMÉ** — Cinq listes coexistent et ne coïncident pas.

| Liste | `0BSD`, `Unlicense` | `Etalab-2.0` | `CC-BY-4.0` | `verified-public-domain` |
| --- | --- | --- | --- | --- |
| Schéma JSON de la politique, énumération `allowed_licenses` ([schéma](../../schemas/training-source-policy.schema.json)) | oui | non | non | non |
| Fichier de politique candidate, liste `allowed_licenses` | oui | oui | oui | non |
| Fichier de politique candidate, liste `acquisition_guard` | non | oui | oui | oui |
| Manifeste d'entraînement `0.2.0` ([validateur](../../tools/validate_training_corpus_manifest.py)) | oui | oui | oui | oui |
| Audit [`verify_corpus_approval.py`](../../tools/verify_corpus_approval.py) | non | non à `db9414d` ; oui depuis `485fd72` (D-033) | oui | oui |

- **CONFIRMÉ** — Les deux lignes du fichier de politique candidate décrivent
  le contenu de ce fichier, pas un refus. Le
  [validateur de la politique](../../tools/validate_training_source_policy.py)
  ne contrôle que l'inclusion. Il accepte dans `acquisition_guard` toute valeur
  de sa liste générale, plus `verified-public-domain` : `0BSD` et `Unlicense`
  sont donc absentes de la liste `acquisition_guard` du fichier candidat, mais
  acceptées par son validateur.
- **CONFIRMÉ** — Le fichier de politique candidate n'est pas conforme à son
  propre schéma. Il contient `CC-BY-4.0` et `Etalab-2.0`, absentes de
  l'énumération, ainsi que des clés de premier niveau que le schéma interdit
  (`additionalProperties: false`), dont `acquisition_guard` et `sources`.
  Aucun test ne valide ce fichier contre le schéma.

Les cinq listes admettent `MIT`, `Apache-2.0`, `BSD-2-Clause`,
`BSD-3-Clause`, `ISC` et `CC0-1.0` ; toutes sauf le schéma admettent aussi
`CC-BY-4.0`. Le registre autorise
nommément `CC-BY-4.0` (D-032) et `Etalab-2.0` (D-033) ; D-031 pose le critère
général « strictement réutilisables ». Aucune entrée ne nomme `0BSD`,
`Unlicense` ni `verified-public-domain`. La licence est contrôlée **par
paquet** ; aucun outil ne détecte un fichier tiers sous une autre licence à
l'intérieur d'un dépôt.

### 2.10 Attestation d'approbation

- **CONFIRMÉ** — Le matérialiseur écrit lui-même `lifecycle_state: VALIDATED`,
  `classification: approved_training` et deux approbations `approved` dans le
  manifeste qu'il produit. L'approbation tient donc au fait que l'opérateur a
  lancé l'outil sur une spécification approuvée.
- **CONFIRMÉ** — Depuis le commit `6d959d7` (2026-09-08), le préflight ne lit
  plus de fichier d'approbation distinct : le manifeste validé suffit. Cette
  simplification n'a pas d'entrée propre au registre.
- **CONFIRMÉ** — Un incrément de l'arène promu en VALIDATED porte
  `classification: synthetic` et `training_authorization: approved`. Or le
  validateur du manifeste `0.2.0` refuse cette combinaison. Aucun chemin
  contractuel ne mène donc d'un incrément promu à un manifeste d'entraînement.

## 3. Lacunes

Les identifiants `Axx` renvoient aux tâches du tri de phase 0 du 2026-09-26.
Aucune n'est livrée par ce document ; un outil prévu n'existe pas tant qu'il
n'est pas fusionné.

| Lacune | Constat | Travail préparatoire possible |
| --- | --- | --- |
| Plusieurs paquets par split | **CONFIRMÉ** — écrasement silencieux et attribution erronée dans le manifeste (section 2.5) ; seul le validateur `0.2.0`, s'il est lancé, refuse le résultat. | Refuser toute valeur `split` en double dans la spécification du matérialiseur ; correctif de code à traiter dans une tâche séparée, non fait ici. |
| Quasi-doublons | **OUVERT** — seule l'égalité exacte des octets est détectée, et pas partout. | Détection par shingles ou MinHash en bibliothèque standard (A37). |
| Découpage par paquet du dérivé étendu | **OUVERT** — le découpage par document viole la règle du manifeste `0.2.0`. | Outil de split par paquet ou par dépôt, sortie RAW candidate (A37). |
| Données personnelles | **OUVERT** — aucun détecteur dans la chaîne corpus. L'exclusion `personal-data` de la politique n'est qu'une déclaration. | Choix de politique d'abord ; aucun outil tant que le niveau n'est pas fixé. |
| Identification de langue | **OUVERT** — l'attribution par répertoire ou par source ne mesure pas la prose. | Heuristique sans dépendance, ou mesure a posteriori avec le tokenizer (A24, [`evaluate_tokenizer.py`](../../tools/evaluate_tokenizer.py), fusionné en `48fc63f` ; l'étiquetage de langue des splits y reste OUVERT). |
| Listes de suffixes | **OUVERT** — acquisition et matérialisation divergent. | Liste unique versionnée, reprise par les deux outils. |
| Troncature | **OUVERT** — l'arrêt à 16 Mio dépend de l'ordre alphabétique. | Refuser au lieu de tronquer, ou sous-échantillonner de façon déterministe (A38). |
| Couverture du filtre de secrets | **OUVERT** — 5 marqueurs, sans compteur d'exclusion. | Réutiliser les catégories du scanner `collector-secret-scan-v1` (A17, fusionné en `30f5e8e`, PROVISOIRE et non câblé) et inscrire les compteurs. |
| Licence par fichier | **OUVERT** — un fichier tiers embarqué dans un dépôt hérite de la licence du dépôt, sauf sous `vendor`. | Liste d'exclusion par chemin et relecture des fichiers `NOTICE`. |
| Contenu généré ou minifié | **OUVERT** — aucun filtre spécifique. | Heuristique de longueur de ligne et de ratio de caractères. |
| Retrait d'une source déjà intégrée | **OUVERT** — procédure absente. | Document dédié (A34). |

## 4. Politique candidate

**PROVISOIRE** — Les règles ci-dessous sont proposées pour discussion. Aucune
n'est appliquée par ce document.

1. Un seul jeu de règles de sélection, versionné, partagé par l'acquisition et
   la matérialisation.
2. Découpage au niveau du paquet pour tout nouveau manifeste, conformément au
   validateur `0.2.0`. Avec plus de trois paquets, cela suppose d'abord de
   corriger le matérialiseur, qui ne sait pas placer plusieurs paquets dans un
   même split (section 2.5).
3. Déduplication exacte obligatoire dans et entre familles, puis détection de
   quasi-doublons avec un seuil approuvé par le propriétaire.
4. Refus plutôt que troncature silencieuse ; tout sous-échantillonnage passe
   par un plan déterministe et haché.
5. Compteurs d'exclusion (secrets, taille, encodage, suffixe, doublon) inscrits
   dans le manifeste, sans contenu.
6. Niveau de filtrage des données personnelles fixé par le propriétaire avant
   toute nouvelle matérialisation.

## 5. Questions ouvertes pour le propriétaire

Chaque question est fermée ; la valeur par défaut proposée est la plus sûre.
Aucune n'est tranchée ici.

**Mise à jour du 2026-09-27** — Après la rédaction, le propriétaire a consigné
D-039 à D-042 au registre de `main` ; voir la
[note de décision G3](../project/decision-brief-g3.md#mise-à-jour-du-2026-09-27).
D-039 ratifie le retrait du fichier d'approbation (section 2.10) et répond à la
question 8 : une version de corpus est autorisée par un manifeste `VALIDATED`
produit par la politique automatique versionnée et auditée, non par un artefact
distinct du propriétaire ; le défaut proposé n'est pas retenu. D-040 tranche le
conflit sur les incréments de l'arène (section 2.10) en faveur de sa règle ;
l'alignement des validateurs reste à faire. Aucune entrée ne choisit les règles
de la section 4 : cette politique reste **PROVISOIRE**, et les questions 1 à 7
et 9 restent ouvertes.

**Mise à jour d'intégration (`main` à `30f5e8e`)** — D-043 à D-045,
consignées ensuite (`367f48a`), portent sur les incréments de l'arène,
l'évaluation E2 et l'approbation automatique des paquets ; elles ne
choisissent aucune règle de la section 4. `main` a aussi reçu l'analyseur
`collector-secret-scan-v1` (PROVISOIRE, non câblé), l'outil d'évaluation des
tokenizers et l'acceptation d'`Etalab-2.0` par l'audit d'approbation
(section 2.9) ; aucune question ci-dessous n'en est tranchée.

1. **Quasi-doublons** : faut-il les retirer avant toute nouvelle
   matérialisation ? Défaut proposé : oui, avec un seuil à fixer après mesure.
2. **Découpage** : le découpage par paquet devient-il obligatoire pour tous
   les nouveaux manifestes, dérivé étendu compris ? Défaut proposé : oui.
3. **Données personnelles** : exclure le fichier, masquer les adresses et
   numéros, ou accepter les attributions d'auteur publiques des dépôts ? Défaut
   proposé : masquer, avec compteur.
4. **Langue** : faut-il une identification par le contenu avant de fixer les
   proportions FR/EN ? Défaut proposé : oui, sans dépendance nouvelle.
5. **Suffixes** : quelle liste unique retenir ? Aucune des deux listes
   actuelles ne contient l'autre (section 2.2). Défaut proposé :
   l'intersection des deux, soit les 12 suffixes `.go .json .md .ps1 .psm1
   .py .rst .sh .toml .txt .yaml .yml`, tant qu'une autre liste n'est pas
   approuvée.
6. **Troncature** : faut-il refuser un split trop grand au lieu de le
   tronquer ? Défaut proposé : refuser.
7. **Secrets** : faut-il étendre le filtre aux catégories du scanner
   `collector-secret-scan-v1` et publier les compteurs ? Défaut proposé : oui.
8. **Attestation** : l'approbation doit-elle rester écrite par le
   matérialiseur, ou être portée par un artefact distinct du propriétaire ?
   Défaut proposé : artefact distinct.
9. **Licences** : faut-il une liste unique, nommée dans une entrée du registre
   et partagée par tous les validateurs ? Défaut proposé : oui.
