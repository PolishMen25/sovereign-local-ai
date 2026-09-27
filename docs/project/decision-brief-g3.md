# Note de décision G3 — corpus, tokenizer et embeddings RAG

- Statut : **PROVISOIRE** (matériau de décision pour le propriétaire) ; les
  sujets 1, 2, 4 et 5 ont été tranchés depuis, voir la
  [mise à jour du 2026-09-27](#mise-à-jour-du-2026-09-27)
- Date : 2026-09-26 ; mise à jour le 2026-09-27
- Base examinée : `main` au commit `db9414d`
- Issue : #7 (gate G3)
- Entrées factuelles : [politique de traitement candidate](../data/corpus-processing-policy.md),
  [inventaire des sources](../data/training-sources-inventory.md)

Cette note rassemble sept décisions que seul le propriétaire peut prendre.
Pour chacune, elle présente le constat, les options, leurs conséquences, les
preuves et une recommandation **PROVISOIRE**. Rien n'y est décidé. Le
[registre](decisions.md) reste inchangé. Aucun numéro `D-` n'est réservé : le
propriétaire attribue le prochain numéro libre au moment où il consigne une
décision. Aucun agent ne crée `core-v1-source-policy.approved.json`.

Étiquettes : **CONFIRMÉ** (vérifiable dans le dépôt), **PROVISOIRE**
(proposition non validée), **OUVERT** (non tranché), **HYPOTHÈSE** (déduction
non mesurée). Aucun état n'a été revérifié en direct à la date de rédaction
(2026-09-26).

## Mise à jour du 2026-09-27

Après la rédaction de cette note, le propriétaire a consigné D-035 à D-042 au
[registre](decisions.md) de `main` (commits `8eb9c07` et `5e28408`). La note
n'est pas réécrite : les sections 1 à 7 restent la trace du matériau présenté.
Leurs recommandations sont caduques là où une entrée tranche.

| # | Sujet | État | Reste ouvert |
| --- | --- | --- | --- |
| 1 | Gate `approved.json` | **CONFIRMÉ** — D-039 ratifie le retrait (proche de l'option A) : un manifeste `VALIDATED` produit par la politique automatique versionnée et auditée autorise une version de corpus, avec un acteur de politique journalisé et une révocation possible avant consommation. L'option C recommandée ici n'est pas retenue. | Mise en œuvre de la journalisation et de la révocation, non vérifiée par cette note. Alignement du README, de la spécification d'auto-entraînement et du gate corpus. Sort de `verify_corpus_approval.py`. |
| 2 | Proportions du corpus | **CONFIRMÉ** — D-041 fixe environ 40 % de français technique, au-delà des options chiffrées de la section 2, et impose l'acquisition de sources françaises sous licence admise par le flux contrôlé. | **OUVERT** : taille du sous-échantillon, plafond par source, répartition entre code et anglais technique, unité de mesure de la part. |
| 3 | Politique de traitement | **OUVERT** — D-039 fixe le cadre (politique, seuils et code versionnés ; modification par PR revue avec CI verte) sans choisir aucun axe de la section 3. | Tous les axes de la section 3. |
| 4 | Tokenizer | **CONFIRMÉ** — D-042 : réentraînement sur le corpus final (proche de l'option C) ; 32 000 unités, 4 tokens spéciaux et contexte 2 048 conservés ; acceptation sur métriques mesurées (octets par token et tokens par mot en français, anglais et code, aller-retour exact). La lignée CORE-30M reste attachée à l'ancien tokenizer. | **OUVERT** : valeurs numériques des seuils d'acceptation. Le corpus final dépend du sujet 2. |
| 5 | Données synthétiques | **CONFIRMÉ** — D-040 : admissibles, limitées au code de Qwen2.5-Coder dont chaque solution est validée par ses tests en bac à sable, étiquetées synthétiques, sans recouvrement avec les jeux d'évaluation ; plafond de 20 % des tokens d'une version de corpus ; sorties de BOOTSTRAP exclues ; conflit entre `promote_arena_increment` et `validate_training_corpus_manifest` résolu en faveur de cette règle (proche de l'option B). | Alignement des validateurs, application du plafond à l'assemblage et contrôle du recouvrement avec E2 : travail postérieur à l'entrée, non fait ici. |
| 6 | `0BSD`, `Unlicense`, `verified-public-domain` | **OUVERT** — D-041 mentionne des licences « permissives » sans les nommer ; aucune entrée ne nomme ces trois valeurs. | Toute la section 6. |
| 7 | Embeddings, reranker, index | **OUVERT** — aucune entrée ne porte sur ce moteur. Le nouvel `AGENTS.md` (`4775afb`) le range parmi les composants à régulariser, sans lock ni reçu de promotion. | Toute la section 7 et l'ADR-0007. |

**HYPOTHÈSE** — Conséquence chiffrée du sujet 2, calculée sur les mesures RAW
publiées de la section 2, en supposant une part mesurée en tokens estimés et
un sous-échantillon maintenu à 10 M : 40 % représentent 4 000 000 tokens de
français, soit 3 593 107 de plus que le disponible. Un suréchantillonnage seul
imposerait un facteur d'environ 9,8. L'acquisition prescrite par D-041 est donc
indispensable avant toute matérialisation à cette proportion.

**CONFIRMÉ** — Les incréments construits sur la suite E2 recopient des
consignes E2 ([inventaire](../data/training-sources-inventory.md), section
2.5). D-040 exige l'absence de recouvrement avec les jeux d'évaluation : ces
incréments ne satisfont pas cette condition en l'état.

D-035 à D-038 ne portent pas sur G3. D-038 fait passer le projet en phase 1.

## Synthèse

| # | Décision | Recommandation PROVISOIRE | Dépendances |
| --- | --- | --- | --- |
| 1 | Gate `approved.json` retiré par `6d959d7` | Ratifier le manifeste comme gate unique, avec une attestation distincte du propriétaire | aucune |
| 2 | Proportions du corpus et sous-échantillon d'environ 10 M | Viser 10 % de français avec de nouvelles sources vérifiées ; plafond par source | 3 |
| 3 | Politique de traitement | Split par paquet, quasi-doublons, masquage des données personnelles, refus de troncature | aucune |
| 4 | Tokenizer canonique, tokens spéciaux, contexte | Pas de tokenizer canonique avant métriques ; 4 tokens spéciaux ; 2 048 confirmé comme candidat | 2, 3 |
| 5 | Données synthétiques de modèles tiers | Inadmissibles tant qu'une classification plafonnée n'est pas définie | évaluation E2 |
| 6 | `0BSD`, `Unlicense`, `verified-public-domain` | Une liste unique consignée ; `0BSD` admise, les deux autres suspendues jusqu'à relecture | aucune |
| 7 | Qwen3-Embedding-0.6B, reranker, index | Ratification seulement après relecture de l'empreinte ; aucun reranker avant mesure | matériel |

## 1. Gate d'approbation du corpus

### Constat

- **CONFIRMÉ** — Le commit `6d959d7` (2026-09-08, « Simplify approved corpus
  and learning queue ») retire l'appel à `verify_corpus_approval()` du
  [préflight tokenizer](../../tools/preflight_core_700m_tokenizer.py). Le
  fichier `core-v1-source-policy.approved.json` n'est plus exigé : un
  manifeste `VALIDATED` suffit, selon le
  [gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md).
- **CONFIRMÉ** — Ce même commit ajoute D-032 au registre, mais aucune entrée
  ne consigne le retrait du gate.
- **CONFIRMÉ** — Le [README](../../README.md) et la section 4 de la
  [spécification d'auto-entraînement](../model/self-training-loop-spec.md)
  affirment encore que `approved.json` est requis.
- **CONFIRMÉ** — Le matérialiseur écrit lui-même les approbations dans le
  manifeste qu'il produit ([politique](../data/corpus-processing-policy.md),
  section 2.10). Depuis `6d959d7`, aucune trace d'approbation distincte de ce
  manifeste n'est exigée.
- **CONFIRMÉ** — [`verify_corpus_approval.py`](../../tools/verify_corpus_approval.py)
  survit comme audit optionnel, avec une liste de licences plus stricte que
  celle du validateur de manifeste.

### Options

| Option | Contenu | Conséquences |
| --- | --- | --- |
| A. Ratifier | Le manifeste `VALIDATED` est le gate unique. | Couvre a posteriori l'usage de pilote-v3. README et spécification à aligner. L'approbation reste celle que l'outil écrit ; aucune trace indépendante du propriétaire. Sort de `verify_corpus_approval.py` à décider. |
| B. Annuler | Rétablir l'appel au vérificateur et exiger `approved.json`. | Le préflight refuse tout lancement tant que le propriétaire n'a pas commité le fichier. Ce fichier lie le catalogue de 10 sources, pas pilote-v3 : il faudrait étendre son schéma. Changement de code et de tests ; liste de licences du vérificateur à aligner d'abord. |
| C. Ratifier avec attestation | Le manifeste reste le gate technique. L'empreinte SHA-256 de chaque manifeste d'entraînement doit être nommée par le propriétaire dans une entrée du registre ou un artefact signé, hors du manifeste. | Ferme l'écart d'une approbation écrite par l'outil lui-même. Le document de gate le fait déjà pour le corpus initial. Il faudrait nommer l'empreinte du manifeste pilote-v3. Le contrôle automatique de cette attestation est un travail ultérieur. |

### Recommandation PROVISOIRE

Option C. Le catalogue de 10 sources et les incréments synthétiques
n'exigeraient alors plus `approved.json`, mais un manifeste et son
attestation. README et spécification seraient alignés après la décision, pas
avant.

## 2. Proportions du corpus et sous-échantillon

### Constat

- **CONFIRMÉ** — Le RAW du catalogue totalise 97 396 860 tokens estimés, dont
  406 893 attribués au français (0,42 %). Le catalogue candidat vise environ
  10 M tokens ([politique candidate](../../configs/corpus/core-v1-source-policy.candidate.json)).
- **CONFIRMÉ** — TypeScript (47,1 M) et Kubernetes (32,1 M) représentent à
  eux deux 81 % du RAW estimé.
- **CONFIRMÉ** — Ces tokens sont des mots comptés par expression régulière,
  pas des tokens Byte-BPE. Le français compté inclut tout le code de DSFR.
- **HYPOTHÈSE** — Le matérialiseur écarterait l'essentiel du code TypeScript,
  JavaScript et HTML ([politique](../data/corpus-processing-policy.md),
  section 2.2). Le volume matérialisable n'est pas mesuré.
- **CONFIRMÉ** — D-033 autorise l'ajout de sources françaises sous
  Etalab-2.0 après vérification du texte de licence.
- **CONFIRMÉ** — Le dérivé étendu (166 421 documents d'entraînement selon le
  point de reprise) reste non approuvé. Son origine n'est pas documentée et
  son découpage par document viole la règle du manifeste `0.2.0`.

### Options pour un sous-échantillon de 10 M tokens estimés

| Option | Part de français | Français requis | Écart avec le disponible | Moyen |
| --- | --- | --- | --- | --- |
| A | environ 4 % | 406 893 | 0 | tout le français disponible, sans répétition |
| B | 5 % | 500 000 | 93 107 | suréchantillonnage ×1,23 ou petite source nouvelle |
| C | 10 % | 1 000 000 | 593 107 | nouvelles sources Etalab-2.0 ou permissives ; sinon suréchantillonnage ×2,46 |
| D | 20 % | 2 000 000 | 1 593 107 | acquisition importante ; sinon suréchantillonnage ×4,92 |

Conséquences communes :

- **HYPOTHÈSE** — Au-delà d'un facteur 2, le suréchantillonnage répète les
  mêmes textes et favorise la mémorisation plutôt que la langue.
- Toute nouvelle source exige une vérification de licence avant acquisition.
  L'acquisition est une opération ponctuelle hors de CORE, à planifier par le
  propriétaire.
- Les proportions doivent être remesurées avec le tokenizer de référence
  (décision 4) avant d'être figées.
- Un plafond par source (par exemple 15 ou 25 % du sous-échantillon, valeur
  **PROPOSÉE**) évite qu'un seul dépôt domine.

Pour le dérivé étendu, deux options : ne rien approuver avant documentation
de son origine et reconstruction par paquet, ou l'approuver en l'état, ce que
le validateur refuserait.

### Recommandation PROVISOIRE

Option C, sans suréchantillonnage supérieur à ×2. Les nouvelles sources
françaises seraient listées avec leur licence avant toute acquisition. Le
plafond par source serait fixé par le propriétaire. Le plan serait produit par
un planificateur déterministe et approuvé par son empreinte. Le dérivé étendu
ne serait pas approuvé en l'état.

## 3. Politique de traitement

### Constat

La [politique candidate](../data/corpus-processing-policy.md) décrit l'état
implémenté et ses lacunes. **CONFIRMÉ** : déduplication exacte partielle,
aucun quasi-doublon, split par document pour le dérivé étendu, aucun détecteur
de données personnelles, langue attribuée par répertoire, 5 marqueurs de
secrets sans compteur, troncature à 16 Mio.

**CONFIRMÉ** — Le matérialiseur accepte plusieurs sources pour un même split
sans le signaler : la dernière écrase les autres, et le manifeste attribue le
split à la première tout en listant toutes les sources. Le validateur `0.2.0`
refuse ensuite ce manifeste, s'il est lancé. Un découpage par paquet avec plus
de trois paquets exige donc d'abord ce correctif
([politique](../data/corpus-processing-policy.md), section 2.5).

### Options par axe

| Axe | Options | Conséquences |
| --- | --- | --- |
| Déduplication | exacte seule / exacte et quasi-doublons | Les quasi-doublons exigent un outil et un seuil mesuré ; sans eux, les versions voisines d'un même dépôt restent répétées. |
| Découpage | par document / par paquet | Le manifeste `0.2.0` impose déjà le paquet ; le dérivé étendu doit être reconstruit, et le matérialiseur corrigé pour placer plusieurs paquets dans un split. |
| Données personnelles | aucun filtre / masquage / exclusion du fichier | Le masquage conserve le code, l'exclusion réduit le volume ; les deux exigent un compteur. |
| Langue | par répertoire / par contenu | L'attribution par contenu est nécessaire pour mesurer les proportions de la décision 2. |
| Secrets | 5 marqueurs / catégories étendues et compteurs | L'extension réduit le risque de fuite et rend l'effet auditable. |
| Troncature | tronquer / refuser | Le refus évite un biais alphabétique silencieux. |

### Recommandation PROVISOIRE

Déduplication exacte et quasi-doublons, découpage par paquet, masquage des
données personnelles avec compteur, langue identifiée par le contenu,
catégories de secrets étendues avec compteurs, refus de troncature. La
politique passerait de PROVISOIRE à approuvée par une entrée du registre.

## 4. Tokenizer canonique, tokens spéciaux et contexte

### Constat

- **CONFIRMÉ** — Deux artefacts Byte-BPE de 32 000 unités coexistent :
  - le `candidate_core` du 2026-09-07, appris sur les 44 enregistrements
    d'entraînement du corpus initial, anglais uniquement, avec un seuil de
    fréquence de 1. Ses empreintes sont publiées dans le
    [gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md) ;
  - le tokenizer lié à pilote-v3, utilisé par CORE-30M
    ([note d'adoption](../model/pilote-v3-tokenizer-adoption.md)). Son
    empreinte n'est pas publiée dans le dépôt.
- **CONFIRMÉ** — La [configuration candidate](../../configs/tokenizers/byte-bpe-v0.candidate.json)
  déclare quatre tokens spéciaux (`<pad>`, `<bos>`, `<eos>`, `<unk>`) et NFC.
  Le module tokenizer fixe leurs identifiants de 0 à 3. `approved_core_v1`
  est réservé à une décision ultérieure.
- **CONFIRMÉ** — Le contexte de 2 048 tokens figure dans les configurations
  CORE-30M et CORE-700M et dans l'[ADR-0004](../architecture/adr-0004-core-700m-and-zone-split.md),
  approuvé pour CORE-700M.
- **CONFIRMÉ** — D-034 exclut tout objectif conversationnel pour CORE-30M.
  Aucun token de rôle n'est donc nécessaire aujourd'hui.
- **CONFIRMÉ** — Aucun outil d'évaluation du tokenizer n'existe dans le
  dépôt : ni fertilité français/anglais/code, ni utilisation du vocabulaire.

### Options

| Option | Contenu | Conséquences |
| --- | --- | --- |
| A | Désigner le tokenizer pilote-v3. | Continuité avec CORE-30M ; son empreinte doit d'abord être publiée ; qualité non mesurée. |
| B | Désigner le `candidate_core` du 2026-09-07. | **HYPOTHÈSE** : peu représentatif, car appris sur 44 enregistrements anglais avec un seuil de 1. |
| C | Aucun canonique avant métriques. | Réentraîner sur le corpus bilingue final (décisions 2 et 3) et comparer plusieurs tailles de vocabulaire sur un même split held-out. Retarde G3, mais fonde les seuils sur une mesure. |

Tokens spéciaux : conserver les quatre, ou ajouter des tokens de rôle, ce qui
supposerait un objectif conversationnel contraire à D-034. Contexte :
confirmer 2 048, ou changer la configuration avec son comptage exact et ses
tests.

### Recommandation PROVISOIRE

Option C, avec le tokenizer pilote-v3 comme référence provisoire pour la
continuité de CORE-30M. Conserver les quatre tokens spéciaux et 2 048 comme
contexte candidat. Aucune promotion `approved_core_v1` sans une entrée du
registre qui nomme l'empreinte, les seuils d'acceptation (octets par token en
français et en anglais), les tokens spéciaux et le contexte.

## 5. Données synthétiques issues de modèles tiers

### Constat

- **CONFIRMÉ** — Les profils auteurs de l'arène utilisent QWEN-CODER
  (Qwen2.5-Coder-7B) et BOOTSTRAP (Qwen2.5-1.5B). D-024 précise que BOOTSTRAP
  « ne valide aucun gate d'entraînement ». D-013 place tokenizer, architecture,
  dataset et entraînement sous contrôle local.
- **CONFIRMÉ** — [`promote_arena_increment.py`](../../tools/promote_arena_increment.py)
  écrit `classification: synthetic` avec `training_authorization: approved`.
  [`validate_training_corpus_manifest.py`](../../tools/validate_training_corpus_manifest.py)
  refuse cette combinaison. Aucun chemin contractuel ne mène donc à un
  manifeste d'entraînement.
- **CONFIRMÉ** — Le plafond de 20 % n'est qu'un champ déclaré dans les
  incréments ; aucun outil ne l'applique au moment d'assembler un corpus.
- **CONFIRMÉ** — L'arène utilise par défaut la suite d'évaluation E2 : ses
  incréments recopient des consignes E2.
- **CONFIRMÉ** — La [spécification d'auto-entraînement](../model/self-training-loop-spec.md)
  reste marquée INACTIVE, alors que des commits décrivent une arène qui
  produit des paquets. Son fonctionnement actuel n'est pas revérifié.
- **OUVERT** — Aucune étiquette de licence n'est définie pour ces textes.

### Options

| Option | Contenu | Conséquences |
| --- | --- | --- |
| A. Inadmissible | Aucune donnée synthétique de modèle tiers dans CORE ; l'arène reste un outil d'évaluation et d'entraînement des agents. | Aucun changement de validateur. La promotion d'incréments devient sans usage pour CORE et pourrait être gelée. |
| B. Admissible restreinte | Seules les solutions QWEN-CODER vérifiées par tests, hors tâches E2 ; nouvelle classification plafonnée ; licence déclarée ; BOOTSTRAP exclu. | Entrée au registre, changement du validateur avec plafond appliqué au mélange, champ de licence dans les incréments, tests. Dépend de la décision sur l'évaluation E2. |
| C. Admissible large | Tous les auteurs, BOOTSTRAP compris, plafond de 20 %. | Contredit la formulation de D-024, qu'il faudrait amender. Mêmes changements techniques que B. |

### Recommandation PROVISOIRE

Option A tant que les conditions de l'option B ne sont pas réunies : décision
sur les tâches E2 contaminées, entrée au registre définissant classification,
licence, plafond et point d'entrée dans le manifeste. Le validateur ne doit
pas être assoupli avant cette entrée.

## 6. Licences `0BSD`, `Unlicense` et `verified-public-domain`

### Constat

- **CONFIRMÉ** — `0BSD` et `Unlicense` figurent depuis `cb67544`
  (2026-09-07) dans la politique candidate et son validateur. Elles figurent
  dans le validateur de manifeste depuis `6d959d7`. Elles sont absentes de la
  liste `acquisition_guard` du fichier candidat, mais acceptées par son
  validateur (contrôle d'inclusion), et absentes de
  `verify_corpus_approval.py`.
- **CONFIRMÉ** — L'énumération du schéma JSON de la politique admet `0BSD` et
  `Unlicense`, mais ni `CC-BY-4.0` ni `Etalab-2.0` : le fichier de politique
  candidate n'est pas conforme à son propre schéma.
- **CONFIRMÉ** — `verified-public-domain` est admis par l'`acquisition_guard`,
  le validateur de manifeste et l'audit, sans définition de ce qui le
  vérifie.
- **CONFIRMÉ** — Aucune entrée du registre ne nomme ces trois valeurs. D-031
  pose le critère « strictement réutilisables » ; D-032 et D-033 nomment
  `CC-BY-4.0` et `Etalab-2.0`.
- **CONFIRMÉ** — Aucune source actuelle n'en dépend : le catalogue et le
  corpus initial sont sous MIT, Apache-2.0 ou BSD-3-Clause.
- Le tableau comparatif des cinq listes figure dans la
  [politique](../data/corpus-processing-policy.md), section 2.9.

### Options

| Option | Contenu | Conséquences |
| --- | --- | --- |
| A. Ratifier | Une entrée nomme la liste complète, trois valeurs comprises. | Les validateurs et le schéma pourront partager une liste unique ; l'incohérence disparaît. |
| B. Retirer | Supprimer les trois valeurs des validateurs jusqu'à ce qu'une source en ait besoin. | Plus strict, sans effet sur les sources actuelles ; changement de code et de tests. |
| C. Statu quo | Documenter l'écart sans rien changer. | L'incohérence entre validateurs demeure. |

**À vérifier par le propriétaire** : la portée d'une renonciation au domaine
public, comme celle d'`Unlicense`, dans son cadre juridique, et le sens exact
de `verified-public-domain`.

### Recommandation PROVISOIRE

Une entrée qui nomme la liste complète admise. `0BSD` y serait admise ;
`Unlicense` et `verified-public-domain` seraient suspendues jusqu'à relecture,
puisqu'aucune source n'en dépend. L'alignement des validateurs sur une
constante partagée suivrait cette entrée, pas l'inverse.

## 7. Moteur d'embeddings RAG, reranker et index

### Constat

- **CONFIRMÉ** — Le commit `d7cc78c` (2026-09-13), écrit par un agent, a
  intégré Qwen3-Embedding-0.6B quantifié Q8_0 (1 024 dimensions) :
  [client loopback](../../services/web/embed_client.py), unité de service et
  outil de réindexation. Il n'existe ni lock, ni reçu de promotion, ni entrée
  au registre, ni ADR.
- **CONFIRMÉ** — D-028 autorise un petit moteur d'embeddings pré-entraîné,
  avec « licence et empreinte vérifiées ». Le point 5 de l'ADR-0004 exige un
  moteur « figé par empreinte et licence ».
- **CONFIRMÉ** — P-004 laisse le reranker et le moteur d'index « à valider
  par benchmark ». Le score hybride 0,45/0,55 est codé en dur, sans mesure.
- **CONFIRMÉ** — Si `SOVEREIGN_EMBED_ENDPOINT` est absente, la passerelle
  utilise un point de terminaison loopback par défaut : la recherche dense
  reste active. Seule une valeur explicitement vide désactive le client ; la
  recherche reste alors lexicale.
- **OUVERT** — Le déploiement réel n'est attesté par aucun relevé versionné.
- L'analyse détaillée figure dans
  [l'ADR-0007 (PROPOSÉ)](../architecture/adr-0007-rag-embedding-reranker-index.md).

### Options

| Option | Contenu | Conséquences |
| --- | --- | --- |
| A. Ratifier a posteriori | Qwen3-Embedding-0.6B Q8_0 devient l'instance de D-028 après relecture matérielle (SHA-256, taille, révision, licence). | Le lock candidat devient un lock réel avec reçu de promotion. Aucun changement de code. |
| B. Suspendre puis ratifier | Recherche lexicale seule jusqu'à la relecture, par `SOVEREIGN_EMBED_ENDPOINT` explicitement vide (pas seulement absente) ; puis option A si la relecture concorde. | Perte temporaire du rappel sémantique ; conformité à D-028 rétablie avant usage. |
| C. Remplacer | Choisir un autre modèle après comparaison mesurée. | Réindexation complète ; nouvelle acquisition et nouveau lock. |

Reranker : aucun, ou petit modèle local après mesure du gain de rappel.
Index : SQLite exhaustif actuel jusqu'à un seuil de volume mesuré, ou une
alternative comparée dans l'ADR-0007.

### Recommandation PROVISOIRE

Option B puis A. Aucun reranker tant qu'une mesure ne montre pas de gain.
Conserver l'index SQLite exhaustif jusqu'à la mesure au volume réel. L'ADR-0007
passerait au statut approuvé par décision du propriétaire, et P-004 serait
mise à jour dans la même entrée.

## Ce que le propriétaire consigne

Pour chaque décision prise :

1. une entrée au [registre](decisions.md), au prochain numéro libre, qui cite
   cette note et les preuves retenues ;
2. l'empreinte de tout artefact approuvé : manifeste, plan de
   sous-échantillon, tokenizer ou modèle d'embeddings ;
3. la liste des documents à aligner ensuite, dont README, spécification
   d'auto-entraînement et gate corpus. Un agent peut faire ces alignements
   après l'entrée, jamais avant.
