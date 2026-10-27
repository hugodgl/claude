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
- [ ] Installer Homebrew, puis lancer `deploy/macmini/install.sh` (uv, ffmpeg, Ollama, modèle `qwen3:14b`)
- [ ] Désactiver la mise en veille (Réglages → Économie d'énergie) et vérifier que `caffeinate` est bien lancé par les services
- [ ] Remplir les `.env` de chaque app à partir des `.env.example`
- [ ] Faire un premier appel réel : `cd apps/veille-marches && .venv/bin/vm collect --limit 20` et me coller la sortie si les champs ne correspondent pas aux fixtures (les API n'étaient pas joignables depuis le sandbox)
- [ ] Sauvegarde : Time Machine + une copie hors site du dossier `data/`

## Administratif
- [ ] Création de la micro-entreprise (URSSAF), choix de l'activité « services », compte bancaire dédié
- [ ] Mentions légales, CGV, politique de confidentialité (modèles fournis dans chaque app, à relire)
