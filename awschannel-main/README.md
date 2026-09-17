# Bot Discord — Salons vocaux temporaires + panneau de configuration

Quand un membre rejoint le salon "➕ Créer un salon", le bot lui crée un salon
vocal personnel avec un panneau de contrôle complet (comme dans l'exemple) :
**Ouvert / Fermé / Privé**, **liste blanche / liste noire**, **Purge**,
**Micro / Vidéo / Soundboards**, **Statut**, **Transférer**, **Réglages**,
**Sauvegarder** (mémorise tes préférences pour les prochains salons).

## 1. Installation

```bash
pip install -r requirements.txt
```

`discord.py` doit être en version **2.4+** pour le bouton "Statut" (fonctionnalité
récente de Discord). Si ta version est plus ancienne : `pip install -U discord.py`

## 2. Configurer le token

Le bot cherche le token dans cet ordre, le premier trouvé est utilisé :

1. **Variable d'environnement** `DISCORD_TOKEN`
2. **Fichier `token.txt`** placé à côté de `bot.py` (juste le token, rien d'autre dedans)
3. **Saisie manuelle** : si aucun des deux n'est trouvé, le bot te le demande
   directement au lancement et le sauvegarde automatiquement dans `token.txt`
   pour la prochaine fois.

Le plus simple si tu ne veux pas t'embêter avec les variables d'environnement :
lance simplement `python bot.py` (ou `lancer.bat`), colle ton token quand il
te le demande, et c'est fait — tu n'auras plus à le refaire.

⚠️ Ne partage jamais ton fichier `token.txt` (le `.gitignore` fourni l'exclut
automatiquement si tu utilises Git/GitHub).

## 3. Intents à activer (Developer Portal > onglet Bot)

- `Server Members Intent`
- `Message Content Intent`

## 4. Permissions du bot à cocher (OAuth2 > URL Generator)

- Gérer les salons (`Manage Channels`)
- Gérer les rôles/permissions du salon
- Déplacer les membres (`Move Members`)
- Envoyer des messages / Intégrer des liens (`Send Messages`, `Embed Links`)
- Se connecter / Voir les salons

## 5. Lancer le bot

```bash
python bot.py
```

## 6. Configurer le bot avec des commandes (comme DraftBot)

Plus besoin de modifier le code : tout se configure avec des **commandes slash**,
réservées aux membres ayant la permission **Gérer le serveur**.

| Commande | Rôle |
|---|---|
| `/config voir` | Affiche la configuration actuelle du serveur |
| `/config salon_declencheur <salon>` | Choisit le salon vocal à rejoindre pour créer un salon temporaire |
| `/config categorie <catégorie>` | Choisit la catégorie où seront créés les salons temporaires |
| `/config prefixe <texte>` | Change le préfixe du nom des salons créés (ex: 🔊, 🎧, [TEMP]) |
| `/config mode_defaut <ouvert/fermé/privé>` | Change le mode appliqué par défaut aux nouveaux salons |
| `/config reset` | Réinitialise toute la configuration du serveur |

Chaque serveur a sa propre configuration, sauvegardée dans `config.json`.
Tant que `/config salon_declencheur` n'a pas été utilisé, le bot cherche un
salon nommé exactement `➕ Créer un salon` par défaut.

⚠️ Les commandes slash peuvent prendre jusqu'à 1h pour apparaître globalement
la première fois (souvent instantané en pratique). Si elles n'apparaissent
pas, vérifie que le bot a bien été invité avec la permission `applications.commands`.

## Comment utiliser le panneau

Seul le **propriétaire** du salon (ou la personne à qui il a été transféré)
peut utiliser les boutons du panneau.

- **Ouvert / Fermé / Privé** : change qui peut voir/rejoindre le salon.
- **Liste blanche / Liste noire** : ouvre un menu pour ajouter ou retirer un membre.
- **Purge** : déconnecte tout le monde sauf le propriétaire et la liste blanche.
- **Micro / Vidéo / Soundboards** : active/désactive ces droits pour les membres non listés.
- **Statut** : ouvre une fenêtre pour écrire un statut affiché sous le salon.
- **Transférer** : donne la propriété du salon à un autre membre présent.
- **Réglages** : renommer le salon, changer la limite de membres.
- **Sauvegarder** : mémorise tes réglages actuels (mode + micro/vidéo/soundboards)
  pour qu'ils soient appliqués automatiquement à tes prochains salons.

## Limites connues

- Le panneau n'est pas "persistant" après un redémarrage du bot : si le bot
  redémarre, les boutons des salons déjà créés avant l'arrêt ne répondront plus
  (le salon fonctionne toujours, juste le panneau). Dis-le-moi si tu veux que
  je rende ça persistant (stockage en base de données).
- Le bouton "Statut" utilise un endpoint Discord récent ; s'il échoue, mets à
  jour `discord.py`.
