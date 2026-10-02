# Alertes Outdoor : robot de surveillance des prix

Un robot passe toutes les 3 heures sur les pages de magasins outdoor que tu choisis. Il relève les prix et publie les grosses baisses sur un site public. Tout tourne gratuitement sur GitHub, même quand ton PC est éteint.

- **Site public** : `https://TON-PSEUDO.github.io/alertes-outdoor/`
- **Réglages (depuis ton téléphone)** : `https://TON-PSEUDO.github.io/alertes-outdoor/admin.html`

## Comment le robot décide qu'une affaire est intéressante

Pour chaque page surveillée, tu règles :

- **un seuil en %** : alerte si le prix baisse d'au moins ce pourcentage par rapport au *prix habituel* (la médiane des 30 derniers jours, calculée par le robot), ou si le magasin affiche lui-même un prix barré avec au moins cette remise ;
- **un plafond en €** : alerte dès que le prix passe en dessous.

Le robot doit avoir relevé une page pendant au moins 3 jours avant de connaître son prix habituel. En attendant, seules les remises affichées par le magasin et le plafond déclenchent des alertes.

Une page peut être une **fiche produit** (un seul article) ou une **page de catégorie / de marque** (tous les articles affichés). Pour une catégorie, le champ « filtre » garde seulement les produits dont le nom contient certains mots (par exemple `salomon`).

## Installation (environ 20 minutes, une seule fois)

1. **Crée un compte GitHub** sur github.com si tu n'en as pas.
2. **Crée le dépôt** : bouton « + » › *New repository* › nom `alertes-outdoor` › *Public* › *Create repository*. Ensuite clique *uploading an existing file* et glisse **tout le contenu** du dossier décompressé, y compris le dossier `.github` (s'il n'apparaît pas, voir plus bas). Valide avec *Commit changes*.
3. **Active le site** : *Settings* › *Pages* › *Source : Deploy from a branch* › branche `main`, dossier `/docs` › *Save*. Le site est en ligne au bout d'une à deux minutes.
4. **Crée ton jeton pour les réglages** : photo de profil › *Settings* › *Developer settings* › *Personal access tokens* › *Fine-grained tokens* › *Generate new token*.
   - *Repository access* : *Only select repositories* › `alertes-outdoor`
   - *Permissions* : **Contents** = *Read and write*, **Actions** = *Read and write*
   - Durée : 1 an. Copie le jeton (`github_pat_…`) : il ne s'affiche qu'une fois.
5. **Ouvre la page de réglages** sur ton téléphone, colle le jeton, et ajoute tes pages à surveiller. Ajoute-la à l'écran d'accueil pour l'avoir comme une appli.
6. **Lance le robot une première fois** avec le bouton « Lancer le robot maintenant ».

### Si le dossier `.github` ne s'envoie pas

Les dossiers qui commencent par un point sont parfois cachés. Dans le dépôt : *Add file* › *Create new file* › nom `.github/workflows/robot.yml` › colle le contenu du fichier `robot.yml` › *Commit changes*.

## Alertes Discord (optionnel)

Pour recevoir chaque nouvelle affaire dans un salon Discord : dans le salon › *Modifier le salon* › *Intégrations* › *Webhooks* › *Nouveau webhook* › *Copier l'URL*. Puis dans GitHub : *Settings* › *Secrets and variables* › *Actions* › *New repository secret*, nom `DISCORD_WEBHOOK`, valeur = l'URL copiée.

## Liens affiliés

Quand tu es accepté dans le programme d'affiliation d'un magasin (souvent via Awin, Effiliation ou Kwanko), colle son modèle de lien dans « Liens affiliés » sur la page de réglages, une ligne par magasin :

```
snowleader.com = https://www.awin1.com/cread.php?awinmid=XXXX&awinaffid=YYYY&ued={url}
```

`{url}` est remplacé par le lien du produit. Le site ajoute alors automatiquement une mention « liens affiliés » en bas de page.

## Quand une page reste en rouge

- **« Le site a refusé l'accès (HTTP 403) »** : le magasin bloque les robots. Il n'y a rien à corriger côté robot. Remplace la page par une autre, ou passe par le flux produits du programme d'affiliation de ce magasin.
- **« Page lue mais aucun prix trouvé »** : le magasin n'inclut pas ses prix dans un format standard. Essaie la fiche produit au lieu de la catégorie, ou l'inverse.

## Fichiers

| Fichier | Rôle |
|---|---|
| `robot/check.py` | le robot (Python) |
| `.github/workflows/robot.yml` | le planning : toutes les 3 h, plus le bouton manuel |
| `docs/index.html` | le site public |
| `docs/admin.html` | la page de réglages |
| `docs/data/watchlist.json` | les pages surveillées et leurs seuils |
| `docs/data/deals.json` | les affaires publiées |
| `docs/data/history.json` | l'historique des prix (120 jours) |
| `docs/data/status.json` | le résultat du dernier passage, page par page |
| `docs/data/config.json` | le nom du site, l'accroche et les liens affiliés |
