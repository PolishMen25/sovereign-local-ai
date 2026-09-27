# Inventaire des sources d'entraînement de CORE

- Statut : **PROVISOIRE** (inventaire documentaire, sans valeur d'approbation)
- Date : 2026-09-26
- Base examinée : `main` au commit `db9414d`
- Issue : #7 (gate G3)
- Documents liés : [politique de traitement candidate](corpus-processing-policy.md),
  [gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md),
  [registre des décisions](../project/decisions.md)

Cet inventaire recense chaque famille de textes qui a servi, sert ou pourrait
servir à entraîner CORE. Pour chacune, il indique l'état, l'approbateur, la
décision ou le commit de référence, la licence et le statut vis-à-vis des
données personnelles. Il n'approuve rien, ne modifie aucun statut et ne recopie
ni contenu, ni chemin interne, ni empreinte : les empreintes déjà publiées
restent dans les documents liés.

## Étiquettes employées

- **CONFIRMÉ** : vérifiable dans un fichier versionné à `db9414d`.
- **PROVISOIRE** : proposition sans validation du propriétaire.
- **OUVERT** : information absente du dépôt ou question non tranchée.
- **HYPOTHÈSE** : déduction de l'auteur, non vérifiée.

Le nœud de calcul et le stockage sont hors ligne depuis environ douze jours.
Aucun état ci-dessous n'a été revérifié en direct. Un chiffre tiré d'un message
de commit ou du point de reprise est signalé comme tel.

## 1. Vue d'ensemble

| Famille | État connu | Approbateur | Décision ou commit | Licence | Données personnelles |
| --- | --- | --- | --- | --- | --- |
| 1. Corpus initial (3 dépôts) | VALIDATED ; a servi au tokenizer `candidate_core` | propriétaire, 2026-09-07 | aucune entrée D- propre ; `b12058a`, `d6b085d` | Apache-2.0, BSD-3-Clause | non analysées |
| 2. pilote-v3 | manifeste `approved` hors Git ; a servi à CORE-30M | déclaré dans le manifeste ; aucune entrée D- | `2777407`, `de5398b`, `6d959d7` | **OUVERT** : composition non publiée ; CC-BY-4.0 présente | **OUVERT** |
| 3. Catalogue de 10 sources | RAW, candidat | non approuvé | `cb67544`, `bf690bd`, `57ccf66` | MIT, Apache-2.0, BSD-3-Clause | non analysées |
| 4. Dérivé étendu | `RAW_DERIVED_PENDING_REVIEW` | non approuvé | `0f11e9d`, `31686a1` | **OUVERT** | **OUVERT** |
| 5. Incréments synthétiques de l'arène | RAW ; promotion VALIDATED possible | propriétaire, par paquet puis par incrément | aucune entrée D- ; `229ffe0`, `689fa70`, `dbca0c6` | **OUVERT** : aucun champ de licence | non analysées ; risque jugé faible (HYPOTHÈSE) |
| 6. Candidats conversationnels | file locale et paquets candidats | D-032 pour la mise en file ; entraînement non approuvé | D-032 ; `9663a52`, `fd743c6` | **OUVERT** | données personnelles par nature ; seuls les secrets sont masqués |

## 2. Détail par famille

### 2.1 Corpus initial approuvé : requests, Flask, Moby

- **État — CONFIRMÉ** : trois archives Git figées (`psf/requests`,
  `pallets/flask`, `moby/moby`), conservées en RAW. Le manifeste validé compte
  44 enregistrements d'entraînement, 109 de validation et 2 423 de test. Il a
  servi à produire le Byte-BPE 32k promu `candidate_core` le 2026-09-07. Les
  empreintes sont publiées dans le
  [gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md).
- **Approbateur — CONFIRMÉ** : le propriétaire, le 2026-09-07, selon ce même
  document (commit `b12058a`).
- **Décision** : aucune entrée D- ne nomme ce corpus. Il relève du critère
  général de D-031. Matérialisation par l'outil introduit en `d6b085d`.
- **Licence — CONFIRMÉ** : Apache-2.0 (requests, Moby), BSD-3-Clause (Flask),
  contrôlées au niveau du dépôt.
- **Données personnelles** : non analysées. Seuls les cinq marqueurs de
  secrets du matérialiseur ont été appliqués.
  **HYPOTHÈSE** : des noms et adresses d'auteurs figurent dans les en-têtes,
  fichiers d'auteurs et journaux de modifications de ces dépôts.
- **Limite** : lot anglais technique uniquement ; le document de gate précise
  qu'il ne valide ni la couverture française ni un tokenizer final.

### 2.2 pilote-v3

- **État — CONFIRMÉ** : corpus technique bilingue matérialisé hors Git. Son
  manifeste déclare un contrat tokenizer `approved`. Les empreintes du
  manifeste et des trois splits sont publiées dans la
  [note d'adoption](../model/pilote-v3-tokenizer-adoption.md).
- **Usage — CONFIRMÉ par document daté** : d'après le
  [point de reprise](../project/claude-code-handoff.md) du 2026-09-09, la
  lignée CORE-30M pré-tokenisée a atteint 19 532 étapes sur ce corpus. Le
  checkpoint final a échoué au contrôle E1 sur une sortie répétitive.
- **Approbateur** : l'approbation est déclarée **dans le manifeste**. Aucune
  entrée du registre ne nomme pilote-v3. Depuis `6d959d7`, le préflight accepte
  ce manifeste sans fichier d'approbation distinct. Cette simplification est
  soumise au propriétaire dans le paquet G3.
- **Licence — OUVERT** : la liste des paquets et de leurs licences n'est pas
  publiée dans le dépôt. La note d'adoption indique que `CC-BY-4.0` est admise
  pour ce pilote avec provenance et attribution conservées (D-032).
- **Données personnelles — OUVERT** : aucun document du dépôt ne décrit un
  contrôle sur ce corpus.

### 2.3 Catalogue candidat de 10 sources

- **État — CONFIRMÉ** : acquis en RAW le 2026-09-08, jamais promu. La
  [politique candidate](../../configs/corpus/core-v1-source-policy.candidate.json)
  porte `status: candidate` et `catalog_status:
  candidate_requires_owner_approval`. Mesures publiées : 169 470 351 octets et
  97 396 860 tokens estimés, dont 406 893 attribués au français (0,42 %).
- **Approbateur** : non approuvé.
- **Décision ou commit** : politique `cb67544`, preuves de licence `bf690bd`,
  mesures RAW `57ccf66`. Proposition de manifeste :
  [corpus français-technique](../model/french-technical-corpus-manifest-proposal.md).
- **Données personnelles** : non analysées.

| Source | Version figée | Licence relevée | Français | Tokens estimés |
| --- | --- | --- | --- | --- |
| FastAPI | `0.115.0` | MIT | traduction embarquée | 2 342 025, dont 64 798 FR |
| Docusaurus | `v3.5.2` | MIT | aucun | 2 735 347 |
| DSFR | `v1.12.1` | MIT, fonte Marianne exclue | original | 342 095, tous comptés FR |
| Vite | `v6.0.0` | MIT | aucun | 1 059 752 |
| Nuxt | `v3.13.0` | MIT | aucun | 697 266 |
| TypeScript | `v5.6.3` | Apache-2.0 | aucun | 47 140 856 |
| PowerShell | `v7.4.5` | MIT | aucun | 6 395 388 |
| Kubernetes | `v1.31.0` | Apache-2.0 | aucun | 32 051 010 |
| Moby | `v27.2.0` | Apache-2.0 | aucun | 4 371 951 |
| Flask | `3.0.3` | BSD-3-Clause | aucun | 261 170 |

Les « tokens estimés » sont des mots et signes de ponctuation comptés à
l'acquisition, pas des tokens Byte-BPE ; voir la
[politique de traitement](corpus-processing-policy.md), section 2.8. Sources
écartées par le catalogue : Node.js (licences composites) et MDN (CC-BY-SA).

### 2.4 Dérivé étendu

- **État — CONFIRMÉ par document daté** : d'après le point de reprise du
  2026-09-09, le corpus étendu a été redécoupé en 166 421 documents
  d'entraînement, 1 690 de validation et 1 771 de test. Les 1 531 documents
  présents dans les holdouts pilote-v3 ont été retirés. Le manifeste produit
  porte `RAW_DERIVED_PENDING_REVIEW` et `automatic_promotion: false`.
- **Approbateur** : non approuvé ; aucun entraînement ne l'utilise d'après ce
  même document.
- **Commit** : outil `0f11e9d`, trace documentaire `31686a1`.
- **Licence — OUVERT** : l'origine et la composition du corpus étendu source
  ne sont décrites nulle part dans le dépôt.
- **Données personnelles — OUVERT**.
- **Blocage — CONFIRMÉ** : le point de reprise exige une reconstruction au
  niveau des paquets avant toute promotion ; le découpage actuel est par
  document.

### 2.5 Incréments synthétiques de l'arène

- **État — CONFIRMÉ** : un paquet de solutions de l'arène, approuvé par le
  propriétaire dans l'interface, devient un incrément RAW. Son manifeste
  porte `arena-corpus-increment.v1`, `classification: synthetic`,
  `max_share_in_corpus_increment: 0.20` et `training_authorization:
  not_approved`. Une approbation d'incrément déposée depuis l'interface est
  appliquée par une minuterie toutes les deux minutes. Elle écrit une copie
  VALIDATED avec `training_authorization: approved`.
- **Volumes — non revérifiés** : le message du commit `dbca0c6`
  (2026-09-13) mentionne 41 paquets, dont 2 convertis en incréments. La
  [spécification d'auto-entraînement](../model/self-training-loop-spec.md)
  cite 28 paquets réels de septembre 2026. Le nombre d'incréments promus en
  VALIDATED est **OUVERT**.
- **Approbateur** : le propriétaire, par un clic par paquet puis par incrément.
  **CONFIRMÉ** : ces approbations sont des fichiers JSON non signés. L'unité
  systemd qui les applique ne déclare aucune directive `User=` ; installée
  comme unité système, elle s'exécute donc en root.
- **Décision** : aucune entrée D-. La spécification d'auto-entraînement reste
  marquée INACTIVE. Commits `229ffe0` (pont RAW), `689fa70` (promotion
  depuis l'interface), `dbca0c6` (conversion par lot).
- **Auteurs des textes — CONFIRMÉ** : les profils auteurs de l'arène utilisent
  les moteurs QWEN-CODER et BOOTSTRAP. D-024 précise que BOOTSTRAP « ne valide
  aucun gate d'entraînement ».
- **Licence — OUVERT** : le manifeste d'incrément n'a pas de champ de
  licence ; le statut des sorties de modèles tiers est à vérifier.
- **Données personnelles** : non analysées. **HYPOTHÈSE** : risque faible,
  car les textes sont des consignes fixes et du code généré.
- **Contrat — CONFIRMÉ** : le validateur du manifeste `0.2.0` refuse
  `synthetic` avec une autorisation d'entraînement `approved`. Un incrément
  promu ne peut donc entrer dans aucun manifeste d'entraînement valide.
- **Contamination — CONFIRMÉ** : l'arène utilise par défaut la suite
  d'évaluation E2 (`configs/evaluation/core-python-e2.candidate.json`). Un
  incrément construit sur cette suite recopie donc des consignes E2 dans ses
  enregistrements. Le traitement des tâches E2 contaminées relève de la
  décision propriétaire sur l'évaluation.

### 2.6 Candidats conversationnels (D-032)

- **État — CONFIRMÉ** : les messages `user` et `assistant` assainis entrent
  dans une file locale de la mémoire privée. L'exporteur produit un répertoire
  candidat immuable marqué `pending_owner_approval` et
  `automatic_promotion=false`, sans écriture dans RAW ni VALIDATED ; voir
  [la note dédiée](../model/conversation-learning-candidates.md).
  Au déploiement du 2026-09-09, la base privée ne contenait aucune paire
  complète à exporter, selon le point de reprise. L'état actuel est
  **OUVERT**.
- **Approbateur** : D-032 autorise la mise en file automatique. Un manifeste,
  ses empreintes et le gate d'entraînement restent requis avant toute
  modification des poids ; aucun paquet n'est approuvé.
- **Commits** : export `9663a52`, reprise des anciens messages `fd743c6`.
- **Licence — OUVERT** : textes du propriétaire et réponses de modèles tiers ;
  aucune étiquette de licence n'est définie pour ce type de paquet.
- **Données personnelles** : présentes par nature. Le masquage appliqué vise
  les secrets probables, pas les données personnelles. Les identifiants sont
  pseudonymisés à l'export. Supprimer une conversation retire ses candidats ;
  un paquet antérieur doit être régénéré et réapprouvé.
- **Évolution en cours** : la PR #17, ouverte, modifie la conservation des
  révisions de conversations relayées vers RAW. Cet inventaire n'en décrit pas
  l'implémentation.

## 3. Hors inventaire

- Les identifiants synthétiques de CORE-MINI ne sont pas une source
  linguistique.
- Les suites d'évaluation E1 et E2 ne sont pas des sources d'entraînement ;
  elles doivent en rester séparées (voir 2.5).
- Les fixtures de tests et les documents du dépôt ne sont pas des sources
  d'entraînement.

## 4. Observations transverses

- **CONFIRMÉ** — Aucune famille n'a fait l'objet d'une analyse des données
  personnelles.
- **CONFIRMÉ** — La licence n'est enregistrée de façon uniforme que pour les
  familles 1 et 3.
- **HYPOTHÈSE** — Flask et Moby figurent dans la famille 1 et dans la
  famille 3 à des versions différentes. Leur contenu se recouvre probablement ;
  aucune déduplication entre familles n'existe.
- **CONFIRMÉ** — Deux familles (2 et 5) reposent sur une approbation portée par
  le manifeste lui-même ou par un JSON non signé, sans entrée au registre.
- **CONFIRMÉ** — Le français disponible en RAW se limite à la traduction de
  FastAPI et à DSFR, soit 406 893 tokens estimés. Dans un sous-échantillon de
  10 M tokens estimés, toute part de français supérieure à environ 4 % exige
  donc de nouvelles sources, par exemple sous Etalab-2.0 (D-033), ou un
  suréchantillonnage.

## 5. Questions ouvertes pour le propriétaire

Chaque question est fermée ; le défaut proposé est le plus sûr. Aucune n'est
tranchée ici.

1. pilote-v3 : faut-il publier, sans contenu, la liste de ses paquets et de
   leurs licences, puis la rattacher à une entrée du registre ? Défaut
   proposé : oui.
2. Dérivé étendu : faut-il documenter l'origine du corpus source avant toute
   reconstruction ? Défaut proposé : oui ; sans origine, pas de promotion.
3. Incréments de l'arène : restent-ils exclus de tout manifeste d'entraînement
   tant que leur classification, leur licence et leur plafond ne sont pas
   décidés ? Défaut proposé : oui.
4. Incréments construits sur E2 : faut-il les exclure de l'entraînement ?
   Défaut proposé : oui.
5. Sorties de BOOTSTRAP : sont-elles admissibles comme données d'entraînement
   malgré la formulation de D-024 ? Défaut proposé : non.
6. Candidats conversationnels : quelle étiquette de licence et quel niveau de
   filtrage des données personnelles avant un premier paquet ? Défaut
   proposé : aucun paquet avant décision.
7. Recouvrements entre familles : la déduplication entre familles devient-elle
   obligatoire ? Défaut proposé : oui.
