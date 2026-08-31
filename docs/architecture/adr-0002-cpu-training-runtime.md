# ADR-0002 — Pile CPU pour entraînement et inférence

**Statut : PROPOSÉ**
**Date : 2026-08-31**

## Contexte

CORE-MINI-1M et CORE-80M sont des architectures créées dans le projet. Aucun
poids, tokenizer ni checkpoint n’existe encore. Le chemin doit fonctionner sur
CPU x86-64 bi-socket NUMA, sans CUDA, sans télémétrie et sans téléchargement
depuis IA-CORE.

## Options

### A — Framework tensoriel CPU pour entraînement, runtime spécialisé ensuite

Utiliser une bibliothèque tensorielle CPU auditable pour entraîner le
mini-modèle, puis conserver un runtime Python de référence et évaluer un format
d’inférence optimisé après validation des poids.

- Avantages : autograd, optimiseur, checkpoints et mesures disponibles ; chemin
  réaliste vers CORE-80M.
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
- **CONFIRMÉ** — L'archive hors ligne mesure `202 498 560` octets et porte le
  SHA-256 `a67b0b10163c914f45bb62a5a59c386d46b766211bdbf33bf4df4dd267ba8fc7`.
  Son empreinte a été vérifiée après transfert vers le nœud de calcul.
- **CONFIRMÉ** — Le bundle n'est pas installé. L'acquisition et le transfert ne
  valent ni approbation de cet ADR, ni autorisation d'entraînement long.
- **CONFIRMÉ** — Le harness CORE-MINI est versionné et ses validations
  structurelles participent à une suite locale de 47 tests réussis. PyTorch
  n'étant pas installé sur la cible, le cycle réel entraînement → checkpoint →
  reprise reste à mesurer.

Ces observations ne ferment pas le contrôle complet des licences, le test
d'absence de télémétrie à l'exécution, le benchmark NUMA ni la restauration des
artefacts. Le statut de l'ADR reste donc **PROPOSÉ**.

## Gates avant approbation

1. identifier le processeur réellement exposé et ses instructions ;
2. choisir versions Python/framework compatibles et produire un lock avec
   empreintes ;
3. vérifier les licences et l’absence de télémétrie/téléchargement automatique ;
4. entraîner CORE-MINI-1M sur corpus synthétique, sauvegarder et reprendre un
   checkpoint ;
5. comparer un socket/deux sockets, affinité, mémoire et débit ;
6. restaurer les artefacts depuis le Synology et reproduire le résultat.

Cette proposition n’autorise pas encore l’installation d’un framework ni
l’entraînement long de CORE-80M.
