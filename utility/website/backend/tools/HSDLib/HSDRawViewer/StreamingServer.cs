using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.Tools.Melee;
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
        private int _frameWidth = 1280;
        private int _frameHeight = 960;
        private int _targetFps = 60;
        private bool _isRunning = false;
        private WebSocket _currentClient = null;
        private StreamWriter _logWriter;
        private string _logPath;

        // Animation state
        private bool _animationPlaying = false;
        private float _animationFrame = 0;
        private float _animationFrameCount = 0;
        private float _animationSpeed = 1.0f;

        // Animation archive manager (for loading real Melee animations)
        private FighterAJManager _ajManager;

        // Cached texture list (populated after first render to avoid Invoke deadlocks)
        private List<TextureInfo> _cachedTextureList = null;

        // Lock to serialize WebSocket sends (prevent concurrent sends from corrupting connection)
        private SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);

        // Store the raw file and path for exporting modified DAT
        private HSDRaw.HSDRawFile _rawFile = null;
        private string _datFilePath = null;

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
            // Don't use Console.WriteLine - blocks when stdout buffer fills (backend doesn't read it)
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
            // Don't use Console.WriteLine - blocks when stdout buffer fills
            try
            {
                _logWriter?.WriteLine(logLine);
            }
            catch { /* Ignore logging errors */ }
        }

        public async Task StartAsync(string datFilePath, string sceneFilePath = null, string ajFilePath = null)
        {
            Log($"Starting streaming server on port {_port}...");
            Log($"Loading DAT file: {datFilePath}");
            if (!string.IsNullOrEmpty(sceneFilePath))
                Log($"Scene file: {sceneFilePath}");
            if (!string.IsNullOrEmpty(ajFilePath))
                Log($"AJ file: {ajFilePath}");

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
            _rawFile = new HSDRaw.HSDRawFile();
            _rawFile.Open(datFilePath);
            _datFilePath = datFilePath;
            var rawFile = _rawFile; // Keep local var for rest of method
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
                        _animationFrameCount = sceneSettings.Animation.FrameCount;

                        // Set to the specified frame
                        _animationFrame = Math.Max(0, sceneSettings.Frame);
                        Log($"Setting animation frame: {_animationFrame}");
                        _renderJObj.RequestAnimationUpdate(FrameFlags.All, _animationFrame);
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

                // Cache texture list after initial render
                _cachedTextureList = _renderJObj.GetTextureList();
                Log($"Cached {_cachedTextureList.Count} textures");
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

            // Load animation archive if provided
            if (!string.IsNullOrEmpty(ajFilePath) && File.Exists(ajFilePath))
            {
                try
                {
                    Log($"Loading AJ file: {ajFilePath}");
                    _ajManager = new FighterAJManager(File.ReadAllBytes(ajFilePath));
                    var animCount = _ajManager.GetAnimationSymbols().Count();
                    Log($"Loaded {animCount} animations from AJ file");
                }
                catch (Exception ex)
                {
                    LogError("Failed to load AJ file", ex);
                }
            }

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
            var receiveBuffer = new byte[65536]; // 64KB for texture data
            var frameInterval = TimeSpan.FromMilliseconds(1000.0 / _targetFps);
            var lastFrameTime = DateTime.UtcNow;
            int frameCount = 0;
            var startTime = DateTime.UtcNow;

            try
            {
                // Send initial info with camera state and animation info
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
                    },
                    animation = new
                    {
                        frameCount = _animationFrameCount,
                        currentFrame = _animationFrame,
                        playing = _animationPlaying,
                        speed = _animationSpeed
                    }
                };
                await SendJsonAsync(webSocket, info);
                Log($"Sent initial info: {_frameWidth}x{_frameHeight} @ {_targetFps}fps, animation frames={_animationFrameCount}");

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

                                // Update animation if playing
                                if (_animationPlaying && _animationFrameCount > 0 && _renderJObj != null)
                                {
                                    _animationFrame += _animationSpeed;
                                    if (_animationFrame >= _animationFrameCount)
                                        _animationFrame = 0;
                                    else if (_animationFrame < 0)
                                        _animationFrame = _animationFrameCount - 1;

                                    _renderJObj.RequestAnimationUpdate(FrameFlags.All, _animationFrame);
                                }

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

                            await SendBinaryAsync(webSocket, frameData);

                            frameCount++;

                            // Log every 100 frames to debug file
                            if (frameCount % 100 == 0)
                            {
                                var totalElapsed = (DateTime.UtcNow - startTime).TotalSeconds;
                                File.AppendAllText(@"C:\Users\david\projects\new aka\logs\FRAME_DEBUG.txt",
                                    $"{DateTime.Now:HH:mm:ss.fff} Frame {frameCount}, {frameCount / totalElapsed:F1} fps\n");
                            }
                        }
                        catch (Exception ex)
                        {
                            File.AppendAllText(@"C:\Users\david\projects\new aka\logs\FRAME_DEBUG.txt",
                                $"{DateTime.Now:HH:mm:ss.fff} FRAME ERROR: {ex.Message}\n");
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
            var dbg = @"C:\Users\david\projects\new aka\logs\RECEIVE_DEBUG.txt";
            try
            {
                while (webSocket.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
                {
                    var result = await webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), _cts.Token);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} CLOSE message received\n");
                        Log("Received close message from client");
                        break;
                    }

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        var message = Encoding.UTF8.GetString(buffer, 0, result.Count);
                        // Log message type (not full message to avoid spam)
                        string msgType = "unknown";
                        try {
                            using var doc = JsonDocument.Parse(message);
                            msgType = doc.RootElement.GetProperty("type").GetString();
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} MSG: {msgType}\n");
                        } catch { }
                        await ProcessCommandAsync(webSocket, message);
                        // Log after processing to see if we're stuck
                        if (msgType == "exportDat")
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} exportDat PROCESSED, wsState={webSocket.State}\n");
                    }
                }
                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} LOOP EXIT: wsState={webSocket.State}\n");
            }
            catch (Exception ex)
            {
                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} EXCEPTION: {ex.Message}\n");
                LogError("Receive error", ex);
            }
        }

        private async Task ProcessCommandAsync(WebSocket webSocket, string json)
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

                    case "animPlay":
                        _animationPlaying = true;
                        Log("Animation playing");
                        break;

                    case "animPause":
                        _animationPlaying = false;
                        Log("Animation paused");
                        break;

                    case "animToggle":
                        _animationPlaying = !_animationPlaying;
                        Log($"Animation {(_animationPlaying ? "playing" : "paused")}");
                        break;

                    case "animSetFrame":
                        if (root.TryGetProperty("frame", out var frameVal))
                        {
                            _animationFrame = (float)frameVal.GetDouble();
                            _animationFrame = Math.Clamp(_animationFrame, 0, Math.Max(0, _animationFrameCount - 1));
                            if (_renderJObj != null)
                                _renderJObj.RequestAnimationUpdate(FrameFlags.All, _animationFrame);
                        }
                        break;

                    case "animSetSpeed":
                        if (root.TryGetProperty("speed", out var speedVal))
                        {
                            _animationSpeed = (float)speedVal.GetDouble();
                            Log($"Animation speed: {_animationSpeed}");
                        }
                        break;

                    case "getAnimList":
                        // Return list of available animations from AJ file
                        Log($"Processing getAnimList, _ajManager is {(_ajManager != null ? "set" : "null")}");
                        try
                        {
                            if (_ajManager != null)
                            {
                                var symbols = _ajManager.GetAnimationSymbols().ToArray();
                                Log($"Sending animation list: {symbols.Length} animations");
                                await SendJsonAsync(webSocket, new { type = "animList", symbols });
                            }
                            else
                            {
                                Log("No AJ file loaded, sending empty animation list");
                                await SendJsonAsync(webSocket, new { type = "animList", symbols = Array.Empty<string>() });
                            }
                        }
                        catch (Exception ex)
                        {
                            LogError("Error in getAnimList", ex);
                            await SendJsonAsync(webSocket, new { type = "animList", symbols = Array.Empty<string>() });
                        }
                        break;

                    case "getTextures":
                        // Return cached texture list (thumbnails for sidebar)
                        try
                        {
                            if (_cachedTextureList != null)
                            {
                                var textureList = _cachedTextureList.Select(t => new
                                {
                                    index = t.Index,
                                    width = t.Width,
                                    height = t.Height,
                                    name = t.Name,
                                    thumbnail = t.ThumbnailBase64
                                }).ToList();
                                await SendJsonAsync(webSocket, new { type = "textureList", textures = textureList });
                            }
                            else
                            {
                                await SendJsonAsync(webSocket, new { type = "textureList", textures = Array.Empty<object>() });
                            }
                        }
                        catch (Exception ex)
                        {
                            LogError("Error in getTextures", ex);
                            await SendJsonAsync(webSocket, new { type = "textureList", textures = Array.Empty<object>() });
                        }
                        break;

                    case "getFullTexture":
                        // Return full resolution texture for editor
                        try
                        {
                            if (root.TryGetProperty("index", out var texIdxProp) && _cachedTextureList != null)
                            {
                                int texIndex = texIdxProp.GetInt32();
                                if (texIndex >= 0 && texIndex < _cachedTextureList.Count)
                                {
                                    var tex = _cachedTextureList[texIndex];
                                    // Convert BGRA to RGBA and encode as PNG
                                    byte[] rgbaData = new byte[tex.RgbaData.Length];
                                    for (int i = 0; i < tex.RgbaData.Length; i += 4)
                                    {
                                        rgbaData[i + 0] = tex.RgbaData[i + 2]; // R
                                        rgbaData[i + 1] = tex.RgbaData[i + 1]; // G
                                        rgbaData[i + 2] = tex.RgbaData[i + 0]; // B
                                        rgbaData[i + 3] = tex.RgbaData[i + 3]; // A
                                    }
                                    using var image = SixLabors.ImageSharp.Image.LoadPixelData<Rgba32>(rgbaData, tex.Width, tex.Height);
                                    using var ms = new MemoryStream();
                                    image.Save(ms, new SixLabors.ImageSharp.Formats.Png.PngEncoder());
                                    string base64Data = Convert.ToBase64String(ms.ToArray());
                                    await SendJsonAsync(webSocket, new { type = "fullTexture", index = texIndex, width = tex.Width, height = tex.Height, data = base64Data });
                                }
                                else
                                {
                                    await SendJsonAsync(webSocket, new { type = "fullTexture", error = "Invalid texture index" });
                                }
                            }
                        }
                        catch (Exception ex)
                        {
                            LogError("Error in getFullTexture", ex);
                            await SendJsonAsync(webSocket, new { type = "fullTexture", error = ex.Message });
                        }
                        break;

                    case "updateTexture":
                        // Update a texture with new image data
                        try
                        {
                            if (root.TryGetProperty("index", out var indexProp) &&
                                root.TryGetProperty("data", out var dataProp))
                            {
                                int texIndex = indexProp.GetInt32();
                                string base64Data = dataProp.GetString();
                                byte[] pngData = Convert.FromBase64String(base64Data);

                                // Use BeginInvoke to avoid deadlock
                                _hostForm.BeginInvoke((Action)(() =>
                                {
                                    try
                                    {
                                        _renderJObj.UpdateTexture(texIndex, pngData);
                                    }
                                    catch (Exception ex)
                                    {
                                        LogError($"Error updating texture {texIndex}", ex);
                                    }
                                }));

                                await SendJsonAsync(webSocket, new { type = "textureUpdated", index = texIndex, success = true });
                            }
                        }
                        catch (Exception ex)
                        {
                            LogError("Error in updateTexture", ex);
                            await SendJsonAsync(webSocket, new { type = "textureUpdated", success = false, error = ex.Message });
                        }
                        break;

                    case "exportDat":
                        // Export the modified DAT file with updated textures
                        try
                        {
                            // Write to dedicated debug file - bypasses all other logging
                            var dbg = @"C:\Users\david\projects\new aka\logs\EXPORT_DEBUG.txt";
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP1\n");
                            Log("Received exportDat command");
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP2\n");

                            if (_rawFile == null)
                            {
                                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} ERROR: _rawFile null\n");
                                await SendJsonAsync(webSocket, new { type = "exportDat", success = false, error = "No DAT file loaded" });
                                break;
                            }

                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP3 - rawFile valid\n");
                            string tempPath = Path.Combine(Path.GetTempPath(), $"export_{Guid.NewGuid()}.dat");
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP4 - tempPath: {tempPath}\n");

                            // Run on background thread - no UI thread needed for file I/O
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP5 - starting Task.Run\n");
                            byte[] datBytes = await Task.Run(() =>
                            {
                                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP6 - inside Task.Run\n");
                                _rawFile.Save(tempPath);
                                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP7 - save done\n");
                                var data = File.ReadAllBytes(tempPath);
                                File.Delete(tempPath);
                                File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP8 - read {data.Length} bytes\n");
                                return data;
                            });
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP9 - Task.Run done\n");

                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP10 - converting to base64\n");
                            string base64Data = Convert.ToBase64String(datBytes);
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP11 - sending response ({datBytes.Length} bytes)\n");
                            await SendJsonAsync(webSocket, new { type = "exportDat", success = true, data = base64Data });
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP12 - DONE!\n");
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP13 - before Log\n");
                            Log($"DAT exported successfully, size: {datBytes.Length} bytes");
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} STEP14 - after Log, about to break\n");
                        }
                        catch (Exception ex)
                        {
                            var dbg = @"C:\Users\david\projects\new aka\logs\EXPORT_DEBUG.txt";
                            File.AppendAllText(dbg, $"{DateTime.Now:HH:mm:ss.fff} EXCEPTION: {ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}\n");
                            LogError("Error in exportDat", ex);
                            await SendJsonAsync(webSocket, new { type = "exportDat", success = false, error = ex.Message });
                        }
                        break;

                    case "loadAnim":
                        // Load a specific animation by symbol name
                        if (_ajManager != null && root.TryGetProperty("symbol", out var symbolProp))
                        {
                            var symbol = symbolProp.GetString();
                            var animData = _ajManager.GetAnimationData(symbol);
                            if (animData != null)
                            {
                                try
                                {
                                    var animFile = new HSDRawFile(animData);
                                    if (animFile.Roots.Count > 0 && animFile.Roots[0].Data is HSD_FigaTree tree)
                                    {
                                        var jointAnim = new JointAnimManager(tree);
                                        float newFrameCount = jointAnim.FrameCount;

                                        // Must run on UI thread for thread safety
                                        _hostForm.Invoke((Action)(() =>
                                        {
                                            _renderJObj.ClearAnimation(FrameFlags.Joint);
                                            _renderJObj.LoadAnimation(jointAnim, null, null);
                                            _animationFrameCount = newFrameCount;
                                            _animationFrame = 0;
                                            _animationPlaying = true;
                                            _renderJObj.RequestAnimationUpdate(FrameFlags.All, 0);
                                        }));

                                        Console.Error.WriteLine($"[ANIM] Loaded: {symbol}, {newFrameCount} frames");

                                        await SendJsonAsync(webSocket, new
                                        {
                                            type = "animLoaded",
                                            symbol,
                                            frameCount = newFrameCount
                                        });
                                    }
                                }
                                catch (Exception ex)
                                {
                                    Console.Error.WriteLine($"[ANIM ERR] {symbol}: {ex.Message}");
                                }
                            }
                            else
                            {
                                Log($"Animation not found: {symbol}");
                            }
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

            // Debug: log when ProcessCommandAsync completes
            File.AppendAllText(@"C:\Users\david\projects\new aka\logs\RECEIVE_DEBUG.txt",
                $"{DateTime.Now:HH:mm:ss.fff} ProcessCommand DONE\n");
        }

        private async Task SendJsonAsync(WebSocket webSocket, object data)
        {
            await _sendLock.WaitAsync();
            try
            {
                if (webSocket.State == WebSocketState.Open)
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
            }
            finally
            {
                _sendLock.Release();
            }
        }

        private async Task SendBinaryAsync(WebSocket webSocket, byte[] data)
        {
            await _sendLock.WaitAsync();
            try
            {
                if (webSocket.State == WebSocketState.Open)
                {
                    await webSocket.SendAsync(
                        new ArraySegment<byte>(data),
                        WebSocketMessageType.Binary,
                        true,
                        _cts.Token
                    );
                }
            }
            finally
            {
                _sendLock.Release();
            }
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
