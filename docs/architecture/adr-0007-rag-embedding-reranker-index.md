# ADR-0007 — Moteur d'embeddings, reranker et index vectoriel du RAG

- Statut : **PROPOSÉ**
- Date : 2026-09-26
- Autorité : aucune ; en attente de validation explicite du propriétaire
- Issue : #7 (gate G3)
- Décision et orientation concernées : D-028 (confirmée), P-004 (provisoire)
- Mise à jour du 2026-09-27 : aucune des entrées D-035 à D-042, consignées
  depuis sur `main`, ne porte sur ce moteur. D-038 fait passer le projet en
  phase 1 ; un nouveau service ou port y exige toujours une décision du
  propriétaire au registre.
- Numérotation : le tri de phase 0 proposait « ADR-0006 » ; ce numéro est
  pris par l'[ADR-0006](adr-0006-research-gateway-vs-direct-deposit.md)
  (Research Gateway, PROPOSÉ). Cet ADR prend donc le numéro 0007.

Ce document décrit le choix de fait d'un moteur d'embeddings pour le RAG, les
options de reranker et d'index, et formule une recommandation provisoire. Il
ne vaut pas décision, n'ajoute aucune entrée au registre, ne modifie aucun
service ni aucune unité et ne ratifie aucun modèle. Il accompagne un lock
**candidat** dont les champs d'empreinte restent en attente.

## Étiquettes employées

- **CONFIRMÉ** : vérifiable dans le dépôt à `db9414d` (code, configuration,
  registre, ADR approuvé).
- **PROVISOIRE** : proposition sans validation du propriétaire.
- **OUVERT** : question sans réponse qui conditionne la décision.
- **HYPOTHÈSE** : appréciation ou estimation de l'auteur, non mesurée.
- **À VÉRIFIER** : licence ou caractéristique d'un artefact tiers qui n'a pas
  été relue depuis sa source.

Aucun état de déploiement n'a été revérifié en direct à la date de rédaction
(2026-09-26) ; aucune mesure n'a été faite pour cet ADR.

## 1. Contexte

### 1.1 Registre et décisions approuvées

- **CONFIRMÉ** — D-028 : un petit moteur d'embeddings RAG pré-entraîné est
  autorisé séparément de CORE, avec « acquisition contrôlée, licence et
  empreinte vérifiées, exécution locale hors ligne, aucune télémétrie ni
  ajustement implicite » ([registre](../project/decisions.md)).
- **CONFIRMÉ** — Le point 5 de l'[ADR-0004](adr-0004-core-700m-and-zone-split.md),
  approuvé, exige un moteur « acquis dans la zone externe, figé par empreinte
  et licence, puis exécuté hors ligne ». Ses poids ne font pas partie de CORE.
- **CONFIRMÉ** — P-004 : architecture hybride partiellement confirmée ; « le
  reranker et le moteur d'index restent à valider par benchmark ».
- **CONFIRMÉ** — La [feuille de route](../ROADMAP.md) prévoit pour J3 un ADR
  sur le moteur d'embeddings et l'éventuel reranker, ainsi qu'une comparaison
  CPU des index vectoriels avec un plan de sauvegarde et de reconstruction.
- **CONFIRMÉ** — La liste « Décisions ouvertes majeures » du registre pose
  encore la question d'un moteur pré-entraîné, déjà tranchée par D-028. Seul
  le propriétaire peut corriger le registre.

### 1.2 Choix de fait : commit `d7cc78c`

- **CONFIRMÉ** — Le commit `d7cc78c` (2026-09-13), écrit par un agent, a
  intégré Qwen3-Embedding-0.6B quantifié Q8_0, en 1 024 dimensions, servi par
  llama.cpp en mode embedding. Il ajoute
  [`services/web/embed_client.py`](../../services/web/embed_client.py),
  l'unité [`infra/embed/sovereign-embed.service`](../../infra/embed/sovereign-embed.service)
  et [`tools/reembed_validated_chunks.py`](../../tools/reembed_validated_chunks.py).
- **CONFIRMÉ** — Aucun lock, reçu de promotion, entrée au registre ni ADR
  n'accompagne ce choix. Aucune empreinte, taille, révision amont ni preuve de
  licence de l'artefact n'est consignée dans le dépôt. À comparer avec le
  [lock Qwen-Coder](../../configs/runtime/qwen2.5-coder-7b-q4km.lock.json) et
  son reçu de promotion.
- **À VÉRIFIER** — La licence `Apache-2.0` n'est affirmée que dans la
  docstring du client et le message de commit.
- **CONFIRMÉ** — Quatre documents disent encore qu'aucun moteur d'embeddings
  n'est installé, ou qu'aucun moteur vérifié ne l'est :
  `current-capabilities.md`, `deployment-status-public.md`,
  `services/knowledge/README.md` et `services/web/README.md`. Leur
  rafraîchissement relève d'autres tâches.
- **OUVERT** — Le déploiement réel n'est attesté par aucun relevé versionné.

### 1.3 Comportement du code à `db9414d`

**CONFIRMÉ par lecture du code :**

- Le client n'accepte qu'un point de terminaison HTTP sur la boucle locale,
  avec un port explicite, sans chemin, identifiant, requête ni fragment. Il
  désactive les proxys et refuse les redirections. Il borne la réponse à
  4 000 000 octets, tronque l'entrée à environ 8 000 caractères et borne la
  dimension à 1 024 ; il
  refuse une valeur non finie ou une norme nulle.
- Une requête reçoit une consigne de recherche en préfixe ; un document est
  encodé tel quel. Toute erreur lève une exception, et l'appelant se replie sur
  la recherche lexicale.
- La passerelle lit `SOVEREIGN_EMBED_ENDPOINT`. Si la variable est absente,
  elle utilise un point de terminaison loopback par défaut : la recherche
  dense est donc active par défaut. Seule une affectation explicitement vide
  désactive le client. L'outil de réindexation applique le même défaut.
- Quand le client est actif, la passerelle encode chaque chunk à l'ingestion
  d'un document (1 200 caractères au plus, 400 chunks au plus par document) et
  la requête de chat ou de l'outil `search_knowledge`.
- [`HybridKnowledgeIndex`](../../services/knowledge/hybrid_index.py) stocke
  chaque vecteur en float32 petit-boutiste dans un BLOB SQLite. La recherche
  hybride prend jusqu'à 100 candidats lexicaux FTS5 (bm25). Elle balaie ensuite
  **tous** les vecteurs de même dimension en Python pur et calcule
  `0,45 × score lexical + 0,55 × (cosinus + 1) / 2`, où le score lexical vaut
  `1 / (1 + rang)`. Ces poids ne proviennent d'aucune mesure.
- Une requête dont tous les termes sont des mots vides renvoie un résultat
  vide, même si un vecteur de requête est fourni.
- L'index entier, vecteurs compris, tient dans un seul fichier SQLite que
  [`backup_knowledge_index.py`](../../tools/backup_knowledge_index.py)
  sauvegarde, vérifie et restaure. Les vecteurs se reconstruisent depuis les
  chunks validés avec `reembed_validated_chunks.py`.

### 1.4 Unité de service

**CONFIRMÉ par lecture de l'unité :** llama.cpp en mode embedding, pooling
`last`, contexte de 8 192, 8 threads, aucune couche GPU, écoute sur la boucle
locale, option `--offline`, utilisateur non privilégié. Contrairement à l'unité
BOOTSTRAP, elle ne déclare ni `NoNewPrivileges`, ni `PrivateTmp`, ni
`ProtectHome`, ni `ProtectSystem`. Aucune des deux ne restreint les familles
d'adresses ni les destinations réseau.

## 2. Critères

| Critère | Question |
| --- | --- |
| Gouvernance | L'artefact est-il figé par empreinte, révision et licence relues (D-028, ADR-0004) ? |
| Qualité de rappel | Le rappel français, anglais et code est-il mesuré sur un jeu d'or ? |
| Volume | Jusqu'à combien de chunks la latence reste-t-elle acceptable ? |
| Sauvegarde et reconstruction | L'index tient-il dans l'artefact déjà sauvegardé, et se reconstruit-il depuis les chunks validés ? |
| Sécurité | Aucun port réseau nouveau ; surface d'analyse d'un fichier tiers ; isolation du processus. |
| Maintenance | Nombre de composants, formats et versions à suivre. |
| Dépendances CPU | Bibliothèque standard, ou code natif tiers à verrouiller ? |
| Exactitude | Recherche exacte ou approximative ? |

## 3. Options

### 3.1 Moteur d'embeddings

| Option | Contenu | Points forts | Points faibles |
| --- | --- | --- | --- |
| E0 | Lexical seul, sans embeddings | Aucun artefact tiers ; déjà fonctionnel | **HYPOTHÈSE** : rappel faible sur les reformulations et entre langues |
| E1 | Qwen3-Embedding-0.6B Q8_0, choix de fait | Déjà intégré ; client strict ; repli lexical | Aucun lock ni empreinte ; licence **à vérifier** ; qualité non mesurée |
| E2 | Autre petit modèle multilingue local, par exemple des familles multilingual-E5 ou BGE-M3 | Comparaison possible sur le même jeu d'or | Nouvelle acquisition, nouveau lock, réindexation ; licences et tailles **à vérifier** |
| E3 | Modèle d'embeddings créé de zéro | Contrôle total | Hors de portée : ni corpus, ni évaluation, ni budget ; D-028 autorise déjà un modèle pré-entraîné |

### 3.2 Reranker

| Option | Contenu | Conséquences |
| --- | --- | --- |
| R0 | Aucun reranker (état actuel) | Aucun coût ; le classement dépend des poids fixes. |
| R1 | Petit cross-encoder local sur la boucle locale, par exemple des familles Qwen3-Reranker ou BGE-reranker | Une passe du modèle par couple requête-candidat : la latence croît avec le nombre de candidats. Nouvel artefact à verrouiller ; licences **à vérifier** ; prise en charge par la version de llama.cpp déclarée **à vérifier**. |
| R2 | Pas de modèle ; fusion par rang (RRF) ou poids mesurés | Aucun artefact ; exige un jeu d'or pour régler la fusion. |

### 3.3 Index vectoriel

| Option | Contenu | Exact | Dépendance nouvelle | Sauvegarde | Port |
| --- | --- | --- | --- | --- | --- |
| I1 | SQLite, balayage exhaustif en Python pur (actuel) | oui | aucune | un seul fichier, déjà couvert | aucun |
| I1b | Même stockage, score vectorisé en bloc | oui | bibliothèque numérique dans le sas ; présence **à vérifier** (NumPy est verrouillé côté CORE) | inchangée | aucun |
| I2 | sqlite-vec, extension chargeable de SQLite | oui ou approché selon le mode | code natif ; `sqlite3` doit autoriser le chargement d'extensions (**à vérifier**) | un seul fichier | aucun |
| I3 | FAISS-cpu | selon l'index | bibliothèque native lourde, avec NumPy | fichier d'index séparé à sauvegarder ou reconstruire | aucun |
| I4 | hnswlib | non (approché) | code natif | fichier séparé | aucun |
| I5 | Serveur vectoriel dédié | selon le produit | service complet | procédure propre | **oui** : exclu sans décision du propriétaire au registre, qu'exige tout nouveau service ou port |

## 4. Estimation statique du balayage exhaustif

**ESTIMATION — aucune de ces valeurs n'est mesurée.** Elle porte sur le seul
calcul du cosinus de l'option I1, hors encodage de la requête et hors SQL.

Hypothèses :

- 1 024 dimensions en float32, soit 4 096 octets de vecteur par chunk ;
- une multiplication-addition par dimension dans une expression génératrice
  CPython ;
- **HYPOTHÈSE** : 50 à 150 ns par multiplication-addition sur un cœur CPU
  généraliste, décodage `struct` compris.

| Chunks | Octets de vecteurs lus | Multiplications-additions | Temps de calcul estimé |
| --- | --- | --- | --- |
| 1 000 | 4 096 000 (≈ 4,1 Mo) | 1 024 000 | 0,05 à 0,15 s |
| 10 000 | 40 960 000 (≈ 41 Mo) | 10 240 000 | 0,5 à 1,5 s |
| 100 000 | 409 600 000 (≈ 410 Mo) | 102 400 000 | 5 à 15 s |
| 1 000 000 | 4 096 000 000 (≈ 4,1 Go) | 1 024 000 000 | 51 à 154 s |

Repère de volume : un document de taille maximale produit au plus 400 chunks,
donc 25 documents de ce type suffisent à atteindre 10 000 chunks.

**HYPOTHÈSE** — Le balayage en Python pur reste acceptable pour une session
interactive jusqu'à quelques milliers de chunks. Au-delà d'environ 10 000, il
devient le coût dominant. Le seuil réel doit être mesuré au volume réel, avec
médiane, dispersion et période de chauffe, conformément à `AGENTS.md`.

## 5. Menaces et points de sécurité

- **Artefact tiers** : un fichier GGUF est une entrée non fiable, analysée par
  le runtime. Sans empreinte figée, une substitution de fichier passe
  inaperçue ; c'est l'objet du lock candidat.
- **Oracle local** : le point de terminaison loopback n'a pas
  d'authentification ; tout processus local du même invité peut l'interroger.
  **HYPOTHÈSE** : risque faible tant que l'invité n'héberge que des services
  du projet.
- **Contenu empoisonné** : un chunk validé mais hostile peut influencer le
  classement. La confiance se décide à la promotion, pas à l'indexation. Les
  documents téléversés entrent aujourd'hui dans le même index ; leur statut
  relève d'une décision propriétaire distincte.
- **Déni de service** : la requête est bornée à 500 caractères et à 20
  résultats, mais le balayage croît avec le nombre de chunks (section 4).
- **Durcissement** : l'unité d'embeddings est moins restreinte que l'unité
  BOOTSTRAP (section 1.4).

## 6. Recommandation

**PROVISOIRE** — Aucune option n'est retenue par ce document.

1. Garder E1 comme **candidat** et ne pas le ratifier avant la relecture
   matérielle : empreinte, taille, révision amont, licence, écoute locale et
   absence de sortie réseau. Le lock candidat reste refusé jusque-là.
2. Avant tout nouvel usage, recherche lexicale seule tant que la relecture
   n'est pas faite : `SOVEREIGN_EMBED_ENDPOINT` explicitement vide, pas
   seulement absente, puisqu'une variable absente active le client sur son
   défaut loopback (section 1.3). Ratification ensuite si la relecture
   concorde.
3. R0 tant qu'un banc de recherche — recall@k, MRR et nDCG en modes lexical,
   vectoriel et hybride, avec balayage des poids — ne montre pas de gain.
4. I1 tant qu'une mesure au volume réel reste sous un budget de latence à
   fixer par le propriétaire. Ensuite, examiner d'abord I1b ou I2, qui
   conservent la sauvegarde en un seul fichier, avant I3 ou I4. I5 reste
   exclu sans décision du propriétaire au registre.
5. Aligner l'unité d'embeddings sur les restrictions de l'unité BOOTSTRAP. Ce
   changement de déploiement relève du propriétaire et n'est pas fait ici.

## 7. Conséquences

Si le propriétaire accepte cet ADR :

- une entrée au registre, au prochain numéro libre, ratifie le modèle comme
  instance de D-028 et met à jour P-004 ;
- le lock candidat devient un lock réel, accompagné d'un reçu de promotion sur
  le modèle de Qwen-Coder ;
- les quatre documents cités en 1.2 sont alignés ;
- toute dépendance nouvelle d'index passe par un lock et une provenance
  vérifiée.

S'il le refuse, E0 s'applique : `SOVEREIGN_EMBED_ENDPOINT` explicitement vide
(pas seulement absente), vecteurs conservés mais inutilisés, et le lock
candidat reste non activable.

## 8. Conditions de révision

- volume mesuré au-delà du budget de latence ;
- nouvelle révision amont ou changement de licence du modèle ;
- résultat du banc de recherche, avec ou sans reranker ;
- dépendance native approuvée pour l'index ;
- déplacement de l'index hors du fichier SQLite de la passerelle ;
- modification de D-028 ou du statut des documents téléversés.

## 9. Questions au propriétaire

Chaque question est fermée ; le défaut proposé est le plus sûr.

1. Ratifier Qwen3-Embedding-0.6B Q8_0 comme instance de D-028 ? Défaut : non
   avant relecture de l'empreinte et de la licence.
2. Suspendre la recherche dense jusqu'à cette relecture, par une valeur
   explicitement vide de `SOVEREIGN_EMBED_ENDPOINT` ? Défaut : oui.
3. Ajouter un reranker ? Défaut : non avant mesure d'un gain.
4. Quel budget de latence p95 déclenche une réévaluation de l'index ?
   Défaut : aucun changement d'index avant mesure.
5. Autoriser une dépendance native d'index ? Défaut : non sans lock ni
   provenance.
6. Durcir l'unité d'embeddings comme l'unité BOOTSTRAP ? Défaut : oui.
7. Garder les poids 0,45/0,55 jusqu'à la mesure ? Défaut : oui, comme valeurs
   non validées.

## 10. Lock candidat

[`configs/runtime/qwen3-embedding-0.6b-q8_0.lock.candidate.json`](../../configs/runtime/qwen3-embedding-0.6b-q8_0.lock.candidate.json)
décrit l'artefact attendu. Ses champs `sha256`, `byte_size`, `revision`,
dépôt, nom de fichier, licence et preuves valent `pending_raw_readback`. Son
reçu de promotion et la ratification valent `pending_*`. Son statut est
`candidate_pending_raw_readback`, son ADR est `proposed` et son état de
déploiement `unverified_no_readback`.

[`tests/test_embedding_model_lock.py`](../../tests/test_embedding_model_lock.py)
applique une vérification d'activation qui refuse :

- toute valeur commençant par `pending`, sans tenir compte de la casse ;
- un statut autre que `promoted_owner_approved`, un objet autre que
  l'embedding RAG séparé de CORE, et un état de déploiement autre que
  `verified_by_readback` ;
- un ADR non accepté : `adr_status` autre que `accepted`, ou chemin qui ne
  désigne pas un fichier `docs/architecture/adr-NNNN-*.md` existant dans le
  dépôt, ou ADR encore marqué PROPOSÉ ;
- une ratification qui ne cite pas une entrée unique et non remplacée du
  registre ; le registre est seulement lu ;
- une empreinte, une taille ou une révision mal formées ;
- un contexte hors de 1 à 32 768 tokens, ou un pooling hors de `cls`, `last`
  et `mean` ;
- un drapeau de la porte d'activation désactivé ;
- une politique d'exécution autre que CPU, hors ligne et loopback ;
- un reçu de promotion absent, qui n'est pas un JSON strict (taille bornée,
  clés en double et valeurs non finies refusées), ou qui ne reprend pas
  exactement l'empreinte, la taille et la révision du lock et sa ratification.

Le test prouve aussi qu'un lock complet et synthétique, accompagné d'un ADR,
d'un registre et d'un reçu synthétiques dans un répertoire temporaire, passe
cette vérification. Le refus n'est donc pas trivial. Le format complet du reçu
de promotion reste à fixer avec la ratification ; le test n'en exige que les
champs liés au lock.

**CONFIRMÉ** — Aucune unité ni aucun service ne lit ce lock : la vérification
est un contrôle du dépôt, pas une barrière d'exécution. Brancher une
vérification au démarrage du runtime serait un changement de déploiement,
hors du périmètre d'un agent tant que le propriétaire n'a pas régularisé ce
moteur.
