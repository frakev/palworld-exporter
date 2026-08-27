package main

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// expo assemble une réponse au format d'exposition Prometheus (texte). Il
// n'émet les lignes # HELP / # TYPE qu'une fois par métrique, ce qui autorise
// plusieurs séries (jeux de labels) sous un même nom.
type expo struct {
	b    strings.Builder
	seen map[string]bool
}

func (e *expo) meta(name, typ, help string) {
	if e.seen == nil {
		e.seen = map[string]bool{}
	}
	if e.seen[name] {
		return
	}
	e.seen[name] = true
	fmt.Fprintf(&e.b, "# HELP %s %s\n# TYPE %s %s\n", name, help, name, typ)
}

// gauge émet une série sans label.
func (e *expo) gauge(name, help string, v float64) {
	e.meta(name, "gauge", help)
	fmt.Fprintf(&e.b, "%s %s\n", name, num(v))
}

// gaugeL émet une série avec labels. labels est déjà formaté (k="v",k2="v2").
func (e *expo) gaugeL(name, help, labels string, v float64) {
	e.meta(name, "gauge", help)
	fmt.Fprintf(&e.b, "%s{%s} %s\n", name, labels, num(v))
}

func (e *expo) String() string { return e.b.String() }

// num formate un flottant sans notation exponentielle (Prometheus l'accepte,
// mais les valeurs en clair se lisent mieux) et sans zéros superflus.
func num(v float64) string { return strconv.FormatFloat(v, 'f', -1, 64) }

func b2f(b bool) float64 {
	if b {
		return 1
	}
	return 0
}

// esc échappe une valeur de label selon la spec d'exposition Prometheus :
// antislash, guillemet et saut de ligne.
func esc(s string) string {
	return strings.NewReplacer(`\`, `\\`, `"`, `\"`, "\n", `\n`).Replace(s)
}

// lbl assemble un jeu de labels à partir de paires clé/valeur.
func lbl(kv ...string) string {
	var parts []string
	for i := 0; i+1 < len(kv); i += 2 {
		parts = append(parts, fmt.Sprintf(`%s="%s"`, kv[i], esc(kv[i+1])))
	}
	return strings.Join(parts, ",")
}

// collect construit l'exposition à partir des deux sources locales, toutes deux
// sur l'hôte de jeu : l'API REST officielle du serveur Palworld (métriques live)
// et le parser de sauvegardes (stats par joueur). Aucune dépendance à un agent.
// Chaque source est facultative et sans effet fatal : indisponible → métriques
// `*_online`/`*_up` à 0 et le reste omis.
func collect(ctx context.Context, rc *restClient, sc *statsClient) string {
	start := time.Now()
	e := &expo{}

	// Stats de sauvegarde (indépendantes de l'état du serveur).
	if sc != nil {
		collectStats(ctx, sc, e)
	}
	// Métriques live via l'API REST du jeu.
	if rc != nil {
		collectGame(ctx, rc, e)
	}

	e.gauge("palworld_scrape_duration_seconds", "Durée de la collecte de l'exporter.", time.Since(start).Seconds())
	return e.String()
}

// collectGame interroge l'API REST du jeu en parallèle et n'ajoute les
// métriques que si elle répond. palworld_game_online = 1 signale un serveur
// démarré et prêt à accueillir (l'API REST ne répond que dans ce cas).
func collectGame(ctx context.Context, rc *restClient, e *expo) {
	var (
		wg      sync.WaitGroup
		m       palMetrics
		info    palInfo
		players struct {
			Players []palPlayer `json:"players"`
		}
		mErr, iErr, pErr error
	)
	wg.Add(3)
	go func() { defer wg.Done(); mErr = rc.get(ctx, "/metrics", &m) }()
	go func() { defer wg.Done(); iErr = rc.get(ctx, "/info", &info) }()
	go func() { defer wg.Done(); pErr = rc.get(ctx, "/players", &players) }()
	wg.Wait()

	online := mErr == nil && iErr == nil && pErr == nil
	e.gauge("palworld_game_online", "1 si l'API REST du jeu répond (serveur démarré et prêt).", b2f(online))
	if !online {
		return
	}

	e.gaugeL("palworld_game_info", "Version et nom du serveur (valeur constante 1).",
		lbl("version", info.Version, "server_name", info.ServerName), 1)
	e.gauge("palworld_server_fps", "FPS du serveur rapporté par le jeu.", m.ServerFPS)
	e.gauge("palworld_server_frametime_ms", "Temps par frame du serveur, en millisecondes.", m.ServerFrameTime)
	e.gauge("palworld_players_current", "Nombre de joueurs actuellement connectés.", float64(m.CurrentPlayers))
	e.gauge("palworld_players_max", "Nombre maximal de joueurs autorisés.", float64(m.MaxPlayers))
	e.gauge("palworld_game_uptime_seconds", "Uptime rapporté par l'API REST du jeu.", float64(m.Uptime))

	// Métriques « live » d'un joueur connecté (labels name/player_id). Le niveau
	// et les compteurs détaillés viennent du parsing des saves (labels
	// uid/name/guild) et ne sont PAS émis ici, pour éviter un même nom de
	// métrique sous deux jeux de labels — ce que Prometheus refuse.
	sort.Slice(players.Players, func(i, j int) bool { return players.Players[i].PlayerID < players.Players[j].PlayerID })
	for _, p := range players.Players {
		if p.PlayerID == "" {
			continue
		}
		l := lbl("name", p.Name, "player_id", p.PlayerID)
		e.gaugeL("palworld_player_online", "1 par joueur actuellement connecté.", l, 1)
		e.gaugeL("palworld_player_ping_ms", "Ping du joueur connecté, en millisecondes.", l, p.Ping)
		e.gaugeL("palworld_player_location_x", "Position X du joueur connecté sur la carte.", l, p.LocationX)
		e.gaugeL("palworld_player_location_y", "Position Y du joueur connecté sur la carte.", l, p.LocationY)
	}
}
