const vscode = require('vscode');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const os = require('os');

let vexProcess = null;
let vexServerPromise = null;

const vexOutputChannel = vscode.window.createOutputChannel('VEX Server');

function getExtendedEnv() {
  const env = { ...process.env };
  const home = os.homedir();
  const extraPaths = [
    path.join(home, '.local', 'bin'),
    path.join(home, '.cargo', 'bin'),
    '/usr/local/bin'
  ];
  env.PATH = `${extraPaths.join(path.delimiter)}${path.delimiter}${env.PATH || ''}`;
  return env;
}

function isVexRunning(url = 'http://127.0.0.1:40000') {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(true);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

function ensureVexServer() {
  vexOutputChannel.show(true);

  if (!vexServerPromise) {
    vexServerPromise = (async () => {
      const running = await isVexRunning();
      if (!running) {
        vexOutputChannel.appendLine('[VEX] Starting VEX process...');

        const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

        vexProcess = spawn('vex', ['-w'], {
          cwd: workspacePath || process.cwd(),
          stdio: ['ignore', 'pipe', 'pipe'],
          shell: true,
          detached: true,
          env: getExtendedEnv()
        });

        vexProcess.stdout.on('data', (data) => {
          vexOutputChannel.appendLine(`[STDOUT] ${data.toString().trim()}`);
        });

        vexProcess.stderr.on('data', (data) => {
          vexOutputChannel.appendLine(`[STDERR] ${data.toString().trim()}`);
        });

        vexProcess.on('exit', (code, signal) => {
          vexOutputChannel.appendLine(`[VEX EXITED] Code: ${code}, Signal: ${signal}`);
          vexProcess = null;
          vexServerPromise = null;
        });

        for (let i = 0; i < 15; i++) {
          await new Promise((r) => setTimeout(r, 400));
          if (await isVexRunning()) {
            vexOutputChannel.appendLine('[VEX] Server active at http://127.0.0.1:40000');
            return true;
          }
        }
        vexOutputChannel.appendLine('[VEX ERROR] Server failed to respond in time.');
        return false;
      }
      return true;
    })();
  }
  return vexServerPromise;
}

function activate(context) {
  ensureVexServer();
  context.subscriptions.push(vexOutputChannel);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('vex-sidebar-view', {
      async resolveWebviewView(webviewView) {
        webviewView.webview.options = { enableScripts: true };
        await ensureVexServer();

        webviewView.webview.onDidReceiveMessage((message) => {
          if (message.type === 'setSession') {
            if (message.sessionId) {
              vscode.window.showInformationMessage(`Active VEX Session: ${message.sessionId}`);
              context.workspaceState.update('activeVexSession', message.sessionId);
            } else {
              // Pass 'undefined' to explicitly clear the state in VS Code
              context.workspaceState.update('activeVexSession', undefined);
            }
          }
        });

        // Fetch session directly inside resolveWebviewView closure
        const activeSession = context.workspaceState.get('activeVexSession', undefined);
        let targetUrl = 'http://127.0.0.1:40000/';
        if (activeSession) {
          targetUrl += `?session=${encodeURIComponent(activeSession)}`;
        }

        webviewView.webview.html = `
          <!DOCTYPE html>
          <html lang="en">
          <head>
            <meta charset="UTF-8">
            <meta http-equiv="Content-Security-Policy" 
                  content="default-src 'none'; frame-src http://127.0.0.1:40000 http://localhost:40000; script-src 'unsafe-inline'; style-src 'unsafe-inline';">
            <style>
              html, body, iframe { 
                width: 100%; height: 100%; 
                margin: 0; padding: 0; 
                border: none; overflow: hidden;
                scrollbar-width: none;
                -ms-overflow-style: none;
              }
              ::-webkit-scrollbar { display: none; width: 0; height: 0; }
            </style>
          </head>
          <body>
            <iframe src="${targetUrl}"></iframe>
            <script>
              const vscode = acquireVsCodeApi();
              window.addEventListener('message', (event) => {
                if (event.data) {
                  vscode.postMessage(event.data);
                }
              });
            </script>
          </body>
          </html>
        `;
      }
    })
  );
}

function deactivate() {
  if (vexProcess && vexProcess.pid) {
    try {
      process.kill(-vexProcess.pid);
    } catch (e) {
      try {
        vexProcess.kill();
      } catch (err) { }
    }
  }
}

module.exports = { activate, deactivate };