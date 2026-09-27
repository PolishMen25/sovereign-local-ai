# Politique URL et SSRF — contrôle statique

> Statut : **PROVISOIRE**. Jeu de règles candidat `url-ssrf-policy-v1` pour l'issue #6, rédigé avant l'ADR du Research Gateway. Il n'est câblé à aucune route, aucun service et aucun port. Le registre `docs/project/decisions.md` n'est pas modifié.

Ce document transforme la mesure T09 de `docs/security/threat-model.md` (« validation d'URL ; refus des adresses privées/métadonnées ») en règles vérifiables. Il est implémenté, sans dépendance tierce, par `services/quarantine/url_policy.py` et vérifié par `tests/test_url_policy.py`.

## Périmètre

Le contrôle porte sur une **URL déclarée** : `sources[].url`, `attachments[].source_url` d'un paquet de recherche, ou toute URL trouvée par l'analyse de secrets. Il répond à une seule question : cette chaîne est-elle acceptable comme référence publique, canonique et sans justificatif ?

Principes :

- **Aucune entrée/sortie réseau.** Le module ne résout aucun nom, n'ouvre aucune socket et ne suit aucune redirection. Un test remplace `socket.getaddrinfo` et les fonctions voisines par des leurres et vérifie qu'ils ne sont jamais appelés.
- **Refuser, jamais réécrire.** Une URL non conforme est refusée avec des codes de motif ; elle n'est ni corrigée ni normalisée. Le RAW reste donc identique aux octets reçus.
- **Codes seulement.** Les motifs ne contiennent aucune partie de l'URL, qui peut porter une signature ou un jeton.
- **Tables explicites.** Les plages d'adresses sont listées dans le module, sans dépendre de `is_private` ou `is_global`, dont la définition a changé selon les versions de Python.

Un résultat vide signifie seulement que les contrôles statiques passent. Il ne prouve pas que la destination est sûre au moment d'un accès.

## Règles et codes de motif

### Forme générale

| Code | Refus |
|---|---|
| `URL_NOT_A_STRING` | Valeur qui n'est pas une chaîne. |
| `URL_TOO_LONG` | Plus de 4 096 caractères, comme `maxLength` du schéma. Aucun autre contrôle n'est alors exécuté. |
| `URL_MALFORMED` | Espace, caractère de contrôle, caractère de format invisible (U+200B, U+00AD…), barre oblique inverse, crochet IPv6 non fermé, IPv6 sans crochets, port non numérique ou supérieur à 65535. |
| `URL_NOT_CANONICAL` | Schéma ou hôte en majuscules, point final d'hôte, port `:443` explicite ou vide, caractère non ASCII, caractère hors RFC 3986 (`<>"{}|^` et accent grave), hôte Unicode au lieu de son A-label, IPv6 hors forme RFC 5952. |
| `URL_SCHEME_NOT_HTTPS` | Tout schéma autre que `https`, ou schéma absent. |
| `URL_USERINFO` | Partie `utilisateur[:mot de passe]@`, même vide. |
| `URL_PORT_NOT_DEFAULT` | Port explicite différent de 443. |
| `URL_HOST_MISSING` | Hôte absent (`https:///chemin`, `https:exemple`). |
| `URL_HOST_INVALID` | Encodage `%` dans l'hôte, étiquette hors LDH, étiquette vide ou de plus de 63 caractères, nom de plus de 253 caractères, A-label `xn--` invalide ou non réversible, étiquette réservée `ab--`, identifiant de zone IPv6, forme numérique non analysable. |

### Noms d'hôte

| Code | Refus |
|---|---|
| `URL_HOST_SINGLE_LABEL` | Nom sans point, que la recherche de suffixes DNS peut compléter vers un nom interne. |
| `URL_HOST_SPECIAL_USE` | Domaine de premier niveau réservé ou interne : `localhost`, `local`, `internal`, `arpa` (dont `home.arpa`, `in-addr.arpa`), `test`, `example`, `invalid`, `onion`, `alt`. S'y ajoutent, par prudence et sans valeur normative, `home`, `corp`, `lan`, `localdomain`, `intranet` et `private`, jamais délégués et souvent employés en interne. |
| `URL_HOST_METADATA` | Nom connu de service de métadonnées : `metadata`, `metadata.google.internal`, `instance-data`, `instance-data.ec2.internal`. |

Les domaines de second niveau d'exemple (`example.com`, `example.org`, `example.net`, RFC 2606) restent publics et acceptés.

### Adresses IP littérales

| Code | Plages IPv4 | Plages IPv6 |
|---|---|---|
| `URL_IP_UNSPECIFIED` | `0.0.0.0/8` | `::/128` |
| `URL_IP_LOOPBACK` | `127.0.0.0/8` | `::1/128` |
| `URL_IP_PRIVATE` | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | — |
| `URL_IP_LINK_LOCAL` | `169.254.0.0/16` | `fe80::/10` |
| `URL_IP_CGNAT` | `100.64.0.0/10` | — |
| `URL_IP_UNIQUE_LOCAL` | — | `fc00::/7` |
| `URL_IP_MULTICAST` | `224.0.0.0/4` | `ff00::/8` |
| `URL_IP_RESERVED` | `192.0.0.0/24`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` (RFC 5737), `192.88.99.0/24`, `198.18.0.0/15`, `240.0.0.0/4` (dont la diffusion générale) | tout ce qui est hors `2000::/3` (dont NAT64 `64:ff9b::/96`, `100::/64`, `fec0::/10`), plus `2001::/23` (dont Teredo), `2001:db8::/32` (RFC 3849), `2002::/16` (6to4), `3fff::/20` |
| `URL_IP_IPV4_MAPPED` | — | `::ffff:0:0/96` ; l'adresse IPv4 incluse est aussi classée |
| `URL_IP_METADATA` | `169.254.169.254`, `169.254.169.253`, `169.254.170.2`, `100.100.100.200`, `168.63.129.16` | `fd00:ec2::254` |

`URL_IP_METADATA` s'ajoute au code de classe : `169.254.169.254` produit `URL_IP_LINK_LOCAL` et `URL_IP_METADATA`. `168.63.129.16` est hors plage réservée mais désigne un service de plateforme ; il est refusé explicitement.

Une adresse IPv4 publique ou IPv6 globale sous forme canonique n'est pas refusée par ce contrôle statique. L'autorisation de destinations précises relève du composant qui accède au réseau.

### Formes IPv4 non standard

| Code | Refus |
|---|---|
| `URL_IP_NONSTANDARD_FORM` | Hôte que les navigateurs et `inet_aton` lisent comme IPv4 sans être un quadruplet décimal canonique : entier décimal (`2130706433`), hexadécimal (`0x7f000001`), octal (`0177.0.0.1`), forme courte (`127.1`), segments mixtes. L'adresse décodée est aussi classée, par exemple `URL_IP_LOOPBACK`. |

La détection suit la règle WHATWG « se termine par un nombre » : si la dernière étiquette est décimale ou hexadécimale `0x…`, l'hôte entier doit s'analyser comme IPv4, sinon il est refusé en `URL_HOST_INVALID`.

### Paramètres signés ou porteurs de justificatifs

Les noms sont comparés sans casse, après décodage `%` et `+`, dans la requête, le fragment et les paramètres de chemin (`;nom=valeur`). Les séparateurs `&`, `;`, `?`, `#` et `/` délimitent les paires. Seules les paires `nom=valeur` comptent : un fragment d'ancre comme `#policy` n'est pas un paramètre.

| Code | Noms refusés |
|---|---|
| `URL_PARAM_SIGNED` | `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`, `AWSAccessKeyId`, `X-Goog-Signature`, `X-Goog-Credential`, `GoogleAccessId`, `Signature`, `sig` et `se` (SAS), `Key-Pair-Id`, `Policy` |
| `URL_PARAM_CREDENTIAL` | `token`, `access_token`, `id_token`, `refresh_token`, `auth_token`, `auth`, `api_key`, `apikey`, `api-key`, `x-api-key`, `key`, `access_key`, `secret_key`, `private_key`, `client_secret`, `secret`, `password`, `passwd`, `pwd`, `credential`, `credentials`, `session`, `sessionid`, `session_id`, `jsessionid`, `phpsessid` |

Ces listes privilégient le refus : un paramètre anodin nommé `policy` ou `key` est refusé. Le producteur doit retirer ces paramètres avant soumission ; le Collector ne les retire pas à sa place.

La fonction `credential_reasons` n'applique que `URL_USERINFO`, `URL_PARAM_SIGNED` et `URL_PARAM_CREDENTIAL`, et tolère un texte mal formé. Elle sert à l'analyse de secrets sur du texte libre.

## Normalisation IDNA

Pour classer un hôte, le module le convertit en ASCII avec le codec `idna` de la bibliothèque standard, qui applique IDNA 2003 (RFC 3490, nameprep) : repli de casse, NFKC, suppression des caractères ignorables, séparateurs `。`, `．` et `｡`. Ainsi `ｌｏｃａｌｈｏｓｔ` est classé comme `localhost`, et `１２７.0.0.1` comme une boucle locale.

La normalisation sert uniquement au classement. Si l'hôte déclaré n'est pas déjà sa propre forme ASCII minuscule, l'URL est refusée en `URL_NOT_CANONICAL`. Chaque A-label `xn--` doit se décoder puis se réencoder à l'identique.

IDNA 2003 et IDNA 2008/UTS 46 divergent sur quelques caractères, par exemple `ß`. Le composant qui résout les noms doit donc refaire ses contrôles après sa propre conversion (HYPOTHÈSE de conception, à confirmer par l'ADR).

## Hors périmètre : contrôles réseau différés

Un contrôle statique ne peut pas voir ce que le réseau renverra. Les contrôles suivants appartiennent au composant qui déréférence réellement les URL. Ce composant n'est pas encore choisi : Research Gateway ou dépôt direct, selon l'ADR du Research Gateway, en attente. Ils dépendent aussi de la matrice de flux de l'issue #4.

- **Résolution DNS** : chaque adresse renvoyée, A et AAAA, doit être reclassée avec les mêmes tables avant toute connexion.
- **Rebinding DNS** : la connexion doit utiliser l'adresse déjà vérifiée (épinglage), sans nouvelle résolution entre contrôle et accès.
- **Redirections** : refusées, ou chaque saut est recontrôlé intégralement (schéma, hôte, port, adresse résolue), avec un nombre de sauts borné.
- **Sortie réseau** : proxy de sortie, allowlist de destinations, TLS vérifié, limites de taille et de durée de téléchargement.
- **Preuves** : tests négatifs sur le réseau réel pour le cas d'abus « un serveur distant redirige le Collector vers une adresse interne ».

Le Collector write-only ne déréférence aucune URL. Il peut appliquer ce contrôle statique à la réception d'un paquet, mais il ne doit jamais aller chercher une source.

## Réutilisation et évolution

- L'analyse de secrets candidate s'appuie sur `credential_reasons` pour détecter les URL signées dans du texte libre.
- Le validateur candidat de `research-package` (`docs/data/research-package-validation.md`) applique `evaluate_url` à chaque URL déclarée.
- Toute modification d'une table ou d'un code crée une nouvelle version du jeu de règles (`url-ssrf-policy-v2`, etc.). Elle ne modifie jamais silencieusement `v1`.

## Utilisation locale

```text
python -B services/quarantine/url_policy.py urls.txt
```

Le fichier contient une URL par ligne, en UTF-8. Seul le saut de ligne `LF` sépare les lignes (un `CR` final est retiré) : U+2028, U+0085 ou un saut de page restent dans la ligne, qui est alors refusée. La sortie donne, pour chaque ligne, son numéro et ses codes de motif, sans recopier l'URL. Code de sortie : 0 si toutes les URL sont admises, 1 si au moins une URL est refusée, 2 si le fichier est illisible, n'est pas en UTF-8 ou dépasse la taille admise.
