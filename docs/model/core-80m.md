# CORE-80M — candidat de modèle local

## Statut

CORE-80M est un **candidat d'architecture calculable**, pas une spécification figée ni une promesse de performance. Il matérialise la cible actuelle d'un modèle de langage dense de 50 à 100 millions de paramètres, exécutable localement sur CPU.

Le projet vise à créer le modèle principal, son tokenizer, son pipeline et tous ses poids — y compris sa matrice d'embedding de tokens — dans ce projet et à les entraîner de zéro. Une décision différente reste ouverte uniquement pour le **moteur d'embeddings du RAG** et un éventuel reranker, qui sont des composants séparés de CORE-80M.

Toute modification des dimensions, des couches, des normalisations ou du partage de poids impose de recalculer et de tester le nombre de paramètres.

La source machine du candidat est [`configs/models/core-80m.candidate.json`](../../configs/models/core-80m.candidate.json). Le compteur et son test lisent ce fichier directement afin d'éviter une dérive silencieuse entre configuration, calcul et documentation.

## Architecture candidate

| Élément | Valeur candidate |
| --- | ---: |
| Famille | Transformer causal dense, decoder-only |
| Taille du vocabulaire | 32 000 |
| Dimension du modèle (`d_model`) | 640 |
| Couches Transformer | 12 |
| Têtes d'attention | 10 |
| Dimension par tête | 64 |
| Dimension feed-forward (`d_ff`) | 1 792 |
| Activation | SwiGLU |
| Encodage de position | RoPE, sans paramètre appris |
| Normalisation | RMSNorm |
| Biais | Aucun |
| Embedding de tokens / tête LM | Poids liés |

La longueur de contexte, les paramètres de RoPE, le tokenizer exact et les détails numériques de l'entraînement restent ouverts. Les dix têtes de 64 dimensions couvrent exactement `10 × 64 = 640` dimensions.

## Calcul exact des paramètres

Hypothèses du calcul : attention multi-têtes standard avec matrices Q, K, V et O complètes ; trois matrices pour SwiGLU ; deux RMSNorm par bloc ; une RMSNorm finale ; aucun biais ; aucune embedding de position apprise ; aucune tête auxiliaire.

### Embedding de tokens et tête de sortie liée

La tête LM réutilise la matrice d'embedding et n'ajoute donc pas une seconde matrice :

```text
vocab_size × d_model
= 32 000 × 640
= 20 480 000
```

### Un bloc Transformer

Attention :

```text
Wq + Wk + Wv + Wo
= 4 × d_model × d_model
= 4 × 640 × 640
= 1 638 400
```

SwiGLU (`W_gate`, `W_up`, `W_down`) :

```text
3 × d_model × d_ff
= 3 × 640 × 1 792
= 3 440 640
```

Deux RMSNorm :

```text
2 × d_model
= 2 × 640
= 1 280
```

Total par bloc :

```text
1 638 400 + 3 440 640 + 1 280
= 5 080 320
```

Pour douze blocs :

```text
12 × 5 080 320
= 60 963 840
```

### Normalisation finale et total

La RMSNorm finale ajoute 640 paramètres :

```text
embedding/tête liée       20 480 000
12 blocs                  60 963 840
RMSNorm finale                   640
                           ----------
TOTAL                     81 444 480
```

Le nom « CORE-80M » est donc une désignation arrondie ; ce candidat précis contient **exactement 81 444 480 paramètres entraînables**.

## Contraintes d'exécution et d'entraînement

- Le chemin de référence est **CPU-only**. Une disponibilité éventuelle de GPU ne doit pas devenir une dépendance implicite.
- La machine d'entraînement confirmée est le ML350 bi-socket avec 2 × Xeon E5-2698 v4, soit 40 cœurs physiques / 80 threads répartis sur deux nœuds NUMA, et 88 Go de RAM installés dont environ 78 Gio sont visibles. La répartition des DIMM par nœud NUMA, les instructions réellement exposées à l'invité, les ressources réservées à Proxmox et le stockage actif doivent encore être inventoriés avant tout dimensionnement.
- L'affinité des processus et des threads, l'allocation mémoire locale à chaque socket et le coût des accès inter-sockets doivent être mesurés. « Deux sockets » ne signifie pas automatiquement « deux fois plus rapide ».
- Les mesures doivent distinguer au minimum un socket et deux sockets, puis relever le débit en tokens/s, le temps par étape, la mémoire de pointe, l'utilisation CPU, les défauts NUMA, le temps d'entrée/sortie et le temps de sauvegarde/reprise.
- La mémoire nécessaire ne se limite pas aux poids : gradients, états de l'optimiseur, activations, tampons, chargeur de données et checkpoints doivent entrer dans le bilan.

## Benchmark miniature obligatoire

Avant toute estimation de durée, de coût ou de faisabilité du CORE-80M, un mini-modèle doit être entraîné avec le **même chemin logiciel** que le candidat : tokenizer et séquences représentatifs, mêmes opérateurs, même précision, même optimiseur envisagé, checkpoint et reprise inclus.

Le benchmark doit :

1. vérifier qu'un cycle complet entraînement → checkpoint → reprise → évaluation fonctionne sur CPU ;
2. comparer les placements NUMA et les réglages de threads ;
3. mesurer plusieurs tailles de lot et longueurs de séquence pertinentes ;
4. produire des résultats bruts reproductibles et la configuration exacte de la machine ;
5. tester au moins deux échelles miniatures afin d'éviter une extrapolation depuis un seul point ;
6. séparer les temps de calcul, de préparation des données et d'entrée/sortie.

Une projection vers CORE-80M ne sera qu'une fourchette fondée sur ces mesures, accompagnée de ses hypothèses et marges d'incertitude. **Aucune durée d'entraînement n'est promise à ce stade.** Si les résultats sont défavorables, le jalon doit d'abord revoir l'implémentation, le contexte, le corpus, le plan d'entraînement ou le calendrier. Sortir de la cible confirmée de 50–100M exige une nouvelle décision explicite du propriétaire ; lancer coûte que coûte n'est pas un critère de succès.

## Décision ouverte : moteur d'embeddings du RAG

Cette décision ne concerne pas la matrice d'embedding de tokens de CORE-80M, qui fait partie du modèle principal créé de zéro. Elle concerne le composant séparé qui transforme les documents et requêtes du RAG en vecteurs, ainsi qu'un éventuel reranker.

Deux voies doivent être comparées dans une note de décision :

- **Moteur RAG entraîné de zéro** : contrôle maximal, mais dataset d'apprentissage et évaluation supplémentaires.
- **Petit modèle d'embeddings pré-entraîné exécuté localement sur CPU** : amorçage potentiellement utile, sous réserve de provenance vérifiable, de licence compatible, de fonctionnement hors ligne, d'absence de télémétrie et d'une évaluation mesurée sur le corpus réel.

Cette décision doit précéder le gel de l'architecture RAG. Si un moteur pré-entraîné est retenu, son origine, son empreinte, sa licence, ses transformations et son statut gelé ou ajustable devront être traçables. Ce choix n'autorise pas l'import de poids pré-entraînés dans CORE-80M.

## Points à décider avant gel de l'architecture

- corpus, langues, licences, règles de qualité, déduplication et budget de tokens ;
- tokenizer et validation du vocabulaire de 32 000 unités ;
- longueur de contexte et configuration de RoPE ;
- précision numérique, optimiseur, plan de taux d'apprentissage et stratégie de checkpoint ;
- bibliothèque d'entraînement CPU et stratégie de parallélisme adaptée au NUMA ;
- moteur d'embeddings du RAG et éventuel reranker, créés de zéro ou pré-entraînés ;
- protocoles d'évaluation de qualité, robustesse, mémorisation, biais et sécurité ;
- format de poids et moteur d'inférence local.

Le candidat ne devient une spécification gelée qu'après validation des données, du benchmark miniature, du budget mémoire et des critères d'évaluation décrits dans la [roadmap](../ROADMAP.md).

