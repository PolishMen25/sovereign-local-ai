# Gate corpus et tokenizer

**Statut : préparation de J3, aucune approbation de corpus.**

Ce projet ne lance pas d'entraînement linguistique tant qu'un corpus, son
tokenizer et son autorisation ne sont pas explicitement approuvés. Le
checkpoint CORE-MINI existant utilise uniquement des identifiants synthétiques :
il ne constitue pas une exception à cette règle. Le chemin technique
`authorized-text` est implémenté et couvert par des tests unitaires et
structurels, mais aucun entraînement PyTorch de bout en bout n'a encore été
exécuté avec ce chemin. Il reste bloqué en pratique tant que les trois artefacts
exacts et leur approbation ne sont pas réunis.

## Politique de sources candidate

La politique versionnée
[`core-v1-source-policy.candidate.json`](../../configs/corpus/core-v1-source-policy.candidate.json)
traduit les choix actuels du propriétaire : français et anglais, priorité au
développement logiciel, à l'administration système et au réseau, et licences
strictement permissives (`MIT`, `Apache-2.0`, familles BSD, `ISC`, `CC0-1.0`,
`0BSD` et `Unlicense`).

Elle exclut les conversations privées, données personnelles, identifiants,
contenus propriétaires et licences inconnues. Elle impose pour chaque futur
paquet une licence, une provenance, une empreinte et une revue humaine. Elle
reste `candidate` : elle ne télécharge rien, n'approuve aucune source et
n'autorise ni tokenizer final ni entraînement.

```bash
python3 -B tools/validate_training_source_policy.py \
  configs/corpus/core-v1-source-policy.candidate.json
```

## Contrat versionné

[`schemas/training-corpus-manifest.schema.json`](../../schemas/training-corpus-manifest.schema.json)
définit le manifeste `0.2.0`, sans contenu ni chemin interne. Chaque lot doit
porter :

- son identifiant de paquet et son identifiant de provenance ;
- les tailles, comptes et empreintes SHA-256 propres à `train`, `validation`,
  `test` et à la matérialisation globale ;
- une licence déclarée, les langues et un état de revue `approved` ;
- une partition exclusive entre entraînement, validation et test ;
- le contrat d'entrée du tokenizer (UTF-8, politique de normalisation et taille
  de vocabulaire candidate) ;
- deux décisions séparées : gouvernance des données et autorisation effective
  d'entraînement.

Le validateur standard contrôle la structure et les invariants, mais ne prouve
ni la licence ni la qualité du contenu. Le chargeur borné
[`tools/authorized_text_bundle.py`](../../tools/authorized_text_bundle.py)
vérifie les octets du seul split `train`, refuse `validation`, `test` et la
matérialisation globale, puis lie son empreinte exacte à celle du tokenizer.

```bash
python3 -B tools/validate_training_corpus_manifest.py manifest.json
```

## Prototype technique disponible

[`tools/train_byte_bpe.py`](../../tools/train_byte_bpe.py) est un entraînement
Byte Pair Encoding déterministe et hors ligne. Il ne lit un corpus que si le
manifeste passe l'autorisation explicite, si la taille et l'empreinte des octets
concordent et si chaque ligne est un enregistrement JSONL strict
`record_id` / `text`, avec identifiant unique et limites explicites.

Le format expérimental `0.2.0` conserve les fusions BPE dans leur ordre. Le
module partagé [`services/inference/tokenizer.py`](../../services/inference/tokenizer.py)
applique la même normalisation NFC pendant l'apprentissage et l'encodage,
rejoue ces fusions par rang, conserve les identifiants spéciaux 0 à 3 et refuse
un vocabulaire, une couverture des 256 octets ou un graphe de fusion altéré.
Son état runtime est immuable et les tailles de texte et de décodage sont
bornées. Un encode/decode déterministe est donc testable hors ligne sans faire
de cet artefact un tokenizer approuvé.

Le résultat reste marqué `experimental` : ni le corpus, ni la politique finale,
ni les 32 000 unités candidates ne sont approuvés. Le prototype est borné à
32 768 unités et son algorithme d'apprentissage naïf n'est pas encore adapté à
un grand corpus. Le producteur et le chargeur utilisent désormais l'empreinte
exacte de la partition `train`, sans autoriser pour autant un entraînement
linguistique. La configuration candidate est
[`configs/tokenizers/byte-bpe-v0.candidate.json`](../../configs/tokenizers/byte-bpe-v0.candidate.json).

L'option ci-dessous est obligatoire avant d'alimenter un entraînement
linguistique. Elle refuse un corpus synthétique, une gouvernance en attente,
une autorisation absente et un tokenizer non approuvé.

```bash
python3 -B tools/validate_training_corpus_manifest.py \
  --require-training-authorization manifest.json
```

## Chemin d'entraînement autorisé

[`tools/train_core_mini.py`](../../tools/train_core_mini.py) conserve le mode
synthétique historique par défaut et n'accède au texte que si
`--data-mode authorized-text` est fourni. Dans ce mode, les trois arguments
suivants sont indissociables :

- `--authorized-manifest` : manifeste `0.2.0` autorisé ;
- `--authorized-train-jsonl` : octets exacts du seul split `train` ;
- `--authorized-tokenizer` : tokenizer expérimental construit depuis ce même
  split et portant le même contrat de normalisation.

Le chargeur vérifie notamment les autorisations distinctes, les tailles,
comptes et SHA-256, les identifiants de corpus, la provenance, la normalisation
et la taille exacte du vocabulaire attendue par CORE-MINI. Une erreur provoque
un refus ; il n'existe aucun repli implicite vers les données synthétiques.

Pour CORE-MINI, le manifeste et le tokenizer doivent déclarer exactement
**4 096 unités**, conformément à
[`core-mini.candidate.json`](../../configs/models/core-mini.candidate.json). Le
candidat de **32 000 unités** destiné à la cible CORE-700M est incompatible avec
CORE-MINI et le harness le refusera.

```bash
python -B -m tools.train_core_mini \
  --config configs/models/core-mini.candidate.json \
  --output-dir runs/core-mini-authorized \
  --data-mode authorized-text \
  --authorized-manifest manifest.json \
  --authorized-train-jsonl train.jsonl \
  --authorized-tokenizer tokenizer.json
```

Cette commande est une forme de référence, pas une autorisation de l'exécuter
avec des données réelles. Lorsqu'un bundle sera approuvé, le harness produira
des séquences déterministes et bornées, un contrat d'entraînement `0.2.0` à
lignée sans contenu brut, ainsi qu'un journal strict dont chaque mesure est
liée au SHA-256 de ce contrat. Le checkpoint enregistre également le SHA-256 du
préfixe exact du journal correspondant à son étape ; la reprise refuse un
journal absent, modifié ou rattaché à une autre étape. Elle exige enfin le même
contrat et un état de checkpoint modèle/optimiseur strictement compatible.

À ce jour, aucun bundle réel n'a franchi ce gate, aucun mini-entraînement
linguistique autorisé n'a été exécuté et aucun poids CORE utile n'a été produit.

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
