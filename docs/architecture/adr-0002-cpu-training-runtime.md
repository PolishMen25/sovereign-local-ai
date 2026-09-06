# ADR-0002 — Pile CPU pour entraînement et inférence

**Statut : PROPOSÉ**
**Date : 2026-08-31**

## Contexte

CORE-MINI-1M et CORE-700M sont des architectures créées dans le projet ;
CORE-80M reste une référence historique. Des
checkpoints synthétiques de validation CORE-MINI existent, mais aucun poids
linguistique utile ni tokenizer final n'est disponible. Le chemin doit
fonctionner sur CPU x86-64 bi-socket NUMA, sans CUDA, sans télémétrie et sans
téléchargement depuis IA-CORE.

## Options

### A — Framework tensoriel CPU pour entraînement, runtime spécialisé ensuite

Utiliser une bibliothèque tensorielle CPU auditable pour entraîner le
mini-modèle, puis conserver un runtime Python de référence et évaluer un format
d’inférence optimisé après validation des poids.

- Avantages : autograd, optimiseur, checkpoints et mesures disponibles ; chemin
  réaliste vers CORE-700M.
- Risques : dépendances lourdes, opérateurs et performances NUMA à mesurer,
  chaîne de paquets à figer hors ligne.

### B — Moteur entièrement développé dans le projet

Écrire tenseurs, autograd, opérateurs, optimiseur et sérialisation.

- Avantages : contrôle maximal.
- Risques : coût et risque de correction très élevés ; retarde fortement le
  modèle et nécessite une suite numérique considérable.

### C — Runtime d’inférence uniquement

Adopter directement un moteur optimisé pour charger des poids existants.

- Avantages : inférence CPU potentiellement efficace.
- Risques : ne produit pas les poids, ne valide pas l’entraînement et peut ne
  pas représenter exactement l’architecture candidate.

## Proposition

Retenir provisoirement **A** pour CORE-MINI-1M : framework tensoriel CPU dans un
environnement isolé, paquets téléchargés sur un poste d’acquisition, empreintes
et licences vérifiées, puis transfert hors ligne. Conserver **C** comme piste
d’inférence seulement après test de compatibilité et comparaison avec le
runtime de référence. Ne pas retenir B pour la V1 sauf impossibilité démontrée.

## État de préparation observé

- **CONFIRMÉ** — Un bundle PyTorch `2.13.0+cpu`, Linux x86-64, CPython `3.13`
  (`cp313`) a été acquis depuis l'index CPU officiel. Le lock versionné dans
  `configs/runtime/pytorch-2.13.0-cpu-cp313-linux-x86_64.lock.json` décrit
  exactement 10 wheels et applique une liste de marqueurs d'accélérateurs
  interdits.
- **CONFIRMÉ** — L'archive hors ligne a été vérifiée contre le manifeste
  versionné avant et après son transfert vers le nœud de calcul. Les empreintes
  détaillées restent dans le lock et le journal technique.
- **CONFIRMÉ** — Le bundle est installé dans un venv dédié avec résolution
  strictement hors ligne depuis le wheelhouse verrouillé. Python système reste
  inchangé. Le runtime observé est PyTorch `2.13.0+cpu` sous Python `3.13.5`,
  sans CUDA ni ROCm.
- **CONFIRMÉ** — NumPy `2.5.2` a été acquis avec taille et SHA-256 publiés
  vérifiés, transféré puis installé hors ligne sans résolution de dépendances.
  Son lock séparé est versionné et sa version participe désormais à la sonde
  et à la preuve NUMA.
- **CONFIRMÉ** — Le harness CORE-MINI est versionné et ses validations
  structurelles participent à la suite complète de 198 tests locaux réussis.
- **CONFIRMÉ** — Le cycle réel entraînement → checkpoint → reprise a réussi sur
  le ML350 sur 20 étapes synthétiques bornées, puis a repris 5 étapes jusqu'à
  l'étape 25. La reprise emploie `weights_only=True`; le contrat ne conserve
  que des types sûrs et les checkpoints sont identifiés par SHA-256.
- **CONFIRMÉ** — Le préflight du runner NUMA répété a validé l'archive source,
  le runtime CPU hors ligne, le placement externe et le refus des sockets
  Internet. Le premier run réel a ensuite refusé un argument appartenant au
  wrapper enfant ; le défaut est corrigé, déployé et couvert par les tests.
  Deux preuves A/B de trois répétitions, même commit et même workload ont été
  produites. La médiane de A est 3,8 % au-dessus de B sur ce mini-test ; cette
  observation descriptive ne choisit pas encore un placement pour CORE-700M.

Ces observations ne ferment pas le test d'absence de télémétrie à l'exécution,
le benchmark NUMA complet avec répétitions et charges plus grandes, ni la
restauration des artefacts depuis le stockage durable. Le statut de l'ADR reste
donc **PROPOSÉ**.

## Gates avant approbation

1. identifier le processeur réellement exposé et ses instructions ;
2. choisir versions Python/framework compatibles et produire un lock avec
   empreintes ;
3. vérifier les licences et l’absence de télémétrie/téléchargement automatique ;
4. entraîner CORE-MINI-1M sur corpus synthétique, sauvegarder et reprendre un
   checkpoint ;
5. comparer un socket/deux sockets, affinité, mémoire et débit ;
6. restaurer les artefacts depuis le Synology et reproduire le résultat.

L'installation bornée du framework et le smoke test CORE-MINI sont réalisés.
Cette proposition n'autorise pas encore l'entraînement long de CORE-700M.
