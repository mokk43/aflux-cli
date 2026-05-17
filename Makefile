.PHONY: build-web dev serve clean

build-web:
	cd web && npm ci && npm run build

dev:
	set -e; \
	aflux serve --host 127.0.0.1 --port 8000 & \
	API_PID=$$!; \
	trap 'kill $$API_PID 2>/dev/null || true' INT TERM EXIT; \
	cd web && npm run dev; \
	STATUS=$$?; \
	kill $$API_PID 2>/dev/null || true; \
	wait $$API_PID 2>/dev/null || true; \
	exit $$STATUS

serve:
	aflux serve

clean:
	rm -rf web/build web/node_modules
