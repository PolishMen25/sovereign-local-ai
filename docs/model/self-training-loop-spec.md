# Boucle d'auto-entraînement à signal externe

## Statut et invariant

**Statut factuel au 2026-09-27**, établi sans accès au serveur de calcul, hors
ligne depuis le 2026-09-14 environ, contre `main` à `c0b169e` (code de l'arène
et du pont inchangé depuis `db9414d`, registre jusqu'à D-042) :

- **Spécification** : ce document ne lance lui-même ni génération, ni sandbox,
  ni entraînement.
- **Code de l'arène versionné** : génération arbitrée par le bac à sable,
  paquets et pont vers les incréments de corpus sont sur `main` depuis
  `0dcbe8c` (2026-09-11) et ses suites : `b5f0227`, `015b815`, `9b31b41`,
  `8ef2f8a`, `cd68960`, `d9c0e42`, `b486851` pour l'arène ; `229ffe0`,
  `689fa70`, `75d234a`, `0655d42`, `5f59591`, `dbca0c6` pour le pont.
- **Exécutions rapportées seulement par des messages de commit** : `8ef2f8a`
  rapporte un démon qui redémarrait en boucle, `dbca0c6` 41 paquets dont 2
  convertis en incréments, `b486851` des mesures sur 28 paquets réels. Aucun
  relevé versionné ne les confirme et l'état présent n'est pas vérifiable.
- **Critères d'activation non consignés** : le pilote CORE-MINI, l'approbation
  explicite du propriétaire et le taux d'acceptation d'au moins 60 % sur 100
  tâches distinctes (§6) ne figurent dans `docs/project/decisions.md` ni comme
  atteints ni comme levés. `AGENTS.md` (phase 1, D-038) range l'arène et la
  boucle d'auto-entraînement parmi les composants en service sans décision au
  registre, à régulariser avant toute extension. **OUVERT**, décision du
  propriétaire. Rien dans ce document ne vaut approbation d'activation.
- **Données produites** : D-040 rend admissible pour l'entraînement de CORE le
  code synthétique de l'arène, dans les limites données au §4 ; cette
  admissibilité ne vaut pas activation de la boucle.
- **Suite jouée non consignée** : la suite par défaut de
  `services/arena/runner.py` est le benchmark scellé E2
  (`configs/evaluation/core-python-e2.candidate.json`) et 14 noms de fonction
  sont communs à E2 et à `configs/arena/practice-suite.v1.json`. La suite
  réellement jouée par l'arène est **OUVERT**.

Les sections suivantes restent la spécification cible ; les écarts du code sont
signalés là où ils s'appliquent. Selon cette spécification, une boucle ne peut
devenir activable qu'après le pilote CORE-MINI décrit ci-dessous, une
approbation explicite du propriétaire et un taux d'acceptation mesuré d'au
moins **60 % sur 100 tâches distinctes**.

Le seul signal de qualité est mécanique : exécution isolée d'un candidat et
succès de la suite de tests fournie avec la tâche. Le modèle ne note jamais sa
propre sortie. Un candidat dont le processus échoue, expire, dépasse ses limites
ou dont un test échoue est rejeté et ne peut pas rejoindre un paquet de données.

## 1. Génération et tâches vérifiables

Chaque tâche décrit une fonction, son interface, des contraintes et des tests
attendus versionnés. Le modèle produit **N = 8** candidats indépendants par
tâche, avec graine, version de modèle, prompt de tâche et identifiant de tâche
journalisés. Les tâches sont statiques et non ambiguës : elles ne peuvent ni
appeler un service réseau, ni dépendre de l'heure, ni lire un chemin hôte. Le
critère vérifiable est la disponibilité du paquet de tests et de sa commande
déterministe avant toute génération.

## 2. Exécution isolée

Chaque candidat est exécuté dans une instance jetable, sans interface réseau ni
DNS, sous UID non privilégié, avec système de base en lecture seule, aucun
montage hôte, et une unique zone de travail temporaire dédiée. Des namespaces ou
micro-VM, un filtrage d'appels système, des cgroups et une limite de processus
doivent imposer : 10 secondes CPU maximum, 512 Mio mémoire maximum, 64 Mio de
sortie et destruction complète de l'instance après chaque candidat. Le test de
conformité bloque la boucle si une résolution DNS, une connexion réseau, une
écriture hors zone ou une limite non imposée est observée.

## 3. Tri et audit

Un candidat est retenu seulement si le lanceur sandbox renvoie le code de succès
et que tous les tests attendus passent. Le journal append-only contient les
empreintes de tâche, candidat, tests et sortie de test, les limites appliquées,
le verdict et la raison de rejet, sans recopier de secret. Le taux d'acceptation
est `retenus / candidats exécutés` par tâche, lot et fenêtre glissante de 50
tâches ; ce calcul est le critère vérifiable du tri.

## 4. Incrément et gate d'approbation

Les candidats retenus forment un paquet séparé : manifeste, SHA-256 des octets,
provenance des tâches/tests, versions du générateur et du sandbox, et rapport de
tri. Il reste RAW jusqu'à un commit propriétaire de
`core-v1-source-policy.approved.json` compatible avec le même vérificateur que
le corpus externe. Aucun résultat de test, journal ou sortie de modèle ne
constitue une promotion automatique vers l'entraînement.
*[Condition d'approbation remplacée par D-039 et D-040 ; voir ci-dessous.]*

**Registre au 2026-09-27.** D-039 ratifie `6d959d7`, qui retire
`core-v1-source-policy.approved.json` du préflight : une version de corpus est
autorisée dès qu'une politique automatique versionnée et auditée produit son
manifeste `VALIDATED`, sans approbation du propriétaire par version ; chaque
décision automatique est journalisée avec un acteur de politique et reste
révocable avant consommation. D-040 rend admissibles les données
synthétiques de l'arène, limitées au code dont chaque solution passe ses tests
en bac à sable, généré par Qwen2.5-Coder, étiqueté synthétique et sans
recouvrement avec les jeux d'évaluation, dans la limite de 20 % des tokens
d'une version de corpus ; les sorties de BOOTSTRAP restent exclues. D-040
résout le conflit entre `promote_arena_increment` et
`validate_training_corpus_manifest` et demande l'alignement des validateurs.

**Écart du code au 2026-09-27.** Dans le code de `main`, un paquet approuvé
depuis `/arena` est converti en incrément RAW synthétique par un outil lancé à
la main (`tools/build_core_increment_from_arena.py`,
`tools/build_increments_for_approved_packets.py`) ; une approbation déposée
depuis `/corpus` est ensuite appliquée toutes les deux minutes par un service
périodique qui promeut l'incrément en `VALIDATED` avec
`training_authorization` `approved` (`tools/promote_arena_increment.py`).
Restent à livrer par PR : la politique automatique de D-039, qui n'est pas
désignée dans le dépôt ; l'alignement de
`tools/validate_training_corpus_manifest.py`, qui refuse encore un matériau
`synthetic` dont l'autorisation vaut `approved` ; et l'exclusion des
solutions qui ne viennent pas de Qwen2.5-Coder : les paquets enregistrent le
moteur de chaque solution (`engine`), les profils `author-bootstrap` de
`services/arena/league.py` sont servis par BOOTSTRAP, et les outils
d'incrément ne lisent pas ce champ. D'ici là, aucun chemin contractuel ne
mène ces incréments à un manifeste d'entraînement.

## 5. Garde-fous anti-effondrement

Chaque incrément limite les tokens synthétiques retenus à **20 %** du total ; le
reste provient de sources déjà approuvées. Avant emballage, les doublons exacts
(`SHA-256` du candidat normalisé) sont supprimés et la répétition est refusée si
une réponse normalisée dépasse 5 % des retenus. La boucle s'arrête si, après 50
tâches, l'acceptation tombe sous 40 % ou si moins de 80 % des retenus sont
uniques ; les mesures et l'arrêt sont vérifiables dans le rapport de lot.

Les deux seuils portent sur **les retenus** — le contenu dédupliqué qui irait
nourrir CORE — et non sur le vivier brut des solutions acceptées. Un vivier
redondant (l'arène qui rejoue la même tâche) est du gaspillage, pas un
effondrement : il reste mesuré et affiché (`pool_unique_ratio`, `accepted` dans
le manifeste) mais ne bloque aucun paquet. Ce qui bloque, c'est la même réponse
normalisée retenue pour plusieurs tâches — ça, la déduplication ne peut pas le
masquer. Un troisième seuil complète les deux premiers : une seule tâche ne
peut peser plus de **25 %** des retenus (`max_task_share`). Il vient d'une
mesure, pas d'une intuition — sur les 28 paquets réels de septembre 2026, la
tâche la plus représentée pesait entre 5 % et 14 %. Un paquet qui enseigne le
même exercice sous douze formes n'apprend pas grand-chose à CORE, même si ses
douze solutions sont distinctes.

Les paquets créés avant cette correction portent l'ancien verdict figé
dans leur manifeste : `tools/recheck_packet_health.py` les remesure à partir de
leur propre `solutions.jsonl`, sans jamais rien approuver.

## 6. Éligibilité mesurée

Le pilote est éligible uniquement si au moins 100 tâches distinctes donnent un
taux d'acceptation global >= 60 %, une unicité >= 80 %, aucune violation
d'isolation et aucune limite dépassée sans refus. En dessous d'un seul seuil, la
boucle reste INACTIVE ; elle ne produit pas de paquet candidat et n'est pas
relancée automatiquement.

## 7. Validation CORE-MINI puis CORE-700M

CORE-MINI valide d'abord la chaîne entière avec un plafond de 100 tâches × 8
candidats × 10 secondes CPU, soit **8 000 CPU-secondes (2,22 CPU-heures) au
maximum théorique** ; l'usage réel et le débit sont mesurés, sans extrapolation
de durée. CORE-700M ne change ni le signal, ni le sandbox, ni le gate : seuls le
budget CPU, la fréquence des checkpoints et les limites de lot sont re-mesurés
après benchmark NUMA approuvé. Il reste inactif tant que CORE-MINI n'a pas
franchi tous les seuils et qu'un incrément retenu n'a pas été approuvé.
