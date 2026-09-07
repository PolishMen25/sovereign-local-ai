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
locks PyTorch et NumPy à la preuve.

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

## Limites et gate G4

Même conforme, cet artefact reste une **preuve répétée miniature et
synthétique**. Il ne mesure pas encore la mémoire de pointe, l'utilisation CPU,
les défauts et accès NUMA, les entrées/sorties, le coût de checkpoint/reprise ou
deux échelles miniatures. Il ne prouve ni la qualité d'un modèle, ni la
faisabilité ou la durée d'entraînement de CORE-700M.

Le gate G4 reste donc **ouvert** jusqu'au benchmark reproductible complet,
accepté par le propriétaire. Aucun résultat de ce runner ne doit être présenté
comme une activation de production.
