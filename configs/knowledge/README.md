# Catalogue RAG de préparation

`catalogue.synthetic.jsonl` est un catalogue **synthétique** de trois notices,
préparé uniquement pour tester le MCP Knowledge. L’interface Web n'est pas
encore reliée à ce catalogue. Il ne contient
ni conversation réelle, ni secret, ni chemin d’infrastructure.

Chaque ligne conserve un `document_id`, un résumé borné et un
`provenance_id`. Ce fichier n’est pas une promotion automatique des données
RAW : un catalogue de production devra être généré par une décision de
validation, avec manifeste, empreintes, ACL et audit séparés.

## Jeu d'or synthétique pour l'évaluation de la recherche

`retrieval-eval.synthetic.jsonl` est un jeu d'or **synthétique** : 24 notices
en français et en anglais, dont deux hors sujet, et 16 requêtes avec une
pertinence graduée de 1 à 3. Il sert à tester
[`tools/evaluate_retrieval.py`](../../tools/evaluate_retrieval.py). Ses scores
ne disent rien de la qualité de la recherche réelle. Il ne contient ni donnée
réelle, ni secret, ni chemin d'infrastructure.

Format JSONL strict : la ligne 1 est l'en-tête (`record_type` `header`,
`schema_version` `retrieval-eval-gold.v1`, `gold_set_id`, `synthetic`). Les
lignes suivantes sont des notices (`document` : `document_id`, `title`,
`content`, `provenance_id`) ou des requêtes (`query` : `query_id`, `language`
parmi `fr`, `en`, `mul`, `query`, `relevant`). Dans un jeu synthétique, chaque
`provenance_id` commence par `synthetic-`.

L'outil construit un index `HybridKnowledgeIndex` jetable dans un répertoire de
travail privé, supprimé à la fin. Il mesure recall@k, MRR (tronqué au plus
grand k) et nDCG@k à gains gradués (2^note − 1) dans trois modes :

- **lexical** : la recherche FTS5/BM25 de production ;
- **hybride** : la recherche de production, avec les poids 0,45 lexical et
  0,55 vectoriel codés en dur ;
- **vectoriel** : le point 0 du balayage du poids lexical.

Le balayage (0 à 1, dont 0,45) re-note les mêmes candidats que la production.
À 0,45, il doit reproduire exactement le classement et les scores de
`HybridKnowledgeIndex.search` ; sinon l'exécution est refusée.

```bash
python3 -B tools/evaluate_retrieval.py \
  --gold configs/knowledge/retrieval-eval.synthetic.jsonl \
  --output rapport-recherche.json

python3 -B tools/evaluate_retrieval.py \
  --gold jeu-or.jsonl --gold-sha256 <sha256> \
  --embed-endpoint http://127.0.0.1:<port> --embedder-label <modele> \
  --output rapport-recherche.json
```

Options :

- sans `--embed-endpoint`, seul le mode lexical est mesuré ; les autres sont
  marqués `unavailable` ;
- `--embed-endpoint` n'accepte qu'une adresse de bouclage littérale
  (`127.0.0.1` ou `::1`) avec un port explicite. L'appel passe par
  `EmbedClient`, sans proxy ni redirection, et exige `--embedder-label` ;
- `--k` (répétable, de 1 à 20, 1/3/5/10 par défaut), `--gold-sha256` (empreinte
  épinglée) et `--work-dir` (répertoire parent existant pour l'index jetable).

Un runtime d'embeddings indisponible dégrade le rapport en mode lexical seul.
Un vecteur invalide est refusé : non fini, nul, non numérique ou de dimension
variable. Le rapport est déterministe. Il porte les empreintes du jeu d'or, de
`hybrid_index.py` et de l'outil, ainsi qu'une empreinte des vecteurs pour
comparer deux exécutions. Il ne contient ni texte ni chemin et n'est jamais
écrasé. `model_identity_verified` reste `false` : l'outil ne vérifie pas le
modèle servi.

Aucun seuil ni poids recommandé n'est fixé. Le choix du reranker et de l'index
(P-004) reste au propriétaire. Il suppose une mesure au volume réel sur le nœud
de calcul, avec un jeu d'or privé non versionné, qui n'a pas encore eu lieu.

Deux constats tirés du code actuel éclairent la lecture des résultats :

- en mode hybride, seules les notices dotées d'un embedding de même dimension
  que la requête sont notées. Une notice sans embedding disparaît donc des
  résultats hybrides, même si elle correspond lexicalement ;
- une requête dont tous les termes sont des mots vides ne renvoie rien, quel
  que soit le mode. Le rapport compte ces requêtes
  (`queries_without_lexical_terms`).
