using System;
using System.IO;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using HSDRaw.Common;
using HSDRawViewer.GUI;
using HSDRawViewer.Rendering;
using HSDRawViewer.Rendering.Models;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Formats.Jpeg;
using HSDRawViewer.Converters.Animation;
using HSDRawViewer.Tools;
using HSDRawViewer.GUI.Controls.JObjEditor;

namespace HSDRawViewer
{
    /// <summary>
    /// WebSocket streaming server for 3D model viewing
    /// Handles headless rendering and frame streaming to web clients
    /// </summary>
    public class StreamingServer : IDisposable
    {
        private HttpListener _httpListener;
        private ViewportControl _viewport;
        private RenderJObj _renderJObj;
        private Form _hostForm;
        private CancellationTokenSource _cts;
        private int _port;
        private int _frameWidth = 720;
        private int _frameHeight = 480;
        private int _targetFps = 30;
        private bool _isRunning = false;
        private WebSocket _currentClient = null;
        private StreamWriter _logWriter;
        private string _logPath;

        public StreamingServer(int port, string logPath = null)
        {
            _port = port;
            _cts = new CancellationTokenSource();
            _logPath = logPath;
            InitializeLogging();
        }

        private void InitializeLogging()
        {
            try
            {
                if (string.IsNullOrEmpty(_logPath))
                {
                    // Default to a logs folder relative to the executable
                    var exeDir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
                    _logPath = Path.Combine(exeDir, "..", "..", "..", "..", "..", "..", "..", "logs");
                }

                // Create logs directory if it doesn't exist
                Directory.CreateDirectory(_logPath);

                var logFile = Path.Combine(_logPath, $"viewer_{DateTime.Now:yyyy-MM-dd_HH-mm-ss}.log");
                _logWriter = new StreamWriter(logFile, append: true) { AutoFlush = true };
                Log($"=== HSDRawViewer Streaming Server Started ===");
                Log($"Log file: {logFile}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to initialize logging: {ex.Message}");
                // Continue without file logging
            }
        }

        private void Log(string message)
        {
            var timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            var logLine = $"[{timestamp}] {message}";
            Console.WriteLine(logLine);
            try
            {
                _logWriter?.WriteLine(logLine);
            }
            catch { /* Ignore logging errors */ }
        }

        private void LogError(string message, Exception ex = null)
        {
            var timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            var logLine = $"[{timestamp}] ERROR: {message}";
            if (ex != null)
            {
                logLine += $"\n  Exception: {ex.GetType().Name}: {ex.Message}\n  Stack: {ex.StackTrace}";
            }
            Console.WriteLine(logLine);
            try
            {
                _logWriter?.WriteLine(logLine);
            }
            catch { /* Ignore logging errors */ }
        }

        public async Task StartAsync(string datFilePath, string sceneFilePath = null)
        {
            Log($"Starting streaming server on port {_port}...");
            Log($"Loading DAT file: {datFilePath}");
            if (!string.IsNullOrEmpty(sceneFilePath))
                Log($"Scene file: {sceneFilePath}");

            // Initialize core systems
            Thread.CurrentThread.CurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
            PluginManager.Init();
            ApplicationSettings.Init();

            // Load DAT file
            if (!File.Exists(datFilePath))
            {
                LogError($"DAT file not found: {datFilePath}");
                throw new FileNotFoundException($"DAT file not found: {datFilePath}");
            }

            // Use MainForm like CSP mode does - this properly loads all model data
            Log("Initializing MainForm...");
            MainForm.Init();
            MainForm.Instance.OpenFile(datFilePath);

            // Wait for file to load
            Log("Waiting for file to load...");
            Thread.Sleep(500);

            // Load the DAT file to find JOBJ nodes
            Log("Opening DAT file...");
            var rawFile = new HSDRaw.HSDRawFile();
            rawFile.Open(datFilePath);
            Log($"DAT file opened. Root count: {rawFile.Roots.Count}");

            // Find character JOBJ
            DataNode characterJobjNode = null;
            foreach (var root in rawFile.Roots)
            {
                Log($"  Root: {root.Name} -> {root.Data?.GetType().Name ?? "null"}");
                if (root.Data is HSD_JOBJ &&
                    (root.Name.Contains("Share_joint") || root.Name.Contains("_joint") || root.Name.Contains("Ply")))
                {
                    Log($"Found character JOBJ: {root.Name}");
                    characterJobjNode = new DataNode(root.Name, root.Data, root: root);
                    break;
                }
            }

            if (characterJobjNode == null)
            {
                // Fallback to first JOBJ
                foreach (var root in rawFile.Roots)
                {
                    if (root.Data is HSD_JOBJ)
                    {
                        Log($"Using fallback JOBJ: {root.Name}");
                        characterJobjNode = new DataNode(root.Name, root.Data, root: root);
                        break;
                    }
                }
            }

            if (characterJobjNode == null)
            {
                LogError("No JOBJ found in DAT file");
                throw new Exception("No JOBJ found in DAT file");
            }

            // Select the node and open editor like CSP mode does
            Log($"Selecting character JOBJ: {characterJobjNode.Text}");
            MainForm.SelectedDataNode = characterJobjNode;
            MainForm.Instance.OpenEditor();

            // Wait for editor to open
            Thread.Sleep(1000);

            // Create viewport and render object
            Log("Creating ViewportControl...");
            _viewport = new ViewportControl();

            if (characterJobjNode.Accessor is HSD_JOBJ jobj)
            {
                Log("Creating RenderJObj...");
                _renderJObj = new RenderJObj(jobj);
                _renderJObj._settings.RenderBones = false;
                _renderJObj._settings.RenderObjects = ObjectRenderMode.Visible;

                var drawable = new SimpleJObjDrawable(_renderJObj);
                _viewport.AddRenderer(drawable);
                Log($"RenderJObj created. DOBJs: {_renderJObj.DObjCount}");
            }

            // Create host form - try VISIBLE to test if minimized breaks OpenGL
            Log("Creating host form...");
            _hostForm = new Form();
            _hostForm.Size = new System.Drawing.Size(_frameWidth + 50, _frameHeight + 50);
            _hostForm.Text = "HSD Viewer (Streaming)";
            // Don't minimize - keep visible to ensure OpenGL works
            _viewport.Dock = DockStyle.Fill;
            _hostForm.Controls.Add(_viewport);
            _hostForm.Show();

            // Pump messages to let OpenGL initialize properly
            Log("Waiting for OpenGL initialization...");
            for (int i = 0; i < 100; i++)  // Pump messages for ~1s
            {
                Application.DoEvents();
                Thread.Sleep(10);
            }

            // Set up viewport
            Log("Setting up viewport...");
            _viewport.EnableBack = true;
            _viewport.DisplayGrid = false;  // Hide grid for cleaner CSP-style view

            // Load scene settings if provided
            SceneSettings sceneSettings = null;
            if (!string.IsNullOrEmpty(sceneFilePath) && File.Exists(sceneFilePath))
            {
                try
                {
                    Log($"Loading scene settings from: {sceneFilePath}");
                    sceneSettings = SceneSettings.Deserialize(sceneFilePath);

                    // Apply camera settings
                    if (sceneSettings.Camera != null)
                    {
                        Log($"Applying camera: X={sceneSettings.Camera.X}, Y={sceneSettings.Camera.Y}, Scale={sceneSettings.Camera.Scale}");
                        _viewport.Camera.X = sceneSettings.Camera.X;
                        _viewport.Camera.Y = sceneSettings.Camera.Y;
                        _viewport.Camera.Z = sceneSettings.Camera.Z;
                        _viewport.Camera.Scale = sceneSettings.Camera.Scale;
                        _viewport.Camera.FovRadians = sceneSettings.Camera.FovRadians;
                        _viewport.Camera.RotationXRadians = sceneSettings.Camera.RotationXRadians;
                        _viewport.Camera.RotationYRadians = sceneSettings.Camera.RotationYRadians;
                        _viewport.Camera.FarClipPlane = sceneSettings.Camera.FarClipPlane;
                        _viewport.Camera.NearClipPlane = sceneSettings.Camera.NearClipPlane;
                    }

                    // Load animation
                    if (sceneSettings.Animation != null && _renderJObj != null)
                    {
                        Log($"Loading animation (FrameCount: {sceneSettings.Animation.FrameCount})");
                        _renderJObj.LoadAnimation(sceneSettings.Animation, null, null);

                        // Set to the specified frame
                        if (sceneSettings.Frame >= 0)
                        {
                            Log($"Setting animation frame: {sceneSettings.Frame}");
                            _renderJObj.RequestAnimationUpdate(FrameFlags.All, sceneSettings.Frame);
                        }
                    }

                    // Apply other scene settings
                    _viewport.DisplayGrid = sceneSettings.ShowGrid;
                    _viewport.EnableBack = sceneSettings.ShowBackdrop;

                    Log("Scene settings applied successfully");
                }
                catch (Exception ex)
                {
                    LogError("Failed to load scene settings", ex);
                }
            }

            Log($"Current camera: Scale={_viewport.Camera.Scale}");

            // Force a render
            Log("Performing initial render...");
            Application.DoEvents();
            _viewport.Render();
            Application.DoEvents();

            // Check DOBJs again after render (they may be loaded lazily)
            if (_renderJObj != null)
            {
                Log($"After first render - DOBJs: {_renderJObj.DObjCount}");

                // Apply hidden nodes now that DOBJs are loaded
                if (sceneSettings?.HiddenNodes != null && sceneSettings.HiddenNodes.Length > 0)
                {
                    Log($"Hiding {sceneSettings.HiddenNodes.Length} DOBJs...");
                    int hiddenCount = 0;
                    foreach (int dobjIndex in sceneSettings.HiddenNodes)
                    {
                        if (dobjIndex >= 0 && dobjIndex < _renderJObj.DObjCount)
                        {
                            _renderJObj.SetDObjVisible(dobjIndex, false);
                            hiddenCount++;
                        }
                    }
                    Log($"Successfully hid {hiddenCount} DOBJs");

                    // Re-render to apply visibility changes
                    Application.DoEvents();
                    _viewport.Render();
                    Application.DoEvents();
                }
            }

            // Log viewport/control sizes for debugging
            Log($"Host form size: {_hostForm.Width}x{_hostForm.Height}");
            Log($"Viewport size: {_viewport.Width}x{_viewport.Height}");

            // Force the form to process layout
            _hostForm.PerformLayout();
            Application.DoEvents();

            Log($"After layout - Host form size: {_hostForm.Width}x{_hostForm.Height}");
            Log($"After layout - Viewport size: {_viewport.Width}x{_viewport.Height}");

            // Save a debug frame to check what's being rendered
            try
            {
                using var debugBitmap = _viewport.GenerateBitmap(_frameWidth, _frameHeight);
                var debugPath = Path.Combine(_logPath, "debug_frame.png");
                debugBitmap.SaveAsPng(debugPath);
                Log($"Debug frame saved to: {debugPath}");
            }
            catch (Exception ex)
            {
                LogError("Failed to save debug frame", ex);
            }

            Log($"Viewport ready. Starting HTTP listener...");

            // Start HTTP/WebSocket listener
            _httpListener = new HttpListener();
            _httpListener.Prefixes.Add($"http://localhost:{_port}/");
            _httpListener.Start();

            _isRunning = true;
            Log($"Streaming server listening on ws://localhost:{_port}/");
            Log("Waiting for client connection...");

            // Start connection handler in background
            _ = Task.Run(() => AcceptConnectionsAsync());

            // Run message pump on main thread to keep UI responsive
            Log("Starting message pump...");
            while (_isRunning && !_cts.Token.IsCancellationRequested)
            {
                Application.DoEvents();
                Thread.Sleep(16);  // ~60fps message pump
            }
        }

        private async Task AcceptConnectionsAsync()
        {
            while (_isRunning && !_cts.Token.IsCancellationRequested)
            {
                try
                {
                    var context = await _httpListener.GetContextAsync();
                    Log($"Incoming request: {context.Request.HttpMethod} {context.Request.Url} IsWebSocket: {context.Request.IsWebSocketRequest}");

                    // Add CORS headers for all responses
                    context.Response.Headers.Add("Access-Control-Allow-Origin", "*");
                    context.Response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
                    context.Response.Headers.Add("Access-Control-Allow-Headers", "*");

                    if (context.Request.IsWebSocketRequest)
                    {
                        Log("Accepting WebSocket connection...");
                        var wsContext = await context.AcceptWebSocketAsync(null);
                        Log("Client connected!");
                        await HandleClientAsync(wsContext.WebSocket);
                    }
                    else
                    {
                        // Handle regular HTTP request (health check)
                        context.Response.StatusCode = 200;
                        context.Response.ContentType = "text/plain";
                        var buffer = Encoding.UTF8.GetBytes("Streaming server running");
                        context.Response.ContentLength64 = buffer.Length;
                        await context.Response.OutputStream.WriteAsync(buffer, 0, buffer.Length);
                        context.Response.Close();
                    }
                }
                catch (Exception ex) when (!_cts.Token.IsCancellationRequested)
                {
                    LogError("Connection error", ex);
                }
            }
        }

        private async Task HandleClientAsync(WebSocket webSocket)
        {
            _currentClient = webSocket;
            var receiveBuffer = new byte[4096];
            var frameInterval = TimeSpan.FromMilliseconds(1000.0 / _targetFps);
            var lastFrameTime = DateTime.UtcNow;
            int frameCount = 0;
            var startTime = DateTime.UtcNow;

            try
            {
                // Send initial info with camera state
                var info = new
                {
                    type = "info",
                    width = _frameWidth,
                    height = _frameHeight,
                    fps = _targetFps,
                    dobjCount = _renderJObj?.DObjCount ?? 0,
                    camera = new
                    {
                        rotX = _viewport.Camera.RotationXRadians * 180.0 / Math.PI,
                        rotY = _viewport.Camera.RotationYRadians * 180.0 / Math.PI,
                        scale = _viewport.Camera.Scale,
                        x = _viewport.Camera.X,
                        y = _viewport.Camera.Y,
                        z = _viewport.Camera.Z
                    }
                };
                await SendJsonAsync(webSocket, info);
                Log($"Sent initial info: {_frameWidth}x{_frameHeight} @ {_targetFps}fps, camera scale={_viewport.Camera.Scale}");

                // Create receive task
                var receiveTask = ReceiveMessagesAsync(webSocket, receiveBuffer);

                // Frame streaming loop
                while (webSocket.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
                {
                    var now = DateTime.UtcNow;
                    var elapsed = now - lastFrameTime;

                    if (elapsed >= frameInterval)
                    {
                        lastFrameTime = now;

                        // Render and send frame on UI thread (OpenGL context is thread-bound)
                        try
                        {
                            Image<Rgba32> bitmap = null;

                            // Must render on the UI thread where OpenGL context was created
                            _hostForm.Invoke((Action)(() =>
                            {
                                Application.DoEvents();
                                bitmap = _viewport.GenerateBitmap(_frameWidth, _frameHeight);
                            }));

                            if (bitmap == null) continue;

                            byte[] frameData;
                            using (bitmap)
                            using (var ms = new MemoryStream())
                            {
                                // Encode as JPEG
                                var encoder = new JpegEncoder { Quality = 75 };
                                bitmap.Save(ms, encoder);
                                frameData = ms.ToArray();
                            }

                            await webSocket.SendAsync(
                                new ArraySegment<byte>(frameData),
                                WebSocketMessageType.Binary,
                                true,
                                _cts.Token
                            );

                            frameCount++;

                            // Log stats every 100 frames
                            if (frameCount % 100 == 0)
                            {
                                var totalElapsed = (DateTime.UtcNow - startTime).TotalSeconds;
                                var avgFps = frameCount / totalElapsed;
                                Log($"Streaming: {frameCount} frames, avg {avgFps:F1} fps, last frame {frameData.Length / 1024.0:F1} KB");
                            }
                        }
                        catch (Exception ex)
                        {
                            LogError("Frame render error", ex);
                        }
                    }

                    // Small delay to prevent busy-waiting
                    await Task.Delay(5);
                }
            }
            catch (WebSocketException ex)
            {
                LogError("WebSocket error", ex);
            }
            finally
            {
                _currentClient = null;
                var totalElapsed = (DateTime.UtcNow - startTime).TotalSeconds;
                Log($"Client disconnected. Streamed {frameCount} frames in {totalElapsed:F1}s ({frameCount / totalElapsed:F1} fps avg)");

                if (webSocket.State == WebSocketState.Open)
                {
                    await webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Closing", CancellationToken.None);
                }
            }
        }

        private async Task ReceiveMessagesAsync(WebSocket webSocket, byte[] buffer)
        {
            try
            {
                while (webSocket.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
                {
                    var result = await webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), _cts.Token);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        Log("Received close message from client");
                        break;
                    }

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        var message = Encoding.UTF8.GetString(buffer, 0, result.Count);
                        ProcessCommand(message);
                    }
                }
            }
            catch (Exception ex)
            {
                LogError("Receive error", ex);
            }
        }

        private void ProcessCommand(string json)
        {
            try
            {
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;

                if (!root.TryGetProperty("type", out var typeElement))
                    return;

                var type = typeElement.GetString();

                switch (type)
                {
                    case "camera":
                        // Delta-based rotation (in degrees)
                        if (root.TryGetProperty("deltaRotX", out var deltaRotX))
                            _viewport.Camera.RotationXRadians += (float)(deltaRotX.GetDouble() * Math.PI / 180.0);
                        if (root.TryGetProperty("deltaRotY", out var deltaRotY))
                            _viewport.Camera.RotationYRadians += (float)(deltaRotY.GetDouble() * Math.PI / 180.0);

                        // Delta-based zoom (additive to scale)
                        if (root.TryGetProperty("deltaZoom", out var deltaZoom))
                        {
                            _viewport.Camera.Scale *= (float)(1.0 + deltaZoom.GetDouble());
                            _viewport.Camera.Scale = Math.Max(0.1f, Math.Min(1000f, _viewport.Camera.Scale));
                        }

                        // Delta-based pan
                        if (root.TryGetProperty("deltaX", out var deltaX))
                            _viewport.Camera.X += (float)deltaX.GetDouble();
                        if (root.TryGetProperty("deltaY", out var deltaY))
                            _viewport.Camera.Y += (float)deltaY.GetDouble();
                        break;

                    case "resize":
                        if (root.TryGetProperty("width", out var w))
                            _frameWidth = Math.Clamp(w.GetInt32(), 320, 1920);
                        if (root.TryGetProperty("height", out var h))
                            _frameHeight = Math.Clamp(h.GetInt32(), 240, 1080);
                        Log($"Resized to {_frameWidth}x{_frameHeight}");
                        break;

                    case "fps":
                        if (root.TryGetProperty("value", out var fps))
                        {
                            _targetFps = Math.Clamp(fps.GetInt32(), 1, 60);
                            Log($"FPS changed to {_targetFps}");
                        }
                        break;

                    default:
                        Log($"Unknown command type: {type}");
                        break;
                }
            }
            catch (Exception ex)
            {
                LogError("Command parse error", ex);
            }
        }

        private async Task SendJsonAsync(WebSocket webSocket, object data)
        {
            var json = JsonSerializer.Serialize(data);
            var bytes = Encoding.UTF8.GetBytes(json);
            await webSocket.SendAsync(
                new ArraySegment<byte>(bytes),
                WebSocketMessageType.Text,
                true,
                _cts.Token
            );
        }

        public void Stop()
        {
            Log("Stopping streaming server...");
            _isRunning = false;
            _cts.Cancel();

            _currentClient?.CloseAsync(WebSocketCloseStatus.NormalClosure, "Server shutdown", CancellationToken.None).Wait(1000);
            _httpListener?.Stop();
            _hostForm?.Close();
            Log("Streaming server stopped");
        }

        public void Dispose()
        {
            Stop();
            _cts?.Dispose();
            _httpListener?.Close();
            _hostForm?.Dispose();
            _viewport?.Dispose();

            Log("=== HSDRawViewer Streaming Server Disposed ===");
            _logWriter?.Dispose();
        }
    }
}
