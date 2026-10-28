# Actions qui ne peuvent être faites que par Hugo

Coche au fur et à mesure. Rien ici ne bloque le développement, mais tout bloque la mise en production.

## Décisions (10 minutes)
- [ ] Plan 2 : choisir le métier de départ (défaut retenu : entreprises d'espaces verts et paysagistes, CPV 77310000) et 2 à 6 départements de test
- [ ] Plan 1 : choisir la ville de départ et 20 commerces à aller voir
- [ ] Plan 3 : confirmer la cible (défaut : cabinets d'expertise comptable) après une vérification manuelle sur LinkedIn, Substack et Kessel qu'aucune newsletter française dédiée n'existe
- [ ] Noms de produits et noms de domaine (1 domaine par produit, ~10 €/an chacun)

## Comptes et clés (1 heure, tout en mode test d'abord)
- [ ] Stripe : compte, clés test, produits et prix (Solo 19 €, Pro 29 €, Réseau 59 € ; Essentiel 29 €, Pro 49 €), secret de webhook
- [ ] Email transactionnel : compte Resend ou Brevo, domaine d'envoi vérifié (SPF, DKIM)
- [ ] SMS : compte smsmode (français) ou Twilio, expéditeur déclaré
- [ ] Google Cloud : projet, écran de consentement OAuth, identifiants « application de bureau » ; **demande d'accès à l'API Google Business Profile** via le formulaire officiel (fiche Google de ton entreprise vérifiée depuis 60 jours + site web obligatoires ; délai d'environ 14 jours) ; activer YouTube Data API v3 sur le même projet
- [ ] YouTube : chaîne créée, compte AdSense lié plus tard
- [ ] Pinterest : compte professionnel, app développeur, jeton
- [ ] LinkedIn : page entreprise, app développeur (produits « Share on LinkedIn » et « Sign In »)
- [ ] TikTok : compte développeur, app « Content Posting » (audit requis avant publication directe)
- [ ] beehiiv (ou Kessel) : publication créée, clé API
- [ ] Anthropic (optionnel) : clé API avec plafond de dépense mensuel

## Mac mini (30 minutes)
- [ ] **Chantier de nuit en local** : suivre le bloc « Passer sur le Mac mini » de `NIGHT-RUN.md` (install, `claude` dans le dossier, `claude setup-token` → fichier de jeton, `gh auth login`, copie de la liste blanche après relecture, `night-shift.sh test` puis `enable`). À partir de là c'est le Mac mini qui développe la nuit et la session cloud se met en retrait toute seule.
- [ ] Session macOS ouverte en permanence (ouverture de session automatique), FileVault désactivé ou déverrouillé, veille désactivée
- [ ] Installer Homebrew, puis lancer `deploy/macmini/install.sh` (uv, ffmpeg, Ollama, modèle `qwen3:14b`)
- [ ] Désactiver la mise en veille (Réglages → Économie d'énergie) et vérifier que `caffeinate` est bien lancé par les services
- [ ] Remplir les `.env` de chaque app à partir des `.env.example`
- [ ] Faire un premier appel réel : `cd apps/veille-marches && .venv/bin/vm collect --limit 20` et me coller la sortie si les champs ne correspondent pas aux fixtures (les API n'étaient pas joignables depuis le sandbox)
- [ ] Sauvegarde : Time Machine + une copie hors site du dossier `data/`
- [ ] VPS (si tu choisis cette option pour le SaaS avis) : `cd deploy/vps && docker compose build` puis `up -d` ; l'image n'a pas pu être construite depuis le sandbox (pas de démon Docker), le Dockerfile est donc à valider à ce moment-là

## Premiers essais réels, app par app (après `deploy/macmini/install.sh`)
- [ ] Veille : `cd apps/veille-marches && .venv/bin/vm collect --limit 20 && .venv/bin/vm stats`. Si « sans CPV » ou « sans département » domine, me coller la sortie : les API n'étaient pas joignables depuis le sandbox et le mapping des champs BOAMP/TED/DECP est à confirmer (liste précise dans le README de l'app).
- [ ] Contenu : `cd apps/content-engine && .venv/bin/ce doctor` (ffmpeg, police, `say`, LLM), puis `ce init`, `ce script --topic-id 1`, `ce approve <id>`, `ce render --draft-id <id>` et regarder `out/<id>/video.mp4`. Première publication réelle uniquement après relecture d'un `publish-*.json`, en `private` / `SELF_ONLY`. Après les premières publications : `ce metrics --pull --dry-run` pour valider les réponses des API (le consentement YouTube doit inclure la lecture et, si voulu, l'analytics : supprimer `data/youtube-token.json` et relancer une publication en `--live` dans un terminal).
- [ ] Newsletter : `cd apps/newsletter-pipeline && .venv/bin/np collect --dry-run && .venv/bin/np stats`, corriger les sources en erreur dans `sources.yaml` (36 sur 39 sont marquées à vérifier), puis `np run-monday` à blanc et relire `issues/001-*.md`.
- [ ] Avis : `cd apps/avis-clients && .venv/bin/avis demo && .venv/bin/avis serve`, parcourir http://localhost:8000 (inscription par lien magique affiché en console, QR, boîte de réception sur les avis simulés). `avis google auth` seulement après l'approbation de l'API Google.
- [ ] Chantier de nuit sur le Mac : voir la section Mac mini ci-dessus (`night-shift.sh test` puis `enable`).

## Administratif
- [ ] Création de la micro-entreprise (URSSAF), choix de l'activité « services », compte bancaire dédié
- [ ] Mentions légales, CGV, politique de confidentialité (modèles fournis dans chaque app, à relire)
