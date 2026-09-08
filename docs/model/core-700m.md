# CORE-700M — candidat principal

CORE-700M est le candidat principal approuvé le 2026-09-01. Il est créé dans ce
projet et entraîné de zéro sur CPU. Il ne possède actuellement aucun poids
linguistique et ne doit pas être présenté comme un chat utilisable.

La source machine est
[`configs/models/core-700m.candidate.json`](../../configs/models/core-700m.candidate.json).
Le compteur relit cette configuration et refuse toute divergence entre
l'architecture et le bloc `parameter_count`.

Le préflight commun relit également une seule copie bornée de ses octets,
refuse les clés JSON dupliquées et les nombres non finis, puis conserve son
SHA-256 avec le comptage exact. Cette vérification n'alloue pas le modèle et ne
constitue ni une mesure RAM ni une autorisation d'entraînement.

## Architecture et comptage exact

| Élément | Définition | Paramètres |
| --- | --- | ---: |
| Embeddings liés | `32 000 × 1 280` | 40 960 000 |
| Attention par bloc | `4 × 1 280²` | 6 553 600 |
| SwiGLU par bloc | `3 × 1 280 × 3 584` | 13 762 560 |
| Deux RMSNorm par bloc | `2 × 1 280` | 2 560 |
| 32 blocs | `32 × 20 318 720` | 650 199 040 |
| RMSNorm finale | `1 280` | 1 280 |
| Tête séparée | embeddings liés | 0 |
| **Total** |  | **691 160 320** |

RoPE n'ajoute aucun paramètre. La dimension de tête est 64 et le contexte
candidat est 2 048 tokens. Toute modification de ces valeurs doit mettre à
jour ensemble la configuration, ce calcul, les tests et le registre.

## Paliers et gates

Les paliers candidats sont 10 millions, 100 millions, 1 milliard puis au plus
8 milliards de tokens. Chaque passage exige une approbation liée aux empreintes
du corpus, du tokenizer, du code, du runtime et du checkpoint précédent.

Avant toute allocation des poids, le préflight
[`preflight_core_700m_tokenizer.py`](../../tools/preflight_core_700m_tokenizer.py)
exige un tokenizer `candidate_core`, le split `train` exact et un vocabulaire
de 32 000 unités correspondant à la configuration CORE-700M. Il ne crée aucun
tenseur du modèle et ne déclenche aucun entraînement.

Un palier est interrompu en cas de perte non finie ou divergente, reprise
invalide, espace insuffisant, pression mémoire dangereuse, seuil thermique
dépassé ou échec des évaluations. Les seuils matériels exacts proviennent du
runbook privé et ne sont pas publiés dans Git.

Le corpus vise prioritairement Python, PowerShell, Bash,
JavaScript/TypeScript, HTML/CSS, SQL, Docker, Linux et réseau, avec du français
et de l'anglais technique. Une source ambiguë, non traçable ou incompatible
avec la politique de réutilisation est refusée.

## Boucle d'amélioration par signal externe

La boucle d'auto-entraînement reste **INACTIVE**. Sa seule source de sélection
est un résultat de tests exécutés dans un bac à sable isolé ; CORE ne juge jamais
ses propres sorties. Les seuils d'activation, l'isolation, les plafonds de
données synthétiques et le passage obligatoire par le gate corpus sont définis
dans [la spécification de boucle](self-training-loop-spec.md). CORE-MINI doit
valider cette chaîne avant toute adaptation de budget à CORE-700M.
