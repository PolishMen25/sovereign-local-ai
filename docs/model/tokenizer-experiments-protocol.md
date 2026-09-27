# Protocole d'expériences tokenizer

**Statut : PROPOSÉ — rédigé en phase 0 ; le passage en phase 1 (D-038) ne
change pas ce statut.** Ce document répond au critère de l'issue #7
« expériences tokenizer avec métriques et corpus d'évaluation ». Il fournit un
outil de mesure hors ligne, une fixture synthétique et un plan d'expériences.
**Aucun seuil n'est décidé** : l'outil décrit, il ne classe pas et ne promeut
rien. Le choix d'un artefact, de ses seuils et de sa promotion reste une
décision du propriétaire au gate G3.

Depuis la rédaction, D-042 a tranché une partie du cadre : le tokenizer est
réentraîné sur le corpus final, avec un vocabulaire de 32 000, quatre tokens
spéciaux et un contexte de 2 048 ; son acceptation se fait sur métriques
mesurées (octets par token et tokens par mot en français, en anglais et sur le
code, aller-retour exact). Ce sont les métriques que mesure l'outil. D-042 ne
fixe aucune valeur de seuil. D-041 fixe environ 40 % de français technique
dans le corpus cible.

Aucun résultat sur un artefact réel n'est consigné ici. Le serveur de calcul
était hors ligne lors de la rédaction ; rien n'a été exécuté sur les splits de
pilote-v3.

## 1. Situation de départ

- Le module [`services/inference/tokenizer.py`](../../services/inference/tokenizer.py)
  définit le Byte-BPE : normalisation NFC, 256 octets de base, fusions
  rejouées par rang, tokens spéciaux `<pad>`, `<bos>`, `<eos>`, `<unk>` aux
  identifiants 0 à 3, vocabulaire borné à 32 768 unités.
- La [note du gate corpus et tokenizer](corpus-and-tokenizer-gate.md) décrit un
  candidat 32k `candidate_core` entraîné le 2026-09-07 sur un split `train` de
  44 enregistrements avec un seuil de fréquence `1`. La
  [note d'adoption pilote-v3](pilote-v3-tokenizer-adoption.md) décrit un
  contrat 32k lié au corpus bilingue pilote-v3.
- Avant cet outil, le dépôt ne contenait aucune mesure de fertilité, de
  compacité ou d'utilisation du vocabulaire. Les deux lignées ne sont donc pas
  comparables aujourd'hui.

## 2. Outil

[`tools/evaluate_tokenizer.py`](../../tools/evaluate_tokenizer.py) utilise la
bibliothèque standard et le module runtime lui-même : chaque enregistrement est
encodé et décodé par le code qui servirait l'inférence. L'outil n'ouvre aucune
connexion réseau et ne modifie aucun de ses fichiers d'entrée.

Essai sur la fixture synthétique :

```bash
python3 -B tools/evaluate_tokenizer.py \
  --tokenizer essai tokenizer.json <sha256-du-tokenizer> \
  --eval-jsonl tests/fixtures/tokenizer_eval_synthetic.jsonl \
  --output rapport-tokenizer.json
```

Comparaison de deux artefacts sur un split tenu à l'écart, lié à son manifeste :

```bash
python3 -B tools/evaluate_tokenizer.py \
  --tokenizer lignee-a tokenizer-a.json <sha256-a> \
  --tokenizer lignee-b tokenizer-b.json <sha256-b> \
  --eval-jsonl validation.jsonl \
  --manifest manifest.json --split validation \
  --output rapport-tokenizer-validation.json
```

Les noms de fichiers ci-dessus sont des exemples. Les chemins réels restent hors
du dépôt.

Codes de sortie :

| Code | Signification |
| --- | --- |
| `0` | Rapport écrit ; tous les allers-retours et invariants tiennent. |
| `3` | Rapport écrit ; au moins un aller-retour ou un invariant échoue. |
| `1` | Entrée refusée ou rapport impossible à écrire ; aucun rapport écrit. |
| `2` | Ligne de commande invalide (argparse) ; aucun rapport écrit. |

Les messages d'erreur ne contiennent ni texte évalué ni chemin local : une
erreur du système de fichiers n'est signalée que par sa classe.

## 3. Entrées figées et garde-fous

- **Artefacts épinglés.** Chaque artefact est donné avec son SHA-256. Un écart
  d'empreinte provoque un refus. L'artefact est ensuite revalidé en entier :
  256 octets canoniques, graphe de fusion rejoué par rang, tokens spéciaux 0 à
  3, taille de vocabulaire. Un artefact altéré est refusé, même si son
  empreinte a été recalculée.
- **Évaluation sur des données tenues à l'écart.** Avec `--manifest` et
  `--split`, les octets, la taille et le nombre d'enregistrements doivent être
  exactement ceux du split `validation` ou `test` du manifeste. Le split
  `train` est refusé. Un artefact dont `training_corpus_sha256` désigne un
  split tenu à l'écart est refusé. Sans manifeste, un fichier identique au
  split d'entraînement déclaré par un artefact est aussi refusé.
- **JSON strict.** Les clés dupliquées, `NaN`, `Infinity`, le BOM, l'octet NUL
  et l'UTF-8 invalide sont refusés. Chaque enregistrement est borné à 1 Mio,
  le fichier à 64 Mio et un million d'enregistrements.
- **Rapport sans contenu.** Le rapport ne contient ni texte évalué, ni
  identifiant d'enregistrement, ni chemin, ni horodatage. Les échecs
  d'aller-retour sont désignés par numéro de ligne. Deux exécutions sur les
  mêmes entrées produisent les mêmes octets et la même empreinte, affichée en
  sortie standard.
- **Pas d'écrasement.** Un rapport existant n'est jamais remplacé.
- **Empreinte sur les octets bruts.** L'empreinte du fichier d'évaluation porte
  sur ses octets exacts, comme `content_sha256` du manifeste et
  `training_corpus_sha256` de l'artefact. Une extraction Git qui convertit les
  fins de ligne (`core.autocrlf`) change donc l'empreinte d'un fichier versionné,
  dont la fixture synthétique : une empreinte épinglée avec `--eval-sha256` ne
  vaut que pour des octets identiques.

Deux formats d'enregistrement sont acceptés, sans mélange dans un même fichier :

| Format | Clés | Groupe dans le rapport |
| --- | --- | --- |
| `plain` | `record_id`, `text` (format des splits) | `und/unlabelled` |
| `labelled` | `record_id`, `text`, `language`, `content_type` | `<language>/<content_type>` |

`language` vaut `fr`, `en`, `mul` (plusieurs langues), `zxx` (pas de contenu
linguistique, par exemple une commande) ou `und` (indéterminé). `content_type`
vaut `prose`, `code`, `shell`, `config` ou `log`.

## 4. Définitions des métriques

Les métriques sont calculées globalement, par langue, par type de contenu et
par couple langue/type.

| Métrique | Définition |
| --- | --- |
| `bytes` | Octets UTF-8 du texte après normalisation NFC (`utf-8-after-nfc`). |
| `words` | Nombre de séquences `\w+` Unicode (`unicode-word-regex-v1`). C'est une convention de comptage, pas une segmentation linguistique ; pour le code, elle compte les identifiants. |
| `tokens` | Identifiants produits par l'encodeur runtime, sans `<bos>` ni `<eos>`. |
| `bytes_per_token` | `bytes / tokens`. Plus la valeur est haute, plus l'encodage est compact. |
| `characters_per_token` | Points de code NFC par token. |
| `tokens_per_word` | Fertilité : `tokens / words`. |
| `single_byte_token_share` | Part des tokens réduits à un octet brut. Une part élevée sur le français signale des caractères accentués non couverts par les fusions. |
| `vocabulary_utilisation` | Tokens distincts utilisés / (taille du vocabulaire − 4). |
| `learned_token_utilisation` | Tokens appris distincts utilisés / nombre de fusions. |

Contrôles d'intégrité, par artefact :

- **aller-retour exact** : `decode(encode(texte))` doit redonner le texte NFC,
  octet pour octet. Au-delà de 65 536 identifiants, le décodage runtime est
  appelé par tranches qui se terminent sur une frontière de caractère UTF-8 ;
- **invariants des tokens spéciaux** : identifiants 0 à 3 fixes ; aucun
  identifiant spécial dans un encodage ordinaire ; `<bos>` et `<eos>` encadrent
  exactement l'encodage ordinaire ; le texte littéral `<pad><bos><eos><unk>`
  n'est pas injectable comme token spécial ; le décodage ignore `<pad>` et
  `<bos>`, s'arrête à `<eos>` et rend `<unk>` par le caractère de remplacement.

Avec plusieurs artefacts, la section `comparison` place côte à côte les tokens,
`bytes_per_token`, `tokens_per_word` et le rapport de tokens au premier
artefact. Elle est marquée `descriptive_only` : aucun classement, aucun
vainqueur.

## 5. Plan d'expériences proposé

Ce plan est une **HYPOTHÈSE** de travail. Il sera exécuté sur le nœud de calcul
quand celui-ci sera de nouveau joignable. On ne publiera que les métriques et
les empreintes, jamais le contenu du corpus.

| Id | Question | Variables | Données |
| --- | --- | --- | --- |
| E-T1 | Les deux lignées 32k documentées se valent-elles ? | artefact | split `validation` de pilote-v3 |
| E-T2 | Quel effet a la taille du vocabulaire ? | 16k, 24k, 32k, même split `train`, même seuil | split `validation` |
| E-T3 | Quel effet a le seuil de fréquence ? | `minimum_frequency` 1 ou 2 | split `validation` |
| E-T4 | Le corpus bilingue final change-t-il le constat ? | réentraînement décidé par D-042, sur un corpus d'environ 40 % de français technique (D-041) | splits du nouveau manifeste |

Règles communes :

- les comparaisons se font sur `validation`. `test` sert une seule fois, à la
  fin, pour confirmer l'artefact retenu par le propriétaire ;
- chaque exécution consigne l'empreinte du rapport, celles des artefacts, celle
  du split, celle du manifeste et le commit de l'outil ;
- chaque rapport est produit deux fois et les deux empreintes doivent être
  identiques ;
- D-042 conserve un vocabulaire de 32 000. E-T2 reste descriptif et ne rouvre
  pas ce choix. Une variante de 48k unités dépasserait en outre la borne
  actuelle de 32 768 du module runtime ; elle sort du cadre de D-042.

## 6. Étiquetage langue et type : OUVERT

Les splits de pilote-v3 ne portent que `record_id` et `text`. L'outil ne devine
pas la langue : l'identification de langue fait partie de la politique de
traitement du corpus, qui n'est pas décidée. Sur ces splits, les métriques par
langue se réduisent donc au groupe `und/unlabelled`.

Options à arbitrer :

1. un échantillon tenu à l'écart, étiqueté à la main et versionné hors Git,
   dont seule l'empreinte est publiée ;
2. l'étiquetage par paquet source, si le manifeste lie chaque paquet à une
   langue et à un type ;
3. accepter la seule mesure agrégée.

D-042 fonde l'acceptation sur des métriques par langue et sur le code :
l'option 3 ne suffit donc plus à elle seule. Le choix entre les options 1 et 2
reste **OUVERT**.

## 7. Ce que l'outil ne fait pas

- Il ne mesure aucun temps. Le coût de l'encodeur runtime croît avec le nombre
  d'enregistrements et de fusions ; il n'est pas estimé ici. Toute mesure de
  débit suivrait les règles de benchmark d'`AGENTS.md`.
- Il ne juge ni la qualité d'un modèle entraîné avec l'artefact, ni la licence
  ou la provenance du corpus.
- Il ne fixe, ne suggère ni n'applique aucun seuil.
- Il ne promeut aucun artefact et n'écrit ni dans RAW ni dans VALIDATED.

## 8. Décisions du propriétaire en attente

Ces points relèvent du gate G3 (issue #7). Ce document n'en tranche aucun :

1. l'artefact 32k canonique, issu du réentraînement décidé par D-042 ;
2. les valeurs des seuils d'acceptation, par exemple l'écart admissible de
   `bytes_per_token` entre français et anglais, à fixer **après** les mesures.
   D-042 désigne les métriques, pas leurs valeurs ;
3. une éventuelle promotion `approved_core_v1`.

Points tranchés depuis la rédaction, rappelés pour mémoire :

- le réentraînement sur le corpus final (D-042) ;
- les quatre tokens spéciaux, qui sont le contrat du code (`SPECIAL_TOKENS` de
  [`services/inference/tokenizer.py`](../../services/inference/tokenizer.py)),
  et le contexte de 2 048 tokens
  ([ADR-0004](../architecture/adr-0004-core-700m-and-zone-split.md), point 1),
  tous deux conservés par D-042.
