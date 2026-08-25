# Politique de sécurité

La sécurité est une exigence d'architecture de ce projet. La V1 repose sur un invariant majeur : **IA-CORE ne dispose d'aucun accès Internet au niveau réseau**. Toute donnée externe transite par une chaîne de collecte séparée en DMZ, une quarantaine et une promotion contrôlée. Un Research Gateway est l'option B provisoirement recommandée, pas encore la décision finale. Aucun retour depuis le cœur vers Internet n'est automatique.

Le détail de la conception et des risques est disponible dans :

- [Architecture de référence](docs/architecture/overview.md)
- [Modèle de menaces](docs/security/threat-model.md)

## Versions prises en charge

Le projet est en phase initiale et aucune version de production n'est encore déclarée prise en charge. Jusqu'à la première version stable :

- seule la branche principale actuelle sert de référence de correction ;
- les branches expérimentales et copies locales ne bénéficient d'aucun engagement de maintenance ;
- les versions, composants et images réellement déployés doivent être consignés dans l'inventaire de chaque installation.

Une matrice de support et un cycle de correctifs seront publiés avant la mise en production.

## Signaler une vulnérabilité

N'ouvrez pas d'issue publique pour une vulnérabilité non corrigée, un secret exposé ou une méthode de contournement de l'isolation.

Utilisez en priorité le **signalement privé de vulnérabilité GitHub** du dépôt, dès qu'il est activé. S'il n'est pas disponible, contactez les mainteneurs par un canal privé déjà vérifié. Aucun courriel de sécurité n'étant encore publié, ne transmettez pas de détail sensible à une adresse supposée : l'activation d'un canal privé officiel est un gate avant publication du projet.

Le signalement devrait contenir :

- composant et version ou commit concernés ;
- préconditions et frontière de confiance franchie ;
- étapes minimales de reproduction ;
- impact observé ou plausible ;
- journaux expurgés et preuve de concept non destructive ;
- contournement temporaire éventuel ;
- moyen sûr de reprendre contact.

Ne joignez jamais de donnée personnelle réelle, de clé active, de corpus confidentiel ou d'image complète d'un système de production. Remplacez les secrets par des marqueurs et indiquez séparément qu'une rotation est nécessaire.

Il n'existe pas encore de SLA public de réponse. Les mainteneurs confirmeront la réception par le canal privé, qualifieront le risque, proposeront une mesure de confinement et coordonneront la correction et la divulgation. Les délais formels seront définis avant la première version stable.

## Périmètre des signalements

Sont notamment pertinents :

- accès Internet ou exfiltration possible depuis IA-CORE ;
- franchissement non autorisé entre DMZ, quarantaine, sas, cœur, administration ou NAS ;
- exécution de code par un contenu importé ;
- contournement d'approbation ou altération d'un manifeste de provenance ;
- abus d'un outil MCP au-delà des droits de l'utilisateur ;
- exposition de secrets, prompts, documents, modèles, index ou sauvegardes ;
- élévation de privilège, défaut d'authentification ou journal d'audit falsifiable ;
- dépendance, image, modèle ou paquet dont l'intégrité ne peut être vérifiée ;
- épuisement réaliste de ressources provoquant une perte de service ou de données.

Les vulnérabilités d'un fournisseur tiers doivent aussi être signalées à ce fournisseur. Un défaut d'intégration qui compromet les invariants de ce projet reste toutefois dans notre périmètre.

## Règles pour les tests de sécurité

- utilisez une installation qui vous appartient ou pour laquelle vous avez une autorisation explicite ;
- préférez des données synthétiques et des secrets révoqués ;
- n'effectuez pas de déni de service prolongé, d'exfiltration réelle ni de mouvement latéral hors périmètre ;
- arrêtez le test si vous accédez à des données d'un tiers ;
- conservez les détails exploitables dans le canal privé jusqu'à disponibilité d'un correctif ;
- ne contournez pas les conditions des fournisseurs externes pour tester le Gateway.

Une recherche de bonne foi respectant ces règles sera traitée comme une contribution à la sécurité, sous réserve du droit applicable. Ce texte n'autorise aucune action sur une infrastructure tierce.

## Exigences pour toute contribution

Une modification ne doit pas :

- ajouter de télémétrie, téléchargement, résolution réseau ou mise à jour automatique dans IA-CORE ;
- créer un retour automatique d'informations vers la DMZ ou Internet ;
- placer une clé, un jeton, un certificat privé ou un mot de passe dans Git, une image ou un exemple ;
- donner à un outil MCP un accès générique au shell, aux secrets, à l'hyperviseur ou à tout le système de fichiers ;
- contourner la quarantaine, la vérification d'empreinte ou l'approbation de promotion ;
- rendre un échec de contrôle permissif ;
- mélanger les droits de production avec ceux permettant d'effacer les sauvegardes.

Toute contribution touchant réseau, identité, secrets, parsers, sandbox, MCP, modèles, dépendances ou sauvegardes doit inclure :

- son impact sur les frontières de confiance ;
- des tests de refus et de limites, pas seulement le scénario nominal ;
- une méthode de retour arrière ;
- la mise à jour du modèle de menaces si le risque change ;
- une revue explicite par une personne différente de l'auteur avant déploiement sensible.

Les dépendances et artefacts doivent être obtenus depuis une source approuvée, figés par version, accompagnés d'une empreinte ou signature quand disponible et importés par la chaîne contrôlée. Une nomenclature logicielle et les licences doivent être conservées pour les livrables.

## Secrets et données sensibles

- stockez les secrets hors du dépôt et injectez-les seulement dans le service qui en a besoin ;
- utilisez des identifiants distincts par environnement, service et fournisseur, avec la portée minimale ;
- interdisez les secrets de la DMZ dans IA-CORE et dans les journaux ;
- masquez prompts, contenus et identifiants sensibles dans les traces ;
- révoquez immédiatement tout secret commité ou affiché, puis purgez-le selon une procédure dédiée ; sa suppression dans le dernier commit ne suffit pas ;
- définissez classification, chiffrement, rétention et destruction avant d'utiliser des données réelles.

Les fichiers d'exemple doivent contenir des valeurs manifestement factices. Un analyseur de secrets local et dans la chaîne d'intégration est attendu avant publication.

## Traitement d'une vulnérabilité

Le processus visé est :

1. accuser réception et protéger le canal de communication ;
2. reproduire avec des données synthétiques ;
3. qualifier actifs, frontières, versions et impact ;
4. contenir : désactiver un outil, suspendre les promotions, révoquer une clé ou isoler une zone ;
5. corriger sur une branche privée et ajouter un test de non-régression ;
6. vérifier que la correction ne rétablit aucun flux interdit ;
7. préparer mise à jour, procédure de retour arrière et avis de sécurité ;
8. divulguer de façon coordonnée après disponibilité d'une mesure sûre.

Une vulnérabilité permettant l'accès Internet depuis le cœur, l'exécution de code entre zones, l'accès administrateur non autorisé, l'exfiltration de secrets ou l'altération silencieuse des données est présumée critique jusqu'à analyse contraire.

## Réponse opérationnelle immédiate

En cas de compromission suspectée :

1. suspendre les nouvelles acquisitions et promotions sans ouvrir de flux de secours ;
2. isoler la zone concernée et préserver les preuves ;
3. révoquer les identifiants exposés depuis un poste sain ;
4. identifier les artefacts, index et sauvegardes liés ;
5. restaurer depuis une version connue et vérifier les invariants réseau avant reprise ;
6. documenter la chronologie, les décisions et les actions ;
7. réviser le modèle de menaces et les tests de non-régression.

Les contacts, responsabilités, obligations de notification, durées de conservation, objectifs RPO/RTO et procédures détaillées restent à formaliser avant production.

## Limites

Le fonctionnement local n'est pas à lui seul une garantie de confidentialité ou de fiabilité. Un utilisateur privilégié, un outil MCP excessif, un document hostile, une sauvegarde mal protégée ou une mauvaise segmentation peuvent contourner l'objectif de souveraineté. Les sorties du modèle restent non fiables et doivent être vérifiées avant toute décision ou action importante.

Cette politique n'affirme aucune certification. La mise en production dépend de preuves techniques : inventaire, tests d'isolation, restauration, contrôle de la chaîne d'import et validation des gates décrits dans l'architecture.

