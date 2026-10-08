all: clean
	uv tool install . --force

vscode:
	cd ./extra/vex_vscode && npx @vscode/vsce package --allow-missing-repository

clean:
	rm -rf ./build/
	rm -rf ./**/*.egg-info
	rm -rf ./**/__pycache__

.PHONY: all clean
