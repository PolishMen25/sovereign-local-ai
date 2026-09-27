# Protocole de preuve répétée CORE-MINI sur placement NUMA

**Statut : PROVISOIRE — phase 0. Le runner et ses contrats sont implémentés ;
deux preuves A/B de trois répétitions ont été produites et comparées. Elles
restent une observation miniature descriptive, sans décision de placement pour
CORE-700M.**

Ce protocole définit une preuve bornée pour **un seul placement externe** de
CORE-MINI-1M. Il permet de répéter un workload synthétique comparable sans
publier l'identité de la machine ni sa topologie détaillée. Il n'autorise ni
entraînement long, ni exposition réseau, ni choix de placement pour CORE-700M.

Les preuves A/B existantes n'épuisent pas le protocole : elles ne mesurent pas
encore les charges élargies, la pression mémoire ni les compteurs NUMA requis
pour fermer G4.

L'implémentation de référence est `tools/core_mini_numa_benchmark.py`. Elle
produit une preuve publique conforme à
[`core-mini-numa-evidence.schema.json`](../../schemas/core-mini-numa-evidence.schema.json)
pour un seul placement. Elle ne compare pas deux placements et n'applique
jamais elle-même une affinité. La version `0.2.0` du contrat lie séparément les
locks PyTorch et NumPy à la preuve. La comparaison de deux preuves relève d'un
outil séparé, `tools/compare_core_mini_numa_evidence.py`, décrit plus bas avec
son contrat de sortie
[`core-mini-numa-comparison.schema.json`](../../schemas/core-mini-numa-comparison.schema.json).

## Frontière du placement externe

Le placement est préparé hors du runner dans un contrat privé et approuvé,
conforme à
[`core-mini-private-placement.schema.json`](../../schemas/core-mini-private-placement.schema.json).
Le schéma est public, mais l'instance et ses valeurs exactes restent hors de
Git. Le contrat strict ne contient que sa version, le libellé opaque du
placement, les identifiants CPU autorisés, les nœuds mémoire autorisés, la
politique mémoire et les nœuds visés par cette politique.

Tous les tableaux d'identifiants doivent être non vides lorsque la politique
l'exige, sans doublon et triés par ordre croissant. Les nœuds visés par la
politique doivent être inclus dans les nœuds mémoire autorisés. Le runner
compare ensuite par égalité exacte le contrat à l'affinité du processus, aux
listes autorisées exposées par le noyau et à la politique mémoire observée. Il
refuse une source absente, incohérente ou hors contrat.

Le runner :

- est lancé sous le placement déjà appliqué ;
- n'accepte sur sa ligne de commande ni commande, ni fragment de shell, ni
  liste brute de processeurs ; ces listes n'existent que dans le contrat privé
  strict ;
- ne modifie jamais lui-même l'affinité CPU ou la politique mémoire ;
- vérifie que les contraintes observées pour son processus correspondent au
  contrat privé avant de lancer une répétition ;
- ne publie que le libellé opaque `placement-a` ou `placement-b` et un
  engagement SHA-256 salé du contrat privé. Le sel aléatoire reste dans le
  répertoire privé du run : la preuve publique ne permet pas de deviner une
  petite topologie candidate par force brute.

La valeur `current-process-matched-private-contract` atteste seulement cette
vérification structurelle. Elle ne prouve pas la localisation de toutes les
pages mémoire ni l'absence d'accès NUMA distant pendant le calcul.

## Contrat de la CLI

La CLI réelle exige quatre options :

| Option | Contrat |
| --- | --- |
| `--run-root` | Nouveau répertoire absolu, inexistant, créé exclusivement sous un parent réel déjà présent. Il reçoit les artefacts privés du run et `evidence.json`; aucun de ses chemins n'entre dans la preuve publique. |
| `--placement-contract` | Fichier régulier borné conforme au schéma privé, lu sans suivre de lien symbolique et haché sur ses octets exacts. |
| `--benchmark-session-id` | Identifiant opaque `session-` suivi d'un UUID v4 canonique en minuscules. Deux preuves destinées à une comparaison doivent partager cet identifiant. |
| `--source-archive` | Archive Git `tar.gz` bornée créée hors de l'arbre source. Le runner exige le commit PAX canonique et vérifie que les fichiers réguliers correspondent exactement à l'arbre source avant et après le run. Il publie le commit et les empreintes de l'archive et de l'arbre, sans chemin. |

Les options bornées sont :

| Option | Défaut | Bornes |
| --- | ---: | ---: |
| `--repetitions` | 3 | 3 à 10 |
| `--steps` | 8 | 6 à 1 000 |
| `--warmup-steps` | 2 | 1 à `steps - 3` |
| `--batch-size` | 2 | 1 à 64 |
| `--sequence-length` | 32 | 2 à 512 |
| `--threads` | 1 | 1 à 256, sans dépasser l'affinité observée |
| `--seed` | 20260831 | entier signé sur 64 bits |
| `--timeout-seconds` | 600 | 30 à 3 600 par processus enfant |

La configuration du modèle et le taux d'apprentissage ne sont pas libres dans
cette CLI : le runner reprend le candidat CORE-MINI versionné, le copie par
création exclusive, le relit avec le chargeur strict commun et fixe le taux à
`3e-4`.

## Précondition d'isolation réseau

Le runner fonctionne uniquement sous Linux avec les interfaces noyau requises
pour observer l'affinité et la politique mémoire. Il ne crée pas son propre bac
à sable réseau : l'opérateur doit le lancer dans un contexte où la création de
sockets de flux et datagrammes des familles `AF_INET` et `AF_INET6` est déjà
refusée.

Avant toute lecture du placement ou création du répertoire de run, le processus
principal tente ces quatre créations et refuse si l'une reste disponible. Une
sonde PyTorch exécutée dans un processus enfant frais confirme le même refus,
l'absence de backend CUDA/ROCm et l'affinité attendue. Chaque phase enfant
atteste aussi son placement et sa politique mémoire avant son programme fixe.
Cette preuve ponctuelle ne couvre pas tous les mécanismes réseau et ne remplace
pas le gate d'isolation réseau complet d'IA-CORE.

## Protocole d'un run de preuve

Une invocation du runner produit au plus une preuve pour un placement :

1. lire une seule fois les octets bornés de la configuration CORE-MINI et du
   contrat privé, puis construire le contrat d'environnement depuis les
   restrictions effectivement appliquées ;
2. vérifier l'archive source et les locks offline PyTorch et NumPy, enregistrer
   l'observation stricte de Python/PyTorch/NumPy/Linux/architecture/glibc, puis fixer
   le commit source, le workload synthétique, la
   graine, le nombre de threads, le lot, la longueur de séquence, le nombre
   d'étapes et la chauffe ;
3. exécuter entre **3 et 10 répétitions** ; chaque répétition lance dans des
   processus frais le trainer, le summarizer et le vérificateur offline, avec
   une liste d'environnement fermée et sans shell ;
4. refuser toute répétition incomplète, expirée, diagnostiquée sur stderr ou
   tout changement du placement entre les phases ;
5. relire le résumé `core-mini-metrics-summary.v2`, exiger que sa sortie fichier
   soit identique à stdout et qu'elle corresponde exactement au journal ;
6. relire le checkpoint avec le vérificateur strict CPU-only, reprendre une
   étape, puis confirmer que le checkpoint source conserve la même taille et
   le même SHA-256 ;
7. lier chaque répétition aux SHA-256 exacts de son journal de métriques, de son
   résumé et de son checkpoint ;
8. recalculer sur les débits des répétitions la moyenne, la médiane, le minimum,
   le maximum, l'écart-type de population et le MAD ;
9. confirmer que les sources du runner, du trainer, du summarizer et du
   vérificateur n'ont pas changé pendant le run, puis créer une sortie JSON
   canonique conforme au schéma
   `schemas/core-mini-numa-evidence.schema.json` dans `evidence.json`, sans
   remplacer une cible existante, et écrire les mêmes octets sur stdout.

La forme canonique `canonical-json-v1` est le résultat UTF-8 sans BOM de
`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"),
allow_nan=False)`. Le SHA-256 `workload_contract_sha256` porte sur l'objet
`workload` seul, sans saut de ligne. Le fichier de preuve emploie la même forme
suivie d'un unique octet LF ; une comparaison future hachera ces octets exacts.

Une preuve partielle n'est jamais publiée. Le nombre de répétitions terminées,
les identifiants `1..N`, les dimensions du workload, les statistiques et toutes
les empreintes sont recalculés et comparés avant émission.

## Preuve d'un placement et comparaison de placements

La preuve du runner établit uniquement que plusieurs runs comparables ont été
terminés sous **un** contrat de placement. Elle ne contient ni gagnant, ni
recommandation, ni projection.

Une comparaison multi-placement est un artefact séparé. Elle doit consommer
exactement deux preuves, `placement-a` et `placement-b`, partageant le même
commit, le même lock, le même contrat d'environnement et le même contrat de
workload, avec deux contrats de placement distincts. Elle doit vérifier les
SHA-256 des preuves avant de calculer des ratios descriptifs. Le libellé opaque
ne permet pas, à lui seul, d'affirmer « un socket » ou « deux sockets ».

## Comparateur de deux preuves (`core-mini-numa-comparison.v2`)

**Statut : PROVISOIRE.** Ce contrat de sortie est testé sur fixtures
synthétiques uniquement. Il n'a pas été rejoué sur les preuves réelles, qui
restent privées et hors Git ; le serveur de calcul est hors ligne.

`tools/compare_core_mini_numa_evidence.py` consomme exactement deux preuves
`0.2.0` :

```text
python3 -B tools/compare_core_mini_numa_evidence.py \
  --placement-a <preuve-a.json> --placement-b <preuve-b.json> \
  --output <comparaison.json>
```

La sortie est créée exclusivement, sans jamais remplacer une cible existante,
sous la forme `canonical-json-v1` suivie d'un unique LF ; les mêmes octets sont
écrits sur stdout. Tout refus renvoie le code 1 et le seul message
`CORE-MINI NUMA comparison refused`, sans chemin, sans valeur et sans trace
Python.

### Refus du comparateur

Avant tout ratio, le comparateur refuse :

- un fichier non régulier, un lien symbolique, une taille hors borne, un JSON
  invalide, une clé dupliquée, une constante non finie, un entier géant ou une
  imbrication excessive ;
- des octets qui ne sont pas exactement la forme `canonical-json-v1` suivie
  d'un unique LF : indentation, clés non triées, CRLF, LF absent ou doublé,
  échappements superflus ;
- une preuve d'une autre version que `0.2.0`, une clé inconnue ou manquante ;
- un `proof_id`, un identifiant de session, un horodatage, un engagement ou une
  empreinte mal formés, ainsi qu'un champ de workload hors du contrat `0.2.0`,
  puisque le workload est recopié dans la sortie ;
- un nombre de répétitions hors de 3 à 10, zéro compris, ou une statistique
  que le recalcul exact ne retrouve pas ;
- deux fichiers de même SHA-256, deux `proof_id` identiques, ou des libellés
  autres que `placement-a` puis `placement-b` ;
- deux sessions différentes, un champ de workload différent (le refus interne
  nomme le champ, la CLI ne l'affiche pas) ou deux empreintes de workload
  différentes ;
- deux preuves qui partagent `placement.contract_commitment_sha256`.

Limite : l'engagement de placement est salé à chaque run. Deux engagements
différents écartent la réutilisation d'une même preuve, mais ne prouvent pas
que les deux contrats privés désignent des placements différents. Le
comparateur ne vérifie donc pas la distinction effective des placements ; sans
vérification privée séparée, une comparaison doit être lue comme « distinction
des placements non vérifiée ».

### Contenu de la sortie v2

| Champ | Contenu |
| --- | --- |
| `schema_version` | `core-mini-numa-comparison.v2` |
| `artifact_type` | `descriptive-two-placement-comparison` |
| `canonicalization` | `canonical-json-v1` |
| `evidence_schema_version` | `0.2.0`, version des deux preuves consommées |
| `benchmark_session_id` | Session commune aux deux preuves. |
| `shared_contract` | `workload_contract_sha256` et l'objet `workload` commun complet : commit et empreintes des sources, locks PyTorch et NumPy, observation du runtime, contrat d'environnement, configuration et dimensions. L'empreinte se recalcule sur cet objet. |
| `placements` | Pour `placement-a` et `placement-b` : `proof_id`, SHA-256 du fichier de preuve, engagement salé, nombre de répétitions et distribution des débits (moyenne, médiane, minimum, maximum, écart-type de population, MAD). |
| `descriptive_ratios` | Ratios B/A de la moyenne, de la médiane, du minimum et du maximum. |
| `separation` | `observed_ranges_overlap`, `outcome` et `higher_median_label`. |
| `interpretation` | `descriptive-only-not-a-core-placement-decision` |
| `gate_status` | `g4-open`, constant. |

Les intervalles observés `[minimum ; maximum]` sont fermés. S'ils se
recouvrent, y compris par une borne commune, `outcome` vaut
`inconclusive-overlapping-observed-ranges` ; sinon il vaut
`disjoint-observed-ranges`. Trois à dix répétitions ne permettent aucune
conclusion statistique : même des intervalles disjoints restent une
description. `higher_median_label` (`placement-a`, `placement-b` ou `tied`)
nomme la médiane la plus haute, jamais un gagnant, et aucun libellé n'est
traduit en socket.

Le schéma est fermé à tous les niveaux. Ses définitions `workload`,
`distribution`, `sha256`, `proofId` et `sessionId` sont identiques à celles du
schéma de preuve `0.2.0`. Les tests valident les artefacts produits contre le
fichier de schéma avec un vérificateur en bibliothèque standard, limité aux
mots-clés employés et qui refuse tout autre mot-clé ; aucune dépendance n'est
ajoutée.

### Migration v1 → v2

Le format `core-mini-numa-comparison.v1` (commit `d13b4cf`) reste documenté
comme **format historique** : c'est celui des artefacts locaux de comparaison
produits le 2026-09-06 et le 2026-09-07, conservés hors Git. Le comparateur
n'émet plus que v2. Les artefacts v1 existants ne sont ni réécrits ni
convertis ; ils restent lisibles grâce à cette table.

| Champ v1 | Équivalent v2 |
| --- | --- |
| `schema_version` = `core-mini-numa-comparison.v1` | `schema_version` = `core-mini-numa-comparison.v2` |
| `artifact_type`, `benchmark_session_id`, `interpretation` | Inchangés. |
| `workload_contract_sha256` (racine) | `shared_contract.workload_contract_sha256` |
| `evidence.placement_a.proof_id` et `evidence.placement_b.proof_id` | `placements.placement-a.proof_id` et `placements.placement-b.proof_id` |
| `evidence.placement_a.sha256` et `evidence.placement_b.sha256` | `placements.<libellé>.proof_file_sha256` |
| `evidence.placement_a.median_tokens_per_second` et son équivalent B | `placements.<libellé>.tokens_per_second.median` |
| `median_tokens_per_second_ratio_a_over_b` (A/B) | `descriptive_ratios.median_b_over_a` (B/A), soit l'inverse du ratio v1. |
| Absents en v1 | `canonicalization`, `evidence_schema_version`, `shared_contract.workload`, engagements, distributions complètes, ratios de la moyenne, du minimum et du maximum, `separation`, `gate_status`. |

L'orientation du ratio s'inverse : le ratio v1 de `0,9497` (A/B) décrit la même
observation qu'un `median_b_over_a` d'environ `1,053`.

Un artefact v1 a été produit avant les refus ci-dessus. Il n'atteste ni la
forme canonique des preuves, ni les bornes de répétitions, ni la différence des
engagements de placement. Le runner impose déjà une sortie canonique et 3 à
10 répétitions lorsqu'il crée une preuve, mais la différence des engagements
entre les deux preuves n'a jamais été contrôlée par le comparateur v1.

Déduction arithmétique, non rejouée : pour la paire du 2026-09-07, la médiane
de B (906,51 tokens/s) se situe dans l'intervalle observé de A
(751,45 à 926,16 tokens/s), si bien que les deux intervalles se recouvrent
nécessairement. La règle v2 classerait donc cette paire
`inconclusive-overlapping-observed-ranges`, avec `higher_median_label` égal à
`placement-b`. La production réelle d'un artefact v2 sur ces preuves privées
reste une étape à exécuter sur le serveur de calcul.

## Minimisation de la sortie publique

Le schéma est fermé avec `additionalProperties: false`. La sortie ne contient
jamais :

- hostname, adresse, identifiant de machine ou nom d'utilisateur ;
- modèle, inventaire, nombre exact ou liste d'identifiants CPU ;
- masque d'affinité, liste de nœuds mémoire ou topologie NUMA exacte ;
- commande, argument libre, variable d'environnement ou chemin de fichier ;
- contenu de métriques, de checkpoint ou de contrat privé.

Le nombre de threads reste présent parce qu'il décrit le workload mesuré, pas
l'inventaire CPU. Les références sensibles sont réduites à des identifiants
opaques bornés et à des SHA-256 ; ces empreintes assurent l'identité des octets,
pas leur authenticité.

## Refus obligatoires

Le runner refuse notamment :

- moins de trois répétitions, une répétition manquante ou dupliquée ;
- un placement absent, non vérifié ou différent pendant la preuve ;
- une archive source non canonique, un commit PAX absent, une dérive du runtime,
  de NumPy, de la configuration ou des hyperparamètres, ou un changement des sources
  hachées pendant le run ;
- un journal, un résumé ou un checkpoint dont l'empreinte ne correspond pas ;
- un nombre non fini, une statistique non reproductible ou une clé inconnue ;
- une sortie existante, un alias de fichier ou toute erreur qui révélerait un
  chemin dans le résultat public.

## Revérification opérationnelle du 2026-09-07

La preuve `proof-5e26f4a2-2cee-4fa7-a9ab-0d800dcc5237` a terminé trois
répétitions sous la révision `6cebad1`, avec checkpoints et reprise vérifiés.
Pour CORE-MINI synthétique, batch 1, séquence 32, 32 threads, 6 étapes dont
1 de chauffe, le débit médian est de 860,88 tokens/s (minimum 751,45 ;
maximum 926,16 ; écart-type population 72,08). Ce run seul ne remplace
pas une comparaison A/B ni le gate CORE-700M.

Le lanceur précédent utilisait `PYTHONPATH` : ses paquets étaient présents
mais invisibles aux enfants Python en mode `-I`, qui ignore cette variable.
Un `venv` standard réutilisant les paquets hors ligne contrôlés via un fichier
`.pth` a permis les imports isolés de NumPy 2.5.2 et PyTorch 2.13.0+cpu.
Le Python système est conservé. Le changement du chemin d'import dans
`6cebad1` ne suffisait donc pas à résoudre cette panne ; le lanceur possédait
déjà une initialisation pour l'exécution directe.

Prérequis de relancement : archive Git de la release exécutée avec préfixe
`source/`, parent du répertoire de preuves déjà créé, contrat distinguant les
nœuds mémoire autorisés des nœuds visés par la politique `bind`, et imports
validés avec le même interpréteur en mode `-I`. Le benchmark a été exécuté
comme service systemd indépendant de SSH avec refus des sockets INET.
Les chemins, contrats et journaux privés restent hors Git.

Une seconde preuve comparable,
`proof-c40e4682-0063-4eea-aa28-e119dc303977`, a été exécutée avec le même
workload et la même session de benchmark. Sa médiane est de 906,51 tokens/s,
contre 860,88 tokens/s pour la première. L'artefact de comparaison local
`core-mini-numa-comparison.v1` (format historique, voir « Migration v1 → v2 »)
donne un ratio A/B de `0,9497`, soit B environ
5,3 % au-dessus de A sur ce test miniature. Cette différence est descriptive :
elle ne choisit pas encore une allocation pour CORE-700M et devra être
confirmée avec des charges, durées et mesures mémoire plus représentatives.

## Limites et gate G4

Même conforme, cet artefact reste une **preuve répétée miniature et
synthétique**. Il ne mesure pas encore la mémoire de pointe, l'utilisation CPU,
les défauts et accès NUMA, les entrées/sorties, le coût de checkpoint/reprise ou
deux échelles miniatures. Il ne prouve ni la qualité d'un modèle, ni la
faisabilité ou la durée d'entraînement de CORE-700M.

Le gate G4 reste donc **ouvert** jusqu'au benchmark reproductible complet,
accepté par le propriétaire. Aucun résultat de ce runner ne doit être présenté
comme une activation de production.
