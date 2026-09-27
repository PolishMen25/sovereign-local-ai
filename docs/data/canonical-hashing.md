# Empreintes et JSON canonique

> Statut : **PROVISOIRE**. Contrat candidat pour l'issue #6, rédigé avant l'ADR du Research Gateway. Il n'est câblé à aucune route, aucun service et aucun port. Sa publication comme contrat attend une décision du propriétaire. Le registre `docs/project/decisions.md` n'est pas modifié.

Ce document précise la section « Empreintes et canonicalisation » de `docs/data/provenance-and-lifecycle.md`. Il est implémenté, sans dépendance tierce, par `services/quarantine/canonical_json.py` et vérifié par `tests/test_canonical_json.py`.

## Trois portées d'empreinte

L'algorithme est SHA-256. Chaque valeur est encodée en 64 caractères hexadécimaux minuscules. Une empreinte détecte une altération ou un doublon ; elle ne prouve pas l'identité de l'émetteur.

| Portée (`hash_scope`) | Octets couverts | Emplacement de la valeur | Fonction |
|---|---|---|---|
| `ingress-payload-bytes` | Corps HTTP exactement reçu par le Collector, après terminaison TLS, sans décodage, normalisation ni retrait de BOM. | Uniquement le reçu (`ingress_payload_sha256`) ou le journal append-only, jamais le paquet. | `ingress_sha256(body)` |
| `canonical-package-excluding-integrity` | JSON canonique RFC 8785 du paquet privé de son seul membre racine `integrity`. | `integrity.package_sha256` du paquet. | `package_sha256(package)` |
| `provider-raw-response-bytes` | Octets bruts d'une réponse fournisseur conservée comme objet séparé. | `integrity.provider_raw_response_sha256`, facultatif. | `provider_response_sha256(raw)` |

Précisions :

- **Ingress.** Proposition : le Collector refuse tout `Content-Encoding` autre que l'identité, afin que les octets hachés soient ceux du document. L'empreinte d'ingress diffère donc d'une soumission à l'autre si seuls les espaces changent ; c'est voulu, puisqu'elle prouve ce qui a été reçu.
- **Paquet.** Seul le membre `integrity` de premier niveau est exclu. Un membre `integrity` imbriqué ailleurs fait partie de l'empreinte. L'absence de `integrity` donne la même valeur, ce qui permet au producteur de calculer l'empreinte avant de l'écrire. Le calcul ne modifie jamais le paquet.
- **Réponse fournisseur.** Cette empreinte ne désigne jamais le paquet JSON qui la contient.

Deux paquets dont seuls l'ordre des membres ou les espaces diffèrent ont la même empreinte canonique et des empreintes d'ingress différentes.

## Règles RFC 8785 appliquées

- Clés d'objet triées par **unités de code UTF-16**, et non par points de code : `"😀"` (U+1F600) précède `"דּ"`.
- Nombres sérialisés comme ECMAScript `Number.prototype.toString` : `1e21` → `1e+21`, `1e20` → `100000000000000000000`, `0.1` → `0.1`, `1.0` → `1`, `1e-7` → `1e-7`, `-0` → `0`.
- Chaînes : seuls `"`, `\` et U+0000 à U+001F sont échappés ; `\b`, `\t`, `\n`, `\f`, `\r` en forme courte, les autres en `\u00xx` minuscule. `/`, U+007F, U+2028 et les caractères non ASCII restent littéraux en UTF-8.
- Aucun espace hors des chaînes ; tableaux dans leur ordre d'origine.

Les vecteurs de l'annexe B de la RFC 8785 et son exemple complet sont rejoués par les tests.

## Refus du profil strict

`loads_strict` applique le profil I-JSON exigé par la RFC 8785. Chaque refus porte un code stable. Le message ne recopie jamais le document, une clé ou une valeur, et l'exception est levée sans chaînage (`__cause__` et `__context__` vides).

| Code | Cas refusé |
|---|---|
| `DUPLICATE_KEY` | Clé répétée dans un objet, à toute profondeur, y compris sous une forme échappée (`"a"` et `"a"`). |
| `NON_FINITE_NUMBER` | `NaN`, `Infinity`, `-Infinity`, ou nombre qui déborde en double (`1e400`). |
| `INTEGER_OUT_OF_RANGE` | Entier hors de ±(2⁵³ − 1). Un tel entier ne serait pas représenté exactement par un producteur ECMAScript. |
| `LONE_SURROGATE` | Demi-code de substitution isolé, dans une clé ou une valeur. Une paire valide est acceptée. |
| `BOM_REFUSED`, `INVALID_UTF8`, `MALFORMED_JSON` | BOM initial, UTF-8 invalide (y compris un substitut encodé), syntaxe JSON invalide. |
| `DEPTH_EXCEEDED`, `SIZE_EXCEEDED` | Imbrication au-delà de 64 niveaux ; document au-delà de 16 Mio par défaut. |
| `UNSUPPORTED_TYPE`, `NON_STRING_KEY` | Valeur Python sans équivalent JSON exact (tuple, ensemble, octets, sous-classe de nombre) ou clé non textuelle. |

Les bornes de 64 niveaux et de 16 Mio sont des hypothèses de travail (HYPOTHÈSE), pas des mesures. Le schéma `research-package` autorise une réponse de 2 000 000 caractères, ce qui peut dépasser 1 Mio en UTF-8.

## `json.dumps(sort_keys=True)` n'est pas RFC 8785

Une sérialisation par `json.dumps(document, sort_keys=True, …)` **n'est pas** une canonicalisation RFC 8785. Elle ne doit jamais être présentée comme telle.

| Écart | `json.dumps(sort_keys=True)` | RFC 8785 |
|---|---|---|
| Ordre des clés | points de code : `"דּ"` avant `"\U0001f600"` | unités UTF-16 : `"\U0001f600"` avant `"דּ"` |
| Nombres | `1.0`, `1e-07` | `1`, `1e-7` |
| NaN et infinis | émis tels quels par défaut (`NaN`) | refusés |
| Non-ASCII | échappé en `\uXXXX` si `ensure_ascii=True` (défaut) | littéral UTF-8 |
| Clés dupliquées à la lecture | `json.loads` garde silencieusement la dernière | refusées |

Constat, sans décision : le collecteur de conversations en service (`services/quarantine/conversation_import.py`, fonction `canonical_bytes`) calcule son `sha256` sur un `json.dumps(sort_keys=True)` resérialisé. Cette empreinte n'est ni RFC 8785 ni l'empreinte des octets reçus. Il s'agit d'un contrat distinct, propre aux conversations. Son alignement éventuel sur ce document est une décision du propriétaire, à coordonner avec le relais Codex qui valide ce reçu. Rien n'est modifié ici.

## Reçu technique du Collector

`schemas/collector-receipt.schema.json` (Draft 2020-12, fermé par `additionalProperties: false`) décrit la réponse candidate de `submit_research_package`. Il contient exactement quatre champs :

| Champ | Contenu |
|---|---|
| `submission_id` | UUID attribué par le Collector ; ne permet aucune lecture ni aucun suivi. |
| `received_at` | Horodatage RFC 3339 de réception, avec décalage. |
| `ingress_payload_sha256` | Empreinte de portée `ingress-payload-bytes`. |
| `status` | `accepted` ou `rejected` : acceptation technique, jamais une validation de connaissance. |

Le reçu ne porte ni extrait du paquet, ni état interne (`PENDING`, `VALIDATED`…), ni résultat d'indexation, ni motif de refus détaillé. Les formats `uuid` et `date-time` restent des annotations tant qu'un validateur ne les affirme pas ; le choix entre `jsonschema` en test ou validateur stdlib est ouvert (OUVERT).

## Utilisation locale

Calcul d'une empreinte hors ligne, pour vérifier un paquet synthétique :

```text
python -B services/quarantine/canonical_json.py --scope package paquet.json
python -B services/quarantine/canonical_json.py --scope ingress corps.bin
```

La sortie est un objet JSON canonique `{"algorithm", "hash_scope", "sha256"}`. Un refus renvoie le code 1 avec le seul code de motif sur la sortie d'erreur.

## Hors périmètre

- Le câblage dans une route du Collector, qui dépend de l'ADR du Research Gateway et des décisions sur le contrat d'ingress.
- La signature ou l'authentification des empreintes (HMAC, Ed25519) : le mécanisme du journal d'événements reste ouvert.
- La vérification sémantique complète du paquet (ordre temporel, citations, URL) : voir `docs/data/research-package-validation.md`, qui recalcule `integrity.package_sha256` avec ce module.
