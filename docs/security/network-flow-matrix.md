# Matrice des flux réseau interzones

**Statut : PROPOSÉ — phase 0.** Ce document prépare l'issue #4 (cartographie
réseau et preuve de l'isolement d'IA-CORE). Il fournit un modèle de zones
abstraites, un contrat JSON à refus par défaut, un validateur statique, un
exemple synthétique et une procédure de tests négatifs. Il ne propose pas et
n'approuve pas de matrice réelle. Il ne décrit ni topologie, ni adresse, ni nom
d'hôte, ni port, ni équipement.

Le serveur de calcul est hors ligne : rien n'a été vérifié sur le réseau réel.
Aucune phrase de ce document ne décrit un état déployé. Produire la matrice
réelle, la faire approuver et exécuter les tests négatifs exige le réseau réel.

## 1. Périmètre

Ce document couvre :

- le modèle de zones logiques utilisé par la matrice ;
- le contrat d'un flux et les règles vérifiables sans réseau ;
- un exemple synthétique qui respecte les décisions déjà enregistrées ;
- les lignes encore **OUVERTES** ;
- la procédure de tests négatifs à exécuter après démarrage, restauration et
  changement.

Il ne couvre pas :

- les adresses, VLAN, ports, règles de pare-feu et équipements. Ces valeurs
  restent dans l'inventaire interne, hors du dépôt public ;
- le choix entre Research Gateway et dépôt direct (issue #5) ;
- le mécanisme du sas de transfert (question 4 de la section « Réseau et
  frontière de sécurité » du questionnaire de découverte) ;
- l'inventaire du Synology (issue #3). Ce dernier a son propre contrat,
  `schemas/synology-inventory.schema.json`, et décrit l'état du NAS. La matrice
  décrit des flux entre zones et ne réutilise aucun de ses artefacts.

Références : gate A1 (`docs/architecture/overview.md` §9), menaces T05, T06,
T07 et T09 et invariants 1, 5 et 9 (`docs/security/threat-model.md`),
décisions D-007, D-008, D-009, D-023, D-029 et D-030, ADR-0004.

| Fichier | Rôle |
|---|---|
| `schemas/network-flow-matrix.schema.json` | contrat structurel (JSON Schema 2020-12) |
| `tools/validate_network_flow_matrix.py` | validateur statique, stdlib seule, règles de graphe |
| `tests/fixtures/network-flow-matrix.synthetic.json` | exemple synthétique à zones abstraites |
| `tests/test_validate_network_flow_matrix.py` | tests du contrat, des règles et des refus |

## 2. Modèle de zones (PROPOSÉ)

Chaque zone est logique. Un invité, un segment réseau, un partage ou un support
amovible peuvent la réaliser ; cette réalisation reste hors du dépôt.

| Identifiant | Zone | Confiance | Origine documentaire |
|---|---|---|---|
| `internet` | Internet et fournisseurs | hostile, non maîtrisée | modèle de menaces §5 |
| `dmz` | collecte externe et Collector ; Research Gateway si l'option B est retenue | exposée | architecture §3, modèle de menaces §5 |
| `quarantine` | quarantaine : analyse, normalisation, décision | contenu hostile confiné | architecture §4.3 |
| `transfer-airlock` | sas de transfert entre quarantaine et intérieur | frontière critique ; mécanisme **OUVERT** | modèle de menaces §5 |
| `ia-core` | IA-CORE | élevée, sans route Internet | D-007, D-029, ADR-0004 |
| `interface-airlock` | sas d'interface : interface, identité locale, accès LAN et tailnet | intermédiaire | D-029, D-030, ADR-0004 |
| `local-clients` | postes clients LAN ou tailnet du propriétaire | poste humain | D-030 |
| `admin` | plan d'administration | privilégiée | architecture §4.7 |
| `storage-raw` | partage RAW isolé, en ajout seul | élevée, écriture seule | architecture flux F3, D-010, D-011 |
| `storage-internal` | partages internes : connaissances, modèles, checkpoints, sauvegardes | élevée | architecture flux F7, D-023 |
| `coding-agent` | nœud séparé de l'agent de programmation | à définir | D-034, ADR-0005 |

**HYPOTHÈSE.** `storage-raw` et `storage-internal` peuvent résider sur le même
NAS. Leur séparation repose alors sur des partages, des identités et des
chemins réseau distincts (architecture §5, ADR-0004). Une compromission du NAS
lui-même (T13) réunit ces deux zones ; la matrice ne couvre pas ce cas.

Ajouter, retirer ou renommer une zone exige une nouvelle version du schéma.

## 3. Contrat d'un flux

Une matrice contient `schema_version`, `matrix_id`, `status`, `synthetic`,
`default_policy` (toujours `deny`) et une liste bornée de 1 à 128 `flows`.
Tout flux absent de la liste est refusé.

| Champ | Contenu |
|---|---|
| `flow_id` | identifiant `NF-NN` ou `NF-NNN`, unique dans la matrice |
| `origin_zone` | zone qui **initie** la connexion |
| `destination_zone` | zone qui accepte la connexion, distincte de l'origine |
| `direction` | sens du **contenu** : `push`, `pull` ou `bidirectional` |
| `identity` | rôle logique en minuscules, sans chiffre, dédié à ce seul flux ; jamais un compte, un hôte ni une instance |
| `data_class` | catégorie de contenu (tableau ci-dessous) |
| `justification` | 20 à 400 caractères de texte libre expurgé, avec la référence documentaire |
| `approval_ref` | `pending-owner-approval`, `D-NNN` ou `ADR-NNNN` |

Sens du contenu :

- `push` : le contenu va de l'origine vers la destination. Le retour ne porte
  qu'un accusé technique, sans contenu (règle AGENTS.md sur l'accusé du
  collecteur) ;
- `pull` : l'origine demande et le contenu va de la destination vers
  l'origine ;
- `bidirectional` : du contenu circule dans les deux sens, par exemple une
  session ou un appel avec réponse.

Catégories de contenu :

| `data_class` | Contenu | Référence | Dans l'exemple |
|---|---|---|---|
| `research-exchange` | requête déclassifiée sortante et contenu externe entrant | flux F0/F1 | oui |
| `raw-package` | original, manifeste et reçu d'ingress | flux F2/F3 | oui |
| `conversation-export` | messages de conversation déjà assainis | D-032 | non, ligne **OUVERTE** |
| `promoted-derivative` | dérivé promu | flux F4 | oui |
| `local-session` | requête locale et résultat | flux F5/F6 | oui |
| `inference-call` | appel d'inférence du sas d'interface vers IA-CORE | D-029 | oui |
| `internal-knowledge` | connaissances approuvées | flux F7 | oui |
| `model-artifact` | modèles et checkpoints retenus | flux F7, D-023 | oui |
| `backup` | sauvegardes | flux F7 | non, ligne **OUVERTE** |
| `management` | opérations d'administration | flux F8 | non, ligne **OUVERTE** |
| `name-resolution` | résolution de noms | questionnaire, réseau Q5 | non, ligne **OUVERTE** |
| `time-sync` | synchronisation horaire | questionnaire, réseau Q5 | non, ligne **OUVERTE** |
| `software-update` | mises à jour hors ligne | architecture §10 | non, ligne **OUVERTE** |

États et approbation :

- `status: proposed` : brouillon soumis au propriétaire ;
- `status: approved` : réservé au propriétaire, après enregistrement d'une
  décision. Un agent ne pose jamais cette valeur. Chaque flux cite alors une
  entrée `D-NNN` du registre ou un ADR approuvé `ADR-NNNN` ;
- `synthetic: true` : exemple sans valeur opérationnelle. Il reste `proposed`
  et tous ses flux restent `pending-owner-approval`.

Le validateur contrôle la **forme** des références. Il ne lit pas le registre
des décisions et ne prouve donc pas qu'une référence autorise réellement le
flux ; cette vérification reste humaine.

## 4. Règles vérifiées par le validateur (PROPOSÉ)

Les règles de graphe raisonnent sur les **arêtes de contenu** : `push` donne
origine → destination, `pull` donne destination → origine, `bidirectional`
donne les deux.

| Règle | Contrôle | Source |
|---|---|---|
| R1 | `default_policy` vaut `deny` ; tout flux non listé est refusé | architecture §2 et §5 |
| R2 | zones connues seulement ; origine et destination distinctes | modèle de zones §2 |
| R3 | tous les champs présents ; justification non vide, bornée | AGENTS.md, refus sûrs |
| R4 | aucun jeton d'infrastructure dans les textes : adresse IPv4 ou IPv6, adresse matérielle, URL, courriel, nom à point, chemin absolu (POSIX, même à un seul segment, UNC, répertoire personnel, lettre de lecteur), barre oblique inverse, port (`<n>/tcp`, `nom:<n>`, `port <n>`), identifiant de conteneur, de VM ou d'invité, caractère de contrôle ou de mise en forme. **Filet partiel** : voir les limites ci-dessous | AGENTS.md, D-025 |
| R5 | `flow_id` uniques ; une identité par flux | ADR-0004 (identités de stockage séparées), moindre privilège |
| R6 | seule la `dmz` échange avec `internet` | architecture flux F0/F1 |
| R7 | tout flux vers `storage-raw` est `push` : archive en ajout seul, sans lecture par l'écrivain | architecture flux F3 |
| R8 | aucun chemin de contenu depuis `internet` ou `dmz` vers `ia-core` ou `storage-internal` qui ne traverse pas `quarantine` | D-008, T06, invariant 3 |
| R9 | aucun chemin de contenu depuis `ia-core`, `storage-internal` ou `storage-raw` vers `dmz` ou `internet` | D-007, D-009, invariants 1 et 5, T07 |
| R10 | pas de relais bidirectionnel par `storage-raw`, `storage-internal` ou `transfer-airlock` : deux zones distinctes ne peuvent pas à la fois y écrire et y lire | architecture §4.6 et §5, T06 |
| R11 | exemple synthétique toujours `proposed` et en attente ; matrice `approved` réelle, avec une référence enregistrée par flux | AGENTS.md, gouvernance du registre |
| R12 | entrée bornée : fichier régulier sans lien symbolique, 256 Kio au plus, UTF-8 strict sans BOM ni NUL, JSON sans clé dupliquée ni nombre non fini ou démesuré | conventions des outils du dépôt |
| R13 | frontière d'IA-CORE, au niveau de la **connexion** et quel que soit le sens du contenu : un flux dont l'origine est `ia-core` a pour destination `storage-internal` ; un flux dont la destination est `ia-core` a pour origine `interface-airlock` et pour contenu `inference-call`. Tout autre flux qui touche `ia-core` est refusé, y compris depuis `admin` | ADR-0004 point 4, D-029, T05, T06, invariants 1 et 2 |

Un relais **à sens unique** par une zone de stockage reste permis : c'est la
forme d'un sas de fichiers. R8 et R9 empêchent qu'il contourne la quarantaine
ou qu'il fasse sortir du contenu interne.

R8 à R10 raisonnent sur les arêtes de contenu. Un `pull` ouvert par IA-CORE
n'ajoute aucune arête sortante d'IA-CORE, alors que sa requête quitte la zone.
R13 raisonne donc sur l'initiateur de la connexion : NT-09 attend l'échec de
toute session ouverte depuis IA-CORE vers une autre zone que le stockage
interne.

**HYPOTHÈSE.** R8 traite `quarantine` comme la seule zone qui assainit le
contenu. Le validateur ne vérifie aucune décision de promotion : il ignore si le
contenu qui sort de la quarantaine a été validé, et il ne modélise pas l'étape
de promotion contrôlée de la chaîne de confiance (AGENTS.md, invariants 3 et 4
du modèle de menaces). Donner à la quarantaine un accès en écriture au stockage
interne est une question du propriétaire, pas une conséquence de ces règles.

Les messages de refus ne recopient jamais le contenu du document. Codes de
sortie : `0` matrice valide, `1` matrice refusée, `2` ligne de commande
invalide.

Limites :

- le validateur ne voit que les flux déclarés. Il ignore la réalisation
  physique : commutateur partagé, pont d'hyperviseur, compromission du NAS ;
- une matrice valide n'est pas une preuve d'isolement. Seuls les tests négatifs
  de la section 7, exécutés sur le réseau réel, apportent cette preuve ;
- R4 est un filet partiel, pas une preuve d'expurgation. Un nom d'hôte sans
  point, un nombre isolé ou un nom de modèle matériel ne se distinguent pas
  d'un mot ordinaire et passent le filtre. Leur absence reste à vérifier par
  une relecture humaine avant tout résumé public.

## 5. Exemple synthétique

`tests/fixtures/network-flow-matrix.synthetic.json` illustre le contrat. Il ne
propose aucune topologie réelle. Ses huit flux restent `pending-owner-approval`.

| Flux | Origine → destination | Sens | Contenu | Rôle |
|---|---|---|---|---|
| NF-01 | `dmz` → `internet` | bidirectional | `research-exchange` | F0/F1, selon l'ADR Research Gateway |
| NF-02 | `dmz` → `quarantine` | push | `raw-package` | F2 |
| NF-03 | `dmz` → `storage-raw` | push | `raw-package` | F3, ajout seul |
| NF-04 | `quarantine` → `storage-internal` | push | `promoted-derivative` | F4 illustré |
| NF-05 | `ia-core` → `storage-internal` | pull | `internal-knowledge` | F7 en lecture |
| NF-06 | `ia-core` → `storage-internal` | push | `model-artifact` | F7 en écriture |
| NF-07 | `local-clients` → `interface-airlock` | bidirectional | `local-session` | F5/F6, D-030 |
| NF-08 | `interface-airlock` → `ia-core` | bidirectional | `inference-call` | D-029 |

Notes :

- NF-04 n'est **pas** une proposition de mécanisme de sas. Il montre une forme
  compatible avec ADR-0004 point 4, que R13 impose : depuis IA-CORE, seul le
  stockage interne approuvé et la réponse à l'appel d'inférence sont autorisés.
  Le dérivé promu doit donc arriver dans une zone d'import inactive qu'IA-CORE
  lit ;
- **HYPOTHÈSE.** NF-04 donne à la quarantaine un accès en écriture au stockage
  interne, qui porte aussi les connaissances approuvées, les modèles, les
  checkpoints et les sauvegardes. Ce n'est pas une forme de référence : R8
  accepte ce flux parce qu'il traverse la quarantaine, sans vérifier aucune
  décision de promotion. Le mécanisme du sas reste **OUVERT** (T06) et cet
  accès en écriture est une question du propriétaire (section 9) ;
- NF-05 et NF-06 utilisent deux identités distinctes : la lecture et
  l'écriture ne partagent aucun droit ;
- tout le reste est refusé : administration, sauvegarde, DNS, NTP, mises à
  jour, lecture du RAW, dépôt entrant et relais de conversations.

## 6. Lignes OUVERTES

Ces lignes ne sont **pas autorisées** tant que le propriétaire n'a rien
décidé. La colonne du milieu indique ce que le validateur impose déjà, quelle
que soit la décision.

| Sujet | Contrainte déjà vérifiée | Question au propriétaire |
|---|---|---|
| DNS (`name-resolution`) | R6 et R9 : aucune résolution externe depuis une zone interne ; R13 : IA-CORE n'ouvre de flux que vers `storage-internal` | IA-CORE a-t-elle besoin d'une résolution interne ? Servie par quelle zone ? |
| NTP (`time-sync`) | R6 et R9 : aucun NTP externe depuis une zone interne ; R13 : IA-CORE n'ouvre de flux que vers `storage-internal` | Quelle source de temps de confiance (T17) ? Par quelle zone passe-t-elle ? |
| Mises à jour hors ligne (`software-update`) | R6 : seule la DMZ touche Internet ; R8 : un contenu venu d'Internet ou de la DMZ n'atteint IA-CORE ou le stockage interne qu'en traversant la quarantaine | Quel chemin (quarantaine, sas, support amovible) et quelle vérification d'empreinte (T14) ? |
| Sauvegarde et restauration (`backup`) | R9 et R10 : pas de sortie ni de relais bidirectionnel par le stockage | Quelle destination, quelle identité en écriture seule, quelle copie indépendante ou hors ligne, quel test de restauration (A6, T13) ? |
| Administration (`management`) | R13 : aucun flux entre `admin` et `ia-core`, dans un sens ou dans l'autre (D-029) ; R8 et R9 : un plan d'administration unique qui échange avec la DMZ **et** avec le stockage interne est refusé, car il crée un chemin de contenu hors quarantaine | Un plan par zone, un bastion, ou une règle d'exception explicite dans une future version du schéma ? Depuis quels postes (questionnaire, réseau Q6) ? |
| Lecture du RAW | R7 : ajout seul ; R9 : jamais vers la DMZ ; R8 : jamais vers IA-CORE hors quarantaine ; R13 : jamais directement vers IA-CORE | Qui lit le RAW (audit, restauration, constitution de corpus) et par quel chemin ? |
| Mécanisme du sas de transfert | R10 : pas de relais bidirectionnel ; R13 : ADR-0004 point 4 exclut déjà un pull ouvert par IA-CORE vers `transfer-airlock`, sauf si cette zone est réalisée comme une partie de `storage-internal` | Pull interne, dépôt intermédiaire, transfert manuel ou diode (questionnaire, réseau Q4) ? Qui écrit dans le stockage interne, et avec quelle décision de promotion ? |
| Dépôt entrant `internet` → `dmz` | R6 et R8 | Hors F0/F1, un dépôt initié depuis Internet est-il admis ? Lié à l'ADR Research Gateway (issue #5) |
| Relais de conversations (`conversation-export`) | R9 : avec NF-07 et NF-08, un poste client qui pousse vers la DMZ crée un chemin de contenu depuis IA-CORE ; le validateur le refuse | Ce relais (D-032) entre-t-il dans la matrice, ou reste-t-il une exception documentée ? Faut-il une frontière humaine explicite ? |
| Poste client et Internet | R6 : une ligne `local-clients` ↔ `internet` est refusée | L'exemple ne modélise pas l'accès Internet propre du poste client. Ce poste est-il une frontière humaine hors matrice, ou une zone modélisée avec une règle explicite ? |
| Agent de programmation (`coding-agent`) | toutes les règles de graphe ; R13 : aucun flux direct avec `ia-core` | Quels flux, quelles identités, quel accès au dépôt de code et au stockage (D-034, ADR-0005) ? |
| Journalisation centralisée | aucune catégorie dédiée | Zone et flux des journaux append-only (questionnaire, réseau Q8) ; exige une révision du schéma |

## 7. Procédure de tests négatifs (PROPOSÉE, non exécutée)

Cette procédure complète la section 9 « Réseau » du modèle de menaces. Elle
n'a jamais été exécutée : le réseau réel n'est pas joignable.

### 7.1 Déclencheurs

La batterie complète s'exécute :

1. **après démarrage** : démarrage à froid de l'hôte, puis de chaque invité
   des zones internes ;
2. **après restauration** : restauration d'un invité, d'une configuration,
   d'une sauvegarde ou retour à un instantané. Une restauration peut rétablir
   un ancien résolveur, une ancienne passerelle ou un proxy ;
3. **après changement** : toute modification du réseau, du pare-feu, de
   l'hyperviseur, du NAS, du DNS ou du DHCP, et toute nouvelle ligne de la
   matrice.

Une exécution périodique supplémentaire est souhaitable ; sa fréquence reste
**OUVERTE**.

### 7.2 Points de mesure

- depuis chaque charge de la zone `ia-core` ;
- depuis les identités de `storage-internal` et de `storage-raw`, lorsque la
  plateforme permet de les exercer ;
- depuis un point de test placé dans la `dmz`, pour simuler sa compromission ;
- depuis `interface-airlock`, si le propriétaire décide que cette zone n'a pas
  d'accès Internet (point à confirmer).

### 7.3 Vérifications

| ID | Vérification | Résultat attendu |
|---|---|---|
| NT-01 | résoudre un nom externe par le résolveur configuré | échec, sans réponse d'origine externe |
| NT-02 | interroger directement un résolveur externe en DNS UDP, en DNS TCP et en DNS chiffré (DoT, DoH) | échec |
| NT-03 | ouvrir une connexion HTTP vers une cible externe désignée par adresse littérale, pour ne pas dépendre du DNS | échec |
| NT-04 | ouvrir une connexion HTTPS et une connexion QUIC vers la même cible | échec |
| NT-05 | proxy : aucune variable de proxy dans l'environnement des services ni dans la configuration système ; une tentative explicite par tout proxy connu | variables absentes, tentative en échec |
| NT-06 | routage et NAT : aucune route par défaut IPv4 ou IPv6, aucune annonce de routeur IPv6 acceptée, aucune traduction sortante pour la zone sur l'équipement frontière | aucune route ; toute tentative s'arrête à la première frontière |
| NT-07 | joindre un serveur de temps externe | échec |
| NT-08 | depuis la DMZ : ouvrir une session d'administration, de partage de fichiers ou HTTP(S) vers `ia-core` et `storage-internal`, puis lire `storage-raw` | échec partout |
| NT-09 | depuis IA-CORE : ouvrir une session vers la DMZ ou la quarantaine | échec |
| NT-10 | identités de stockage : l'archiveur RAW ne peut ni lire, ni lister, ni supprimer ; le lecteur d'IA-CORE ne peut pas écrire ; aucune identité d'inférence ne peut supprimer une sauvegarde | refus à chaque opération |
| NT-11 | conformité : chaque flux approuvé fonctionne avec sa seule identité ; pour chaque paire de zones sans flux, une tentative échoue | flux approuvés seuls opérationnels |

### 7.4 Règles d'exécution

- « échec » signifie un refus explicite, ou un délai dépassé sans aucune
  réponse d'origine externe ;
- les cibles externes de test sont désignées dans la procédure interne privée,
  jamais dans le dépôt ;
- aucun contrôle n'est désactivé pour faciliter un test, et aucun secret n'est
  utilisé ;
- une connexion interdite qui réussit est un **incident**. Conformément à
  l'invariant 9, on arrête et on ne crée aucun flux de secours. On conserve les
  preuves, on corrige, puis on rejoue toute la batterie ;
- les tests du dépôt n'exécutent aucune sonde réseau. Un script exécutable
  éventuel ne sera écrit qu'après accord du propriétaire, et ne s'exécutera que
  sur l'hôte réel.

### 7.5 Preuves

- enregistrement interne : date UTC, commit du dépôt, zone, identifiant du
  test, déclencheur, résultat attendu et observé, opérateur ;
- résumé public expurgé : identifiant du test, déclencheur, date et résultat,
  sans adresse, nom d'hôte ni équipement.

## 8. Utilisation

```bash
python -B tools/validate_network_flow_matrix.py tests/fixtures/network-flow-matrix.synthetic.json
```

Parcours proposé pour la matrice réelle, entièrement à la main du
propriétaire :

1. établir la matrice réelle hors du dépôt public, avec les seules zones
   abstraites ;
2. la valider avec l'outil ;
3. enregistrer la décision dans le registre ;
4. passer la matrice à `approved` et citer la décision dans chaque flux ;
5. exécuter les tests négatifs de la section 7 sur le réseau réel ;
6. ne publier qu'un résumé expurgé.

## 9. Questions au propriétaire

Aucune de ces questions n'est tranchée ici :

1. Le modèle de zones de la section 2 convient-il, y compris la séparation du
   stockage, `local-clients` et `coding-agent` ?
2. Les règles R5 (une identité par flux), R8 à R10 et R13 sont-elles retenues
   telles quelles ?
3. Le poste client est-il une frontière humaine hors matrice, ou une zone
   modélisée ?
4. Quelle organisation pour le plan d'administration ?
5. Quel mécanisme pour le sas de transfert, compatible avec ADR-0004 ?
6. Qui lit le RAW, et par quel chemin ?
7. Quels chemins et quelles identités pour le DNS, le NTP, les mises à jour et
   la sauvegarde ?
8. Le dépôt entrant et le relais de conversations entrent-ils dans la matrice,
   ou restent-ils des exceptions documentées ? Cette question est liée à l'ADR
   Research Gateway (issue #5).
9. Où conserver la matrice réelle, et sous quelle forme publique ?
10. À quelle fréquence exécuter les tests négatifs périodiques ?
11. La quarantaine peut-elle écrire dans le stockage interne (forme de NF-04),
    ou le dérivé promu doit-il passer par `transfer-airlock` ou par une zone
    d'import distincte ? Quelle décision de promotion le validateur devrait-il
    alors exiger ?
12. Faut-il aussi refuser tout contenu de `quarantine` vers `dmz` ou
    `internet`, c'est-à-dire une dépendance inverse de la chaîne de confiance
    (AGENTS.md) ?
