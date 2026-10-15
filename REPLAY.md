# Rejouer une journée réelle sur la plateforme locale

Rejoue une journée de prod SDIS-77 (dump `~/pyronear/test/analyse77/<date>/`, jours
disponibles : 2026-07-10 à 2026-07-13) contre la stack locale, avec une **horloge
simulée pilotable** : la plateforme affiche la journée aux vraies heures (datée
d'aujourd'hui), et on avance/pause/ralentit à la demande.

## 1. Prérequis (une fois)

**Image API avec l'horloge simulée** — deux branches dans le worktree
`~/pyronear/api/pyro-api-replay-20260710`, selon la journée à rejouer (la prod a
déployé #629 entre le 10 au soir et le 12 au matin — vérifié sur les données :
la tolérance bbox de #629 est visible dans les séquences du 12) :

| Journée rejouée | Branche à builder |
|---|---|
| 2026-07-10 (et 11 matin) | `replay-clock-20260710` (avant #629 — les doublons d'alertes sont fidèles) |
| 2026-07-12, 2026-07-13 | `replay-clock-20260712` (#629+#630+#631 + patch horloge) |

```bash
cd ~/pyronear/api/pyro-api-replay-20260710
git checkout replay-clock-20260712    # ou replay-clock-20260710 selon la journée
make build                            # -> image pyronear/alert-api:latest
```

(Pour rejouer avec le code actuel : cherry-pick des 2 commits d'horloge sur main,
puis `make build`.)

`/etc/hosts` doit contenir `127.0.0.1 minio` (pour voir les images dans la plateforme).

## 2. Lancer la stack

```bash
cd ~/pyronear/devops/pyro-envdev
docker compose -f docker-compose.yml -f docker-compose.replay.yml up -d db minio pyro_api init_script frontend
```

Attendre que le seed se termine (`docker logs -f init` → "completed successfully").

- Plateforme : **http://localhost:8080** — compte **`test77` / `test`**
- API : http://localhost:5050/docs — superadmin `mateo`/`mateo` (cf. `.env`)

## 3. Lancer le replay interactif

```bash
python3 scripts/replay_day.py --day 2026-07-10 --ctl
```

Le script mappe les caméras/poses de prod sur l'env local, redémarre l'API sur
l'horloge pilotable, et démarre **en pause** juste avant la première détection.
Il tourne en avant-plan jusqu'à la fin de la journée (le laisser ouvert dans son
terminal, piloter depuis un autre).

## 4. Piloter (`scripts/replay_ctl.py`)

Effet immédiat, aucun redémarrage :

```bash
python3 scripts/replay_ctl.py status      # heure simulée, vitesse, prochaines étapes
python3 scripts/replay_ctl.py next        # ➜ étape suivante : avance rapide, atterrit
                                          #   3 min APRÈS le début de la séquence
                                          #   (images déjà visibles), puis PAUSE
python3 scripts/replay_ctl.py next 10     #   idem mais reprend la lecture à 10x
python3 scripts/replay_ctl.py goto 12h00  # avance jusqu'à 12h00 HEURE DE PARIS, puis PAUSE
python3 scripts/replay_ctl.py goto 16:50 10   # idem mais reprend à 10x en arrivant
python3 scripts/replay_ctl.py play 60     # lecture 60x (journée en ~11 min)
python3 scripts/replay_ctl.py slow 5      # ralenti 5x
python3 scripts/replay_ctl.py pause       # gel de la simulation
```

Repères pour le 10/07 (heures affichées, Paris) : **12h00-12h15 feu de Barbizon**
(croix-augas-01 puis triangulation nemours-02, enchevêtrement de doublons pré-#629),
16h00-17h30 série d'alertes de l'après-midi, 18h50-19h40 cluster du soir.

On ne peut pas revenir en arrière (les données sont en base) — pour revoir un
moment, reset (§6) et `goto`.

## 5. Rejouer une autre journée (11, 12, 13/07…)

Toujours **reset d'abord** (l'ancien jour pollue les fenêtres de regroupement et la
vue live). Si on change d'époque (10-11/07 ↔ 12-13/07), rebuilder l'image sur la
bonne branche (§1) **avant** le `up`. Puis relancer le driver avec la date voulue :

```bash
cd ~/pyronear/devops/pyro-envdev
# arrêter le driver en cours (Ctrl-C dans son terminal, ou pkill)
pkill -f replay_day.py
rm -f replay_control/clock.json replay_control/steps.json
docker compose -f docker-compose.yml -f docker-compose.replay.yml down -v
docker compose -f docker-compose.yml -f docker-compose.replay.yml up -d db minio pyro_api init_script frontend
# attendre le seed: docker logs -f init  ->  "completed successfully"

python3 scripts/replay_day.py --day 2026-07-12 --ctl
```

Journées disponibles dans le dump : `2026-07-10`, `2026-07-11`, `2026-07-12`,
`2026-07-13`. Le pilotage (`replay_ctl.py`) est identique quel que soit le jour.

Repères (heures affichées, Paris) :
- **12/07** : 14h41 détection du feu d'Achères/Noisy sur croix-augas-02
  (localisation fausse à 5,5 km via le panache, corrigée à 17h35 — alertes
  multiples), après-midi très chargée 14h-17h30.
- **13/07** : 09h24 fumée sur l'axe Faisanderie (croix-augas-02), 14h32 la
  séquence « détection SDIS » (azimut 222°), 19h04 confirmation moret — journée
  la plus chaotique (le feu de 800 ha brûle toute la journée).

## 6. Tout remettre à zéro

```bash
cd ~/pyronear/devops/pyro-envdev
pkill -f replay_day.py
rm -f replay_control/clock.json replay_control/steps.json
docker compose -f docker-compose.yml -f docker-compose.replay.yml down -v
docker compose -f docker-compose.yml -f docker-compose.replay.yml up -d db minio pyro_api init_script frontend
```

À faire **entre deux journées rejouées** (sinon l'ancien jour pollue les fenêtres
de regroupement et la vue live).

## Comment ça marche

- L'API (patchée) lit son horloge dans `replay_control/clock.json` (monté dans le
  conteneur) : segments `(real0, sim0, speed)` relus à chaud — `replay_ctl.py` ne
  fait qu'ajouter des segments. Tout le pipeline (fenêtres de séquences,
  triangulation, vue live « 24 h ») vit dans ce temps simulé ; les JWT restent sur
  l'horloge réelle.
- `replay_day.py --ctl` poste les détections dès que l'horloge les rend « dues »,
  avec **une file séquentielle par caméra** (comme en prod — la concurrence
  intra-caméra crée des séquences dupliquées) ; l'avance rapide est plafonnée à
  60x, sinon la file prend du retard sur l'horloge et une séquence active peut se
  scinder à la frontière du saut.
- Fidélité mesurée vs prod (10/07 à 60x) : mêmes regroupements sur les événements
  multi-caméras, localisations identiques à ~5 m, horodatages à ±3 s.

## Modes secondaires

- `--clock` (sans `--ctl`) : horloge fixe à `--speed`, sans pilotage (le mode du
  premier test de bout en bout).
- Sans `--clock` : posts à l'heure réelle + réécriture SQL des horodatages
  historiques à la fin (`--no-restore-times` pour désactiver) ; nécessite les
  fenêtres réduites — obsolète, préférer `--ctl`.
- `--dry-run` : vérifie le mapping caméras/poses sans rien poster.

## Limites

- Seules les séquences validées en prod sont dans le dump (le bruit non validé
  n'est pas rejoué) ; les 2 séquences > 100 détections sont tronquées à 100.
- 5 détections à bbox dégénérée `(0,0,0,0,0)` sont filtrées (l'API les rejette).
- Le gate temporel est désactivé (fail-open, fidèle au comportement du 10/07).
