# Déploiement VPS (partie publique)

Décision d'architecture : `avis-clients` tourne **entièrement** sur le VPS (web + jobs) parce que ses clients y accèdent 24/7 et qu'une base SQLite ne se partage pas entre deux machines. Le Mac mini lui fournit le LLM gratuitement via Tailscale (`OLLAMA_BASE_URL=http://<nom-tailscale-du-mac>:11434`), ou l'app utilise l'API Anthropic avec un plafond de dépense.

## Mise en route (Hetzner CX22 ou équivalent, ~5 €/mois, Debian/Ubuntu)
```bash
# sur le VPS
curl -fsSL https://get.docker.com | sh
git clone <repo> /srv/sideproject && cd /srv/sideproject
cp apps/avis-clients/.env.example apps/avis-clients/.env && nano apps/avis-clients/.env   # clés Stripe, SMS, mail, LLM
export AVIS_DOMAIN=avis.mondomaine.fr                     # DNS A du domaine → IP du VPS
cd deploy/vps && docker compose up -d --build
docker compose logs -f avis-web
```
Caddy obtient le certificat HTTPS tout seul. Mise à jour : `git pull && docker compose up -d --build`.

## Sauvegarde quotidienne de la base
```bash
# crontab -e
15 3 * * * docker compose -f /srv/sideproject/deploy/vps/docker-compose.yml exec -T avis-web python -c "import sqlite3;s=sqlite3.connect('data/avis.db');d=sqlite3.connect('data/backup.db');s.backup(d)" && rclone copy /var/lib/docker/volumes/vps_avis-data/_data/backup.db remote:sideproject/avis/
```

## Ollama du Mac mini accessible depuis le VPS
1. Tailscale sur les deux machines (gratuit pour un usage perso).
2. Sur le Mac : `launchctl setenv OLLAMA_HOST 0.0.0.0` puis redémarrer Ollama (`brew services restart ollama`).
3. Dans le `.env` du VPS : `LLM_PROVIDER=ollama` et `OLLAMA_BASE_URL=http://<mac>.<tailnet>.ts.net:11434`.
Si le Mac est éteint, les brouillons de réponse attendent ; rien n'est perdu.
