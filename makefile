init_sandbox_rules:
	sbx kit add "claude-$$(basename "$$(pwd)")" ./dev-kit/

add_skills:
	npx skills install internetofwater/geoconnex.us

deps:
	uv sync --all-extras

run_test:
	uv run src/template.py --limit 2000

run_full:
	uv run src/template.py

prek:
	prek install
	prek run --all-files

build_geoconnex_bulk_container:
	docker build -t geoconnex_bulk .

run_geoconnex_bulk_container:
	docker run --rm geoconnex_bulk

run_geoconnex_bulk_container_local:
	docker run --rm -v "$(PWD)":/data geoconnex_bulk --gpkg_file /data/mainstems_v3.gpkg