# ADR-0006 — Research Gateway ou dépôt direct sur le Collector

- Statut : **PROPOSÉ**
- Date : 2026-09-26
- Autorité : aucune ; en attente de validation explicite du propriétaire
- Issue : #5 (phase 0, gate G1)
- Orientation concernée : P-001, qui reste provisoire tant que cet ADR n'est
  pas accepté

Ce document compare des options et formule une recommandation provisoire. Il
ne vaut pas décision, n'ajoute aucune entrée au registre, n'autorise aucun appel
fournisseur et ne déploie rien en DMZ.

## Étiquettes employées

- **CONFIRMÉ** : vérifiable dans le dépôt à la date de rédaction (code, schéma,
  registre ou trace de déploiement versionnée et datée).
- **PROVISOIRE** : orientation ou proposition sans validation du propriétaire.
- **OUVERT** : question sans réponse qui conditionne la décision.
- **HYPOTHÈSE** : appréciation de l'auteur, notamment les notes de la matrice,
  à confirmer ou corriger.
- **PROPOSÉ** : valeur soumise au propriétaire (poids, défauts sûrs), sans effet
  avant sa validation.

Aucun état de service n'a été revérifié en direct pour cet ADR. Un composant
décrit comme actif l'est d'après une trace datée du dépôt, pas d'après une
observation récente.

## 1. Contexte

### 1.1 Registre et orientations

- **CONFIRMÉ** — D-008 : les connaissances externes entrent par un flux
  contrôlé ; collecte, quarantaine, validation et promotion précèdent l'usage
  interne ([registre](../project/decisions.md)).
- **CONFIRMÉ** — D-009 : le collecteur externe ne permet aucune lecture
  interne ; il se limite à un API/MCP minimal de dépôt.
- **CONFIRMÉ** — D-012 : toute donnée Internet est non fiable, y compris la
  réponse d'un fournisseur connu.
- **CONFIRMÉ** — D-032 autorise la mise en file automatique des messages de
  conversation déjà assainis dans une file locale supprimable. Son texte ne
  mentionne ni le Collector HTTP ni une exposition réseau.
- **PROVISOIRE** — P-001 : préférer une Research Gateway qui appelle les API
  externes puis dépose les résultats. La validation attendue est une
  comparaison formelle avec un dépôt direct, une politique de sortie, des
  fournisseurs et un budget. Cet ADR fournit la comparaison ; il ne valide pas
  P-001.
- **PROVISOIRE** — P-002 : deux services MCP séparés, Collector externe et
  Knowledge interne. Son invariant — aucune identité, aucun droit de lecture et
  aucun processus de confiance partagés entre ingress externe et consultation
  interne — s'applique à toutes les options ci-dessous.
- **CONFIRMÉ** — Aucune entrée D- ne tranche entre Gateway et dépôt direct.
  Les « fournisseurs externes, gestion des clés, budgets, rétention et
  conditions contractuelles » figurent parmi les décisions ouvertes majeures.
- **CONFIRMÉ** — La [feuille de route](../ROADMAP.md) fait de cet ADR un
  livrable de J2 et le cinquième des premiers tickets.

### 1.2 Contrat d'ingress documenté

- **CONFIRMÉ** — [`research-package` 0.1.0](../../schemas/research-package.schema.json)
  impose `lifecycle_state: RAW`, accepte un `producer.gateway_version`
  facultatif, porte une auto-attestation de scan de secrets à revérifier côté
  serveur, une intégrité SHA-256 sur forme canonique RFC 8785 et des pièces
  jointes réduites à leurs métadonnées.
- **CONFIRMÉ** — Le contrat du Collector décrit dans
  [MCP Collector et MCP Knowledge](../mcp/collector-and-knowledge.md) expose une
  seule capacité, `submit_research_package`. L'accusé contient
  `submission_id`, `received_at`, `ingress_payload_sha256` et un statut
  `accepted` ou `rejected`. Aucune opération `get`, `list`, `search`, `status`,
  `update` ou `delete` n'existe.
- **CONFIRMÉ** — Aucun code n'implémente `submit_research_package` : seuls la
  documentation et le schéma y font référence.
- **CONFIRMÉ** — Les états postérieurs à `RAW` appartiennent au journal
  interne ([provenance et cycle de vie](../data/provenance-and-lifecycle.md)).

### 1.3 Research Gateway

- **CONFIRMÉ** — [`services/research-gateway`](../../services/research-gateway/README.md)
  contient un contrat de responsabilité de deux paragraphes et aucun code.
- **CONFIRMÉ** — Aucun appel fournisseur n'est implémenté. Aucun fournisseur,
  compte ni budget n'est choisi : la section « Recherche externe » du
  [questionnaire](../project/discovery-questionnaire.md) est sans réponse.
- **PROVISOIRE** — L'[architecture](overview.md) (§1, §4.1, flux F0, §6 étape 2,
  §8), le [modèle de menaces](../security/threat-model.md) (§2), le README racine,
  `SECURITY.md` et la documentation MCP présentent l'option B comme une
  orientation recommandée mais non décidée, ou conditionnent un flux à sa
  validation.

### 1.4 Chemin de dépôt direct existant : `POST /v1/conversations`

- **CONFIRMÉ** — [`conversation_http.py`](../../services/mcp-collector/conversation_http.py)
  expose un endpoint en écriture seule. Il exige un jeton Bearer unique d'au
  moins 32 caractères comparé en temps constant, `application/json` et un
  corps d'au plus 1 Mio. Il écoute sur la boucle locale et confie TLS et
  exposition à un reverse proxy ou un tunnel. `GET /healthz` ne renvoie qu'un
  état technique.
- **CONFIRMÉ** — [`conversation_import.py`](../../services/quarantine/conversation_import.py)
  valide un format de conversation 0.1.0 à quatre champs, refuse par motif les
  secrets probables avant écriture, calcule le SHA-256 d'une sérialisation
  JSON triée et compacte, et renvoie l'accusé
  `{state: raw_imported | already_imported, conversation_id, sha256}`.
- **CONFIRMÉ** — [`codex_conversation_sync.py`](../../tools/codex_conversation_sync.py)
  est le client côté poste. Il extrait les seuls messages utilisateur et
  assistant, retire les secrets probables, met en file, envoie en HTTPS sans
  proxy ambiant ni redirection, puis valide l'accusé avant de vider la file.
  Adresse et jeton restent hors dépôt ([README du Collector](../../services/mcp-collector/README.md)).
- **CONFIRMÉ (trace datée)** — L'[état public du déploiement](../project/deployment-status-public.md),
  vérifié au 2026-09-07, et les [capacités actuelles](../project/current-capabilities.md)
  enregistrent un « ingress write-only actif » derrière un relais HTTPS,
  qualifié de preuve opérationnelle réversible de phase 0.
- **OUVERT** — Aucun ADR ni aucune entrée D- n'approuve l'exposition réseau de
  ce chemin. La portée du relais, privée ou publique, n'est pas documentée dans
  le dépôt public. Cet ADR ne l'approuve pas a posteriori.
- **PROVISOIRE** — La [PR #17](https://github.com/PolishMen25/sovereign-local-ai/pull/17),
  ouverte et non fusionnée à la date de rédaction,
  modifie `conversation_import.py`. Un contenu différent sous un
  `conversation_id` existant y devient un instantané versionné conservé à côté
  de l'original, au lieu d'être refusé. La forme de l'accusé ne change pas, et
  des octets identiques renvoient toujours `already_imported`. Cet ADR décrit
  le chemin dans cet état et renvoie aux fichiers sans les modifier.

### 1.5 Écart entre les deux contrats d'ingress

- **CONFIRMÉ** — Le chemin existant ne suit pas le contrat documenté ; le
  tableau ci-dessous détaille l'écart.
- **PROVISOIRE** — Sa résolution relève de l'issue #6 et n'est pas conçue dans
  cet ADR.

| Aspect | `submit_research_package` (documenté) | `/v1/conversations` (code) | Statut |
|---|---|---|---|
| Format | `research-package` 0.1.0 | conversation 0.1.0 | CONFIRMÉ |
| Protocole | outil MCP candidat | HTTP simple | CONFIRMÉ |
| Accusé | `submission_id`, `received_at`, `ingress_payload_sha256`, `accepted`/`rejected` | `state`, `conversation_id`, `sha256` | CONFIRMÉ |
| Empreinte | octets reçus, calculée par le Collector, plus empreinte RFC 8785 déclarée | sérialisation triée du module, non déclarée conforme RFC 8785 | CONFIRMÉ |
| Idempotence | exigée, sémantique non précisée | `already_imported` sur octets canoniques identiques | CONFIRMÉ |
| Limite de débit | exigée | absente du code | CONFIRMÉ |
| Identité | authentification forte Gateway → Collector | jeton Bearer partagé unique | CONFIRMÉ |

## 2. Invariants éliminatoires

Une option qui viole l'un de ces invariants est écartée quelle que soit sa
note. Chaque invariant est **CONFIRMÉ** par sa source.

1. IA-CORE ne contacte jamais Internet, directement ou indirectement (D-007,
   `AGENTS.md`).
2. Le Collector n'offre aucune lecture interne ni opération `get`, `list`,
   `search`, `status`, `update` ou `delete` (D-009).
3. `RAW` n'est pas `VALIDATED` ; l'original est conservé et aucune promotion
   n'est automatique (D-010, D-011).
4. Aucun contexte interne ne sort automatiquement vers Internet (architecture
   §2 principe 8, modèle de menaces invariant 5).
5. Ingress externe et consultation interne ne partagent ni identité, ni droit,
   ni processus (invariant de P-002).
6. Cet ADR n'entraîne ni appel fournisseur ni déploiement DMZ (issue #5).

- **HYPOTHÈSE** — Les trois options peuvent respecter ces invariants par
  construction. Seuls les tests négatifs de l'issue #4 pourront le confirmer.

## 3. Options

### A — Dépôt direct authentifié sur le Collector

- **PROVISOIRE** — Des clients externes authentifiés (outils du propriétaire,
  relais de poste, scripts d'export) produisent eux-mêmes le paquet et le
  déposent sur le Collector write-only.
- **HYPOTHÈSE** — Les clés des fournisseurs restent sur les postes clients,
  hors du périmètre contrôlé par le projet.
- **HYPOTHÈSE** — La DMZ n'émet aucune requête sortante.
- **CONFIRMÉ** — `POST /v1/conversations` est déjà une instance de A, limitée à
  un client et à un format (§1.4).

### B — Research Gateway, puis dépôt

- **PROVISOIRE** — Un Gateway en DMZ détient les clés, applique une liste
  fermée de destinations et de méthodes, les quotas, la politique de
  déclassification et le journal d'appel, construit un `research-package` et
  reste le seul déposant du Collector.
- **CONFIRMÉ** — La documentation MCP précise que les conversations tenues sur
  des interfaces tierces ne sont pas récupérables automatiquement et exigent un
  export ou un import explicite. B seul ne couvre donc pas ces exports.
- **OUVERT** — Sous B strict, le chemin `/v1/conversations` est retiré ou
  conservé comme exception documentée ; voir Q-C.

### C — Hybride

- **PROVISOIRE** — B pour toute recherche initiée par API.
- **PROVISOIRE** — Un dépôt direct authentifié limité aux exports historiques
  initiés par le propriétaire, soit le chemin `/v1/conversations` actuel, avec
  identité, contrat et quotas distincts de ceux du Gateway et sans capacité de
  recherche.
- **HYPOTHÈSE** — Deux contrats d'ingress durables coexistent et doivent être
  maintenus, testés et audités séparément.

## 4. Critères pondérés

- **PROPOSÉ** — Les poids ci-dessous attendent la validation du propriétaire
  (Q-B). Leur somme vaut 100.
- **HYPOTHÈSE** — Les notes vont de 1 à 5 (5 = meilleur) et reflètent le jugement
  de l'auteur à partir des éléments du §1. Le total d'une option vaut
  Σ (poids × note) / 5, sur 100.
- **HYPOTHÈSE** — Le critère 8 recoupe les invariants du §2. Sa note mesure
  seulement le risque résiduel, pas le respect de l'invariant.

| # | Critère (issue #5) | Poids PROPOSÉ | A | B | C | Justification (HYPOTHÈSE) |
|---|---|---:|---:|---:|---:|---|
| 1 | Sécurité et surface exposée | 20 | 3 | 3 | 2 | A : aucune sortie depuis la DMZ, mais un ingress ouvert à plusieurs clients. B : ingress réduit au seul Gateway, mais une sortie Internet et un point de concentration des clés. C : cumule la sortie du Gateway et un ingress direct supplémentaire. |
| 2 | Compatibilité MCP/API réelle | 10 | 3 | 3 | 4 | A : prouvée pour le relais HTTP de conversations ; chaque nouveau client doit construire le paquet. B : un seul composant parle aux API, mais les interfaces tierces restent hors champ. C : couvre API et exports, au prix de deux contrats. |
| 3 | Authentification, gestion et rotation des clés | 15 | 2 | 4 | 3 | A : clés dispersées sur les postes, un jeton de dépôt par client. B : rotation en un point, une seule identité de dépôt. C : clés concentrées plus une identité de dépôt distincte. |
| 4 | Déclassification des demandes sortantes | 15 | 2 | 4 | 3 | A : aucun point d'application dans le projet ; repose sur la discipline humaine. B : point d'application unique avant tout appel, politique encore à écrire. C : B pour l'API ; les exports arrivent après une sortie faite hors contrôle. |
| 5 | Fournisseurs, quotas, coûts et journalisation | 10 | 2 | 5 | 4 | A : coûts et quotas auto-déclarés par client, sans journal central. B : plafonds, quotas et journal d'appel centralisés. C : centralisés pour l'API ; exports hors journal d'appel. |
| 6 | Conservation intégrale et import des exports historiques | 10 | 3 | 3 | 4 | A : accepte exports et recherches manuelles, intégralité invérifiable. B : réponses API intégrales, exports sans chemin prévu. C : les deux chemins sont prévus. |
| 7 | Résilience, idempotence et ajout d'un fournisseur | 5 | 4 | 3 | 3 | A : moins de composants ; ajout d'un fournisseur sans changement serveur mais sans contrôle. B : composant de plus à rendre fail-closed ; ajout par adaptateur revu. C : deux chemins à maintenir. |
| 8 | Absence de lecture interne et de retour automatique | 10 | 4 | 3 | 3 | A : aucun composant sortant ; oracle d'accusé exposé à chaque client. B : le Gateway est un canal sortant latent à fermer vers l'intérieur ; oracle limité au Gateway. C : même canal latent ; oracle exposé à deux identités. |
| 9 | Contraintes contractuelles et données personnelles | 5 | 2 | 3 | 2 | A : conditions de chaque compte client et données personnelles des conversations. B : contrats API identifiés, mais chaque requête reste une divulgation au fournisseur. C : cumule les deux. |
| | **Total sur 100** | **100** | **54** | **70** | **61** | |

### Sensibilité

- **CONFIRMÉ (arithmétique)** — Avec des notes inchangées, C dépasse B si et
  seulement si `w2 + w6 > w1 + w3 + w4 + w5 + w9`, où `wN` est le poids du
  critère N. Avec les poids proposés : 20 contre 65.
- **CONFIRMÉ (arithmétique)** — A dépasse B si et seulement si
  `w7 + w8 > 2·w3 + 2·w4 + 3·w5 + w9`. Avec les poids proposés : 15 contre 95.
- **HYPOTHÈSE** — Le classement dépend donc surtout des notes, pas des poids :
  une révision des notes des critères 3, 4 et 5 pèse plus qu'un rééquilibrage
  raisonnable des poids.
- **HYPOTHÈSE** — Si Q1 reçoit sa réponse par défaut (aucun fournisseur), les
  critères 3, 4 et 5 perdent leur objet pour B et la matrice devient sans
  portée pratique : aucun Gateway n'est construit.

## 5. Deltas de menace

Les identifiants renvoient au [modèle de menaces](../security/threat-model.md).

### T08 — Vol des clés d'API

- **HYPOTHÈSE** — A : les clés des fournisseurs sont dispersées sur des postes
  hors du contrôle du projet, et chaque client détient un jeton de dépôt.
  La rotation et la révocation deviennent un inventaire de postes.
- **HYPOTHÈSE** — B : les clés sont concentrées dans le Gateway, cible unique
  de forte valeur. Parades attendues : clés à portée minimale, plafond côté
  fournisseur, coffre hors dépôt, rotation et alerte d'usage anormal.
- **HYPOTHÈSE** — C : les clés de B, plus le jeton de dépôt du propriétaire pour
  les exports, qui doit rester une identité distincte de celle du Gateway.

### T09 — SSRF et contournement des destinations

- **HYPOTHÈSE** — A : le Collector ne va rien chercher ; le risque SSRF
  n'existe en DMZ que si un composant déréférence une URL d'un paquet, ce que
  la quarantaine doit aussi s'interdire.
- **HYPOTHÈSE** — B et C : le Gateway émet des requêtes et porte le risque SSRF
  principal. Parades attendues : liste fermée, contrôle de l'adresse résolue,
  refus des redirections, des adresses privées et des plages de métadonnées,
  résistance au DNS rebinding et filtrage de sortie au niveau réseau (#4).

### Compromission du Gateway (B, C)

- **HYPOTHÈSE** — Un attaquant obtiendrait les clés, une capacité de sortie et la
  possibilité de déposer des paquets forgés, donc un vecteur d'empoisonnement
  (T04) qui reste soumis à la quarantaine.
- **CONFIRMÉ** — L'invariant 2 du modèle de menaces interdit qu'une telle
  compromission ouvre une session vers IA-CORE, et l'architecture (§8) exige que
  la perte du Gateway n'ouvre aucun accès Internet depuis IA-CORE.

### T07 — Exfiltration et retour automatique

- **HYPOTHÈSE** — A : aucun composant du projet n'émet vers Internet ; le seul
  risque de sortie est humain, lors d'une recherche faite hors du système.
- **HYPOTHÈSE** — B et C : le Gateway est le seul composant sortant. Tout flux
  interne → Gateway (recherche déclenchée par un agent ou par IA-CORE) créerait
  un canal d'exfiltration. L'architecture (§4.1) ne l'autorise pas
  implicitement ; il exigerait une décision et un ADR distincts.

### Oracle d'existence de l'accusé `already_imported`

- **CONFIRMÉ (code sur `main`)** — L'accusé distingue `raw_imported` de
  `already_imported`. Un détenteur du jeton peut donc tester si des octets
  canoniques exacts sont déjà en RAW : un oracle d'un bit.
- **CONFIRMÉ (code sur `main`)** — Un document valide qui réutilise un
  `conversation_id` existant avec un autre contenu reçoit un refus `422`. Pour
  qui connaît l'identifiant, ce refus révèle son existence.
- **PROVISOIRE (PR #17 non fusionnée)** — Après la PR #17, ce second signal
  disparaît, puisque le contenu est conservé comme nouvelle version, mais
  l'oracle `already_imported` demeure.
- **HYPOTHÈSE** — L'impact reste faible tant que le seul client est le
  propriétaire, car il faut connaître les octets exacts. L'oracle entre
  toutefois en tension avec deux règles : l'accusé ne contient aucun état
  interne ultérieur (documentation MCP) et aucune donnée interne
  (`AGENTS.md`). Il est exposé à chaque client sous A, à la seule
  identité du Gateway sous B, et au Gateway plus au relais d'export sous C.
- **OUVERT** — Le traitement (accusé uniforme, idempotence propre à chaque
  client ou autre) relève de l'issue #6.

## 6. Décision

- **OUVERT** — Décision en attente du propriétaire.
- **PROVISOIRE** — Recommandation : retenir **B** comme cible pour toute
  recherche initiée par API, **si et seulement si** le propriétaire autorise au
  moins un fournisseur (Q1). Dans la matrice, B obtient 70, C 61 et A 54 ;
  l'avance de B tient à la gestion des clés, à la déclassification et au
  contrôle des coûts (critères 3, 4 et 5).
- **PROVISOIRE** — Le chemin `/v1/conversations` doit recevoir un statut
  explicite, quelle que soit l'option : exception documentée et bornée sous B,
  ou chemin régulier sous A ou C (Q-C). Cet ADR ne tranche pas.
- **PROVISOIRE** — Tant que Q1 garde son défaut sûr (aucun fournisseur), aucun
  Gateway n'est construit. La seule entrée externe reste alors le chemin de
  conversations, dont le statut doit quand même être tranché.
- **CONFIRMÉ** — Cette recommandation n'approuve pas l'exposition actuelle du
  Collector, ne remplace pas P-001, ne réserve aucun numéro de décision et
  n'autorise ni appel fournisseur ni déploiement.

## 7. Conséquences

### Si A est retenue

- **HYPOTHÈSE** — Aucun Gateway n'est construit ; P-001 est remplacée par une
  décision de dépôt direct.
- **HYPOTHÈSE** — Le Collector doit gérer plusieurs identités clientes, avec
  quotas, révocation et journal propres à chacune, et traiter l'oracle
  d'accusé avant d'ajouter un deuxième client.
- **HYPOTHÈSE** — La politique de déclassification devient une procédure
  humaine écrite, sans point d'application technique.

### Si B est retenue

- **HYPOTHÈSE** — Le Gateway reste à concevoir (placement via #4, contrat via
  #6) ; aucun code n'est écrit en phase 0.
- **HYPOTHÈSE** — Le Collector n'accepte plus qu'une identité : celle du Gateway.
  Le chemin `/v1/conversations` est retiré ou devient une exception documentée,
  datée et révisable.
- **HYPOTHÈSE** — Les exports historiques exigent un import explicite distinct,
  hors Gateway.

### Si C est retenue

- **HYPOTHÈSE** — Deux contrats d'ingress sont maintenus : `research-package`
  pour le Gateway, conversation versionnée pour les exports. Chacun reçoit son
  identité, ses quotas, ses tests négatifs et son traitement de l'oracle.
- **HYPOTHÈSE** — Le chemin de dépôt direct est limité par contrat aux exports
  initiés par le propriétaire et ne doit jamais devenir un second canal de
  recherche.

### Dans tous les cas

- **PROVISOIRE** — Le propriétaire enregistre sa décision au registre sous le
  prochain numéro libre au moment de l'enregistrement, puis marque P-001 selon
  la procédure du registre, sans la réécrire.
- **PROVISOIRE** — Une passe d'alignement suit la décision : architecture
  (§1, §4.1, F0, §6, §8), modèle de menaces (§2), documentation MCP, README des
  services, README racine et `SECURITY.md`. La ligne de chaîne de confiance
  d'`AGENTS.md` relève du propriétaire. Le README du Collector ne sera modifié
  qu'après fusion de la PR #17.
- **CONFIRMÉ** — Le modèle de menaces (§2) indique encore que le DL380p Gen8 ne
  participe pas à la V1, alors que D-006 est remplacée par D-034. La passe
  d'alignement doit le signaler, pas le corriger en silence.
- **PROVISOIRE** — La conception du contrat (§1.5 et oracle du §5) est
  renvoyée à l'issue #6 ; le placement du Gateway et du Collector à l'issue #4.

## 8. Conditions de révision

Cet ADR, même accepté, est à réviser si l'un de ces éléments change :

- **OUVERT** — La matrice des flux de l'issue #4 est approuvée : placement du
  Gateway et du Collector, flux F0/F1, liste fermée de sortie et tests négatifs
  (aucune route Gateway/Collector → IA-CORE, SSRF vers adresses privées et
  métadonnées refusée, perte du Gateway sans ouverture d'Internet pour IA-CORE).
- **OUVERT** — La liste des fournisseurs autorisés (Q1) est fixée ou modifiée,
  ou les conditions d'un fournisseur changent.
- **OUVERT** — Un budget ou un plafond (Q2) est fixé ou modifié ; les valeurs
  restent hors dépôt public.
- **OUVERT** — Une demande vise à laisser un agent ou IA-CORE déclencher une
  recherche externe (Q3) ; ce flux exige un nouvel ADR.
- **OUVERT** — Le contrat d'ingress évolue sous l'issue #6, notamment si le
  format de conversation est fusionné dans `research-package` ou versionné à
  part.
- **OUVERT** — Un deuxième client de dépôt direct est envisagé (A ou C).
- **OUVERT** — L'issue de la PR #17 change la sémantique de l'accusé.
- **OUVERT** — Un incident touche le Gateway, le Collector ou une clé.

## 9. Questions au propriétaire

Chaque question est fermée. Le défaut sûr (**PROPOSÉ**) s'applique tant
qu'aucune réponse n'est enregistrée. Les réponses détaillées qui ne doivent pas
être publiques (comptes, montants, adresses) restent hors dépôt.

### Questions de décision

- **Q-A — Option retenue** : A, B ou C ?
  Défaut sûr : aucune option retenue ; P-001 reste provisoire et aucun Gateway
  n'est construit.
- **Q-B — Poids des critères** : validés tels quels, ou ajustés (préciser) ?
  Défaut sûr : poids non validés ; la matrice reste indicative.
- **Q-C — Chemin `/v1/conversations`** : dans le périmètre de l'option retenue
  (A ou C), exception documentée et bornée dans le temps (B), ou suspendu
  jusqu'au durcissement de l'issue #6 ? Portée du relais : privée uniquement ou
  publique ?
  Défaut sûr : statu quo gelé, sans nouveau client, sans extension du contrat
  et sans exposition supplémentaire ; le chemin reste non approuvé. Maintenir
  ou restreindre la portée actuelle du relais est une décision du propriétaire ;
  aucun agent ne la modifie.

### Annexe — questionnaire « Recherche externe », Q1 à Q7

- **Q1 — Fournisseurs autorisés** : aucun ; liste fermée de fournisseurs d'IA
  par API ; liste fermée de moteurs de recherche par API ; récupération directe
  d'URL Web ?
  Défaut sûr : aucun fournisseur, donc aucun appel ni Gateway. La récupération
  directe d'URL maximise le risque T09 et exigerait sa propre liste fermée.
- **Q2 — Comptes et budgets** : (a) un compte dédié au projet par fournisseur,
  séparé des comptes personnels, oui ou non ? (b) un plafond imposé côté
  fournisseur en plus d'un plafond local, oui ou non ? (c) comptes et montants
  conservés hors dépôt public, oui ou non ?
  Défaut sûr : oui aux trois ; aucun appel sans plafond configuré des deux
  côtés.
- **Q3 — Initiation des recherches** : propriétaire seul, par saisie manuelle ;
  demandes préparées localement, approuvées une par une ; déclenchement
  automatique par un agent ou par IA-CORE ?
  Défaut sûr : propriétaire seul. Le troisième choix contredit l'invariant 4
  et exigerait un nouvel ADR ; il n'est listé que pour être refusé
  explicitement.
- **Q4 — Déclassification** : pour chaque classe — secrets et justificatifs,
  données personnelles de tiers, détails d'infrastructure interne, code ou
  documents privés, contenu de mémoire, de RAG ou de RAW interne — faut-il
  supprimer, pseudonymiser, soumettre à approbation humaine ou refuser la
  demande ?
  Défaut sûr : refus de toute demande qui contient l'une de ces classes ; les
  secrets et justificatifs sont toujours refusés, sans option.
- **Q5 — Exports historiques** : aucun ; conversations du relais existant au
  format conversation 0.1.0 ; autres exports tiers (formats à lister) ?
  Défaut sûr : le seul format existant. Tout nouveau format exige un parseur
  isolé, un contrat versionné (#6) et des fixtures synthétiques.
- **Q6 — Pièces jointes** : aucune, avec métadonnées seulement comme dans
  `research-package` 0.1.0 ; ou liste fermée de types MIME avec taille
  maximale ?
  Défaut sûr : aucune pièce jointe binaire ; métadonnées seulement.
- **Q7 — Conservation, droit d'auteur, suppression et audit** : (a) RAW
  conservé selon D-011, avec suppression exceptionnelle seulement par une
  procédure tracée sans recopie du contenu, oui ou non ? (b) contenu externe
  protégé réservé à l'usage interne et exclu du corpus d'entraînement sans
  licence autorisée (D-031 à D-033), oui ou non ? (c) journaux d'audit sans
  contenu ni secret, oui ou non ? (d) durée de conservation des journaux et des
  rejets ?
  Défaut sûr : oui à (a), (b) et (c) ; pour (d), aucune purge automatique
  avant décision.

Les réponses retenues seront reportées par le propriétaire dans le
questionnaire et le registre ; cet ADR ne les pré-remplit pas.
