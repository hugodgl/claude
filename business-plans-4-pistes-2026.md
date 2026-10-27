# Business plans : les 4 pistes retenues (octobre 2026)

> Suite du dossier `business-passif-mac-mini-2026.md`. Rédigé le 27 octobre 2026. Projet side, sans lien avec Eryon Consulting.
> Chaque plan est développé sur **une niche d'exemple concrète** choisie pour sa faisabilité (données accessibles, demande prouvée, concurrence lisible). Tu peux la remplacer : les critères de choix et les alternatives sont donnés à chaque fois.
> Tous les montants sont en € HT. Les projections sortent d'un modèle à 24 mois dont les hypothèses sont affichées. Ce sont des ordres de grandeur, pas des promesses.

---

## Sommaire

0. Hypothèses communes et comment les 4 plans s'emboîtent
1. Plan 1 : SaaS par abonnement, « avis clients pour commerces de proximité »
2. Plan 2 : Produit données, « marchés publics pour un métier précis »
3. Plan 3 : Newsletter de niche, « l'IA pour les cabinets d'expertise comptable »
4. Plan 4 : Moteur de contenu YouTube, TikTok, Pinterest (et LinkedIn)
5. Synthèse : ordre de lancement, pile cohérente, critères d'arrêt
6. Sources

---

## 0. Hypothèses communes

| Hypothèse | Valeur retenue |
|---|---|
| Temps disponible | 10-15 h/semaine les 3 premiers mois, puis 5-8 h/semaine |
| Capital engagé sur 12 mois | moins de 500 € |
| Statut | micro-entreprise séparée (plafond services 2026 : 83 600 € ; franchise TVA 37 500 €) |
| Infrastructure | Mac mini (jobs, agents, LLM local) + VPS à 5 €/mois pour la partie publique + Cloudflare + Stripe |
| Coût LLM | 0 € avec Ollama en local (Qwen3 / Gemma 4) ; plafond 30 €/mois si API cloud pour la qualité |
| Coûts fixes par plan | 35 €/mois (domaine, VPS, envoi d'emails, monitoring) |
| Scénarios | pessimiste / réaliste / optimiste, qui diffèrent sur l'acquisition et le churn, pas sur le prix |
| Temps du fondateur | non valorisé dans les projections, mais compté en heures par semaine |

**Comment les 4 plans s'emboîtent**

```
Plan 4 (contenu : YouTube, TikTok, Pinterest, LinkedIn)
        │ amène l'audience, capte les emails
        ▼
Plan 3 (newsletter)  ──► sponsors + abonnement payant
        │ liste qualifiée, confiance
        ▼
Plan 2 (produit données) ──► abonnement 29-49 €/mois, zéro interface
        │ même pipeline de collecte / analyse / livraison
        ▼
Plan 1 (SaaS) ──► abonnement 19-59 €/mois, interface client, actif revendable
```

Les plans 1 et 2 partagent une cible (TPE et artisans). Le plan 3 vise une cible différente (cabinets d'expertise comptable) parce que c'est là que les sponsors ont des budgets. La section 5 donne la variante « pile cohérente » si tu préfères une seule cible pour tout.

---

## 1. Plan 1 : SaaS par abonnement

### Niche d'exemple : avis clients pour commerces de proximité

**Résumé exécutif.** Un outil self-service à 19-59 €/mois qui fait trois choses pour un restaurant, un coiffeur, un garage ou un cabinet : **collecter plus d'avis** (QR code, lien SMS ou WhatsApp après la visite), **répondre à chaque avis** en moins de 24 h avec un brouillon rédigé dans le ton de l'établissement et validé en un clic, et **envoyer un rapport mensuel** (note, volume, mots qui reviennent, concurrents du quartier). Les acteurs en place (Partoo, Guest Suite, Solocal, Custplace) vendent sur devis à des réseaux et des franchises. Le commerce indépendant n'a pas d'offre à 29 € qu'il peut activer seul en dix minutes. Le Mac mini fait tourner la surveillance des avis, la rédaction des brouillons et les rapports.

### 1.1 Problème, cible, promesse

| | |
|---|---|
| Client idéal | commerce indépendant avec 1 à 5 établissements, 50 à 500 clients par semaine, dont la fiche Google est le premier canal d'acquisition |
| Problème | peu d'avis, avis négatifs sans réponse, aucune routine ; le gérant n'a ni le temps ni l'envie |
| Promesse | « Plus d'avis, une réponse à chacun, sans y passer du temps » |
| Preuve de demande | Partoo (levées de fonds répétées), Guest Suite, Trustpilot à partir de 79 €/mois : le marché paie, mais au-dessus du commerçant indépendant |
| Pourquoi maintenant | la visibilité locale dépend de plus en plus des avis et de leurs réponses (recherche IA locale), et Google ne propose pas d'outil de collecte |

### 1.2 Marché et concurrence

| Acteur | Cible | Prix | Faiblesse exploitable |
|---|---|---|---|
| Partoo (agent IA « Jim », Review Booster SMS + QR) | réseaux, franchises | sur devis | vente par commerciaux, onboarding lourd, hors budget TPE |
| Guest Suite, Custplace, Goodays | multi-sites, grands comptes | sur devis | idem |
| Solocal Manager | TPE | non public | notoriété mitigée, offre floue |
| Trustpilot | e-commerce | 79 à 479 €/mois par domaine, facturé à l'année | pas fait pour le commerce physique |
| Google Business Profile seul | tous | gratuit | pas de collecte, réponse IA testée aux États-Unis, Brésil, Inde seulement |
| Petits outils QR « avis Google » | TPE | 5 à 20 €/mois | collecte seule, pas de réponse, pas de rapport |

Taille adressable : plusieurs centaines de milliers de commerces et services de proximité en France. Il en faut **150 pour 4 400 € de MRR**. La taille du marché n'est pas la contrainte, l'acquisition l'est.

### 1.3 Offre et prix

| Formule | Prix HT/mois | Contenu |
|---|---|---|
| Solo | 19 € | 1 établissement, QR code et lien de collecte, brouillons de réponse, alertes |
| Pro | 29 € | + 100 SMS ou WhatsApp de sollicitation par mois, multi-plateformes (Google, Facebook, Tripadvisor, Pages Jaunes), rapport mensuel |
| Réseau | 59 € | jusqu'à 5 établissements, rapport consolidé |
| Annuel | 10 mois payés sur 12 | |

ARPU retenu dans le modèle : 29 €.

### 1.4 Produit

**MVP (4 semaines, une seule promesse : « plus d'avis et une réponse à chacun »)**
1. Onboarding : connexion Google, choix du ton (3 exemples de réponses à valider), QR code généré, lien court de collecte.
2. Collecte : page « laissez-nous un avis » avec lien direct vers le formulaire Google ; envoi SMS ou WhatsApp d'une demande après visite (saisie manuelle du numéro ou import CSV).
3. Réponses : polling des nouveaux avis, brouillon rédigé par LLM dans le ton choisi, validation en un clic depuis l'email ou l'interface, publication via l'API.
4. Alerte : notification immédiate sur un avis à 1 ou 2 étoiles.

**V2 (mois 3-6)** : rapport mensuel PDF, multi-plateformes, mode « auto-publication » pour les avis positifs, widget d'avis pour le site du commerçant.
**V3 (mois 6-12)** : multi-établissements, suivi des concurrents du quartier, export pour les agences qui gèrent plusieurs commerces (canal de revente).

**Ce que fait le Mac mini, H24**
- toutes les 15 minutes : récupération des nouveaux avis de chaque client (API Google Business Profile, approbation manuelle de Google requise : fiche vérifiée depuis 60 jours et site web, formulaire « Basic API Access », quota 300 requêtes/minute une fois approuvé, environ 14 jours de délai d'après les retours)
- rédaction des brouillons avec un modèle local (Qwen3 14B suffit ; un modèle cloud peut être réservé aux avis négatifs)
- envoi des demandes d'avis programmées (SMS via un fournisseur français, 0,05 à 0,07 € l'unité)
- génération des rapports mensuels
- la partie visible (site, interface, webhooks Stripe) tourne sur le VPS, pas sur le Mac mini

**Stack** : Next.js ou SvelteKit sur le VPS, Postgres, Stripe, n8n ou scripts Python sur le Mac mini, Ollama, fournisseur SMS, Resend ou Brevo pour les emails.

**Prérequis bloquant à lancer dès la semaine 1** : la demande d'accès à l'API Google Business Profile. En attendant, la collecte (QR, SMS) fonctionne sans API, car l'URL d'avis Google est publique.

### 1.5 Acquisition

| Canal | Mécanique | Part attendue des clients à 12 mois |
|---|---|---|
| Porte-à-porte et démo locale | 20 commerces de ta ville, démo en 5 minutes avec un QR imprimé, offre « 1er mois offert » | 30 % des 50 premiers, puis marginal |
| Contenu (plan 4) | shorts et pins « comment avoir plus d'avis Google », page de capture, essai gratuit | 40 % |
| Partenaires prescripteurs | agences web locales, comptables, imprimeurs de QR, associations de commerçants : 20 % de commission récurrente | 20 % |
| Bouche-à-oreille | parrainage : 1 mois offert pour chaque filleul | 10 % |

Funnel cible : visite page → essai 14 jours : 5 % ; essai → payant : 40 %.

### 1.6 Unit economics

| Poste | Valeur |
|---|---|
| ARPU | 29 €/mois |
| Coût variable par client | ~3,5 €/mois (SMS 1,8 €, LLM 0,5 €, Stripe 0,7 €, emails 0,1 €) |
| Marge brute | ~88 % |
| Churn mensuel (réaliste) | 5 % (benchmarks SMB : 3 à 6,4 %) |
| Durée de vie moyenne | 20 mois |
| LTV brute | ~510 € |
| CAC maximum acceptable (LTV/3) | 170 € ; cible réelle sous 50 € (organique, terrain) |
| Coûts fixes | 35 €/mois + 150 € de mise en place (domaine, matériel QR, premiers SMS) |

### 1.7 Projections 24 mois

Hypothèses d'acquisition (nouveaux clients par mois) et de churn :

| Scénario | M1-M3 | M4-M12 | M13-M24 | Churn mensuel |
|---|---|---|---|---|
| Pessimiste | 0, 2, 3 | 3 | 3 | 7 % |
| Réaliste | 0, 3, 7 | de 6 à 12 | 12 | 5 % |
| Optimiste | 2, 6, 12 | de 12 à 25 | 25 | 3,5 % |

Résultats (clients actifs / MRR / trésorerie cumulée nette des coûts, hors temps du fondateur) :

| Mois | Pessimiste | Réaliste | Optimiste |
|---|---|---|---|
| M3 | 5 / 141 € / −80 € | 10 / 286 € / 73 € | 20 / 570 € / 499 € |
| M6 | 12 / 357 € / 575 € | 28 / 805 € / 1 612 € | 57 / 1 660 € / 3 753 € |
| M9 | 18 / 530 € / 1 723 € | 50 / 1 437 € / 4 722 € | 105 / 3 049 € / 10 413 € |
| M12 | 23 / 669 € / 3 267 € | 75 / 2 165 € / 9 671 € | 162 / 4 706 € / 21 215 € |
| M18 | 30 / 872 € / 7 249 € | 118 / 3 435 € / 24 959 € | 269 / 7 787 € / 55 597 € |
| M24 | 35 / 1 003 € / 12 066 € | 151 / 4 369 € / 45 869 € | 354 / 10 275 € / 104 354 € |

Lecture : le scénario réaliste donne **2 200 €/mois à 12 mois et 4 400 €/mois à 24 mois**, avec un actif revendable (un SaaS à 50 k€ d'ARR se vend typiquement 2,5 à 4 fois l'ARR). Le pessimiste reste positif mais ne justifie pas le temps passé : c'est le critère d'arrêt.

### 1.8 Plan d'exécution

| Semaine | Livrable |
|---|---|
| 1 | demande d'accès API Google ; 10 entretiens de 15 min avec des commerçants (douleur, prix, ton) ; nom, domaine, Stripe, micro-entreprise |
| 2-3 | collecte (QR, page d'avis, SMS), onboarding, page de vente ; premiers 5 commerces en bêta gratuite |
| 4-5 | brouillons de réponse et validation en un clic (dès l'approbation API) ; alertes 1-2 étoiles |
| 6 | lancement payant : les 5 bêta passent à 19 € ou partent ; démarchage des 20 commerces |
| 7-8 | 10 clients payants ; mise en route de la machine à contenu (plan 4) sur ce sujet |
| 9-12 | rapport mensuel, programme de parrainage, premiers partenaires prescripteurs ; objectif 20 clients à M3 |
| M4-M6 | multi-plateformes, mode auto-publication ; objectif 30 clients à M6 |
| M7-M12 | multi-établissements, offre agences ; objectif 75 clients à M12 |

Semaine type en régime de croisière (à partir de M6) : 2 h de support, 1 h de suivi des métriques, 2 h de contenu validé, 1 h d'améliorations. Le reste tourne seul.

### 1.9 Risques et parades

| Risque | Probabilité | Parade |
|---|---|---|
| Google intègre la réponse IA aux avis en Europe (testée aux États-Unis, Brésil, Inde) | moyenne | la valeur est dans la collecte, le multi-plateformes, le ton, le rapport ; la réponse est le produit d'appel, pas le fossé |
| Refus ou retard d'accès à l'API Google | moyenne | lancer la collecte sans API ; prévoir Facebook et Tripadvisor en parallèle ; demander l'accès depuis une fiche bien établie |
| Churn élevé des TPE (saisonnalité, fermetures) | élevée | prélèvement annuel à −2 mois, rapport mensuel qui montre la valeur, alerte avant chaque renouvellement |
| Acquisition trop lente | élevée | le terrain pour les 50 premiers, puis les prescripteurs ; ne pas payer de pub avant 10 clients |
| Non-conformité (faux avis, filtrage) | faible si cadré | jamais de filtrage des clients mécontents (interdit par Google), jamais d'avis rédigés à la place du client, mention « réponse préparée avec IA » possible |

### 1.10 KPIs et critères d'arrêt

- Hebdo : essais démarrés, essais convertis, avis collectés par client, délai moyen de réponse, churn.
- Arrêt ou pivot : moins de 10 clients payants à M3 malgré 50 démos, ou churn supérieur à 8 % sur 3 mois consécutifs.
- Succès : 75 clients à M12 avec churn sous 5 %. À ce stade, décider entre continuer seul, recruter un commercial à la commission, ou vendre.

### 1.11 Juridique et RGPD

- Tu es **sous-traitant** des données des clients du commerçant (numéros de téléphone) : contrat de sous-traitance (DPA) dans les CGV, hébergement en UE, suppression à la résiliation.
- Sollicitation d'avis par SMS : message sans contenu commercial, identification claire de l'émetteur, désinscription en un clic, pas de relance marketing. Vérifier le cadre CNIL avant le lancement.
- Avis en ligne : interdiction des faux avis et de la sélection des avis (code de la consommation, directive Omnibus) ; les règles Google interdisent de dissuader les avis négatifs.
- Mentions légales, CGV, politique de confidentialité, facturation conforme.

---

## 2. Plan 2 : Produit données

### Niche d'exemple : marchés publics pour les entreprises d'espaces verts et paysagistes

**Résumé exécutif.** Chaque matin, un email de 2 minutes : les nouveaux appels d'offres qui correspondent au métier et à la zone du client, **résumés en langage clair** (objet, lieu, montant estimé, date limite, pièces à fournir, « vaut-il le coup de répondre ? » avec un score). Chaque semaine, un **brief de marché** tiré des données d'attribution : qui a remporté quoi près de chez lui, à quel prix, quels acheteurs publient régulièrement. Aucune interface à construire : le produit est un email, un espace de réglage minimal et une facture Stripe. Le Mac mini collecte, filtre, résume et envoie.

Pourquoi ce métier : filière fragmentée (environ 30 000 entreprises), les communes et intercommunalités sont des acheteurs récurrents (entretien, création, élagage), les marchés sont souvent de taille moyenne, et un code CPV unique (77310000, services de plantation et d'entretien d'espaces verts) rend le filtrage fiable. Alternatives équivalentes : nettoyage de locaux, peinture et finitions, électricité, menuiserie, signalétique.

### 2.1 Problème, cible, promesse

| | |
|---|---|
| Client idéal | entreprise de 3 à 50 salariés, déjà sollicitée par des collectivités ou qui veut l'être, sans personne dédiée à la veille |
| Problème | les avis sont dispersés sur BOAMP, TED, PLACE et des dizaines de profils d'acheteurs ; les outils de veille existants sont génériques, sur devis, et renvoient des avis bruts |
| Promesse | « Les marchés qui valent le coup, résumés chaque matin, pour 39 € par mois » |
| Preuve de demande | commande publique 2024 : 233,3 Md€ et 223 383 marchés recensés (OECP), 60 % des marchés attribués à des PME en nombre ; les veilles payantes existent depuis vingt ans |
| Pourquoi maintenant | API BOAMP ouverte (2 publications par jour, 7 j/7) ; API DECP lancée en juin 2026 par l'AIFE avec recherche et export ; les résumés en langage clair sont devenus gratuits à produire |

### 2.2 Marché et concurrence

| Acteur | Positionnement | Prix | Faiblesse exploitable |
|---|---|---|---|
| France Marchés, Marchés Online « Veille Intégrale », Klekoon, Doubletrade, Vecteur Plus | veille générique multi-secteurs | sur devis ou abonnement mensuel non public, le plus souvent au-dessus de 100 €/mois d'après les retours terrain (non vérifié) | avis bruts, pas de résumé ni de score, pas de brief d'attribution, vente par commerciaux |
| BOAMP, marches-publics.gouv.fr | source officielle | gratuit | alertes rudimentaires, aucune analyse |
| Agences de réponse aux appels d'offres | service | plusieurs centaines d'euros par dossier | ne font pas la veille au quotidien |

Il faut **48 clients pour 1 700 €/mois**. Sur 30 000 entreprises, c'est 0,16 % de pénétration.

### 2.3 Offre et prix

| Formule | Prix HT/mois | Contenu |
|---|---|---|
| Essentiel | 29 € | alertes quotidiennes, 1 métier, 2 départements, résumé et score |
| Pro | 49 € | + jusqu'à 6 départements, brief hebdo d'attribution (DECP), résumé des pièces du DCE sur demande, export CSV |
| Annuel | 10 mois payés | |

ARPU retenu : 36 €.

### 2.4 Produit et sources de données

| Source | Contenu | Accès | Usage |
|---|---|---|---|
| API BOAMP (DILA) | avis de marchés au-dessus des seuils et une partie des MAPA | ouvert, 2 mises à jour par jour, format eForms | alertes quotidiennes |
| API DECP (AIFE, juin 2026) et miroir data.economie.gouv.fr | données essentielles des marchés conclus (attributaires, montants, acheteurs) | ouvert, recherche et export | brief hebdo « qui gagne quoi » |
| TED (UE) | avis européens | ouvert | alertes au-dessus des seuils européens |
| Profils d'acheteurs régionaux | petits MAPA | hétérogène | V2, par région, après validation de la demande |

Limite à connaître : les procédures de petit montant ne sont souvent publiées que sur le profil de l'acheteur. Le MVP couvre BOAMP + TED, ce qui suffit pour les marchés de taille moyenne ; les profils régionaux sont ajoutés en V2 par département, en commençant par ceux de tes premiers clients.

**Pipeline sur le Mac mini**
1. 6 h et 14 h : collecte BOAMP et TED, filtrage par CPV et zone.
2. Résumé structuré par LLM local (objet, lieu, montant, délai, pièces, critères), score d'opportunité par règles + LLM (montant compatible, délai suffisant, critères prix/technique, acheteur déjà connu).
3. 7 h : email par client, uniquement s'il y a du nouveau. Zéro email vide.
4. Dimanche : brief DECP par zone (attributions de la semaine, montants, acheteurs actifs, concurrents récurrents).
5. Journal de qualité : chaque résumé garde le lien vers l'avis source ; une erreur signalée par un client est corrigée dans les règles.

Le résumé d'un avis est calculé une fois et partagé entre tous les clients concernés : le coût LLM ne croît presque pas avec le nombre de clients.

### 2.5 Acquisition

| Canal | Mécanique | Part attendue |
|---|---|---|
| Prospection directe | liste des attributaires récents (DECP) dans un métier : ce sont des entreprises qui répondent déjà aux marchés ; email personnalisé avec un exemple d'alerte réelle de leur zone | 50 % des 30 premiers |
| Contenu LinkedIn et YouTube (plan 4) | « comment répondre à un appel d'offres quand on est une entreprise de 10 personnes », exemples de marchés commentés | 30 % |
| Fédérations et réseaux professionnels | UNEP, CAPEB, chambres de métiers : webinaire gratuit, offre négociée pour les adhérents | 15 % |
| Parrainage | 1 mois offert | 5 % |

Argument de vente le plus fort : envoyer à un prospect, avant même qu'il réponde, **trois marchés réels de sa zone résumés**. Le produit se démontre tout seul.

### 2.6 Unit economics

| Poste | Valeur |
|---|---|
| ARPU | 36 €/mois |
| Coût variable par client | ~1,2 €/mois (LLM partagé 0,3 €, emails 0,1 €, Stripe 0,8 €) |
| Marge brute | ~97 % |
| Churn mensuel (réaliste) | 6 % (clients qui remportent un marché et arrêtent la veille, saisonnalité) |
| LTV brute | ~580 € |
| CAC maximum | 190 € ; cible réelle sous 40 € |
| Coûts fixes | 35 €/mois + 50 € de mise en place |

### 2.7 Projections 24 mois

Hypothèses :

| Scénario | M1-M3 | M4-M12 | M13-M24 | Churn |
|---|---|---|---|---|
| Pessimiste | 0, 1, 2 | 2 | 2 | 8 % |
| Réaliste | 0, 2, 4 | de 4 à 8 | 8 | 6 % |
| Optimiste | 1, 4, 8 | de 8 à 15 | 15 | 4 % |

Résultats (clients / MRR / cumul) :

| Mois | Pessimiste | Réaliste | Optimiste |
|---|---|---|---|
| M3 | 3 / 105 € / −19 € | 6 / 212 € / 119 € | 13 / 459 € / 497 € |
| M6 | 8 / 281 € / 531 € | 18 / 635 € / 1 428 € | 37 / 1 330 € / 3 367 € |
| M9 | 12 / 418 € / 1 513 € | 32 / 1 140 € / 4 125 € | 66 / 2 372 € / 9 098 € |
| M12 | 15 / 525 € / 2 832 € | 48 / 1 711 € / 8 417 € | 99 / 3 566 € / 18 150 € |
| M18 | 19 / 672 € / 6 200 € | 74 / 2 669 € / 21 539 € | 159 / 5 724 € / 46 173 € |
| M24 | 21 / 762 € / 10 214 € | 92 / 3 330 € / 39 160 € | 206 / 7 413 € / 85 073 € |

Lecture : plafond plus bas que le plan 1 sur un seul métier, mais le même pipeline se **duplique à un deuxième métier en deux semaines** (autre code CPV, autre liste de prospects). Trois métiers en réaliste donnent 5 000 €/mois à 24 mois pour le même travail d'infrastructure.

### 2.8 Plan d'exécution

| Semaine | Livrable |
|---|---|
| 1 | accès API BOAMP et DECP, choix du métier et du CPV, 10 appels à des entreprises attributaires récentes (douleur, outils actuels, prix) |
| 2 | collecte + filtrage + résumé fonctionnels en local, 20 exemples envoyés aux 10 entreprises appelées pour avis |
| 3 | score d'opportunité, page de vente, Stripe, réglages (zone, montant min) ; 5 bêta-testeurs gratuits 30 jours |
| 4-5 | brief DECP hebdo ; lancement payant ; 50 emails de prospection par semaine avec alerte réelle en pièce jointe |
| 6-8 | 10 clients payants ; premier webinaire avec un réseau professionnel ; contenu LinkedIn hebdo |
| 9-12 | profils d'acheteurs régionaux pour les départements des clients ; objectif 20 clients à M3 |
| M4-M6 | résumé du DCE sur demande, export CSV ; objectif 30 clients |
| M7-M12 | deuxième métier ; objectif 50 clients cumulés à M12 |

Semaine type en croisière : 1 h de contrôle qualité des résumés, 1 h de support, 2 h de prospection ou contenu. Le reste tourne seul.

### 2.9 Risques et parades

| Risque | Probabilité | Parade |
|---|---|---|
| Couverture incomplète des petits marchés | élevée | l'annoncer clairement ; ajouter les profils régionaux là où sont les clients ; viser des entreprises qui répondent à des marchés moyens |
| Résumé erroné (montant, date) qui fait rater une réponse | moyenne | lien source dans chaque alerte, champs clés extraits par règles et non par LLM seul, mention « vérifiez l'avis original » |
| Clients qui partent après avoir remporté un marché | élevée | formule annuelle, brief d'attribution qui garde de la valeur hors période de réponse |
| Changement de format des API | faible | eForms est standardisé ; tests quotidiens de la collecte avec alerte si volume anormal |
| Concurrent établi qui baisse ses prix | faible | ton positionnement est le métier et le résumé, pas le prix |

### 2.10 KPIs et critères d'arrêt

- Hebdo : alertes envoyées, taux d'ouverture (cible 60 %+), clics vers les avis, clients, churn, erreurs signalées.
- Arrêt ou pivot de métier : moins de 10 clients à M3 malgré 150 emails de prospection, ou taux d'ouverture sous 35 %.
- Succès : 50 clients sur 2 métiers à M12.

### 2.11 Juridique

- Données BOAMP, DECP, TED : réutilisation commerciale autorisée sous Licence Ouverte (mention de la source obligatoire).
- Prospection email B2B : autorisée en France sur adresses professionnelles liées à l'activité, avec identification et désinscription.
- CGV avec clause explicite : outil d'aide à la veille, aucune garantie d'exhaustivité ni de conformité juridique des réponses.

---

## 3. Plan 3 : Newsletter de niche semi-automatisée

### Niche d'exemple : « l'IA pour les cabinets d'expertise comptable »

**Résumé exécutif.** Une newsletter hebdomadaire, le mardi matin, en français, pour les experts-comptables et leurs collaborateurs : ce qui a changé cette semaine (outils, réglementation, pratiques des éditeurs), un cas d'usage concret par numéro avec le prompt ou le process prêt à copier, et une veille sur ce que font les cabinets concurrents. Le Mac mini collecte les sources, résume, propose un brouillon ; tu le relis et le signes en 45 minutes. Monétisation par sponsors (éditeurs et fintechs qui ciblent les cabinets) et par un niveau payant à 9 €/mois donnant accès aux prompts, process et modèles.

Pourquoi cette cible : environ 21 000 experts-comptables, plus de 25 000 cabinets et 120 000 à 190 000 collaborateurs selon les sources ; une profession en pleine transformation par l'IA (60 % des experts-comptables interrogés l'utilisent pour des analyses, baromètre SVP 2026) ; des éditeurs à gros budgets marketing qui cherchent exactement cette audience ; **aucune newsletter française dédiée n'est ressortie** des recherches (à vérifier à la main sur LinkedIn, Substack et Kessel avant de lancer). Alternatives : « l'IA pour les agents immobiliers », « l'IA pour les artisans du bâtiment » (même cible que le plan 2).

### 3.1 Lecteur, problème, promesse

| | |
|---|---|
| Lecteur idéal | expert-comptable ou chef de mission dans un cabinet de 2 à 50 personnes, sous pression des clients et des éditeurs, qui veut comprendre sans y passer ses soirées |
| Problème | veille éclatée (LinkedIn, éditeurs, presse pro), beaucoup de bruit, peu d'exemples applicables à un cabinet |
| Promesse | « Chaque mardi, ce que l'IA change pour votre cabinet, en 5 minutes, avec un process à appliquer » |
| Différence | pas une newsletter IA généraliste : chaque numéro parle de tenue, révision, social, fiscal, relation client, recrutement |

### 3.2 Concurrence et sponsors

- Newsletters IA généralistes en français : nombreuses, aucune centrée sur la profession.
- Contenus des éditeurs (Dext, Pennylane, Cegid, Sage, ACD, MyUnisoft) : abondants mais orientés produit ; ce sont des **sponsors**, pas des concurrents.
- Médias professionnels (Revue Fiduciaire, Lefebvre Dalloz, Compta Online) : généralistes, lents sur le sujet, payants ou institutionnels.
- Sponsors potentiels : éditeurs comptables, fintechs (banques pro, paiement, trésorerie), paie et RH, formation continue, assureurs. Repères de prix B2B français : un kit média 2023 d'un titre spécialisé facturait un envoi sponsorisé environ 230 € HT pour 1 000 abonnés ; la méthode courante des éditeurs est un CPM cible de 100 € sur les ouvertures.

### 3.3 Format et pipeline

**Format hebdo (lecture 5 minutes)** : 3 actualités commentées ; 1 cas d'usage détaillé avec le prompt ou le workflow ; 1 chiffre ; 1 outil testé ; 1 question de lecteur. Mention en pied : « veille assistée par IA, relue et signée par un humain ».

**Pipeline sur le Mac mini**
1. Lundi 5 h : collecte des sources (flux RSS des éditeurs, presse pro, comptes LinkedIn et X clés, BOFiP, URSSAF, Légifrance, newsletters concurrentes anglophones), déduplication, classement par thème.
2. Résumé et scoring de pertinence par LLM local ; sélection des 8 items les plus pertinents.
3. Brouillon complet du numéro dans ton style (quelques numéros écrits à la main servent d'exemples).
4. Lundi matin : relecture, réécriture de l'éditorial, choix du cas d'usage. 45 à 60 minutes.
5. Mardi 7 h : envoi. Mercredi : relance automatique aux non-ouvreurs avec un autre objet.
6. En continu : extraction des posts LinkedIn à partir du numéro (plan 4), réponses aux lecteurs, mise à jour de la bibliothèque de prompts pour le niveau payant.

Plateforme : beehiiv (gratuit jusqu'à 2 500 abonnés, puis plan Scale, estimé 45 €/mois ; le réseau publicitaire exige le plan Scale et vise surtout des annonceurs anglophones : ne pas compter dessus), ou Kessel pour une plateforme française avec paiement intégré, ou Substack.

### 3.4 Acquisition des abonnés

| Canal | Mécanique | Part attendue |
|---|---|---|
| LinkedIn (plan 4) | 3 posts par semaine tirés du numéro, un post « coulisses » par mois, commentaires sur les posts des éditeurs et des ordres | 50 % |
| Partenariats | échange de visibilité avec des newsletters voisines (paie, juridique, gestion), intervention dans des webinaires d'éditeurs | 20 % |
| Référencement | page d'archives publique, un article long par mois « l'IA en cabinet : guide » | 15 % |
| Parrainage | un abonné qui en amène 3 reçoit la bibliothèque de prompts | 15 % |

### 3.5 Monétisation en escalier

| Palier | Déclencheur | Revenu |
|---|---|---|
| 0 à 2 000 abonnés | | 0 € ; on construit la preuve (taux d'ouverture 45 %+) |
| 2 000 abonnés | kit média d'une page avec taux d'ouverture et profil des lecteurs | sponsor : 300 € minimum par envoi, puis 100 € pour 1 000 abonnés par envoi |
| 1 000 abonnés (dès M4) | bibliothèque de prompts et process, modèles de lettres de mission IA, replays | niveau payant 9 €/mois ou 79 €/an ; conversion 2 % attendue |
| 5 000 abonnés | | sponsor principal mensuel (4 envois) + sponsor secondaire |
| 10 000 abonnés | | 1 000 à 2 000 € par envoi en direct ; atelier payant trimestriel en option (non passif) |

### 3.6 Projections 24 mois

Hypothèses :

| Scénario | Nouveaux abonnés nets / mois | Désabonnement mensuel | Prix sponsor pour 1 000 abonnés par envoi | Envois sponsorisés | Conversion payant |
|---|---|---|---|---|---|
| Pessimiste | 100 | 1,5 % | 60 € | 1 sur 4 | 1 % |
| Réaliste | de 150 à 400 | 1,5 % | 100 € | 2 sur 4 | 2 % |
| Optimiste | de 300 à 900 | 1,5 % | 150 € | 3 sur 4 | 3 % |

Résultats (abonnés / revenu mensuel / cumul) :

| Mois | Pessimiste | Réaliste | Optimiste |
|---|---|---|---|
| M3 | 296 / 0 € / −45 € | 511 / 0 € / −45 € | 1 049 / 0 € / −45 € |
| M6 | 578 / 52 € / 41 € | 1 201 / 216 € / 427 € | 2 536 / 1 826 € / 2 633 € |
| M9 | 848 / 76 € / 201 € | 2 062 / 971 € / 1 934 € | 4 440 / 3 197 € / 10 607 € |
| M12 | 1 106 / 100 € / 431 € | 3 086 / 1 173 € / 5 092 € | 6 743 / 4 855 € / 23 272 € |
| M18 | 1 588 / 143 € / 1 092 € | 5 130 / 1 950 € / 14 522 € | 11 360 / 8 179 € / 63 724 € |
| M24 | 2 028 / 483 € / 2 300 € | 6 997 / 2 659 € / 28 373 € | 15 577 / 11 215 € / 122 900 € |

Au M12 réaliste : 617 € de sponsoring et 556 € d'abonnements payants. Au M24 : 1 400 € et 1 260 €.

Lecture : c'est le plan le plus lent à payer et le plus dépendant de ta régularité, mais c'est aussi **l'actif le plus durable** : une liste de 7 000 professionnels qualifiés vaut plus que son revenu direct, parce qu'elle vend ensuite n'importe quel produit (plan 1 ou 2 adapté aux cabinets, formation, service).

### 3.7 Plan d'exécution

| Semaine | Livrable |
|---|---|
| 1 | vérification manuelle de la concurrence, choix du nom, plateforme, page d'inscription, 3 numéros écrits à la main (ils servent de base de style) |
| 2 | pipeline de collecte et de brouillon sur le Mac mini, test sur 2 numéros |
| 3 | lancement : envoi aux 50 premiers contacts, 3 posts LinkedIn par semaine |
| 4-8 | rythme hebdo tenu, 2 partenariats d'échange, objectif 500 abonnés à M2 |
| 9-12 | bibliothèque de prompts, niveau payant, article long mensuel ; objectif 1 000 abonnés à M3 (optimiste) ou 500 (réaliste) |
| M4-M6 | kit média, premiers sponsors dès 2 000 abonnés |
| M7-M12 | sponsor mensuel, parrainage, 3 000 abonnés |

Temps hebdo en croisière : 1 h de relecture et d'édito, 1 h de LinkedIn, 30 min de réponses aux lecteurs et sponsors.

### 3.8 Risques et parades

| Risque | Probabilité | Parade |
|---|---|---|
| Croissance lente des abonnés | élevée | LinkedIn quotidien les 3 premiers mois, partenariats croisés, un aimant à abonnés fort (bibliothèque de prompts) |
| Contenu perçu comme générique ou « IA » | moyenne | un cas d'usage réel par numéro, ton personnel, relecture systématique, signature humaine |
| Sponsors absents en dessous de 3 000 abonnés | élevée | niveau payant dès M4, sponsors « fondateurs » à prix réduit contre engagement 6 mois |
| Un éditeur lance la même newsletter | faible | ton indépendance est l'argument ; les éditeurs ne peuvent pas parler de leurs concurrents |
| Délivrabilité | moyenne | domaine dédié, double opt-in, nettoyage trimestriel des inactifs |

### 3.9 KPIs et critères d'arrêt

- Hebdo : nouveaux abonnés, taux d'ouverture (cible 45 %), taux de clic (cible 5 %), désabonnements, réponses reçues.
- Arrêt : moins de 500 abonnés à M4 ou taux d'ouverture sous 30 % pendant 2 mois.
- Succès : 3 000 abonnés et un sponsor récurrent à M12.

### 3.10 Juridique

- RGPD : double opt-in, mention claire de l'usage, désinscription en un clic, hébergement de la liste chez un prestataire conforme.
- Sponsoring signalé comme tel dans chaque numéro.
- Mention de l'assistance par IA (AI Act art. 50 en vigueur depuis le 2 août 2026 pour les textes publiés sur des sujets d'intérêt public ; ici facultative mais recommandée).
- Pas de conseil fiscal personnalisé : la newsletter informe, elle ne conseille pas.

---

## 4. Plan 4 : Moteur de contenu YouTube, TikTok, Pinterest (et LinkedIn)

**Rôle.** Ce plan ne vend rien. Il produit chaque jour, sur le Mac mini, du contenu court et utile sur les problèmes que résolvent les plans 1, 2 et 3, avec 15 minutes de validation humaine, pour amener des visiteurs vers une page de capture puis vers le produit. Le revenu direct des plateformes est un bonus, modélisé pour mémoire.

### 4.1 Les règles du jeu par plateforme (état octobre 2026)

| Plateforme | Monétisation directe | Seuils | Règle IA | Rôle dans le plan |
|---|---|---|---|---|
| YouTube (longs + Shorts) | Partner Program | palier « fan funding » : 500 abonnés + 3 000 h de visionnage sur 12 mois ou 3 M de vues Shorts sur 90 jours ; palier complet : 1 000 abonnés + 4 000 h ou 10 M de vues Shorts ; relèvement annoncé pour les nouveaux au 1er février 2027 (8 000 h ou 20 M de vues Shorts), à vérifier sur la page officielle | contenu « inauthentique » (templaté, produit à la chaîne, sans apport d'auteur) démonétisé ; voix synthétique sur script original acceptée ; étiquetage du contenu modifié ou synthétique | référencement durable des vidéos « comment faire », Shorts pour la découverte |
| TikTok | Creator Rewards | 18 ans, compte personnel, 10 000 abonnés, 100 000 vues sur 30 jours glissants, vidéos de plus d'une minute, contenu 100 % original ; France listée comme éligible par plusieurs sources (vérifier dans l'application) | label IA obligatoire sous peine de strike ; l'originalité exclut le contenu généré en masse | découverte rapide, test des angles |
| Pinterest | aucune (affiliation autorisée avec mention) | | répétition et programmation massive = filtre anti-spam ; mention « lien affilié » en haut de la description | trafic durable vers les pages longues (guides, modèles) |
| LinkedIn | aucune | | pas de règle IA spécifique, mais le contenu générique est ignoré par l'algorithme | canal principal pour les plans 2 et 3 (B2B) |

Repères de revenu direct en France (sources non officielles) : vidéos longues 1 à 5 € pour 1 000 vues, 3,5 à 7 € en niche business ; Shorts 0,02 à 0,08 € pour 1 000 vues ; TikTok Creator Rewards 0,50 à 1,20 € pour 1 000 vues qualifiées.

### 4.2 Ligne éditoriale par produit

| Produit servi | Angle | Exemples de formats |
|---|---|---|
| Plan 1 (commerces) | « plus de clients pour ton commerce » | Short : « 3 phrases pour obtenir un avis Google sans gêner le client » ; long : « j'ai analysé 200 fiches Google de restaurants, voilà ce qui sépare les 4,8 des 4,2 » ; pin : affiche QR à imprimer |
| Plan 2 (entreprises espaces verts, artisans) | « les marchés publics sans jargon » | Short : « ce marché d'entretien à 80 k€ n'a eu qu'une seule réponse » ; long : « répondre à un appel d'offres en 10 personnes, pas à pas » ; LinkedIn : marché de la semaine commenté |
| Plan 3 (cabinets) | « l'IA en cabinet, concrètement » | LinkedIn : 1 cas d'usage par post ; long YouTube : démonstration d'un process ; carrousel |

Règle : chaque contenu répond à une question qu'un prospect tape vraiment. Zéro contenu « tendance IA » générique.

### 4.3 Pipeline de production sur le Mac mini

| Étape | Outil | Automatisé ? |
|---|---|---|
| 1. Banque de sujets | recherche des questions (Google Suggest, commentaires, réponses de prospects, mots-clés) classée par produit | oui, hebdo |
| 2. Script | LLM local, dans ton style, 3 variantes par sujet, longueur adaptée au format | oui |
| 3. Validation | lecture, choix, correction de 3 à 5 scripts par jour | **humain, 15 min** |
| 4. Voix | TTS local (Kokoro) ou ElevenLabs si qualité requise ; ou ta voix enregistrée en lot le dimanche (meilleur pour TikTok et l'originalité) | oui |
| 5. Visuels | captures d'écran du produit, images générées en local (Flux.2 klein via Ollama, Draw Things), sous-titres automatiques | oui |
| 6. Montage | ffmpeg (templates verticaux et horizontaux), miniatures générées | oui |
| 7. Étiquetage | label IA côté TikTok et YouTube quand il y a de la voix ou de l'image synthétique | oui, par défaut |
| 8. Programmation | Postiz auto-hébergé ou Metricool ; 1 Short/jour, 1 TikTok/jour, 5 pins/jour, 3 posts LinkedIn/semaine, 1 long YouTube/semaine | oui |
| 9. Boucle | métriques récupérées chaque nuit, les angles qui performent sont déclinés, les autres abandonnés | oui |

Cadence réaliste : 20 à 25 contenus courts par semaine, 1 vidéo longue, 3 posts LinkedIn. Le long YouTube hebdo est celui qui demande le plus d'humain (20 à 40 minutes de ta part, ou ton visage à l'écran).

Pour TikTok, l'exigence d'originalité pousse vers **ta voix et ton visage** sur une partie des contenus ; un compte uniquement synthétique sera exclu du Creator Rewards et limité par l'algorithme.

### 4.4 Funnel et KPIs

Hypothèses à M12 : vues mensuelles cumulées toutes plateformes, taux de clic vers la page de capture, taux de capture d'email, conversion email vers client payant.

| Scénario | Vues / mois | Clics | Emails captés | Clients produit / mois | Revenu direct plateformes |
|---|---|---|---|---|---|
| Pessimiste | 60 000 | 240 | 36 | 1 à 2 | ~20 € |
| Réaliste | 250 000 | 1 500 | 300 | ~15 | ~100 € |
| Optimiste | 800 000 | 6 400 | 1 600 | ~95 | ~300 € |

Le scénario réaliste du plan 4 est ce qui alimente les 12 nouveaux clients par mois du plan 1 réaliste et les 300 à 400 abonnés par mois du plan 3 réaliste. **Sans ce moteur, les plans 1 à 3 tombent dans leur scénario pessimiste.**

KPIs hebdo : contenus publiés, vues, taux de clic vers la capture, emails captés, coût en temps par email capté (cible : sous 2 minutes de ton temps par email).

### 4.5 Plan d'exécution

| Semaine | Livrable |
|---|---|
| 1 | comptes créés (YouTube, TikTok, Pinterest, LinkedIn), banque de 100 sujets par produit, 5 scripts écrits à la main pour fixer le style |
| 2 | pipeline script → voix → montage → programmation opérationnel ; 10 premiers contenus publiés |
| 3-4 | cadence quotidienne ; page de capture avec aimant (checklist, modèle, exemple d'alerte) |
| 5-8 | boucle d'analyse : 3 angles conservés, 3 abandonnés par semaine ; première vidéo longue par semaine |
| 9-12 | 1 000 abonnés cumulés (objectif réaliste), premiers emails captés qui convertissent |
| M4-M12 | déclinaison des contenus qui marchent, série longue mensuelle, candidature aux programmes quand les seuils sont atteints |

### 4.6 Risques et parades

| Risque | Probabilité | Parade |
|---|---|---|
| Démonétisation ou bridage pour contenu de masse | moyenne | validation humaine systématique, ta voix et ton visage sur une partie, zéro republication en lot, angles originaux tirés de tes données produit |
| Aucune traction sur un canal | élevée | couper le canal après 8 semaines sans signal ; LinkedIn et YouTube long sont les plus prévisibles en B2B |
| Temps réel supérieur aux 15 minutes promises | élevée au début | industrialiser avant d'augmenter la cadence ; moins de contenus, mieux ciblés |
| Risque réputationnel (erreur factuelle en vidéo) | moyenne | sources citées dans la description, pas de chiffres non vérifiés, correction publique rapide |

### 4.7 Juridique

- Étiquetage du contenu synthétique sur YouTube et TikTok ; AI Act art. 50 pour les deepfakes et les contenus d'intérêt public.
- Jamais de visage ou de voix d'une personne réelle sans accord ; les avatars synthétiques sont acceptés s'ils sont étiquetés.
- Musique et images libres de droits ou générées ; mention « lien affilié » si affiliation.

---

## 5. Synthèse

### Ordre de lancement recommandé

1. **Semaines 1-2 : plan 4 (socle) + choix entre plan 1 et plan 2.** Le moteur de contenu se construit une fois et sert tout le reste. Choisis le plan 1 si tu peux faire du terrain dans ta ville (boucle de vente la plus rapide : un commerce signe en 5 minutes devant un QR code). Choisis le plan 2 si tu préfères vendre à distance par email et LinkedIn (produit le plus simple à construire, données ouvertes, aucune approbation d'API).
2. **Mois 1-3 : un seul produit jusqu'à 10 clients payants.** Pas deux. Le second produit n'arrive que si le premier a 10 clients et un churn sous 8 %.
3. **Mois 3-6 : plan 3 en parallèle** si tu tiens déjà la cadence de contenu sans dépasser ton budget temps. Sinon, repousser.
4. **Mois 6-12 : dupliquer** ce qui marche (deuxième métier pour le plan 2, offre agences pour le plan 1, sponsor récurrent pour le plan 3).

### Variante « pile cohérente » (une seule cible)

Si tu veux que les 4 plans parlent au même public, prends les artisans et entreprises du bâtiment et du paysage :
- Plan 2 : marchés publics pour ce métier (inchangé).
- Plan 1 : avis clients pour artisans (les avis Google pèsent autant pour un plombier que pour un restaurant).
- Plan 3 : « IA et digital pour les entreprises du bâtiment » (sponsors : logiciels de devis, banques pro, assureurs décennale, négoces de matériaux).
- Plan 4 : un seul univers éditorial.
Le revenu sponsor du plan 3 sera un peu plus faible qu'avec les cabinets comptables, mais chaque contenu sert les trois produits et chaque client peut en acheter deux.

### Projection consolidée (scénario réaliste, en lançant plan 4 + plan 1 à M1, plan 3 à M4, plan 2 à M7)

| | M6 | M12 | M18 | M24 |
|---|---|---|---|---|
| Plan 1 | 805 € | 2 165 € | 3 435 € | 4 369 € |
| Plan 3 (décalé de 3 mois) | 0 € | 971 € | 1 560 € | 2 300 € |
| Plan 2 (décalé de 6 mois) | 0 € | 635 € | 1 711 € | 2 669 € |
| Plan 4 (direct) | ~30 € | ~100 € | ~150 € | ~200 € |
| **Total mensuel** | **~835 €** | **~3 870 €** | **~6 850 €** | **~9 540 €** |

C'est le chemin réaliste, pas le pessimiste : il suppose la cadence tenue et un produit qui plaît dès le premier métier. Le scénario pessimiste consolidé tourne autour de 1 500 €/mois à M24, ce qui ne justifie pas le temps investi : d'où les critères d'arrêt à M3 et M4 dans chaque plan.

### Critères d'arrêt communs

- Un produit sans 10 clients payants à M3 malgré 50 démos ou 150 prospections : changer de niche.
- Un canal sans signal après 8 semaines : couper.
- Plus de 15 h par semaine passées pendant plus de 2 mois après le lancement : le pipeline n'est pas assez automatisé, arrêter d'ajouter et industrialiser.
- Trésorerie personnelle : aucune dépense au-delà de 500 € sur 12 mois sans client payant pour la couvrir.

---

## 6. Sources

Plateformes et règles
- YouTube Partner Program 2026 : [air.io](https://air.io/en/monetization/youtube-partner-program-requirements-2026-the-complete-guide), [vidiq.com](https://vidiq.com/blog/post/monetize-youtube-guide/) ; RPM France : [ibrahimkamara.com](https://ibrahimkamara.com/blog/rpm-cpm-youtube-france-2026), [formalive.fr](https://www.formalive.fr/remuneration-youtube/), [tubeanalytics.net](https://tubeanalytics.net/benchmarks/france)
- TikTok Creator Rewards : [metricool.com](https://metricool.com/fr/tiktok-creativity-program/), [swello.com](https://swello.com/fr/blog/gagner-de-largent-sur-tiktok/), [ttcalculator.net](https://ttcalculator.net/learn/creator-fund-countries/), [adaptlypost.com](https://adaptlypost.com/en/blog/tiktok-creator-fund-eligibility-requirements)
- Pinterest et affiliation : [community.pinterest.biz](https://community.pinterest.biz/t/use-of-affiliate-links-without-being-considered-spam/41093.md), [pingenerator.com](https://pingenerator.com/blog/pinterest-affiliate-links-policy)

Plan 1
- API Google Business Profile : [singhamandeep.com](https://singhamandeep.com/google-business-profile-api-access/), [slashpost.ai](https://slashpost.ai/blogs/google-business-profile/google-business-profile-api-documentation-2026), [community.n8n.io](https://community.n8n.io/t/google-reviews-response-automation/304701), [developers.google.com](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/updateReply)
- Concurrence : [foxeet.fr (classement 2026)](https://foxeet.fr/contenu/top-logiciels-de-gestion-des-avis-clients-2026), [lafabriquedunet.fr (Partoo)](https://www.lafabriquedunet.fr/logiciel/partoo), [leptidigital.fr](https://www.leptidigital.fr/logiciels/partoo/), [custplace.com (réponse IA Google)](https://fr.custplace.com/business/reponses-automatiques-aux-avis-google-business-profile/), [custplace.com (QR code)](https://fr.custplace.com/business/qr-code-collecte-avis/), [wisestart.fr](https://wisestart.fr/guides/premiers-clients/obtenir-avis-google-clients/)
- Churn SMB : [visionary-marketing.co.uk](https://visionary-marketing.co.uk/blog/saas-churn-benchmarks-2026), [shno.co](https://www.shno.co/marketing-statistics/saas-churn-benchmarks-statistics), [wearefounders.uk](https://www.wearefounders.uk/saas-churn-rates-and-customer-acquisition-costs-by-industry-2025-data/)

Plan 2
- Données : [data.gouv.fr (BOAMP)](https://www.data.gouv.fr/datasets/boamp), [data.gouv.fr (API DECP)](https://www.data.gouv.fr/datasets/api-decp/discussions), [weka.fr (API DECP, juin 2026)](https://www.weka.fr/actualite/commande-publique/article/une-nouvelle-application-pour-faciliter-la-declaration-des-donnees-essentielles-de-la-commande-publique-216165/), [acteurspublics.fr](https://acteurspublics.fr/articles/bercy-lance-une-application-pour-encourager-la-transparence-des-marches-publics/)
- Marché : [seban-associes.avocat.fr (chiffres OECP 2024)](https://www.seban-associes.avocat.fr/panorama-de-la-commande-publique-les-chiffres-de-2024/), [marche-public.fr](https://marche-public.fr/Commande-publique.htm), [economie.gouv.fr (DAJ)](https://www.economie.gouv.fr/node/53352), [hayot-expertise.fr](https://hayot-expertise.fr/blog/comment-repondre-a-un-appel-d-offre), [marchesonline.com (CGU Veille Intégrale)](https://www.marchesonline.com/conditions-utilisation)

Plan 3
- Profession : [tool-advisor.fr](https://tool-advisor.fr/blog/chiffres-expertise-comptable/), [tailride.so (marché)](https://tailride.so/fr/blog/statistiques-marche-comptabilite-france), [tailride.so (IA)](https://tailride.so/fr/blog/statistiques-ia-comptabilite-2026), [cci-paris-idf.fr](https://entreprises.cci-paris-idf.fr/fiches-pratiques/le-metier-dexpert-comptable), [optionfinance.fr](https://www.optionfinance.fr/entreprise-finance/experts-comptables-une-profession-a-lepreuve-de-lintelligence-artificielle.html), [dext.com](https://dext.com/fr/ressources/blog-actualite-comptable/single/tendances-comptables-2026)
- Sponsoring : [salesdorado.com](https://salesdorado.com/marketing-b2b/sponsoring-newsletter/), [electroniques.biz (kit média 2023)](https://www.electroniques.biz/app/uploads/sites/5/2022/10/KIT-MEDIA-ELECTRONIQUES-2023-MD.pdf), [dupple.com (CPM B2B 2026)](https://dupple.com/learn/cpm-benchmarks-b2b-newsletters), [blogdumoderateur.com](https://www.blogdumoderateur.com/comment-creer-newsletter-payante-outils-bonnes-pratiques/)
- beehiiv : [Ad Network FAQ (juillet 2026)](https://www.beehiiv.com/support/article/17507491038231-Ad-Network-FAQ), [beehiiv.com/blog](https://www.beehiiv.com/blog/beehiiv-ad-network), [emarketer.com](https://www.emarketer.com/content/beehiiv-doubles-ad-sales-team-newsletter-monetization-heats-up)

Cadre général
- Dossier précédent `business-passif-mac-mini-2026.md` (politiques YouTube, Deezer, Google, Etsy, KDP, AI Act, micro-entreprise 2026).
