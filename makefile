init_sandbox_rules:
	sbx kit add "claude-$$(basename "$$(pwd)")" ./dev-kit/

add_skills:
	npx skills install internetofwater/geoconnex.us