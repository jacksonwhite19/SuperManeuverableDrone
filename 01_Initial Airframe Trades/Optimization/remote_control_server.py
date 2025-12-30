"""
Remote Control Web Server for Optimizer
Run this script to access a web interface for monitoring and controlling the optimizer.
Access at http://localhost:8080 (or your computer's IP address)
"""

import http.server
import socketserver
import json
import os
import urllib.parse
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "optimizer_status.json")
CONTROL_FILE = os.path.join(SCRIPT_DIR, "optimizer_control.txt")
LOG_CSV = os.path.join(SCRIPT_DIR, "opt_history.csv")
OUTPUT_LOG = os.path.join(SCRIPT_DIR, "optimizer_output.log")
PORT = 8080

class OptimizerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests for status and control interface."""
        if self.path == '/' or self.path == '/index.html':
            # Try to serve dashboard first, fallback to control interface
            dashboard_file = os.path.join(SCRIPT_DIR, "dashboard.html")
            if os.path.exists(dashboard_file):
                try:
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    with open(dashboard_file, 'r', encoding='utf-8') as f:
                        self.wfile.write(f.read().encode('utf-8'))
                except Exception as e:
                    # Fallback to control interface if dashboard fails
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(self.get_html_interface().encode())
            else:
                # No dashboard yet, show control interface
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(self.get_html_interface().encode())
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            status = self.get_status()
            self.wfile.write(json.dumps(status).encode())
        elif self.path == '/log':
            # Return the last N lines of the output log
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            log_content = self.get_log_content()
            self.wfile.write(log_content.encode('utf-8'))
        elif self.path == '/control' or self.path == '/control.html':
            # Serve the control interface
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_html_interface().encode())
        elif self.path == '/dashboard.html' or self.path == '/dashboard':
            # Serve the generated dashboard
            dashboard_file = os.path.join(SCRIPT_DIR, "dashboard.html")
            if os.path.exists(dashboard_file):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                with open(dashboard_file, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"Dashboard not found. Run 'python monitor_dashboard.py' first.")
        elif self.path == '/viewer' or self.path == '/viewer.html':
            # Serve the 3D viewer
            viewer_file = "viewer.html"  # Relative path since we chdir to SCRIPT_DIR
            if os.path.exists(viewer_file):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                with open(viewer_file, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                error_msg = f"Viewer not found. Looking for: {os.path.abspath(viewer_file)}"
                self.wfile.write(error_msg.encode())
        elif self.path.startswith('/convert_vsp3'):
            # Convert VSP3 to STL on demand
            import subprocess
            import urllib.parse
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            vsp_file = params.get('file', ['current.vsp3'])[0]
            
            try:
                # Check if STL already exists and is recent
                stl_file = vsp_file.replace('.vsp3', '.stl')
                vsp_path = os.path.join(SCRIPT_DIR, vsp_file)
                stl_path = os.path.join(SCRIPT_DIR, stl_file)
                
                if os.path.exists(stl_path) and os.path.exists(vsp_path):
                    stl_time = os.path.getmtime(stl_path)
                    vsp_time = os.path.getmtime(vsp_path)
                    if stl_time > vsp_time:
                        # STL is newer, no conversion needed
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'success': True, 'message': 'STL already exists'}).encode())
                        return
                
                # Convert using OpenVSP
                VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
                # Use absolute path for STL file to ensure it's created in the right place
                stl_abs_path = os.path.abspath(os.path.join(SCRIPT_DIR, stl_file))
                # Convert Windows backslashes to forward slashes for OpenVSP script (Windows accepts both)
                stl_path_for_script = stl_abs_path.replace('\\', '/')
                vsp_path_for_script = os.path.join(SCRIPT_DIR, vsp_file).replace('\\', '/')
                
                script_content = f'''void main()
{{
    ClearVSPModel();
    ReadVSPFile("{vsp_path_for_script}");
    Update();
    
    // Export to STL using correct API signature
    // ExportFile(file_name, thick_set, file_type, subsFlag, thin_set, useMode, modeID)
    // file_type: EXPORT_STL (or 2) for STL format
    // thick_set: 0 = all thick surfaces
    string stl_file = "{stl_path_for_script}";
    string result = ExportFile(stl_file, 0, EXPORT_STL, 1, -1, false, "");
    Print("ExportFile returned: " + result);
    Print("Exported to: " + stl_file);
}}'''
                script_file = "convert_to_stl.vspscript"
                script_path = os.path.join(SCRIPT_DIR, script_file)
                with open(script_path, 'w') as f:
                    f.write(script_content)
                
                result = subprocess.run(
                    [VSP_EXE, "-script", script_file],
                    capture_output=True,
                    text=True,
                    cwd=SCRIPT_DIR,
                    timeout=60
                )
                
                # Check if STL file was created (check both relative and absolute paths)
                stl_file_rel = stl_file
                stl_file_abs = os.path.abspath(os.path.join(SCRIPT_DIR, stl_file))
                if os.path.exists(stl_file_rel) or os.path.exists(stl_file_abs):
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': True, 'message': 'Conversion successful'}).encode())
                else:
                    # Build detailed error message
                    error_parts = []
                    if result.returncode != 0:
                        error_parts.append(f"OpenVSP returned code {result.returncode}")
                    if result.stderr:
                        error_parts.append(f"STDERR: {result.stderr[-500:]}")
                    if result.stdout:
                        error_parts.append(f"STDOUT: {result.stdout[-500:]}")
                    error_parts.append(f"Expected STL at: {os.path.abspath(stl_file_rel)}")
                    
                    error_msg = " | ".join(error_parts) if error_parts else "STL file not created"
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': False, 'error': error_msg}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
        elif self.path.endswith('.stl'):
            # Serve STL files
            stl_file = self.path.lstrip('/')
            stl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), stl_file)
            if os.path.exists(stl_path):
                self.send_response(200)
                self.send_header('Content-type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'inline; filename="{stl_file}"')
                self.end_headers()
                with open(stl_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"STL file not found")
        elif self.path.startswith('/control?'):
            # Handle control commands: /control?command=stop
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            command = params.get('command', [None])[0]
            
            if command in ['stop', 'pause', 'resume', 'shutdown']:
                try:
                    if command == 'shutdown':
                        # Immediate shutdown (with delay for safety)
                        import subprocess
                        import threading
                        def delayed_shutdown():
                            time.sleep(30)  # 30 second delay
                            subprocess.run(['shutdown', '/s', '/t', '0'])
                        threading.Thread(target=delayed_shutdown, daemon=True).start()
                        response = {'success': True, 'command': command, 'message': 'Shutdown initiated - 30 seconds to cancel'}
                    else:
                        with open(CONTROL_FILE, 'w') as f:
                            f.write(command)
                        response = {'success': True, 'command': command, 'message': f'Command "{command}" sent'}
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {'success': False, 'error': str(e)}
                    self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {'success': False, 'error': 'Invalid command'}
                self.wfile.write(json.dumps(response).encode())
        elif self.path == '/test_viewer':
            # Test endpoint to verify routing
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            viewer_exists = os.path.exists("viewer.html")
            cwd = os.getcwd()
            msg = f"Test endpoint works!\nCWD: {cwd}\nviewer.html exists: {viewer_exists}\nPath requested: {self.path}"
            self.wfile.write(msg.encode())
        else:
            # Fall through to default file serving for static files
            super().do_GET()
    
    def get_log_content(self, max_lines=500):
        """Get the last N lines of the output log."""
        if not os.path.exists(OUTPUT_LOG):
            return "Log file not found. Optimizer may not be running yet.\n"
        
        try:
            with open(OUTPUT_LOG, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                # Return last max_lines
                return ''.join(lines[-max_lines:])
        except Exception as e:
            return f"Error reading log file: {e}\n"
    
    def get_status(self):
        """Read and return current optimizer status."""
        status = {
            'status': 'unknown',
            'paused': False,
            'iteration': 0,
            'generation': 0,
            'elapsed_minutes': 0,
            'best_objective': None,
            'timestamp': None,
            'error': None
        }
        
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, 'r') as f:
                    status.update(json.load(f))
            except Exception as e:
                status['error'] = f'Error reading status: {e}'
        else:
            status['error'] = 'Status file not found - optimizer may not be running'
        
        # Get latest iteration info from CSV if available
        if os.path.exists(LOG_CSV):
            try:
                with open(LOG_CSV, 'r') as f:
                    lines = f.readlines()
                    if len(lines) > 1:  # Has header + at least one data row
                        last_line = lines[-1].strip().split(',')
                        if len(last_line) > 0:
                            status['latest_iteration'] = int(last_line[0]) if last_line[0].isdigit() else None
            except:
                pass
        
        return status
    
    def get_html_interface(self):
        """Generate HTML interface for remote control."""
        status = self.get_status()
        
        # Format elapsed time
        elapsed_str = f"{status.get('elapsed_minutes', 0):.1f} min"
        if status.get('elapsed_minutes', 0) > 60:
            hours = int(status['elapsed_minutes'] // 60)
            mins = int(status['elapsed_minutes'] % 60)
            elapsed_str = f"{hours}h {mins}m"
        
        # Status color
        status_color = {
            'running': '#28a745',
            'stopped': '#dc3545',
            'paused': '#ffc107',
            'unknown': '#6c757d'
        }.get(status.get('status', 'unknown'), '#6c757d')
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Optimizer Remote Control</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 10px;
        }}
        .status-card {{
            background: #f8f9fa;
            border-left: 4px solid {status_color};
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .status-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        .status-item:last-child {{
            border-bottom: none;
        }}
        .status-label {{
            font-weight: 600;
            color: #555;
        }}
        .status-value {{
            color: #333;
        }}
        .controls {{
            margin: 30px 0;
        }}
        .btn {{
            padding: 12px 24px;
            margin: 5px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
        }}
        .btn-stop {{
            background: #dc3545;
            color: white;
        }}
        .btn-stop:hover {{
            background: #c82333;
        }}
        .btn-pause {{
            background: #ffc107;
            color: #333;
        }}
        .btn-pause:hover {{
            background: #e0a800;
        }}
        .btn-resume {{
            background: #28a745;
            color: white;
        }}
        .btn-resume:hover {{
            background: #218838;
        }}
        .btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .message {{
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            display: none;
        }}
        .message.success {{
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }}
        .message.error {{
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }}
        .auto-refresh {{
            margin: 20px 0;
            padding: 10px;
            background: #e7f3ff;
            border-radius: 4px;
        }}
        .timestamp {{
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }}
        .log-viewer {{
            margin: 30px 0;
        }}
        .log-viewer h2 {{
            margin-bottom: 10px;
        }}
        .log-container {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 4px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        .log-container::-webkit-scrollbar {{
            width: 10px;
        }}
        .log-container::-webkit-scrollbar-track {{
            background: #2d2d2d;
        }}
        .log-container::-webkit-scrollbar-thumb {{
            background: #555;
            border-radius: 5px;
        }}
        .log-controls {{
            margin-bottom: 10px;
        }}
        .btn-refresh {{
            background: #007bff;
            color: white;
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}
        .btn-refresh:hover {{
            background: #0056b3;
        }}
    </style>
    <script>
        function sendCommand(command) {{
            fetch(`/control?command=${{command}}`)
                .then(response => response.json())
                .then(data => {{
                    const msgDiv = document.getElementById('message');
                    msgDiv.style.display = 'block';
                    if (data.success) {{
                        msgDiv.className = 'message success';
                        msgDiv.textContent = data.message || `Command "${{command}}" sent successfully`;
                    }} else {{
                        msgDiv.className = 'message error';
                        msgDiv.textContent = data.error || 'Error sending command';
                    }}
                    setTimeout(() => {{
                        msgDiv.style.display = 'none';
                    }}, 3000);
                    // Refresh status after command
                    setTimeout(updateStatus, 1000);
                }})
                .catch(error => {{
                    const msgDiv = document.getElementById('message');
                    msgDiv.style.display = 'block';
                    msgDiv.className = 'message error';
                    msgDiv.textContent = 'Error: ' + error;
                }});
        }}
        
        function updateStatus() {{
            fetch('/status')
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('status').textContent = data.status || 'unknown';
                    document.getElementById('iteration').textContent = data.iteration || 0;
                    document.getElementById('generation').textContent = data.generation || 0;
                    document.getElementById('elapsed').textContent = data.elapsed_minutes ? 
                        (data.elapsed_minutes > 60 ? 
                            `${{Math.floor(data.elapsed_minutes/60)}}h ${{Math.floor(data.elapsed_minutes%60)}}m` :
                            `${{data.elapsed_minutes.toFixed(1)}} min`) : '0 min';
                    document.getElementById('best_obj').textContent = data.best_objective ? 
                        data.best_objective.toFixed(4) : 'N/A';
                    document.getElementById('timestamp').textContent = data.timestamp || 'N/A';
                    
                    // Update button states
                    const pauseBtn = document.getElementById('btn-pause');
                    const resumeBtn = document.getElementById('btn-resume');
                    if (data.paused) {{
                        pauseBtn.disabled = true;
                        resumeBtn.disabled = false;
                    }} else {{
                        pauseBtn.disabled = false;
                        resumeBtn.disabled = true;
                    }}
                }})
                .catch(error => {{
                    console.error('Error updating status:', error);
                }});
        }}
        
        function updateLog() {{
            fetch('/log')
                .then(response => response.text())
                .then(data => {{
                    const logDiv = document.getElementById('log-content');
                    logDiv.textContent = data;
                    // Auto-scroll to bottom
                    logDiv.scrollTop = logDiv.scrollHeight;
                }})
                .catch(error => {{
                    console.error('Error updating log:', error);
                    document.getElementById('log-content').textContent = 'Error loading log: ' + error;
                }});
        }}
        
        // Auto-refresh every 5 seconds
        setInterval(updateStatus, 5000);
        setInterval(updateLog, 5000);  // Also update log every 5 seconds
        
        // Initial load
        window.onload = function() {{
            updateStatus();
            updateLog();
        }};
    </script>
</head>
<body>
    <div class="container">
        <h1>🚁 Optimizer Remote Control</h1>
        
        <div class="auto-refresh">
            <strong>Auto-refreshing every 5 seconds</strong> | Last update: <span id="timestamp">{status.get('timestamp', 'N/A')}</span>
        </div>
        
        <div id="message" class="message"></div>
        
        <div class="status-card">
            <h2>Status</h2>
            <div class="status-item">
                <span class="status-label">Status:</span>
                <span class="status-value" id="status">{status.get('status', 'unknown')}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Iteration:</span>
                <span class="status-value" id="iteration">{status.get('iteration', 0)}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Generation:</span>
                <span class="status-value" id="generation">{status.get('generation', 0)}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Elapsed Time:</span>
                <span class="status-value" id="elapsed">{elapsed_str}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Best Objective:</span>
                <span class="status-value" id="best_obj">{status.get('best_objective', 'N/A')}</span>
            </div>
            {f'<div class="status-item"><span class="status-label">Error:</span><span class="status-value" style="color: red;">{status.get("error", "")}</span></div>' if status.get('error') else ''}
        </div>
        
        <div class="controls">
            <h2>Control</h2>
            <button class="btn btn-pause" id="btn-pause" onclick="sendCommand('pause')" {'disabled' if status.get('paused') else ''}>
                ⏸ Pause
            </button>
            <button class="btn btn-resume" id="btn-resume" onclick="sendCommand('resume')" {'disabled' if not status.get('paused') else ''}>
                ▶ Resume
            </button>
            <button class="btn btn-stop" onclick="sendCommand('stop')">
                ⏹ Stop
            </button>
            <button class="btn btn-stop" onclick="if(confirm('Shutdown computer in 30 seconds? Press OK to confirm.')) sendCommand('shutdown')" style="margin-left: 10px;">
                🔌 Shutdown PC
            </button>
        </div>
        
        <div class="log-viewer">
            <h2>📋 Output Log</h2>
            <div class="log-controls">
                <button class="btn-refresh" onclick="updateLog()">🔄 Refresh Log</button>
                <span style="margin-left: 10px; color: #666; font-size: 0.9em;">Auto-updates every 5 seconds</span>
            </div>
            <div class="log-container" id="log-content">
                Loading log...
            </div>
        </div>
        
        <div class="timestamp">
            <p><strong>Note:</strong> Commands are sent via file system. The optimizer checks for commands between iterations.</p>
            <p>To access remotely, use your computer's IP address: <code>http://[YOUR_IP]:{PORT}</code></p>
        </div>
    </div>
</body>
</html>"""
        return html

if __name__ == "__main__":
    import socket
    
    # Get local IP address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except:
        local_ip = 'localhost'
    finally:
        s.close()
    
    # Change to script directory to ensure file paths work
    os.chdir(SCRIPT_DIR)
    
    print("="*80)
    print("Optimizer Remote Control Server")
    print("="*80)
    print(f"\nServer starting on port {PORT}...")
    print(f"Working directory: {os.getcwd()}")
    print(f"\nAccess the web interface at:")
    print(f"  Local:  http://localhost:{PORT}")
    print(f"  Remote: http://{local_ip}:{PORT}")
    print(f"  Viewer: http://localhost:{PORT}/viewer")
    print(f"\nPress Ctrl+C to stop the server")
    print("="*80)
    
    try:
        with socketserver.TCPServer(("", PORT), OptimizerHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"\nError: Port {PORT} is already in use.")
            print("Either stop the other service or change PORT in this script.")
        else:
            raise

