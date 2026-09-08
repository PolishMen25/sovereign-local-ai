# Gate corpus et tokenizer

## Approbation propriétaire obligatoire du catalogue candidat

Le catalogue candidat n'est jamais une approbation. Seul le propriétaire peut
créer et commiter sur la PR le fichier
`configs/corpus/core-v1-source-policy.approved.json`. Ce geste est la décision
humaine traçable : une conversation, une sortie de modèle, un message ou un
outil ne peut ni créer ni simuler cette approbation.

Le fichier est volontairement absent du dépôt tant que le propriétaire ne
l'ajoute pas lui-même. Son schéma est le suivant : les `sources` reprennent à
l'identique chaque entrée du candidat, à l'exception du `sha256` remplacé par
l'empreinte réelle de l'archive reçue. `candidate_policy_commit` identifie le
commit du catalogue approuvé.

```jsonc
{
  "approved_by": "owner identifier", // propriétaire qui décide
  "approved_at": "2026-09-08T12:00:00Z", // date ISO-8601 de la décision
  "candidate_policy_commit": "bf690bd", // commit exact du catalogue candidat
  "sources": [
    {
      // copie exacte d'une source du candidat ; aucun ajout, retrait ou changement
      "name": "Example source",
      "url": "https://example.invalid/repository",
      "license_detected": "MIT",
      "sha256": "64 hexadecimal characters from the received archive"
    }
  ]
}
```

`tools/verify_corpus_approval.py` compare cette liste au candidat, refuse une
approbation absente, une empreinte `pending`/`unverified`, une licence hors
allowlist ou une divergence de source. `tools/preflight_core_700m_tokenizer.py`
appelle ce vérificateur avant toute autre opération et n'offre aucun bypass.

**Statut : la politique Git reste candidate tant que le fichier d'approbation
propriétaire est absent ; aucun préflight ne peut donc démarrer.**

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

## Corpus initial approuvé le 2026-09-07

Le propriétaire a approuvé un corpus technique initial, distinct des
conversations privées et limité à trois archives Git figées : `psf/requests`
à `dae7ef63b4df6eded86637f251fc4e3a06c3b479` (Apache-2.0),
`pallets/flask` à `d318b683471101618febed18996405ad26462110`
(BSD-3-Clause), et `moby/moby` à
`2280567b60633e2a4ac8723961bc1f351e71e099` (Apache-2.0).

Les archives RAW sont conservées avec les empreintes respectives
`55999922723576238c243ca02183f2c367c9b0c197a3c1afc671b35c2daf96c2`,
`d9e95f6100bb2479247da4b8055b80a52ef8c059cd74ade5b7df46ce01033d77`
et `8aa8d4cda384a4aff4dacc04195feade22d237e4eb7987c9053ac06209431fe3`.
Le manifeste validé du corpus est
`ad199338663ae96bedd341aeec8ac4eec6db78d5e503c19e784e7b621b643985`.
Il contient 44 enregistrements d'entraînement, 109 de validation et 2 423 de
test. Ce premier lot est anglais technique ; il ne valide pas encore la
couverture française ni un tokenizer final pour CORE-700M.

## Tokenizer CORE-700M candidat le 2026-09-07

Le Byte-BPE 32k créé hors ligne depuis le seul split `train` a atteint
exactement 32 000 unités, avec 31 740 fusions et un seuil de fréquence `1`.
Son artefact source `experimental` a pour empreinte
`c1a506f71d2b2a17054aa531deccb6826d79e852dec13b674bd037126a5a98bb`.
Après validation de sa lignée, il a été promu en artefact distinct
`candidate_core`, d'empreinte
`6f7509737b7af73077c76756c12b2454fed83dc8f04e5159f717298b60a4821c`.
Le reçu de promotion a pour empreinte
`583ad7c9e79cdbbec66844a9c434be3ac7f2a97a415a25362f7d884ab6cd2894`.

Le préflight non allouant lie ce candidat au manifeste ci-dessus, au split
`train` `a34d50ab83d899137ab50d43bd1dac41e9cf0dff076b56693e39dd69c4b467bb`
et à la configuration CORE-700M de 691 160 320 paramètres. Cette validation ne
crée pas de poids, ne lance pas d'entraînement et ne rend pas le tokenizer
final ou multilingue.

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

Un entraînement Byte-BPE produit toujours d'abord un artefact `experimental`.
Une promotion distincte peut le rendre `candidate_core` après vérification du
manifeste approuvé, du split `train`, du vocabulaire et des empreintes ; elle
produit un reçu séparé liant les deux versions. `approved_core_v1` reste
réservé à une décision ultérieure. Le prototype est borné à 32 768 unités et
conserve les règles de sortie de référence tout en mettant à jour localement les
occurrences de paires ; le détail de l'adoption contrôlée pour pilote-v3 est
décrit dans [la note d'adoption](pilote-v3-tokenizer-adoption.md).
Pour un corpus réduit, le seuil minimal de fréquence `1` est admis, consigné dans
l'artefact et doit rester explicite dans le reçu de promotion.
La configuration candidate est
[`configs/tokenizers/byte-bpe-v0.candidate.json`](../../configs/tokenizers/byte-bpe-v0.candidate.json).

L'option ci-dessous est obligatoire avant d'alimenter un entraînement
linguistique. Elle refuse un corpus synthétique, une gouvernance en attente,
une autorisation absente et un contrat tokenizer non approuvé.

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
- `--authorized-tokenizer` : tokenizer `experimental` ou `candidate_core`
  construit depuis ce même split et portant le même contrat de normalisation.

Le chargeur vérifie notamment les autorisations distinctes, les tailles,
comptes et SHA-256, les identifiants de corpus, la provenance, la normalisation
et la taille exacte du vocabulaire attendue par CORE-MINI. Une erreur provoque
un refus ; il n'existe aucun repli implicite vers les données synthétiques.

Pour CORE-MINI, le manifeste et le tokenizer doivent déclarer exactement
**4 096 unités**, conformément à
[`core-mini.candidate.json`](../../configs/models/core-mini.candidate.json). Le
candidat de **32 000 unités** destiné à la cible CORE-700M est incompatible avec
CORE-MINI et le harness le refusera.

`derive_core_mini_manifest.py` produit le manifeste 4 096 distinct à partir du
manifeste d'entraînement déjà approuvé. Il conserve les empreintes et les splits
mais crée un `corpus_id` séparé ; le tokenizer MINI ne peut donc pas être pris
pour le candidat 32k de CORE-700M.

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

Le candidat 32k peut être promu `candidate_core` pour CORE-700M, mais n'est pas
un tokenizer final ou multilingue. Avant le gate G3, le propriétaire doit encore
approuver :

1. les sources, licences, consentements et exclusions ;
2. la proportion français/anglais/code/documentation et les domaines visés ;
3. la politique de normalisation, de déduplication et de découpage ;
4. la longueur de contexte et les critères de qualité du tokenizer ;
5. la stratégie séparée d'embeddings et de reranking pour le RAG.

Les conversations relayées vers la zone RAW ne sont ni un corpus
d'entraînement ni une connaissance validée par défaut. Elles exigent la même
revue de consentement, de données personnelles, de secrets, de licence et de
promotion que toute autre source.
