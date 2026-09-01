# Architecture de référence — V1

> Statut : architecture cible à valider. Ce document distingue les décisions acquises des choix encore ouverts. Il ne constitue pas une configuration réseau prête à déployer.

## 1. Mission et périmètre

La V1 fournit une IA locale souveraine, exploitable sans GPU et sans accès direct à Internet. Elle doit permettre l'inférence locale, l'indexation de connaissances approuvées, l'accès contrôlé par MCP et l'alimentation depuis des sources externes au travers d'une chaîne dédiée.

Décisions acquises :

- calcul principal sur un HPE ML350 Gen9 CPU-only, bi-socket et NUMA ; les
  valeurs exactes proviennent de l'inventaire matériel approuvé et ne sont pas
  recopiées dans l'architecture publique ;
- virtualisation sur Proxmox ;
- stockage durable de la V1 assuré par un Synology RS3617xs+ ; ses capacités et
  son état exacts restent dans l'inventaire interne approuvé ;
- stratégie de stockage hybride acceptée : stockage local Proxmox pour le calcul actif et le temporaire, Synology pour RAW, connaissances, modèles conservés et sauvegardes (D-023) ;
- fonctionnement CPU-only pour la V1 ;
- IA-CORE sans accès Internet au niveau réseau ;
- chaîne de collecte externe et Collector séparés d'IA-CORE dans une zone DMZ ;
- tout contenu externe passe par une quarantaine et une promotion contrôlée ;
- aucun retour automatique de données, de contexte ou de résultat depuis IA-CORE vers Internet ;
- le HPE DL380p Gen8 est hors périmètre de la V1.

Ne sont pas encore figés : l'adoption définitive d'un Research Gateway, son placement exact, le système invité, le moteur d'inférence, la base vectorielle, les protocoles de stockage, le format de déploiement, les VLAN, les règles ACL, les produits de sécurité et la méthode exacte de transfert entre zones.

## 2. Principes structurants

1. **Refus par défaut** : un flux, un outil ou une identité qui n'est pas explicitement autorisé reste bloqué.
2. **Séparation des niveaux de confiance** : Internet, DMZ, quarantaine, transfert, cœur et administration sont des domaines distincts, même si leur implantation physique reste à déterminer.
3. **Données externes non fiables** : téléchargement réussi ne signifie jamais contenu approuvé.
4. **Promotion explicite** : chaque artefact importé est identifié, contrôlé, traçable et approuvé avant d'être utilisable par IA-CORE.
5. **Pas de dépendance cachée au cloud** : télémétrie, résolution de dépendances et vérification de licence ne doivent pas créer une sortie réseau depuis IA-CORE.
6. **Moindre privilège** : comptes, services MCP, partages et secrets sont limités à leur fonction.
7. **Reproductibilité et retour arrière** : modèles, index, configurations et mises à jour sont versionnés et restaurables.
8. **Validation humaine aux frontières** : une action qui publierait, exporterait ou déclassifierait des données ne peut pas être déclenchée automatiquement par le modèle.

## 3. Vue d'ensemble

```text
                 DOMAINE NON FIABLE
  Internet / API / dépôts / sites et documents externes
                         │
                         ▼
  ┌─────────────────────────────────────────────────────┐
  │ DMZ                                                 │
  │ collecte externe* ─► Collector ──► zone de dépôt    │
  │ sorties limitées, secrets dédiés, journalisation    │
  └──────────────────────────┬──────────────────────────┘
                             │ artefacts + manifeste
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │ QUARANTAINE                                         │
  │ analyse, normalisation, provenance, revue, décision │
  └──────────────────────────┬──────────────────────────┘
                             │ promotion contrôlée
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │ DOMAINE IA-CORE — HPE ML350 Gen9 / Proxmox          │
  │ import │ catalogue │ index │ CORE-80M │ MCP local   │
  │                  aucune route Internet              │
  └──────────────────────────┬──────────────────────────┘
                             │ stockage/backup restreint
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │ Synology RS3617xs+                                  │
  │ données durables, instantanés et sauvegardes selon  │
  │ une politique qui reste à valider                   │
  └─────────────────────────────────────────────────────┘

  Administration : plan séparé, accès nominatifs et audités.
  Aucun chemin automatique IA-CORE ──► DMZ ──► Internet.
  * Research Gateway si l'option B est validée.
```

Le dessin simplifie deux chemins distincts : dès acceptation technique, l'original part en écriture append-only vers un partage RAW Synology isolé ; seul un dérivé validé est promu vers IA-CORE. Le dessin exprime des frontières de confiance, pas des VLAN, ports ou règles de pare-feu. Ces paramètres doivent être dérivés d'un inventaire réel et testés avant mise en service.

## 4. Composants logiques

### 4.1 Research Gateway — option provisoirement recommandée

Si l'architecture B est validée après audit, le Gateway concentrera les interactions autorisées avec les fournisseurs et sources externes. Il devra :

- appliquer une liste explicite de destinations et de méthodes autorisées ;
- isoler les identifiants d'API dans la DMZ ;
- limiter volume, durée, fréquence et taille des requêtes ;
- produire un journal d'acquisition et un manifeste de provenance ;
- déposer les résultats en quarantaine, jamais directement dans un index actif ;
- empêcher l'ajout automatique de contexte sensible issu d'IA-CORE à une requête externe.

Une éventuelle soumission de recherches depuis le domaine interne devra être conçue comme un flux distinct, avec minimisation, validation humaine et preuve d'absence de contenu sensible. Elle n'est pas autorisée implicitement par cette architecture.

### 4.2 Collector

Le Collector récupère et encapsule les contenus autorisés. Il calcule au minimum une empreinte, conserve l'URL ou l'identifiant source, l'horodatage, le type détecté, la taille et la licence lorsqu'elle est connue. Les parseurs de formats actifs ou complexes sont exécutés dans un environnement jetable et fortement limité.

Le Gateway et le Collector peuvent être deux services sur une même plateforme ou deux plateformes séparées. Leur placement, leur niveau d'isolation et leur haute disponibilité sont des décisions ouvertes ; ils ne doivent toutefois jamais partager le domaine de confiance d'IA-CORE.

### 4.3 Quarantaine et promotion

La quarantaine conserve séparément l'original, la version normalisée et le manifeste. Une promotion exige des contrôles adaptés au type de contenu :

- cohérence entre extension, type réel, taille et structure ;
- détection de contenu actif, d'archives récursives et de charges malveillantes ;
- contrôle de provenance, licence, données personnelles et sensibilité ;
- signalement des instructions intégrées susceptibles de détourner un agent ou un outil ;
- résultat d'analyse, décision et identité du validateur — personne ou service de politique explicitement autorisé — dans le manifeste ;
- empreinte recalculée lors du franchissement de frontière.

La promotion copie un paquet validé vers une zone d'import inactive. IA-CORE vérifie le manifeste avant indexation. Un rejet ne supprime pas silencieusement les preuves : sa durée de conservation reste à définir.

### 4.4 IA-CORE

IA-CORE regroupe les fonctions de confiance :

- service d'inférence local, dont CORE-80M constitue le candidat de modèle documenté séparément ;
- catalogue des modèles, jeux de données et versions ;
- pipeline d'import et d'indexation ;
- stockage des connaissances approuvées ;
- API locale et serveurs MCP autorisés ;
- évaluations, journaux et supervision locale.

Tous les composants du cœur doivent fonctionner lorsque DNS externe, proxy et route par défaut Internet sont absents. Une erreur de configuration applicative ne doit pas suffire à rétablir une sortie réseau : le blocage est aussi imposé à la frontière réseau.

### 4.5 MCP local

MCP est une frontière d'autorisation, pas un raccourci autour de l'isolation. Chaque serveur ou outil expose une capacité étroite, avec schéma d'entrée, identité appelante, limites de ressources et journal d'audit. Les accès génériques au shell, au système de fichiers, aux hyperviseurs, aux secrets ou à la DMZ sont interdits par défaut.

Les outils de consultation locale peuvent être automatisés après validation. Toute opération modifiant des données importantes, important un paquet, administrant l'infrastructure ou préparant une publication exige une politique plus stricte et, selon le risque, une confirmation humaine.

### 4.6 Stockage Synology

Le Synology héberge les données durables, dépôts d'artefacts et sauvegardes de la V1 ; ses protocoles, performances et modalités d'isolation restent à valider. Les partages sont séparés par usage et montés avec le minimum de droits. Un compte de service d'inférence ne doit pas pouvoir supprimer ses sauvegardes.

Le protocole, le chiffrement, les instantanés, la rétention, la réplication et l'existence d'une copie hors ligne restent à décider. Le NAS ne doit pas devenir une passerelle implicite entre DMZ et IA-CORE.

### 4.7 Administration et observabilité

Le plan d'administration est séparé des flux de données. Les accès sont nominatifs, authentifiés fortement, limités dans le temps lorsque possible et journalisés. Les consoles Proxmox, Synology et sécurité ne sont pas exposées à Internet.

Les métriques et journaux restent locaux. Ils doivent permettre de reconstruire une acquisition, une promotion, un appel MCP et un changement d'administration sans enregistrer inutilement prompts, secrets ou documents complets.

## 5. Flux autorisés de référence

| Flux | Origine → destination | Contenu | Conditions minimales |
|---|---|---|---|
| F0 | collecte externe → fournisseur Internet | requête de recherche | uniquement si l'option B est validée ; destinations/méthodes allowlistées, données déclassifiées, quotas et audit |
| F1 | fournisseur Internet → collecte externe/Collector | réponses, fichiers, métadonnées | réponse à F0 ou dépôt autorisé, limites et journalisation |
| F2 | DMZ → quarantaine | original + manifeste | aucun accès direct à l'index actif |
| F3 | service d'archivage → partage RAW Synology isolé | paquet accepté + reçu d'ingress | écriture append-only, aucune lecture DMZ, identité et partage dédiés |
| F4 | quarantaine → zone d'import IA-CORE | dérivé promu | contrôles réussis, décision, empreinte vérifiée |
| F5 | client local → IA-CORE | requête locale | identité, autorisation, quotas |
| F6 | IA-CORE → client local | résultat | politique de données locale |
| F7 | IA-CORE → partages internes Synology | connaissances, modèles, checkpoints, sauvegardes | partages distincts du RAW, droits minimaux, traçabilité |
| F8 | administration → composants | opérations de gestion | poste et identité autorisés, audit |

Tout autre flux est refusé. En particulier, F3 n'accorde au Collector ou à la DMZ aucun montage lisible du Synology, et F4 n'implique ni session initiée par IA-CORE vers la DMZ ni canal de commande bidirectionnel. Les partages RAW et internes, leurs identités et leurs chemins réseau restent séparés afin que le NAS ne devienne pas un pont. Le mécanisme précis — média amovible contrôlé, sas de fichiers, relais à sens unique ou autre — est un **gate d'architecture**.

## 6. Cycle de vie d'une donnée externe

1. Une recherche est formulée sans transfert automatique de contexte interne.
2. Le service de collecte externe autorise ou refuse la destination et l'opération ; il s'agit du Gateway si l'option B est validée.
3. Le Collector récupère le contenu et crée son manifeste.
4. Après les contrôles d'acceptation d'ingress, l'original et son reçu sont immédiatement archivés en append-only dans le partage RAW isolé.
5. L'artefact est placé en quarantaine, non exécutable et non indexé.
6. Les contrôles techniques, juridiques et de sensibilité sont appliqués ; un futur classement `REJECTED` ne supprime pas le RAW accepté.
7. Un validateur habilité applique la politique de promotion ; une personne approuve les classes sensibles, ambiguës ou explicitement soumises à revue humaine.
8. Le dérivé promu franchit le sas ; IA-CORE en revérifie l'intégrité.
9. L'index est construit en version inactive, évalué, puis activé atomiquement.
10. Le catalogue conserve la lignée : source, transformation, version d'index et décision.
11. Un retour arrière restaure la version précédente sans nouvelle acquisition Internet.

## 7. Déploiement CPU-only

La V1 doit être calibrée par mesure, sans réserver à l'avance des nombres arbitraires de vCPU ou de gigaoctets :

- mesurer débit, latence, mémoire maximale, temps d'indexation et concurrence ;
- tenir compte des deux sockets et de la topologie NUMA du ML350 ;
- préserver des ressources pour Proxmox, l'observabilité et les traitements d'import ;
- appliquer des limites pour empêcher une requête ou un parseur d'épuiser RAM, disque ou threads ;
- privilégier les formats et quantifications compatibles CPU seulement après tests de qualité ;
- conserver des marges de disque pour versions, journaux, index temporaires et restauration.

Le choix entre VM, conteneurs système et conteneurs applicatifs reste ouvert. Les composants qui traitent du contenu non fiable doivent être plus isolés que les services d'inférence et ne doivent pas hériter de leurs secrets.

## 8. Disponibilité, sauvegarde et reprise

La V1 ne promet pas de haute disponibilité tant que les objectifs RPO/RTO ne sont pas définis. Elle doit néanmoins fournir :

- des sauvegardes versionnées de la configuration, des manifestes, du catalogue et des données nécessaires ;
- une séparation des droits entre production et sauvegarde ;
- une procédure de reconstruction documentée ;
- des tests de restauration périodiques sur un environnement isolé ;
- un inventaire des éléments reproductibles qui n'ont pas besoin d'être sauvegardés en totalité ;
- un mode dégradé sûr : l'indisponibilité de la collecte externe — Gateway si l'option B est validée — ne doit pas ouvrir l'accès Internet d'IA-CORE.

Les index dérivés peuvent être reconstruits si les sources approuvées et leurs manifestes sont préservés. La décision dépendra du temps de reconstruction mesuré.

## 9. Gates avant mise en service

| Gate | Preuve attendue |
|---|---|
| A0 — inventaire | versions, interfaces, volumes, propriétaires et dépendances recensés |
| A1 — réseau | schéma réel approuvé ; tests négatifs DNS/HTTP/HTTPS depuis IA-CORE ; flux interzones vérifiés |
| A2 — identités et secrets | rôles, MFA d'administration, rotation, stockage et révocation testés |
| A3 — ingestion | types autorisés, analyses, manifeste, revue et retour arrière opérationnels |
| A4 — MCP | inventaire des outils, autorisations, sandbox, limites et audit testés |
| A5 — modèle et données | provenance, licence, évaluations et critères de promotion documentés |
| A6 — sauvegarde | restauration réussie avec mesure RPO/RTO réelle |
| A7 — capacité | charge CPU/RAM/disque et concurrence testées sur le ML350 |
| A8 — exploitation | supervision, alertes, runbooks et responsables nommés |

Une démonstration fonctionnelle peut précéder certains gates. Aucune donnée sensible ni mise en production ne doit les précéder.

## 10. Informations à collecter

- versions et état de support de Proxmox, Synology DSM, firmwares, BIOS et microcodes ;
- interfaces physiques, commutateurs, pare-feu, adressage existant et capacités de segmentation ;
- emplacement prévu du Gateway, du Collector et de la quarantaine ;
- méthode de transfert interzones et sens d'établissement des connexions ;
- protocoles et performances réelles entre ML350 et Synology ;
- mécanismes actuels d'identité, MFA, PKI, coffre de secrets et bastion ;
- sources/API autorisées, conditions contractuelles, quotas et types de documents ;
- classification des données, exigences de conservation et obligations de confidentialité ;
- nombre d'utilisateurs, profils de charge, langues, tailles de contexte et objectifs de latence ;
- objectifs RPO/RTO, stratégie hors ligne et protection contre le rançongiciel ;
- procédure de mise à jour hors ligne et source de temps de confiance ;
- contraintes électriques, UPS, refroidissement, accès physique et pièces de rechange ;
- propriétaires opérationnels, approbateurs de promotion et circuit de réponse aux incidents.

Ces réponses transformeront cette architecture de référence en architecture détaillée, puis en règles de déploiement vérifiables.

