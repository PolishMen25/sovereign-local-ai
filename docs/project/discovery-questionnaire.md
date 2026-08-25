# Questionnaire de découverte

Ce questionnaire ne répète pas les informations déjà confirmées. Il sert à fermer les inconnues avant de figer l'architecture ou de déployer un service. Les réponses doivent être ajoutées par lots à une issue de découverte puis reportées dans le registre des décisions.

## Priorité 0 — critères de succès

1. Quels sont les trois premiers cas d'usage concrets de la V1, par ordre de priorité ?
2. Qui utilisera la V1 et combien d'utilisateurs simultanés sont attendus ?
3. Quelle qualité minimale doit être démontrée pour chacun de ces cas d'usage ?
4. La V1 doit-elle uniquement répondre avec des citations, ou aussi planifier/exécuter des outils internes ?
5. Quelles actions doivent toujours nécessiter une validation humaine ?

## Corpus et tokenizer

1. Quelles proportions viser entre français, anglais, code, commandes, logs et documentation technique ?
2. Quels langages de programmation et domaines métier sont prioritaires ?
3. Quels formats et volumes existent déjà ? Où se trouvent-ils ?
4. Des données personnelles, secrets, contrats ou contenus sous licence sont-ils présents ?
5. Le tokenizer et tous les poids de CORE étant créés de zéro, faut-il aussi créer le moteur d'embeddings du RAG et le reranker de zéro, ou un petit modèle pré-entraîné local est-il autorisé pour ces deux composants séparés ?
6. Quelle longueur de contexte est nécessaire dans les cas d'usage réels ?

## ML350 Gen9 et Proxmox

1. Version de Proxmox, noyau et microcode actuels ?
2. Répartition exacte des DIMM par socket et canal ; NUMA visible et équilibré ?
3. Contrôleurs, types de disques, RAID/ZFS/LVM, volumes et espace libre réel ?
4. Interfaces réseau, débits et liaisons physiques disponibles ?
5. Charges existantes et ressources à réserver à Proxmox ou à d'autres VM ?
6. Préférence opérationnelle et contraintes entre VM et LXC ?
7. Fenêtres d'entraînement autorisées, limites électriques, thermiques et sonores ?
8. UPS, arrêt propre et supervision matérielle disponibles ?

## Synology RS3617xs+

1. Version DSM et système de fichiers de chaque volume ?
2. Modèle RAID, état SMART, confirmation des ~8,1 To utiles / ~7 To libres déclarés et politique de scrubbing ?
3. NFS, SMB, iSCSI et Container Manager disponibles ou autorisés ?
4. Interfaces 1/10 GbE, agrégation, MTU et réseau réellement utilisé ?
5. Snapshots, réplication, chiffrement au repos et ACL actuellement configurés ?
6. RPO, RTO, seconde copie et procédure de restauration testée ?
7. Quotas souhaités pour RAW, datasets, checkpoints, modèles et audit ?

## Réseau et frontière de sécurité

1. Schéma actuel des routeurs, pare-feu, switches, VLAN, sous-réseaux et hyperviseurs ?
2. Quel équipement appliquera l'absence de route Internet depuis IA-CORE ?
3. Où seront placés Research Gateway, Collector, quarantaine et stockage ?
4. Comment le contenu franchira-t-il la DMZ vers l'intérieur : pull interne, dépôt intermédiaire, transfert manuel ou diode logique/physique ?
5. Quels flux d'administration, DNS, NTP, mises à jour et sauvegarde sont indispensables ?
6. Depuis quels postes et réseaux l'administration sera-t-elle autorisée ?
7. Quel mécanisme d'identité, MFA, certificats et rotation des secrets est disponible ?
8. Les journaux peuvent-ils être centralisés dans une zone distincte et append-only ?

## Recherche externe

1. Fournisseurs autorisés : OpenAI, Anthropic, Google, moteurs de recherche, autres ?
2. Comptes, budgets mensuels, plafonds de tokens et règles de facturation ?
3. Les recherches seront-elles créées uniquement par l'utilisateur, ou aussi par des demandes préparées localement ?
4. Si une demande sort, quelles classes de données doivent être supprimées, pseudonymisées ou approuvées ?
5. Faut-il importer des exports historiques de conversations, et dans quels formats ?
6. Quelles pièces jointes sont autorisées, avec quelles tailles et quels types MIME ?
7. Quelles exigences de conservation, droit d'auteur, suppression et audit s'appliquent ?

## Validation et gouvernance des connaissances

1. Qui peut promouvoir `PENDING` vers `VALIDATED` ?
2. Une double validation est-elle requise pour certains domaines ?
3. Quels critères de source, fraîcheur, contradiction et confiance sont acceptables ?
4. Comment traiter une source devenue fausse, supprimée ou remplacée ?
5. Quelles informations doivent expirer automatiquement ?
6. Qui peut corriger, rejeter, archiver ou purger une donnée ?

## Interface et exploitation

1. Interface Web interne, API, CLI ou combinaison ? IIS est-il une exigence ou seulement un exemple historique ?
2. Système d'identité souhaité : comptes locaux, LDAP/Active Directory, SSO ?
3. Historique par utilisateur, partage de conversations et niveaux de confidentialité ?
4. Navigateurs, appareils et exigences d'accessibilité ?
5. Besoin de haute disponibilité en V1, ou restauration manuelle acceptable ?
6. Niveau de supervision : santé, capacité, performances, coûts externes et alertes ?

## Projet et conformité

1. Licence souhaitée et éventuelles restrictions de redistribution ?
2. Dépendances ou langages interdits/imposés par l'organisation ?
3. Politique de revue, branches, signatures de commits et sauvegarde Git ?
4. Exigences RGPD, sectorielles ou contractuelles applicables ?
5. Qui approuve architecture, sécurité, données et mise en production ?

## Critère de sortie de découverte

La phase 0 peut être close quand les cas d'usage et critères de succès sont écrits, l'inventaire matériel/réseau est vérifié, les flux autorisés et interdits sont approuvés, la gouvernance des données est nommée, la politique du moteur d'embeddings RAG est décidée, les choix structurants ont un ADR et les risques bloquants ont un propriétaire.

