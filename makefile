all:
	rm -rf ./build/
	rm -rf *.egg-info
	uv tool install . --force

vscode:
	cd ./extra/vex_vscode && npx @vscode/vsce package --allow-missing-repository

.PHONY: all
