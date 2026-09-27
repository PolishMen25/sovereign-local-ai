# Protocole de preuve répétée CORE-MINI sur placement NUMA

**Statut : PROVISOIRE — phase 0. Le runner et ses contrats sont implémentés ;
deux preuves A/B de trois répétitions ont été produites et comparées. Elles
restent une observation miniature descriptive, sans décision de placement pour
CORE-700M. La section « Protocole G4 étendu » spécifie les mesures qui
manquent ; elle n'est ni implémentée, ni validée sur matériel, ni approuvée.**

Ce protocole définit une preuve bornée pour **un seul placement externe** de
CORE-MINI-1M. Il permet de répéter un workload synthétique comparable sans
publier l'identité de la machine ni sa topologie détaillée. Il n'autorise ni
entraînement long, ni exposition réseau, ni choix de placement pour CORE-700M.

Les preuves A/B existantes n'épuisent pas le protocole : elles ne mesurent pas
encore les charges élargies, la pression mémoire ni les compteurs NUMA requis
pour fermer G4. Ces mesures sont spécifiées dans « Protocole G4 étendu ».

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
  imbrication excessive. Le refus des liens repose sur un contrôle `lstat`
  explicite, partagé avec le vérificateur de distinction, qui vaut aussi là où
  `O_NOFOLLOW` n'existe pas, par exemple sous Windows ;
- des octets qui ne sont pas exactement la forme `canonical-json-v1` suivie
  d'un unique LF : indentation, clés non triées, CRLF, LF absent ou doublé,
  échappements superflus ;
- une preuve d'une autre version que `0.2.0`, une clé inconnue ou manquante ;
- un `proof_id`, un identifiant de session, un horodatage, un engagement ou une
  empreinte mal formés, ainsi qu'un champ de workload hors du contrat `0.2.0`,
  puisque le workload est recopié dans la sortie ;
- un nombre de répétitions hors de 3 à 10, zéro compris, ou une statistique
  que le recalcul exact ne retrouve pas ou ne peut pas représenter (débits
  finis proches du maximum flottant) ;
- une répétition hors du contrat `0.2.0` : `repetition_id` non entier (un
  booléen compris), empreinte mal formée, nombre d'étapes ou de jetons mesurés
  différent de celui que fixe le workload, durées d'étape absentes, non finies,
  négatives ou autres que des flottants. Ces champs ne sont pas recopiés dans
  la sortie ; ils restent liés à elle par le SHA-256 du fichier de preuve ;
- deux fichiers de même SHA-256, deux `proof_id` identiques, ou des libellés
  autres que `placement-a` puis `placement-b` ;
- deux sessions différentes, un champ de workload différent (le refus interne
  nomme le champ, la CLI ne l'affiche pas) ou deux empreintes de workload
  différentes ;
- deux preuves qui partagent `placement.contract_commitment_sha256`.

Limite : l'engagement de placement est salé à chaque run. Deux engagements
différents écartent la réutilisation d'une même preuve, mais ne prouvent pas
que les deux contrats privés désignent des placements différents. Le
comparateur ne vérifie donc pas la distinction effective des placements : c'est
le rôle du reçu séparé décrit dans « Reçu de distinction des placements ».
Sans ce reçu, une comparaison doit être lue comme « distinction des placements
non vérifiée ».

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
| `separation` | `observed_ranges_overlap`, `outcome` et `higher_median_label`, limités par le schéma à leurs combinaisons cohérentes. |
| `interpretation` | `descriptive-only-not-a-core-placement-decision` |
| `gate_status` | `g4-open`, constant. |

Les intervalles observés `[minimum ; maximum]` sont fermés. S'ils se
recouvrent, y compris par une borne commune, `outcome` vaut
`inconclusive-overlapping-observed-ranges` ; sinon il vaut
`disjoint-observed-ranges`. Trois à dix répétitions ne permettent aucune
conclusion statistique : même des intervalles disjoints restent une
description. `higher_median_label` (`placement-a`, `placement-b` ou `tied`)
nomme la médiane la plus haute, jamais un gagnant, et aucun libellé n'est
traduit en socket. Le schéma n'admet que les combinaisons cohérentes : un
recouvrement donne toujours l'issue `inconclusive-overlapping-observed-ranges`,
des intervalles disjoints l'issue `disjoint-observed-ranges`, et `tied` n'est
jamais disjoint, puisque deux médianes égales appartiennent aux deux
intervalles.

`shared_contract.workload` recopie `threads`, comme le font déjà les preuves
`0.2.0`. Si ce niveau égale la taille exacte de l'affinité, une comparaison v2
répète donc un effectif de CPU. Le point 7 des « Points soumis au
propriétaire » (D-025, **OUVERT**) couvre aussi les artefacts de comparaison
v2 ; le comparateur reste inchangé en attendant cette décision.

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

## Reçu de distinction des placements (`core-mini-placement-distinctness.v1`)

**Statut : PROVISOIRE.** L'outil est testé sur fixtures synthétiques
uniquement. Il n'a été exécuté ni sur les contrats ni sur les sels réels, qui
restent privés et hors Git.

`tools/verify_core_mini_placement_distinctness.py` s'exécute hors ligne, là où
se trouvent les répertoires privés des deux runs :

```text
python3 -B tools/verify_core_mini_placement_distinctness.py \
  --placement-a <preuve-a.json> --contract-a <contrat-a.json> --salt-a <sel-a.bin> \
  --placement-b <preuve-b.json> --contract-b <contrat-b.json> --salt-b <sel-b.bin> \
  --output <recu.json>
```

Le sel d'un run est le fichier `placement-commitment-salt.bin` de son répertoire
privé. Le contrat est le fichier exact passé au runner. L'outil :

1. relit les deux preuves avec les contrôles du comparateur, et exige une paire
   que le comparateur accepterait ;
2. relit chaque contrat avec le chargeur strict du runner, et chaque sel, qui
   doit faire exactement 32 octets. Il ne suit aucun lien symbolique et refuse
   ces fichiers privés s'ils se trouvent dans l'arbre source ;
3. recalcule chaque engagement sur les octets exacts du contrat, jamais
   resérialisés, avec le séparateur `core-mini-placement-commitment-v1`. Il
   exige l'égalité avec l'engagement publié par la preuve du même libellé ;
4. compare les deux contrats sur deux axes : l'ensemble des CPU autorisés
   (`cpu_sets_differ`) et les nœuds visés par la politique mémoire
   (`policy_nodes_differ`).

Tout refus renvoie le code 1 et le seul message
`CORE-MINI placement distinctness refused`, sans chemin, sans valeur et sans
trace Python. L'outil refuse :

- un engagement non retrouvé, ou un contrat dont le libellé contredit sa
  preuve ;
- le même sel pour les deux runs ;
- deux placements identiques sur les deux axes ;
- un lien symbolique, un fichier non régulier, trop grand ou tronqué ;
- une preuve non canonique, ou un contrat que le runner aurait refusé ;
- une sortie existante.

Deux contrats qui ne diffèrent que par le mode de politique mémoire ou par les
nœuds mémoire autorisés sont aussi refusés : le reçu ne pourrait pas le dire
sans publier davantage. L'extension du reçu à ces axes est **OUVERTE**.

Le reçu est fermé par
[`core-mini-placement-distinctness.schema.json`](../../schemas/core-mini-placement-distinctness.schema.json).
Il ne contient que des constantes, les deux engagements et les deux booléens,
dont au moins un vaut `true`. Il ne contient ni identifiant de CPU ou de nœud,
ni effectif, ni sel, ni chemin, ni mesure. Il se rattache à une comparaison v2
par l'égalité des deux engagements.

**Règle PROVISOIRE :** une comparaison ne peut être présentée comme portant sur
deux placements distincts que si elle est accompagnée d'un reçu portant les
mêmes engagements. Sans reçu, elle est qualifiée de « distinction des
placements non vérifiée ». Les comparaisons v1 du 2026-09-06 et du 2026-09-07
n'ont pas de reçu. Les produire sur les preuves réelles reste une étape à
exécuter sur le serveur de calcul.

Le reçu atteste une différence entre contrats. Il ne prouve ni la localisation
effective des pages mémoire ni l'absence d'accès distants. La mesure de
localité est spécifiée dans « Protocole G4 étendu ».

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
comme une activation de production. La section suivante spécifie
ce qui manque pour le fermer.

## Protocole G4 étendu

**Statut : PROVISOIRE — spécification seulement.** Rien dans cette section n'est
implémenté dans le runner ni validé sur matériel : le serveur de calcul est
hors ligne. Elle prépare l'approbation exigée par l'issue #8 (« Le propriétaire
approuve le protocole avant le benchmark long »). Elle reste PROVISOIRE tant
que le propriétaire n'a pas consigné cette approbation dans le registre des
décisions.

Les statuts ont ici un sens précis :

- **CONFIRMÉ** : comportement présent dans le dépôt et couvert par ses tests.
  Ce n'est ni une validation sur matériel, ni une approbation ;
- **PROVISOIRE** : règle spécifiée ici, pas encore implémentée ;
- **OUVERT** : choix réservé au propriétaire ;
- **HYPOTHÈSE** : propriété à vérifier sur l'hôte réel.

Préconditions communes (PROVISOIRE) :

- G4 doit d'abord être recadré après D-034. CORE-80M est historique, CORE-700M
  ne reçoit pas de palier long, et la lignée CORE-30M a déjà été entraînée hors
  de ce protocole. Restent **OUVERTS** : ce que G4 conditionne désormais, le
  modèle visé par l'extrapolation et l'usage éventuel des temps d'étape de
  cette lignée, mesurés avec un autre protocole ;
- l'hôte est au repos : les autres charges de calcul sont arrêtées pendant
  toute la session, et l'opérateur le consigne dans l'enregistrement privé du
  run. La façon de le vérifier depuis l'invité est **OUVERTE** ;
- toutes les exécutions restent CPU-only et sans réseau, sous les préconditions
  d'isolation déjà imposées par le runner.

### Correspondance avec l'issue #8

| # | Point de la liste de l'issue #8 | Statut | Section |
| ---: | --- | --- | --- |
| 1 | Au moins deux tailles miniatures avec MHA, RoPE, RMSNorm, SwiGLU et poids liés | **OUVERT** (la première échelle est CONFIRMÉE) | « Échelles et workload » |
| 2 | Dataset autorisé, tokenizer, séquence, lots et optimiseur représentatifs | **OUVERT** (le workload synthétique est CONFIRMÉ) | « Échelles et workload » |
| 3 | Un socket/deux sockets, placements NUMA et nombres de threads | **PROVISOIRE** (contrats, comparateur et reçu CONFIRMÉS) | « Matrice de balayage et ordre d'exécution », « Reçu de distinction des placements » |
| 4 | Tokens/s, temps/étape, mémoire de pointe, CPU, défauts NUMA et I/O | **PROVISOIRE** (tokens/s et temps/étape CONFIRMÉS ; défauts NUMA **OUVERT** : ratio de localité proposé à la place, point 10) | « Métriques système », « Temps séparés » |
| 5 | Checkpoint, interruption, reprise, évaluation et inférence | **PROVISOIRE** (checkpoint et reprise d'une étape CONFIRMÉS) | « Interruption et reprise », « Évaluation et inférence » |
| 6 | Chauffe, répétitions, médiane, dispersion et format brut | **CONFIRMÉ** | « Protocole d'un run de preuve », « Format brut et statistiques » |
| 7 | Méthode d'extrapolation et incertitudes | **PROVISOIRE** (modèle visé OUVERT) | « Extrapolation » |
| 8 | Critères d'arrêt sûrs pour RAM, disque, température et stabilité | **PROVISOIRE** (tous les seuils OUVERTS) | « Critères d'arrêt sûrs » |

| Critère d'acceptation de l'issue #8 | Statut | Section |
| --- | --- | --- |
| Protocole relisible et exécutable sans GPU ni accès Internet | **CONFIRMÉ** pour le runner (refus de CUDA/ROCm, sockets INET refusés) ; **PROVISOIRE** pour les extensions, qui n'ajoutent ni dépendance ni accès réseau | « Précondition d'isolation réseau » |
| Configuration matérielle et logicielle complète avec chaque résultat | **PROVISOIRE**, en attente du point 11 sur sa lecture sous D-025 (liaison logicielle par empreintes CONFIRMÉE) | « Configuration et publication » |
| Aucune estimation de jours ou de mois avant les mesures | **PROVISOIRE** | « Extrapolation » |
| Approbation du protocole par le propriétaire avant le benchmark long | **OUVERT** | « Points soumis au propriétaire » |

### Échelles et workload (points 1 et 2)

**CONFIRMÉ.** Le runner exécute une seule échelle, CORE-MINI-1M
([`core-mini.candidate.json`](../../configs/models/core-mini.candidate.json)) :
MHA standard, RoPE, RMSNorm, SwiGLU, poids liés, sans biais, vocabulaire de
4 096. Il refuse toute autre configuration. Son workload est synthétique
(`arithmetic-v1`, sans tokenizer : les identifiants de jetons sont engendrés),
l'optimiseur est AdamW au taux fixe `3e-4`, et le lot, la séquence et les
threads sont des options bornées.

**OUVERT : seconde échelle.**
[`core-30m.candidate.json`](../../configs/models/core-30m.candidate.json)
emploie les mêmes familles d'opérations, mais le runner ne l'accepte pas. Le
propriétaire choisit entre cette configuration et une nouvelle échelle
intermédiaire. Dans les deux cas, le runner lira la configuration versionnée
avec le même chargeur strict et publiera son empreinte ; une échelle n'est
jamais une option libre de la CLI.

**OUVERT : workload représentatif.** Rester en synthétique ou passer au mode
`authorized-text` du trainer avec le paquet pilote-v3 dépend du gate G3 et de
l'issue #7. Le synthétique reste la référence pour comparer des placements, car
il ne dépend d'aucun corpus. Un workload réel exige un tokenizer et un
manifeste approuvés, publiés seulement par empreinte. Il constitue un autre
protocole : ses résultats ne se comparent pas aux preuves synthétiques.

### Matrice de balayage et ordre d'exécution (point 3)

**CONFIRMÉ.** Les contrats privés de placement, le comparateur v2 et le reçu de
distinction existent et sont testés sur fixtures.

**PROVISOIRE.** Les artefacts restent séparés par question posée :

| Question | Variable | Paramètres fixés | Artefacts |
| --- | --- | --- | --- |
| Effet du placement | `placement-a` contre `placement-b` | échelle, threads, lot, séquence, étapes, graine | deux preuves, une comparaison v2, un reçu de distinction |
| Effet des threads | nombre de threads | placement, échelle, lot, séquence, étapes, graine | une preuve par niveau sous un même contrat ; artefact d'agrégation à définir |
| Effet du lot et de la séquence | lot, puis séquence | placement, échelle, threads | une preuve par cellule |

Règles :

- un seul facteur varie à la fois autour d'une cellule de référence ; le plan
  factoriel complet n'est pas exigé ;
- une comparaison de placements ne mélange jamais deux nombres de threads, et
  un balayage de threads ne mélange jamais deux placements ;
- chaque cellule compte 3 à 10 répétitions. Toutes les cellules d'une session
  partagent l'archive source, les locks et l'identifiant de session ;
- les invocations alternent les placements dans l'ordre A, B, B, A, ou dans
  l'ordre inverse, pour que la dérive de l'hôte ne se confonde pas avec l'effet
  du placement. L'ordre réel de passage est consigné. La paire du 2026-09-07
  place la médiane de B au-dessus de celle de A, alors que
  [l'état des capacités](../project/current-capabilities.md) rapporte pour la
  paire du 2026-09-06 un écart en sens inverse ;
- les niveaux de threads, de lot et de séquence restent des paramètres de
  workload publiés, comme `threads` aujourd'hui. Un niveau égal à la taille
  exacte de l'affinité révélerait un effectif de CPU : sa publication relève
  de D-025 et reste **OUVERTE** ;
- la grille des niveaux est **OUVERTE**. Les bornes actuelles du runner
  (lot 1 à 64, séquence 2 à 512, threads 1 à 256) n'en fixent que le domaine
  admissible ;
- associer publiquement `placement-a` et `placement-b` aux classes « un
  socket » et « deux sockets » est **OUVERT** (D-025).

### Métriques système (point 4)

**CONFIRMÉ.** Chaque répétition publie déjà son débit en tokens/s et la
distribution des durées des étapes mesurées après la chauffe.

**PROVISOIRE.** Les métriques suivantes seront relevées pour chaque phase
enfant (entraînement, résumé, vérification et reprise). Elles entreront dans
une nouvelle version du schéma de preuve, qui reste à écrire.

| Métrique | Source prévue | Publication |
| --- | --- | --- |
| Mémoire résidente de pointe | `ru_maxrss` de la `rusage` que renvoie `os.wait4` pour le pid de l'enfant (en kibioctets sous Linux) | octets, par phase |
| Temps CPU utilisateur et système | `ru_utime` et `ru_stime` de la même `rusage` | secondes par phase, et rapport temps CPU / temps mural à titre descriptif |
| Entrées/sorties | `read_bytes` et `write_bytes` de `/proc/self/io`, lus par l'enfant juste avant sa sortie ; à défaut, `ru_inblock` et `ru_oublock` | octets, par phase |
| Localité NUMA | `/proc/self/numa_maps`, lu par l'enfant d'entraînement après la dernière étape mesurée : pages des champs `N<nœud>=<pages>`, pondérées par `kernelpagesize_kB`, situées sur les nœuds de référence, divisées par le total | un seul ratio dans [0 ; 1] |
| Défauts NUMA | **OUVERT** : aucun compteur par processus n'est retenu à ce stade (voir les réserves ci-dessous) ; le ratio de localité est proposé à la place, sous réserve du point 10 soumis au propriétaire | rien tant que le point 10 reste ouvert |

`getrusage(RUSAGE_CHILDREN)` ne convient pas à la mémoire de pointe : il renvoie
le maximum sur tous les enfants terminés, pas celui d'une phase. Les nœuds de
référence sont ceux de la politique du contrat. Pour la politique `local`, qui
n'en nomme aucun, ce sont les nœuds des CPU du contrat, lus dans la topologie du
noyau. Le ratio mesure l'adhésion des pages à la politique, pas une
performance. La lecture de `numa_maps` parcourt les tables de pages : elle a
lieu une fois par répétition, hors des étapes mesurées, pour ne pas en fausser
la durée.

Réserves propres à l'invité conteneurisé non privilégié de la zone CORE, déjà
décrit publiquement comme conteneur dans
[l'état des capacités](../project/current-capabilities.md) (**HYPOTHÈSE** à
vérifier sur l'hôte au repos) :

- `/proc/vmstat` et les compteurs `numastat` par nœud y décrivent l'hôte
  entier et incluent les autres charges. Ils ne mesurent pas le run et ne
  servent ni de métrique publiée ni de critère de comparaison ;
- selon la configuration du conteneur, `/proc/meminfo` peut refléter l'hôte ou
  une vue virtualisée. Les fichiers cgroup v2 `memory.max`, `memory.current` et
  `memory.events` donnent la vue du conteneur ;
- l'accès à `/proc/self/numa_maps` et à `/proc/self/io` depuis l'invité est
  supposé, pas encore constaté ;
- le ratio de localité compte les pages présentes à un instant donné, pas les
  accès : ce n'est pas un taux d'accès distants.

Publication : seuls les scalaires par phase et le ratio sont publiés, jamais un
identifiant de nœud, un nombre de nœuds ni une ventilation par nœud.

### Temps séparés (points 4 et 5)

**CONFIRMÉ.** La durée d'une étape est la différence entre deux horodatages
cumulés du trainer. Elle englobe la préparation du lot (génération synthétique
ou lecture des jetons autorisés), la passe avant, la perte, la passe arrière, le
contrôle de finitude des gradients et l'étape d'optimiseur. À partir de la
deuxième étape, elle inclut aussi l'écriture du journal de l'étape précédente.
Le runner mesure déjà la durée murale de chaque processus enfant, sans la
publier.

**PROVISOIRE.** Chaque répétition publiera séparément :

- la préparation des lots, chronométrée autour de la seule construction du
  lot ;
- le calcul, soit la durée d'étape moins la préparation ;
- l'écriture du checkpoint final, de la sérialisation jusqu'au `fsync` du
  répertoire ;
- la reprise : le chargement strict du checkpoint, puis une étape ;
- la durée murale de chaque phase enfant.

`tokens_per_second` garde sa définition actuelle, qui porte sur les étapes
mesurées après la chauffe. Les nouvelles durées sont publiées à côté.

### Interruption et reprise (point 5)

**CONFIRMÉ.** Chaque répétition relit le checkpoint final avec le vérificateur
strict, reprend une étape, puis confirme que le checkpoint source garde sa
taille et son SHA-256. Le trainer n'écrit son checkpoint qu'en fin de run, dans
un fichier temporaire synchronisé par `fsync` puis substitué de façon atomique.

**PROVISOIRE.** Un test d'interruption s'y ajoute. Il utilise une répétition
dédiée, qui n'entre pas dans les statistiques de débit :

1. partir d'un checkpoint de référence produit par un run complet ;
2. lancer une reprise de plusieurs étapes, puis envoyer `SIGTERM` à l'enfant
   d'entraînement dès qu'une étape intermédiaire, fixée à l'avance et identique
   pour tous les placements, est journalisée ;
3. exiger qu'aucun nouveau checkpoint accepté par le chargeur strict
   n'apparaisse, qu'aucun fichier temporaire ne soit pris pour un checkpoint, et
   que le checkpoint de référence garde sa taille et son SHA-256 ;
4. reprendre depuis le checkpoint de référence jusqu'au terme prévu. Vérifier
   ensuite le compteur d'étapes, la finitude de la perte et, avec le
   vérificateur strict, le nouveau checkpoint et son SHA-256 ;
5. publier l'issue du test (réussite ou refus) et la durée de la reprise, sans
   chemin.

L'égalité bit à bit entre un run interrompu puis repris et un run continu n'est
pas exigée : le calcul multithread sur CPU n'est pas garanti déterministe.
L'exiger, par exemple avec un seul thread et des algorithmes déterministes,
reste **OUVERT**. En mode synthétique, le journal de métriques est ouvert en
ajout. Le traitement des étapes journalisées au-delà du dernier checkpoint
reste à définir avant l'implémentation.

### Évaluation et inférence (point 5)

**PROVISOIRE.** Deux mesures s'ajoutent après chaque répétition. Elles tournent
dans des processus enfants frais, sous le même placement :

- **perte held-out** : perte moyenne sur un jeu d'évaluation fixe, disjoint des
  lots d'entraînement. En synthétique, ce jeu est engendré à partir d'une
  graine d'évaluation distincte et publiée. Avec un corpus autorisé, il vient
  de sa partition de validation, publiée seulement par empreinte. Cette perte
  contrôle la santé du run et la comparabilité entre placements ; elle ne
  mesure pas la qualité du modèle ;
- **inférence gloutonne** : pour une longueur de prompt et un nombre de jetons
  générés fixés, débit du préremplissage et débit de la génération, publiés à
  part du débit d'entraînement, avec chauffe et répétitions comme lui.

La longueur du prompt, le nombre de jetons générés et la taille du jeu
d'évaluation sont **OUVERTS**. Les critères de qualité relèvent de l'issue #9,
pas de ce protocole.

### Format brut et statistiques (point 6)

**CONFIRMÉ.** La section « Protocole d'un run de preuve » fixe déjà la chauffe
(1 à `steps - 3` étapes) et le nombre de répétitions (3 à 10). Elle fixe aussi
les statistiques recalculées (moyenne, médiane, minimum, maximum, écart-type
de population et MAD) et la preuve `canonical-json-v1`, fermée par schéma. Les
journaux bruts restent privés et sont liés à la preuve par SHA-256.

**PROVISOIRE.** Les métriques ajoutées suivent la même règle : valeurs brutes
par répétition dans la preuve, distribution recalculée et vérifiée, nouvelle
version du schéma de preuve avec note de migration. Les preuves `0.2.0`
existantes restent comparables entre elles. Une comparaison entre deux
versions de preuve différentes sera refusée.

### Extrapolation (point 7)

**PROVISOIRE.** L'extrapolation ne commence qu'avec des preuves conformes sur
au moins deux échelles. Ces preuves suivent ce même protocole, sur le même
placement, avec les mêmes threads et le même workload. Des résultats de
protocoles différents ne sont jamais combinés.

Méthode :

1. Coût d'entraînement par jeton pour chaque échelle, selon l'approximation
   usuelle de Kaplan et al. (2020) : `C ≈ 6·N + 6·L·T·d` opérations en virgule
   flottante. `N` compte les paramètres hors embeddings plus la projection de
   sortie `d·V`, qui est calculée même quand les poids sont liés. `L` est le
   nombre de couches, `T` la longueur de séquence et `d` la largeur
   d'attention. Ces valeurs sont dérivées de la configuration versionnée par
   le compteur exact du dépôt, jamais saisies à la main.
2. Débit effectif `E = C × tokens/s`, calculé pour chaque répétition de chaque
   échelle.
3. Fourchette de débit de la cible : de `E_min / C_cible` à `E_max / C_cible`,
   où `E_min` et `E_max` sont les extrêmes de `E` sur toutes les répétitions
   des deux échelles. Si `E` varie d'une échelle à l'autre plus qu'entre les
   répétitions d'une même échelle, le résultat est marqué « non
   stationnaire », et la fourchette est élargie pour couvrir les prédictions
   tirées de chacune des deux échelles.
4. Mémoire : la mémoire de pointe mesurée est ajustée sur les deux échelles
   comme la somme d'un terme proportionnel aux paramètres (poids, gradients et
   deux états AdamW) et d'un terme proportionnel aux activations (lot ×
   séquence × largeur × couches). Elle est publiée en fourchette.
5. Incertitude : dispersion observée, écart entre les prédictions des deux
   échelles, et facteur d'extrapolation `N_cible / N_max_mesuré`, toujours
   publié. Le facteur maximal admis est **OUVERT**.

Le résultat est une fourchette de débit et de mémoire. **Aucune durée**
(heures, jours ou mois) n'est calculée ni publiée. Convertir une fourchette en
durée exige un budget de jetons, un modèle cible et l'accord du propriétaire,
après des mesures reproductibles sur le serveur de calcul. Le modèle cible est
**OUVERT** (recadrage de G4 après D-034).

### Critères d'arrêt sûrs (point 8)

**CONFIRMÉ.** Le runner impose un délai de 30 à 3 600 s par processus enfant.
Il refuse toute répétition incomplète, expirée ou diagnostiquée sur stderr, et
toute valeur non finie. Le trainer vérifie la finitude des gradients à chaque
étape. Une preuve partielle n'est jamais publiée.

**PROVISOIRE.** Les catégories d'arrêt ci-dessous sont surveillées pendant les
étapes et entre les phases. Un déclenchement arrête le run sans preuve
publique ; la catégorie est consignée dans l'enregistrement privé du run.

| Catégorie | Source prévue | Déclenchement | Seuil |
| --- | --- | --- | --- |
| Mémoire disponible | la plus petite de deux marges : `MemAvailable` de `/proc/meminfo` et `memory.max − memory.current` du cgroup | marge sous un plancher | **OUVERT** |
| OOM | enfant terminé par `SIGKILL`, ou incrément de `oom_kill` dans `memory.events` | toute occurrence | sans seuil : arrêt immédiat |
| Disque libre | `statvfs` du système de fichiers du répertoire de run, avant chaque checkpoint | espace sous un plancher | **OUVERT** |
| Température | source **OUVERTE** : les capteurs `hwmon` ne sont probablement pas visibles depuis l'invité non privilégié (**HYPOTHÈSE**) ; une surveillance côté hôte devrait alors arrêter le run | valeur au-dessus d'un plafond | **OUVERT** |
| Stabilité numérique | perte ou gradient non fini (déjà refusé) ; perte qui dépasse un multiple de sa valeur à la fin de la chauffe | valeur non finie ; divergence au-delà du seuil | **OUVERT** pour la divergence |
| Dérive du temps d'étape | médiane glissante des dernières étapes, comparée à la médiane des premières étapes mesurées | rapport au-delà du seuil | **OUVERT** |

La dérive du temps d'étape signale un étranglement thermique ou une contention.
Elle arrête le run parce qu'elle fausserait la mesure, même sans danger pour le
matériel. Le propriétaire fixe les fenêtres, les seuils numériques, la source
de température et la réaction attendue côté hôte.

### Configuration et publication

**CONFIRMÉ.** Chaque preuve lie par SHA-256 l'archive source et son arbre, les
locks PyTorch et NumPy, l'observation du runtime (Python, PyTorch, NumPy,
Linux, architecture et glibc), le contrat d'environnement et la configuration
du modèle. Elle publie aussi les paramètres du workload. Les documents
correspondants restent dans le répertoire privé du run.

**PROVISOIRE.** Le matériel exact n'est pas publié (D-025). L'enregistrement
privé rattache chaque session de benchmark à l'inventaire interne mesuré et aux
contrats de placement. Le type d'invité n'y est pas réservé : la zone CORE est
déjà décrite publiquement comme un conteneur non privilégié (D-029 et
[l'état des capacités](../project/current-capabilities.md)). Pour le matériel,
le dépôt public ne conserve que le caractère bi-socket NUMA et CPU-only.

Le critère de l'issue #8 « configuration matérielle et logicielle complète avec
chaque résultat » est donc lu ici comme satisfait par cet enregistrement privé,
lié à chaque résultat par l'identifiant de session. Cette lecture n'est pas
tranchée : elle est soumise au propriétaire (point 11), qui peut exiger à la
place un résumé public expurgé accompagnant chaque résultat.

Toute sortie publique ajoutée par ce protocole suit « Minimisation de la sortie
publique » : scalaires, ratios, booléens et empreintes seulement. Elle ne
contient jamais d'identifiant ni d'effectif de CPU ou de nœud, de modèle de
processeur, de nom d'hôte ni de chemin. Publier une valeur exacte d'inventaire
exige l'autorisation explicite du propriétaire.

### Points soumis au propriétaire

L'approbation demandée par l'issue #8 porte sur une version précise de ce
document, identifiée par son commit, et sur les points **OUVERTS** :

1. le recadrage de G4 après D-034 : ce que G4 conditionne, le modèle visé par
   l'extrapolation et l'usage éventuel des temps de la lignée CORE-30M ;
2. la seconde échelle miniature et le workload (synthétique ou corpus
   autorisé) ;
3. la grille des threads, des lots et des séquences, et le facteur maximal
   d'extrapolation ;
4. la longueur du prompt, le nombre de jetons générés et la taille du jeu
   d'évaluation ;
5. les seuils d'arrêt (mémoire, disque, température, divergence et dérive) et
   la source de température ;
6. l'exigence éventuelle d'une reprise bit à bit ;
7. la publication éventuelle des classes « un socket » et « deux sockets » pour
   les libellés opaques, et celle d'un niveau de threads égal à la taille de
   l'affinité, que les preuves `0.2.0` et les comparaisons v2 recopient ;
8. l'extension du reçu de distinction à d'autres axes que les CPU et les nœuds
   de la politique ;
9. la façon de vérifier que l'hôte est au repos ;
10. les défauts NUMA, que l'issue #8 cite parmi les métriques : accepter le
    ratio de localité à leur place, ou chercher un compteur par processus. Les
    candidats sont les champs `numa_faults` de `/proc/<pid>/sched`, qui
    dépendent de la configuration du noyau et n'existent que si l'équilibrage
    NUMA automatique est actif, ou l'événement `node-load-misses` de `perf`.
    Leur disponibilité depuis l'invité non privilégié est une **HYPOTHÈSE** à
    vérifier ;
11. la façon de satisfaire, sous D-025, le critère « configuration matérielle
    et logicielle complète avec chaque résultat » : enregistrement privé lié
    par session, comme proposé dans « Configuration et publication », ou résumé
    public expurgé accompagnant chaque résultat.

Tant que le propriétaire n'a pas consigné cette approbation dans le registre
des décisions, ce protocole reste PROVISOIRE, et aucun benchmark long ne peut
s'en réclamer.
