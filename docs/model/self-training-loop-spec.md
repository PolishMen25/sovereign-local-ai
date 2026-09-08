# Boucle d'auto-entraînement à signal externe

## Statut et invariant

**INACTIVE.** Cette spécification ne lance ni génération, ni sandbox, ni
entraînement. Une boucle ne peut devenir activable qu'après le pilote CORE-MINI
décrit ci-dessous, une approbation explicite du propriétaire et un taux
d'acceptation mesuré d'au moins **60 % sur 100 tâches distinctes**.

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

## 5. Garde-fous anti-effondrement

Chaque incrément limite les tokens synthétiques retenus à **20 %** du total ; le
reste provient de sources déjà approuvées. Avant emballage, les doublons exacts
(`SHA-256` du candidat normalisé) sont supprimés et la répétition est refusée si
une réponse normalisée dépasse 5 % des retenus. La boucle s'arrête si, après 50
tâches, l'acceptation tombe sous 40 % ou si moins de 80 % des retenus sont
uniques ; les mesures et l'arrêt sont vérifiables dans le rapport de lot.

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
