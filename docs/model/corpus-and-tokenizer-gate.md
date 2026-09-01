# Gate corpus et tokenizer

**Statut : préparation de J3, aucune approbation de corpus.**

Ce projet ne lance pas d'entraînement linguistique tant qu'un corpus, son
tokenizer et son autorisation ne sont pas explicitement approuvés. Le modèle
CORE-MINI déjà présent utilise uniquement des identifiants synthétiques : il
ne constitue pas une exception à cette règle.

## Contrat versionné

[`schemas/training-corpus-manifest.schema.json`](../../schemas/training-corpus-manifest.schema.json)
définit un manifeste sans contenu ni chemin interne. Chaque lot doit porter :

- son identifiant de paquet et son identifiant de provenance ;
- les empreintes SHA-256 du paquet, de chaque partition et de la matérialisation ;
- une licence déclarée, les langues et un état de revue `approved` ;
- une partition exclusive entre entraînement, validation et test ;
- le contrat d'entrée du tokenizer (UTF-8, politique de normalisation et taille
  de vocabulaire candidate) ;
- deux décisions séparées : gouvernance des données et autorisation effective
  d'entraînement.

Le validateur standard contrôle la structure et les invariants, mais ne prouve
ni la licence, ni le contenu, ni l'empreinte des octets : ces contrôles restent
à exécuter dans le pipeline de matérialisation isolé.

```bash
python3 -B tools/validate_training_corpus_manifest.py manifest.json
```

L'option ci-dessous est obligatoire avant d'alimenter un entraînement
linguistique. Elle refuse un corpus synthétique, une gouvernance en attente,
une autorisation absente et un tokenizer non approuvé.

```bash
python3 -B tools/validate_training_corpus_manifest.py \
  --require-training-authorization manifest.json
```

## Ce qui reste à décider

Le candidat de 32 000 unités est une hypothèse de travail, pas le tokenizer
final. Avant le gate G3, le propriétaire doit approuver :

1. les sources, licences, consentements et exclusions ;
2. la proportion français/anglais/code/documentation et les domaines visés ;
3. la politique de normalisation, de déduplication et de découpage ;
4. la longueur de contexte et les critères de qualité du tokenizer ;
5. la stratégie séparée d'embeddings et de reranking pour le RAG.

Les conversations relayées vers la zone RAW ne sont ni un corpus
d'entraînement ni une connaissance validée par défaut. Elles exigent la même
revue de consentement, de données personnelles, de secrets, de licence et de
promotion que toute autre source.
