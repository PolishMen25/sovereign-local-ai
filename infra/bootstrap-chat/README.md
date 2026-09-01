# Chat BOOTSTRAP en LXC

Ce lot déploie temporairement un chat local réel, distinct de CORE :

- LXC Debian non privilégié `sovereign-ml` ;
- runtime CPU-only llama.cpp `b10537` vérifié par SHA-256 ;
- modèle Qwen 2.5 1.5B Instruct Q4_K_M vérifié par SHA-256 ;
- interface Web native de llama.cpp liée au loopback du LXC ;
- aucun outil, agent, proxy MCP ou téléchargement à l'exécution.

Le service attend les chemins privés suivants dans le LXC :

```text
/opt/sovereign/runtime/llama-b10537/llama-server
/opt/sovereign/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Les artefacts restent hors Git. Les URLs et empreintes de référence sont dans
`configs/runtime/bootstrap-qwen2.5-1.5b-q4km.lock.json`. CORE reste sans poids
conversationnels : ce service est seulement le chat BOOTSTRAP provisoire.
