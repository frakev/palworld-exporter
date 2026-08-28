package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"
)

// statsClient interroge le parser de sauvegardes (server.py) qui tourne sur le
// même hôte, en HTTP clair sur la boucle locale. Le parser relit les saves
// périodiquement ; on ne fait ici que lire son dernier snapshot.
type statsClient struct {
	url  string
	http *http.Client
}

func newStatsClient(url string) *statsClient {
	return &statsClient{url: url, http: &http.Client{Timeout: 8 * time.Second}}
}

// statsData reflète la réponse de GET /metrics-data du parser.
type statsData struct {
	TakenAt     int64         `json:"taken_at"`
	Players     []statsPlayer `json:"players"`
	GuildCount  int           `json:"guild_count"`
	PlayerCount int           `json:"player_count"`
	PalCount    int           `json:"pal_count"`
	LuckyCount  int           `json:"lucky_count"`
}

type statsPlayer struct {
	UID                  string   `json:"uid"`
	Name                 string   `json:"name"`
	Guild                string   `json:"guild"`
	GuildID              string   `json:"guild_id"`
	Level                int      `json:"level"`
	Exp                  int64    `json:"exp"`
	PalsOwned            int      `json:"pals_owned"`
	PalsBox              int      `json:"pals_box"`
	PalsParty            int      `json:"pals_party"`
	PalsLucky            int      `json:"pals_lucky"`
	Captures             int      `json:"captures"`
	TribesCaptured       int      `json:"tribes_captured"`
	Paldeck              int      `json:"paldeck"`
	Technologies         int      `json:"technologies"`
	TechnologyPoints     int      `json:"technology_points"`
	BossTechnologyPoints int      `json:"boss_technology_points"`
	TowerBosses          int      `json:"tower_bosses"`
	FieldBosses          int      `json:"field_bosses"`
	Dungeons             int      `json:"dungeons"`
	ZonesExplored        int      `json:"zones_explored"`
	FastTravels          int      `json:"fast_travels"`
	Effigies             int      `json:"effigies"`
	QuestsCompleted      int      `json:"quests_completed"`
	LastOnline           *float64 `json:"last_online"`
}

func (c *statsClient) fetch(ctx context.Context) (*statsData, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.url+"/metrics-data", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("parser injoignable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("parser /metrics-data: %s", resp.Status)
	}
	var d statsData
	if err := decodeJSON(resp.Body, &d); err != nil {
		return nil, err
	}
	return &d, nil
}

// dotNetTicksToUnix convertit un timestamp .NET (ticks de 100 ns depuis le
// 01/01/0001 UTC, comme LastOnlineDateTime des saves) en secondes epoch. 0 pour
// une valeur absente ou incohérente.
func dotNetTicksToUnix(ticks float64) float64 {
	if ticks <= 0 {
		return 0
	}
	const epochOffset = 62135596800 // secondes entre 0001-01-01 et 1970-01-01
	return ticks/1e7 - epochOffset
}

// collectStats ajoute les métriques dérivées du parsing des saves : agrégats du
// serveur et compteurs par joueur (Pals boîte/équipe/lucky, niveau, captures,
// technologies…). Non fatal : parser absent ou pas encore de snapshot → on émet
// juste palworld_stats_up = 0.
func collectStats(ctx context.Context, sc *statsClient, e *expo) {
	d, err := sc.fetch(ctx)
	if err != nil || d == nil {
		e.gauge("palworld_stats_up", "1 si le parser de sauvegardes répond, 0 sinon.", 0)
		return
	}
	e.gauge("palworld_stats_up", "1 si le parser de sauvegardes répond, 0 sinon.", 1)
	if d.TakenAt > 0 {
		e.gauge("palworld_stats_snapshot_timestamp_seconds", "Date du dernier parsing des saves (epoch).", float64(d.TakenAt))
	}

	// Agrégats serveur (dérivés du monde sauvegardé).
	e.gauge("palworld_guilds_total", "Nombre de guildes dans la sauvegarde.", float64(d.GuildCount))
	e.gauge("palworld_players_known_total", "Nombre de joueurs connus dans la sauvegarde.", float64(d.PlayerCount))
	e.gauge("palworld_pals_total", "Nombre total de Pals possédés (tous joueurs).", float64(d.PalCount))
	e.gauge("palworld_pals_lucky_total", "Nombre total de Pals lucky (shiny), tous joueurs.", float64(d.LuckyCount))

	// Par joueur. Labels uid (clé stable de la save) + name + guild + guild_id.
	// Le nom de guilde n'est pas unique — deux guildes distinctes s'appellent
	// « Unnamed Guild » tant que personne ne les renomme —, donc agréger par
	// « guild » les confond. guild_id (préfixe 8 hexa de l'identifiant de la
	// save, même forme que uid) est le discriminant à utiliser côté dashboard.
	for _, p := range d.Players {
		if p.UID == "" {
			continue
		}
		l := lbl("uid", p.UID, "name", p.Name, "guild", p.Guild, "guild_id", p.GuildID)
		e.gaugeL("palworld_player_level", "Niveau du joueur (sauvegarde).", l, float64(p.Level))
		e.gaugeL("palworld_player_exp", "Expérience totale du joueur.", l, float64(p.Exp))
		e.gaugeL("palworld_player_pals_owned", "Nombre total de Pals possédés par le joueur.", l, float64(p.PalsOwned))
		e.gaugeL("palworld_player_pals_box", "Pals du joueur rangés dans la boîte (palbox).", l, float64(p.PalsBox))
		e.gaugeL("palworld_player_pals_party", "Pals du joueur dans l'équipe active.", l, float64(p.PalsParty))
		e.gaugeL("palworld_player_pals_lucky", "Pals lucky (shiny) du joueur.", l, float64(p.PalsLucky))
		e.gaugeL("palworld_player_captures", "Nombre total de captures du joueur.", l, float64(p.Captures))
		e.gaugeL("palworld_player_tribes_captured", "Nombre d'espèces (tribus) capturées.", l, float64(p.TribesCaptured))
		e.gaugeL("palworld_player_paldeck", "Entrées de Paldeck débloquées.", l, float64(p.Paldeck))
		e.gaugeL("palworld_player_technologies", "Technologies débloquées.", l, float64(p.Technologies))
		e.gaugeL("palworld_player_technology_points", "Points de technologie disponibles.", l, float64(p.TechnologyPoints))
		e.gaugeL("palworld_player_boss_technology_points", "Points de technologie anciens (boss) disponibles.", l, float64(p.BossTechnologyPoints))
		e.gaugeL("palworld_player_tower_bosses", "Boss de tour vaincus.", l, float64(p.TowerBosses))
		e.gaugeL("palworld_player_field_bosses", "Boss de terrain (alpha) vaincus.", l, float64(p.FieldBosses))
		e.gaugeL("palworld_player_dungeons", "Donjons terminés.", l, float64(p.Dungeons))
		e.gaugeL("palworld_player_zones_explored", "Zones de la carte explorées.", l, float64(p.ZonesExplored))
		e.gaugeL("palworld_player_fast_travels", "Points de voyage rapide débloqués.", l, float64(p.FastTravels))
		e.gaugeL("palworld_player_effigies", "Effigies de Pal ramassées.", l, float64(p.Effigies))
		e.gaugeL("palworld_player_quests_completed", "Quêtes terminées.", l, float64(p.QuestsCompleted))
		if p.LastOnline != nil {
			if ts := dotNetTicksToUnix(*p.LastOnline); ts > 0 {
				e.gaugeL("palworld_player_last_online_timestamp_seconds", "Dernière connexion du joueur (epoch).", l, ts)
			}
		}
	}
}
