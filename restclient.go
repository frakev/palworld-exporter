package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// restClient parle directement à l'API REST officielle du serveur Palworld, qui
// écoute en boucle locale sur l'hôte de jeu (RESTAPIEnabled=True dans le .ini).
// L'exporter tournant sur la même machine, aucune dépendance à un agent : il
// interroge http://127.0.0.1:8212/v1/api/* en authentification Basic (admin +
// AdminPassword du serveur).
type restClient struct {
	base string
	user string
	pass string
	http *http.Client
}

func newRestClient(base, user, pass string) *restClient {
	return &restClient{
		base: strings.TrimSuffix(base, "/"),
		user: user,
		pass: pass,
		http: &http.Client{Timeout: 8 * time.Second},
	}
}

// get exécute un GET authentifié sur /v1/api<path> et désérialise le JSON.
func (c *restClient) get(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/v1/api"+path, nil)
	if err != nil {
		return err
	}
	req.SetBasicAuth(c.user, c.pass)
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("API REST Palworld injoignable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("API REST %s: %s", path, resp.Status)
	}
	return decodeJSON(resp.Body, out)
}

// ---- Types miroir de l'API REST du jeu ----------------------------------

type palMetrics struct {
	ServerFPS       float64 `json:"serverfps"`
	CurrentPlayers  int     `json:"currentplayernum"`
	ServerFrameTime float64 `json:"serverframetime"`
	MaxPlayers      int     `json:"maxplayernum"`
	Uptime          int64   `json:"uptime"`
}

type palInfo struct {
	Version    string `json:"version"`
	ServerName string `json:"servername"`
}

type palPlayer struct {
	Name      string  `json:"name"`
	PlayerID  string  `json:"playerId"`
	Ping      float64 `json:"ping"`
	LocationX float64 `json:"location_x"`
	LocationY float64 `json:"location_y"`
	Level     int     `json:"level"`
}
