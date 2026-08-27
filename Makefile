# palworld-exporter — build & install helpers.
# The exporter is a single static Go binary; the optional save-stats parser is
# a small Python service. Both run on the Palworld host.

BIN     ?= palworld-exporter
REMOTE  ?= user@host          # override: make deploy REMOTE=admin@1.2.3.4 HOME_IP=x.x.x.x
HOME_IP ?= CHANGE_ME

.PHONY: help build test fmt vet clean deploy parser-deploy

help:
	@echo "make build          - build the exporter binary (static, linux/amd64)"
	@echo "make test           - run Go tests"
	@echo "make deploy         - scp + install.sh the exporter on REMOTE (needs HOME_IP)"
	@echo "make parser-deploy  - scp + install.sh the save-stats parser on REMOTE"

build:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o $(BIN) .
	@ls -lh $(BIN)

test:
	go test ./...

fmt:
	gofmt -w .

vet:
	go vet ./...

clean:
	rm -f $(BIN)

# --- Remote install (Palworld host) -----------------------------------------

deploy: build
	@test "$(HOME_IP)" != "CHANGE_ME" || { echo "Set HOME_IP=<your public IP>"; exit 1; }
	ssh $(REMOTE) 'mkdir -p /tmp/palworld-exporter-install'
	scp $(BIN) palworld-exporter.service install.sh $(REMOTE):/tmp/palworld-exporter-install/
	ssh -t $(REMOTE) 'cd /tmp/palworld-exporter-install && chmod +x install.sh $(BIN) && sudo ./install.sh --home-ip $(HOME_IP)'

parser-deploy:
	ssh $(REMOTE) 'mkdir -p /tmp/palworld-parser-install'
	scp -r parser/server.py parser/requirements.txt parser/palworld_stats \
	       parser/palworld-parser.service parser/config.example.env parser/install.sh \
	       $(REMOTE):/tmp/palworld-parser-install/
	ssh -t $(REMOTE) 'cd /tmp/palworld-parser-install && chmod +x install.sh && sudo ./install.sh $(if $(SAVE_DIR),--save-dir $(SAVE_DIR),)'
