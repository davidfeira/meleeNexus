import { useState, useEffect, useRef, useCallback } from 'react'

const API_URL = '/api'

// Animation name mappings - internal name -> friendly name
const ANIM_NAMES = {
  // Jabs
  'Attack11': 'Jab 1',
  'Attack12': 'Jab 2',
  'Attack13': 'Jab 3',
  'Attack100Start': 'Rapid Jab (Start)',
  'Attack100Loop': 'Rapid Jab (Loop)',
  'Attack100End': 'Rapid Jab (End)',

  // Tilts
  'AttackHi3': 'Up Tilt',
  'AttackLw3': 'Down Tilt',
  'AttackS3S': 'Forward Tilt',
  'AttackS3Hi': 'Forward Tilt (Up)',
  'AttackS3HiS': 'Forward Tilt (Up-Mid)',
  'AttackS3Lw': 'Forward Tilt (Down)',
  'AttackS3LwS': 'Forward Tilt (Down-Mid)',

  // Smashes
  'AttackHi4': 'Up Smash',
  'AttackLw4': 'Down Smash',
  'AttackS4S': 'Forward Smash',
  'AttackS4Hi': 'Forward Smash (Up)',
  'AttackS4Lw': 'Forward Smash (Down)',

  // Dash Attack
  'AttackDash': 'Dash Attack',

  // Aerials
  'AttackAirN': 'Neutral Air',
  'AttackAirHi': 'Up Air',
  'AttackAirF': 'Forward Air',
  'AttackAirLw': 'Down Air',
  'AttackAirB': 'Back Air',
  'LandingAirN': 'Nair Landing',
  'LandingAirHi': 'Uair Landing',
  'LandingAirF': 'Fair Landing',
  'LandingAirLw': 'Dair Landing',
  'LandingAirB': 'Bair Landing',

  // Specials (Grounded)
  'SpecialN': 'Neutral Special',
  'SpecialNStart': 'Neutral Special (Start)',
  'SpecialNLoop': 'Neutral Special (Loop)',
  'SpecialNEnd': 'Neutral Special (End)',
  'SpecialHi': 'Up Special',
  'SpecialLw': 'Down Special',
  'SpecialS': 'Side Special',
  'SpecialSStart': 'Side Special (Start)',
  'SpecialSLoop': 'Side Special (Loop)',
  'SpecialSEnd': 'Side Special (End)',

  // Specials (Aerial)
  'SpecialAirN': 'Neutral Special (Air)',
  'SpecialAirNStart': 'Neutral Special (Air Start)',
  'SpecialAirNLoop': 'Neutral Special (Air Loop)',
  'SpecialAirNEnd': 'Neutral Special (Air End)',
  'SpecialAirHi': 'Up Special (Air)',
  'SpecialAirLw': 'Down Special (Air)',
  'SpecialAirS': 'Side Special (Air)',
  'SpecialAirSStart': 'Side Special (Air Start)',
  'SpecialAirSLoop': 'Side Special (Air Loop)',
  'SpecialAirSEnd': 'Side Special (Air End)',

  // Grabs & Throws
  'Catch': 'Grab',
  'CatchDash': 'Dash Grab',
  'CatchCut': 'Grab Release',
  'CatchAttack': 'Pummel',
  'ThrowF': 'Forward Throw',
  'ThrowB': 'Back Throw',
  'ThrowHi': 'Up Throw',
  'ThrowLw': 'Down Throw',

  // Misc Attacks
  'Appeal': 'Taunt',
  'AppealL': 'Taunt (Left)',
  'AppealR': 'Taunt (Right)',
  'CliffAttackQuick': 'Ledge Attack (<100%)',
  'CliffAttackSlow': 'Ledge Attack (>100%)',
  'DownAttackD': 'Getup Attack (Face Down)',
  'DownAttackU': 'Getup Attack (Face Up)',
  'AirCatch': 'Z-Air',
  'AirCatchHit': 'Z-Air (Hit Wall)',

  // Movement
  'Wait1': 'Idle 1',
  'Wait2': 'Idle 2',
  'Wait3': 'Idle 3',
  'Wait4': 'Idle 4',
  'Walk': 'Walk',
  'WalkSlow': 'Walk (Slow)',
  'WalkMiddle': 'Walk (Medium)',
  'WalkFast': 'Walk (Fast)',
  'Dash': 'Dash',
  'Run': 'Run',
  'RunBrake': 'Run Brake',
  'Turn': 'Turn',
  'TurnRun': 'Turn (Running)',
  'Jump': 'Jump',
  'JumpF': 'Jump (Forward)',
  'JumpB': 'Jump (Back)',
  'JumpAerialF': 'Double Jump (Forward)',
  'JumpAerialB': 'Double Jump (Back)',
  'Fall': 'Fall',
  'FallF': 'Fall (Forward)',
  'FallB': 'Fall (Back)',
  'FallAerial': 'Fall (After Double Jump)',
  'FallAerialF': 'Fall (After DJ Forward)',
  'FallAerialB': 'Fall (After DJ Back)',
  'FallSpecial': 'Fall (Helpless)',
  'FallSpecialF': 'Fall (Helpless Forward)',
  'FallSpecialB': 'Fall (Helpless Back)',
  'Landing': 'Landing',
  'LandingFallSpecial': 'Landing (Helpless)',
  'Squat': 'Crouch',
  'SquatWait': 'Crouch (Hold)',
  'SquatRv': 'Crouch (Stand Up)',
  'Pass': 'Platform Drop',

  // Shield & Dodge
  'Guard': 'Shield',
  'GuardOn': 'Shield (Start)',
  'GuardOff': 'Shield (Release)',
  'GuardDamage': 'Shield (Hit)',
  'GuardReflect': 'Powershield',
  'EscapeF': 'Roll Forward',
  'EscapeB': 'Roll Back',
  'Escape': 'Spot Dodge',
  'EscapeAir': 'Air Dodge',

  // Ledge
  'CliffWait': 'Ledge Hang',
  'CliffClimbQuick': 'Ledge Getup (<100%)',
  'CliffClimbSlow': 'Ledge Getup (>100%)',
  'CliffJumpQuick1': 'Ledge Jump (<100%)',
  'CliffJumpQuick2': 'Ledge Jump 2 (<100%)',
  'CliffJumpSlow1': 'Ledge Jump (>100%)',
  'CliffJumpSlow2': 'Ledge Jump 2 (>100%)',
  'CliffEscapeQuick': 'Ledge Roll (<100%)',
  'CliffEscapeSlow': 'Ledge Roll (>100%)',

  // Damage
  'DamageN1': 'Damage (Light)',
  'DamageN2': 'Damage (Medium)',
  'DamageN3': 'Damage (Heavy)',
  'DamageHi1': 'Damage High (Light)',
  'DamageHi2': 'Damage High (Medium)',
  'DamageHi3': 'Damage High (Heavy)',
  'DamageLw1': 'Damage Low (Light)',
  'DamageLw2': 'Damage Low (Medium)',
  'DamageLw3': 'Damage Low (Heavy)',
  'DamageAir1': 'Damage Air (Light)',
  'DamageAir2': 'Damage Air (Medium)',
  'DamageAir3': 'Damage Air (Heavy)',
  'DamageFlyHi': 'Knockback (Up)',
  'DamageFlyN': 'Knockback (Normal)',
  'DamageFlyLw': 'Knockback (Down)',
  'DamageFlyTop': 'Knockback (Straight Up)',
  'DamageFlyRoll': 'Tumble',
  'DamageFall': 'Tumble Fall',

  // Down States
  'DownBoundU': 'Bounce (Face Up)',
  'DownBoundD': 'Bounce (Face Down)',
  'DownWaitU': 'Lying Down (Face Up)',
  'DownWaitD': 'Lying Down (Face Down)',
  'DownDamageU': 'Hit While Down (Face Up)',
  'DownDamageD': 'Hit While Down (Face Down)',
  'DownStandU': 'Getup (Face Up)',
  'DownStandD': 'Getup (Face Down)',
  'DownFowardU': 'Getup Roll Forward (Face Up)',
  'DownFowardD': 'Getup Roll Forward (Face Down)',
  'DownBackU': 'Getup Roll Back (Face Up)',
  'DownBackD': 'Getup Roll Back (Face Down)',

  // Tech
  'Passive': 'Tech',
  'PassiveStandF': 'Tech Roll Forward',
  'PassiveStandB': 'Tech Roll Back',
  'PassiveWall': 'Wall Tech',
  'PassiveWallJump': 'Wall Tech Jump',
  'PassiveCeil': 'Ceiling Tech',

  // KO
  'DeadUp': 'Star KO',
  'DeadLeft': 'Screen KO (Left)',
  'DeadRight': 'Screen KO (Right)',
  'DeadUpStar': 'Star KO (Alt)',
  'DeadUpFall': 'Star KO Fall',

  // Entry
  'Entry': 'Entry',
  'EntryStart': 'Entry (Start)',
  'EntryEnd': 'Entry (End)',

  // Win/Loss
  'Win1': 'Victory Pose 1',
  'Win2': 'Victory Pose 2',
  'Win3': 'Victory Pose 3',
  'Lose': 'Clapping',
}

// Animation categories for organization
const ANIM_CATEGORIES = {
  'Grounded Attacks': ['Attack11', 'Attack12', 'Attack13', 'Attack100', 'AttackDash', 'AttackHi3', 'AttackLw3', 'AttackS3', 'AttackHi4', 'AttackLw4', 'AttackS4'],
  'Aerials': ['AttackAirN', 'AttackAirHi', 'AttackAirF', 'AttackAirLw', 'AttackAirB', 'LandingAir'],
  'Specials': ['SpecialN', 'SpecialHi', 'SpecialLw', 'SpecialS', 'SpecialAirN', 'SpecialAirHi', 'SpecialAirLw', 'SpecialAirS'],
  'Grabs & Throws': ['Catch', 'Throw'],
  'Movement': ['Wait', 'Walk', 'Dash', 'Run', 'Turn', 'Jump', 'Fall', 'Landing', 'Squat', 'Pass'],
  'Defense': ['Guard', 'Escape', 'Cliff', 'Passive'],
  'Damage': ['Damage', 'Down'],
  'Misc': ['Appeal', 'Entry', 'Dead', 'Win', 'Lose'],
}

// Extract the core animation name from full symbol
// e.g. "PlyFox5K_Share_ACTION_Wait1_figatree" -> "Wait1"
const extractAnimName = (symbol) => {
  // Match pattern: Ply{Char}_Share_ACTION_{AnimName}_figatree
  const match = symbol.match(/_ACTION_(.+?)_figatree$/)
  if (match) return match[1]

  // Also try without _figatree suffix
  const match2 = symbol.match(/_ACTION_(.+)$/)
  if (match2) return match2[1]

  return symbol
}

// Get friendly name for animation
const getAnimDisplayName = (symbol) => {
  const coreName = extractAnimName(symbol)
  if (ANIM_NAMES[coreName]) return ANIM_NAMES[coreName]
  return coreName
}

// Categorize an animation
const getAnimCategory = (symbol) => {
  const coreName = extractAnimName(symbol)
  for (const [category, prefixes] of Object.entries(ANIM_CATEGORIES)) {
    if (prefixes.some(prefix => coreName.startsWith(prefix))) {
      return category
    }
  }
  return 'Other'
}

// Group animations by category
const groupAnimations = (animList) => {
  const grouped = {}
  for (const symbol of animList) {
    const category = getAnimCategory(symbol)
    if (!grouped[category]) grouped[category] = []
    grouped[category].push(symbol)
  }

  // Sort categories in preferred order
  const categoryOrder = Object.keys(ANIM_CATEGORIES).concat(['Other'])
  const sorted = {}
  for (const cat of categoryOrder) {
    if (grouped[cat] && grouped[cat].length > 0) {
      sorted[cat] = grouped[cat]
    }
  }
  return sorted
}

// Module-level flag to prevent double-start from React StrictMode
let viewerStarting = false

/**
 * 3D Model Viewer Component
 * Streams rendered frames from HSDRawViewer via WebSocket
 */
const ModelViewer = ({ character, skinId, onClose }) => {
  const canvasRef = useRef(null)
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [viewerInfo, setViewerInfo] = useState(null)

  // Camera state
  const [isDragging, setIsDragging] = useState(false)
  const [dragButton, setDragButton] = useState(null) // 0 = left (rotate), 2 = right (pan)
  const lastMousePos = useRef({ x: 0, y: 0 })

  // Animation state
  const [animPlaying, setAnimPlaying] = useState(false)
  const [animFrame, setAnimFrame] = useState(0)
  const [animFrameCount, setAnimFrameCount] = useState(0)

  // Animation picker state
  const [animList, setAnimList] = useState([])
  const [selectedAnim, setSelectedAnim] = useState('')
  const [animFilter, setAnimFilter] = useState('')

  // Start the viewer backend
  const startViewer = useCallback(async () => {
    // Prevent double-start from React StrictMode
    if (viewerStarting) {
      console.log('Viewer already starting, skipping')
      return
    }
    viewerStarting = true

    try {
      setIsLoading(true)
      setError(null)

      const response = await fetch(`${API_URL}/viewer/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character, skinId })
      })

      const data = await response.json()
      console.log('Viewer start response:', data)

      if (!data.success) {
        throw new Error(data.error || 'Failed to start viewer')
      }

      // Connect to WebSocket
      console.log('Connecting to WebSocket:', data.wsUrl)
      const ws = new WebSocket(data.wsUrl)
      wsRef.current = ws

      ws.binaryType = 'blob'

      ws.onopen = () => {
        console.log('WebSocket connected to viewer')
        setIsConnected(true)
        setIsLoading(false)
        // Request animation list
        ws.send(JSON.stringify({ type: 'getAnimList' }))
      }

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          // Binary frame data - render to canvas
          const bitmap = await createImageBitmap(event.data)
          const canvas = canvasRef.current
          if (canvas) {
            const ctx = canvas.getContext('2d')
            canvas.width = bitmap.width
            canvas.height = bitmap.height
            ctx.drawImage(bitmap, 0, 0)
          }
        } else {
          // JSON message
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'info') {
              setViewerInfo(msg)
              // Update animation state from server
              if (msg.animation) {
                setAnimFrameCount(msg.animation.frameCount || 0)
                setAnimFrame(msg.animation.currentFrame || 0)
                setAnimPlaying(msg.animation.playing || false)
              }
            } else if (msg.type === 'animList') {
              // Received list of available animations
              console.log(`Received ${msg.symbols?.length || 0} animations`)
              setAnimList(msg.symbols || [])
            } else if (msg.type === 'animLoaded') {
              // Animation loaded successfully
              console.log(`Animation loaded: ${msg.symbol}, frames: ${msg.frameCount}`)
              setSelectedAnim(msg.symbol)
              setAnimFrameCount(msg.frameCount || 0)
              setAnimFrame(0)
              setAnimPlaying(true)
            }
          } catch (e) {
            console.log('Non-JSON message:', event.data)
          }
        }
      }

      ws.onerror = (event) => {
        console.error('WebSocket error:', event)
        setError('Connection error')
      }

      ws.onclose = () => {
        console.log('WebSocket closed')
        setIsConnected(false)
      }

    } catch (err) {
      console.error('Failed to start viewer:', err)
      setError(err.message)
      setIsLoading(false)
      viewerStarting = false // Allow retry
    }
  }, [character, skinId])

  // Stop the viewer
  const stopViewer = useCallback(async () => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    try {
      await fetch(`${API_URL}/viewer/stop`, { method: 'POST' })
    } catch (err) {
      console.error('Error stopping viewer:', err)
    }

    // Reset flag after stop completes so re-opening works
    viewerStarting = false
  }, [])

  // Send delta-based camera update to viewer
  const sendCameraUpdate = useCallback((deltas) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'camera',
        ...deltas
      }))
    }
  }, [])

  // Animation controls
  const toggleAnimation = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'animToggle' }))
      setAnimPlaying(p => !p)
    }
  }, [])

  const setAnimationFrame = useCallback((frame) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'animSetFrame', frame }))
      setAnimFrame(frame)
    }
  }, [])

  // Load a specific animation by symbol name
  const loadAnimation = useCallback((symbol) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log(`Loading animation: ${symbol}`)
      wsRef.current.send(JSON.stringify({ type: 'loadAnim', symbol }))
    }
  }, [])

  // Mouse handlers for camera control
  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    setIsDragging(true)
    setDragButton(e.button) // 0 = left, 2 = right
    lastMousePos.current = { x: e.clientX, y: e.clientY }
  }, [])

  const handleMouseMove = useCallback((e) => {
    if (!isDragging) return

    const deltaX = e.clientX - lastMousePos.current.x
    const deltaY = e.clientY - lastMousePos.current.y
    lastMousePos.current = { x: e.clientX, y: e.clientY }

    if (dragButton === 2) {
      // Right-click: Pan
      const panSpeed = 0.1
      sendCameraUpdate({
        deltaX: -deltaX * panSpeed,
        deltaY: deltaY * panSpeed
      })
    } else {
      // Left-click: Rotate (0.5 degrees per pixel)
      sendCameraUpdate({
        deltaRotX: deltaY * 0.5,
        deltaRotY: deltaX * 0.5
      })
    }
  }, [isDragging, dragButton, sendCameraUpdate])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
    setDragButton(null)
  }, [])

  const handleWheel = useCallback((e) => {
    e.preventDefault()

    // Zoom - use multiplicative factor
    // Scroll up (negative deltaY) = zoom in (positive factor)
    // Scroll down (positive deltaY) = zoom out (negative factor)
    const zoomFactor = e.deltaY > 0 ? -0.1 : 0.1
    sendCameraUpdate({ deltaZoom: zoomFactor })
  }, [sendCameraUpdate])

  // Prevent context menu on right-click
  const handleContextMenu = useCallback((e) => {
    e.preventDefault()
  }, [])

  // Block scroll on the overlay when viewer is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  // Handle close
  const handleClose = useCallback(async () => {
    await stopViewer()
    onClose()
  }, [stopViewer, onClose])

  // Start viewer on mount
  useEffect(() => {
    startViewer()

    return () => {
      stopViewer()
    }
  }, [startViewer, stopViewer])

  // Global mouse up handler
  useEffect(() => {
    const handleGlobalMouseUp = () => setIsDragging(false)
    window.addEventListener('mouseup', handleGlobalMouseUp)
    return () => window.removeEventListener('mouseup', handleGlobalMouseUp)
  }, [])

  return (
    <div className="model-viewer-overlay" onClick={handleClose}>
      <div
        className="model-viewer-container"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="model-viewer-header">
          <h3>3D Model Viewer</h3>
          <button className="model-viewer-close" onClick={handleClose}>
            &times;
          </button>
        </div>

        <div className="model-viewer-content">
          {isLoading && (
            <div className="model-viewer-loading">
              <div className="spinner"></div>
              <p>Loading model...</p>
            </div>
          )}

          {error && (
            <div className="model-viewer-error">
              <p>Error: {error}</p>
              <button onClick={() => {
                viewerStarting = false
                setError(null)
                startViewer()
              }}>Retry</button>
            </div>
          )}

          {!isLoading && !error && (
            <canvas
              ref={canvasRef}
              className="model-viewer-canvas"
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onWheel={handleWheel}
              onContextMenu={handleContextMenu}
              style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
            />
          )}
        </div>

        {/* Animation picker */}
        {animList.length > 0 && (
          <div className="model-viewer-anim-picker">
            <input
              type="text"
              placeholder="Filter animations..."
              value={animFilter}
              onChange={(e) => setAnimFilter(e.target.value)}
              className="anim-filter-input"
            />
            <select
              value={selectedAnim}
              onChange={(e) => {
                const symbol = e.target.value
                if (symbol) {
                  loadAnimation(symbol)
                }
              }}
              className="anim-select"
            >
              <option value="">Select animation...</option>
              {Object.entries(groupAnimations(
                animList.filter(sym => {
                  if (!animFilter) return true
                  const filter = animFilter.toLowerCase()
                  const displayName = getAnimDisplayName(sym).toLowerCase()
                  return sym.toLowerCase().includes(filter) || displayName.includes(filter)
                })
              )).map(([category, symbols]) => (
                <optgroup key={category} label={category}>
                  {symbols.map(sym => (
                    <option key={sym} value={sym}>
                      {getAnimDisplayName(sym)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        )}

        {/* Animation controls */}
        {animFrameCount > 0 && (
          <div className="model-viewer-animation-controls">
            <button
              className="anim-play-btn"
              onClick={toggleAnimation}
              title={animPlaying ? 'Pause' : 'Play'}
            >
              {animPlaying ? '⏸' : '▶'}
            </button>
            <input
              type="range"
              min="0"
              max={Math.max(0, animFrameCount - 1)}
              step="1"
              value={animFrame}
              onChange={(e) => setAnimationFrame(parseFloat(e.target.value))}
              className="anim-slider"
            />
            <span className="anim-frame-info">
              {Math.floor(animFrame)} / {Math.floor(animFrameCount)}
            </span>
          </div>
        )}

        <div className="model-viewer-footer">
          <span className={`status-indicator ${isConnected ? 'connected' : 'disconnected'}`}>
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          {viewerInfo && (
            <span className="viewer-info">
              {viewerInfo.width}x{viewerInfo.height} @ {viewerInfo.fps}fps
            </span>
          )}
          <span className="controls-hint">
            Left-drag: rotate | Right-drag: pan | Scroll: zoom
          </span>
        </div>
      </div>
    </div>
  )
}

export default ModelViewer
