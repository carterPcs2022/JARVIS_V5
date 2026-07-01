.PHONY: dev up down logs restart deploy oracle-setup health

# ── Local development ────────────────────────────────────────────────────────

dev:
	uvicorn server.api:app --host 0.0.0.0 --port 8000 --reload

friday-dev:
	cd ../FRIDAY && python server.py

# ── Docker ───────────────────────────────────────────────────────────────────

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=100

logs-jarvis:
	docker compose logs -f --tail=100 jarvis

logs-friday:
	docker compose logs -f --tail=100 friday

# ── Health checks ─────────────────────────────────────────────────────────────

health:
	@echo "JARVIS:" && curl -sf http://localhost:8000/health && echo " ✓" || echo " ✗"
	@echo "FRIDAY:" && curl -sf http://localhost:8080/health && echo " ✓" || echo " ✗"

# ── Oracle Cloud deployment ───────────────────────────────────────────────────

oracle-setup:
	@test -n "$(IP)" || (echo "Usage: make oracle-setup IP=1.2.3.4" && exit 1)
	ssh -i $(SSH_KEY) ubuntu@$(IP) "bash -s" < oracle_setup.sh

deploy:
	@test -n "$(IP)" || (echo "Usage: make deploy IP=1.2.3.4" && exit 1)
	bash deploy.sh $(IP)

# ── Utilities ─────────────────────────────────────────────────────────────────

install:
	pip3 install -r requirements.txt

test-search:
	curl -s -X POST http://localhost:8000/stark/search \
	  -H "Content-Type: application/json" \
	  -H "Authorization: Bearer $$(grep JARVIS_API_TOKEN .env | cut -d= -f2)" \
	  -d '{"query":"latest news"}' | python3 -m json.tool

test-chat:
	curl -s -X POST http://localhost:8000/stark/chat \
	  -H "Content-Type: application/json" \
	  -H "Authorization: Bearer $$(grep JARVIS_API_TOKEN .env | cut -d= -f2)" \
	  -d '{"message":"what time is it"}' | python3 -m json.tool

crypto-benchmark:
	curl -s http://localhost:8000/stark/crypto/benchmark \
	  -H "Authorization: Bearer $$(grep JARVIS_API_TOKEN .env | cut -d= -f2)" | python3 -m json.tool
