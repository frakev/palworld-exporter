package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeRest monte une fausse API REST Palworld (HTTP + Basic auth) répondant aux
// trois routes que l'exporter interroge.
func fakeRest(t *testing.T, up bool) *restClient {
	mux := http.NewServeMux()
	guard := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			u, p, ok := r.BasicAuth()
			if !ok || u != "admin" || p != "s3cret" {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
				return
			}
			if !up {
				http.Error(w, "server starting", http.StatusServiceUnavailable)
				return
			}
			h(w, r)
		}
	}
	mux.HandleFunc("/v1/api/metrics", guard(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"serverfps":58.4,"currentplayernum":2,"serverframetime":17.1,"maxplayernum":32,"uptime":3500}`))
	}))
	mux.HandleFunc("/v1/api/info", guard(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"version":"v1.0.3.101283","servername":"My \"Example\" Server"}`))
	}))
	mux.HandleFunc("/v1/api/players", guard(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"players":[{"name":"Alice","playerId":"abc123","ping":42.5,"location_x":100.0,"location_y":-50.0,"level":40}]}`))
	}))
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return newRestClient(srv.URL, "admin", "s3cret")
}

// fakeParser monte un faux server.py qui répond sur /metrics-data.
func fakeParser(t *testing.T) *statsClient {
	mux := http.NewServeMux()
	mux.HandleFunc("/metrics-data", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"taken_at":1787800000,"guild_count":1,"player_count":1,"pal_count":137,"lucky_count":3,
			"players":[{"uid":"a1b2c3d4","name":"Alice","guild":"ExampleWorld","level":42,"exp":123456,
			"pals_owned":30,"pals_box":25,"pals_party":5,"pals_lucky":2,"captures":410,"tribes_captured":88,
			"paldeck":112,"technologies":180,"technology_points":40,"boss_technology_points":10,
			"tower_bosses":3,"field_bosses":12,"dungeons":7,"zones_explored":55,"fast_travels":30,
			"effigies":66,"quests_completed":9,"last_online":638600000000000000}]}`))
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return newStatsClient(srv.URL)
}

func TestCollectRunning(t *testing.T) {
	out := collect(context.Background(), fakeRest(t, true), fakeParser(t))

	must := []string{
		// Live via l'API REST du jeu.
		"palworld_game_online 1",
		`palworld_game_info{version="v1.0.3.101283",server_name="My \"Example\" Server"} 1`,
		"palworld_server_fps 58.4",
		"palworld_players_current 2",
		`palworld_player_ping_ms{name="Alice",player_id="abc123"} 42.5`,
		`palworld_player_online{name="Alice",player_id="abc123"} 1`,
		// Dérivées du parsing des saves (labels uid/name/guild).
		"palworld_stats_up 1",
		"palworld_pals_total 137",
		"palworld_pals_lucky_total 3",
		`palworld_player_pals_box{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 25`,
		`palworld_player_pals_party{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 5`,
		`palworld_player_pals_lucky{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 2`,
		`palworld_player_level{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 42`,
		`palworld_player_captures{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 410`,
	}
	for _, m := range must {
		if !strings.Contains(out, m) {
			t.Errorf("sortie sans la ligne attendue:\n  %s", m)
		}
	}
	// Le nom de serveur contient un guillemet : il doit être échappé.
	if !strings.Contains(out, `server_name="My \"Example\" Server"`) {
		t.Errorf("guillemet non échappé dans le label server_name")
	}
	// Chaque nom de métrique n'a qu'un seul bloc # TYPE.
	if n := strings.Count(out, "# TYPE palworld_player_pals_box "); n != 1 {
		t.Errorf("attendu 1 en-tête TYPE pour palworld_player_pals_box, obtenu %d", n)
	}
}

func TestCollectServerStopped(t *testing.T) {
	// API REST muette (serveur éteint) mais parser présent : les stats save
	// restent disponibles, et game_online passe à 0.
	out := collect(context.Background(), fakeRest(t, false), fakeParser(t))
	if !strings.Contains(out, "palworld_game_online 0") {
		t.Error("serveur éteint: palworld_game_online devrait valoir 0")
	}
	if strings.Contains(out, "palworld_server_fps") {
		t.Error("serveur éteint: aucune métrique de jeu ne devrait apparaître")
	}
	if !strings.Contains(out, "palworld_stats_up 1") {
		t.Error("les stats save devraient rester disponibles serveur éteint")
	}
}

func TestCollectParserOnly(t *testing.T) {
	// Sans client REST (REST_PASSWORD vide), seules les stats save sont émises.
	out := collect(context.Background(), nil, fakeParser(t))
	if strings.Contains(out, "palworld_game_online") {
		t.Error("sans client REST, aucune métrique live ne devrait apparaître")
	}
	if !strings.Contains(out, "palworld_player_pals_box") {
		t.Error("les stats save devraient être présentes")
	}
}
