package main

import (
	"bufio"
	"context"
	"crypto/subtle"
	"encoding/json"
	"flag"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// palworld-exporter est un exporter Prometheus autonome qui tourne sur la
// machine de jeu. Il interroge en boucle locale l'API REST officielle du serveur
// Palworld (métriques live) et, si présent, le parser de sauvegardes (stats par
// joueur), puis réexpose le tout au format Prometheus sur /metrics. Aucune
// dépendance à un agent : Prometheus (dans le cluster) le scrute directement, le
// pare-feu restreignant le port à l'IP maison.
type config struct {
	Listen       string // adresse d'écoute HTTP, ex. ":9812"
	RestURL      string // API REST du jeu, ex. "http://127.0.0.1:8212"
	RestUser     string // utilisateur Basic (par défaut "admin")
	RestPassword string // AdminPassword du serveur ; vide = pas de métriques live
	ParserURL    string // parser de saves ; vide = pas de métriques save
	MetricsToken string // si défini, exige "Authorization: Bearer <token>" sur /metrics
}

func main() {
	cfgPath := flag.String("config", "/etc/palworld-exporter/exporter.env", "fichier de configuration")
	flag.Parse()

	cfg, err := loadConfig(*cfgPath)
	if err != nil {
		log.Fatalf("configuration: %v", err)
	}

	var rc *restClient
	if cfg.RestPassword != "" {
		rc = newRestClient(cfg.RestURL, cfg.RestUser, cfg.RestPassword)
	} else {
		log.Print("REST_PASSWORD vide : métriques live du jeu désactivées (stats save seulement)")
	}
	var sc *statsClient
	if cfg.ParserURL != "" {
		sc = newStatsClient(cfg.ParserURL)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, "ok") })
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		if cfg.MetricsToken != "" {
			want := []byte("Bearer " + cfg.MetricsToken)
			if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), want) != 1 {
				http.Error(w, "token invalide", http.StatusUnauthorized)
				return
			}
		}
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		io.WriteString(w, collect(ctx, rc, sc))
	})

	srv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("palworld-exporter écoute sur %s (rest=%s)", cfg.Listen, cfg.RestURL)
	log.Fatal(srv.ListenAndServe())
}

func decodeJSON(r io.Reader, out any) error {
	return json.NewDecoder(r).Decode(out)
}

// loadConfig lit un fichier KEY=value (syntaxe EnvironmentFile systemd) puis
// applique les variables d'environnement de même nom, qui priment.
func loadConfig(path string) (*config, error) {
	c := &config{
		Listen:    ":9812",
		RestURL:   "http://127.0.0.1:8212",
		RestUser:  "admin",
		ParserURL: "http://127.0.0.1:8100",
	}
	kv := map[string]string{}

	if f, err := os.Open(path); err == nil {
		defer f.Close()
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			line := strings.TrimSpace(sc.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			if k, v, ok := strings.Cut(line, "="); ok {
				kv[strings.ToUpper(strings.TrimSpace(k))] = unquote(strings.TrimSpace(v))
			}
		}
		if err := sc.Err(); err != nil {
			return nil, err
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}

	get := func(key string) string {
		if v, ok := os.LookupEnv(key); ok {
			return v
		}
		return kv[key]
	}
	set := func(key string, dst *string) {
		if v := get(key); v != "" {
			*dst = v
		}
	}
	set("LISTEN", &c.Listen)
	set("REST_URL", &c.RestURL)
	set("REST_USER", &c.RestUser)
	set("REST_PASSWORD", &c.RestPassword)
	set("PARSER_URL", &c.ParserURL)
	set("METRICS_TOKEN", &c.MetricsToken)
	return c, nil
}

func unquote(s string) string {
	if len(s) >= 2 && (s[0] == '"' && s[len(s)-1] == '"' || s[0] == '\'' && s[len(s)-1] == '\'') {
		return s[1 : len(s)-1]
	}
	return s
}
