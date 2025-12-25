import { useState, useEffect, useRef } from 'react'
import { io } from 'socket.io-client'
import './StorageViewer.css'
import './IsoBuilder.css'
import { DEFAULT_CHARACTERS } from '../defaultCharacters'
import ModelViewer from './ModelViewer'

const API_URL = 'http://127.0.0.1:5000/api/mex'
const BACKEND_URL = 'http://127.0.0.1:5000'

const DAS_STAGES = [
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: `${BACKEND_URL}/vanilla/stages/dreamland.jpg` },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: `${BACKEND_URL}/vanilla/stages/pokemon stadium.jpg` },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: `${BACKEND_URL}/vanilla/stages/Yoshis story.jpg` },
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: `${BACKEND_URL}/vanilla/stages/battlefield.jpg` },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: `${BACKEND_URL}/vanilla/stages/Fountain of Dreams.webp` },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: `${BACKEND_URL}/vanilla/stages/final destination.png` }
]

// Skeleton loading components
const SkeletonCard = () => (
  <div className="character-card skeleton-card">
    <div className="character-image-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '70%', margin: '0.5rem auto' }}></div>
    <div className="skeleton skeleton-text" style={{ width: '40%', margin: '0 auto', height: '12px' }}></div>
  </div>
)

const SkeletonSkinCard = () => (
  <div className="skin-card skeleton-card">
    <div className="skin-image-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '60%', margin: '0.5rem auto' }}></div>
  </div>
)

export default function StorageViewer({ metadata, onRefresh }) {
  const [mode, setMode] = useState('characters') // 'characters', 'stages', or 'patches'
  const [isLoading, setIsLoading] = useState(true)
  const [selectedCharacter, setSelectedCharacter] = useState(null)
  const [selectedStage, setSelectedStage] = useState(null)
  const [stageVariants, setStageVariants] = useState({})
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')

  // XDelta patches state
  const [xdeltaPatches, setXdeltaPatches] = useState([])
  const [showXdeltaImportModal, setShowXdeltaImportModal] = useState(false)
  const [xdeltaImportData, setXdeltaImportData] = useState({ name: '', description: '', file: null, image: null })
  const [importingXdelta, setImportingXdelta] = useState(false)
  const [showXdeltaEditModal, setShowXdeltaEditModal] = useState(false)
  const [editingXdelta, setEditingXdelta] = useState(null)

  // XDelta build modal state
  const [showXdeltaBuildModal, setShowXdeltaBuildModal] = useState(false)
  const [xdeltaBuildState, setXdeltaBuildState] = useState('idle') // 'idle', 'building', 'complete', 'error'
  const [xdeltaBuildPatch, setXdeltaBuildPatch] = useState(null)
  const [xdeltaBuildFilename, setXdeltaBuildFilename] = useState(null)
  const [xdeltaBuildError, setXdeltaBuildError] = useState(null)
  const [xdeltaBuildProgress, setXdeltaBuildProgress] = useState(0)
  const [xdeltaBuildMessage, setXdeltaBuildMessage] = useState('')
  const socketRef = useRef(null)

  // XDelta create patch state
  const [showXdeltaCreateModal, setShowXdeltaCreateModal] = useState(false)
  const [xdeltaCreateData, setXdeltaCreateData] = useState({ name: '', description: '', moddedIsoPath: '' })
  const [xdeltaCreateState, setXdeltaCreateState] = useState('idle') // 'idle', 'creating', 'complete', 'error'
  const [xdeltaCreateId, setXdeltaCreateId] = useState(null)
  const [xdeltaCreateProgress, setXdeltaCreateProgress] = useState(0)
  const [xdeltaCreateMessage, setXdeltaCreateMessage] = useState('')
  const [xdeltaCreateError, setXdeltaCreateError] = useState(null)
  const [xdeltaCreateResult, setXdeltaCreateResult] = useState(null)

  // Slippi dialog state
  const [showSlippiDialog, setShowSlippiDialog] = useState(false)
  const [slippiDialogData, setSlippiDialogData] = useState(null)
  const [pendingFile, setPendingFile] = useState(null)
  const [retestingItem, setRetestingItem] = useState(null) // For retest dialog

  // Edit modal state
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingItem, setEditingItem] = useState(null) // { type: 'costume'/'stage', data: {...} }
  const [editName, setEditName] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [newScreenshot, setNewScreenshot] = useState(null) // File object for new screenshot
  const [screenshotPreview, setScreenshotPreview] = useState(null) // Preview URL for new screenshot
  const [newCsp, setNewCsp] = useState(null) // File object for new CSP
  const [cspPreview, setCspPreview] = useState(null) // Preview URL for new CSP
  const [newStock, setNewStock] = useState(null) // File object for new stock
  const [stockPreview, setStockPreview] = useState(null) // Preview URL for new stock
  const [editSlippiSafe, setEditSlippiSafe] = useState(null) // Track slippi changes for stages
  const [lastImageUpdate, setLastImageUpdate] = useState(Date.now()) // For cache-busting images
  const [show3DViewer, setShow3DViewer] = useState(false) // 3D model viewer
  const [slippiAdvancedOpen, setSlippiAdvancedOpen] = useState(false) // Collapsible Slippi controls
  const [showSkinCreator, setShowSkinCreator] = useState(false) // Skin creator modal
  const [skinCreatorStep, setSkinCreatorStep] = useState('select') // 'select' or 'edit'
  const [vanillaCostumes, setVanillaCostumes] = useState([])
  const [selectedVanillaCostume, setSelectedVanillaCostume] = useState(null)
  const [skinCreatorLoading, setSkinCreatorLoading] = useState(false)
  const [skinCreatorError, setSkinCreatorError] = useState(null)
  const [viewerWs, setViewerWs] = useState(null)
  const [modelTextures, setModelTextures] = useState([])
  const [selectedTextureIndex, setSelectedTextureIndex] = useState(null)
  const skinCreatorCanvasRef = useRef(null)
  const paintCanvasRef = useRef(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const lastDrawPos = useRef(null)
  const [viewerDragging, setViewerDragging] = useState(false)
  const [viewerDragButton, setViewerDragButton] = useState(null)
  const viewerLastMousePos = useRef({ x: 0, y: 0 })

  // Drag and drop state
  const [draggedItem, setDraggedItem] = useState(null) // { index, id }
  const [dragStartIndex, setDragStartIndex] = useState(null) // Original position when drag started
  const [dragOverIndex, setDragOverIndex] = useState(null)
  const [reordering, setReordering] = useState(false)
  const [contextMenu, setContextMenu] = useState(null) // { x, y, type: 'skin'/'variant', item, index }
  const [previewOrder, setPreviewOrder] = useState(null) // Live preview of reordered items during drag

  // Folder state
  const [expandedFolders, setExpandedFolders] = useState({}) // { folderId: true/false }
  const [editingFolderId, setEditingFolderId] = useState(null)
  const [editingFolderName, setEditingFolderName] = useState('')
  const [dragTargetFolder, setDragTargetFolder] = useState(null) // Folder being hovered over during drag

  // Fetch stage variants when in stages mode or when metadata changes
  useEffect(() => {
    if (mode === 'stages') {
      fetchStageVariants()
    }
  }, [mode, metadata])

  // Fetch xdelta patches when in patches mode
  useEffect(() => {
    if (mode === 'patches') {
      fetchXdeltaPatches()
    }
  }, [mode])

  // WebSocket connection for xdelta build/create progress
  useEffect(() => {
    const socket = io(BACKEND_URL)
    socketRef.current = socket

    socket.on('connect', () => {
      console.log('Connected to WebSocket for xdelta progress')
    })

    socket.on('xdelta_progress', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildProgress(data.percentage)
        setXdeltaBuildMessage(data.message)
      }
    })

    socket.on('xdelta_complete', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildProgress(100)
        setXdeltaBuildFilename(data.filename)
        setXdeltaBuildState('complete')
      }
    })

    socket.on('xdelta_error', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildError(data.error)
        setXdeltaBuildState('error')
      }
    })

    // XDelta create events
    socket.on('xdelta_create_progress', (data) => {
      if (xdeltaCreateId && data.create_id === xdeltaCreateId) {
        setXdeltaCreateProgress(data.percentage)
        setXdeltaCreateMessage(data.message)
      }
    })

    socket.on('xdelta_create_complete', (data) => {
      if (xdeltaCreateId && data.create_id === xdeltaCreateId) {
        setXdeltaCreateProgress(100)
        setXdeltaCreateResult(data)
        setXdeltaCreateState('complete')
        // Refresh patches list
        fetchXdeltaPatches()
      }
    })

    socket.on('xdelta_create_error', (data) => {
      if (xdeltaCreateId && data.create_id === xdeltaCreateId) {
        setXdeltaCreateError(data.error)
        setXdeltaCreateState('error')
      }
    })

    return () => {
      socket.disconnect()
    }
  }, [xdeltaBuildPatch, xdeltaCreateId])

  const fetchXdeltaPatches = async () => {
    try {
      const response = await fetch(`${API_URL}/xdelta/list`)
      if (!response.ok) {
        console.error('Failed to fetch xdelta patches: Server returned', response.status)
        return
      }
      const text = await response.text()
      if (!text || text.startsWith('<!')) {
        console.error('Failed to fetch xdelta patches: Server returned HTML instead of JSON')
        return
      }
      const data = JSON.parse(text)
      if (data.success) {
        setXdeltaPatches(data.patches)
      }
    } catch (err) {
      console.error('Failed to fetch xdelta patches:', err)
    }
  }

  const handleImportXdelta = async () => {
    if (!xdeltaImportData.file) {
      alert('Please select an xdelta file')
      return
    }

    setImportingXdelta(true)

    try {
      const formData = new FormData()
      formData.append('file', xdeltaImportData.file)
      formData.append('name', xdeltaImportData.name || xdeltaImportData.file.name.replace('.xdelta', ''))
      formData.append('description', xdeltaImportData.description)
      if (xdeltaImportData.image) {
        formData.append('image', xdeltaImportData.image)
      }

      const response = await fetch(`${API_URL}/xdelta/import`, {
        method: 'POST',
        body: formData
      })

      const data = await response.json()

      if (data.success) {
        setShowXdeltaImportModal(false)
        setXdeltaImportData({ name: '', description: '', file: null, image: null })
        await fetchXdeltaPatches()
      } else {
        alert(`Import failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Import error: ${err.message}`)
    } finally {
      setImportingXdelta(false)
    }
  }

  const handleBuildXdeltaIso = async (patch) => {
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')

    if (!vanillaIsoPath) {
      alert('No vanilla ISO path set. Please set it in Settings first.')
      return
    }

    // Open modal and set building state
    setXdeltaBuildPatch(patch)
    setXdeltaBuildState('building')
    setXdeltaBuildFilename(null)
    setXdeltaBuildError(null)
    setXdeltaBuildProgress(0)
    setXdeltaBuildMessage('Starting...')
    setShowXdeltaBuildModal(true)

    try {
      const response = await fetch(`${API_URL}/xdelta/build/${patch.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vanillaIsoPath })
      })

      const data = await response.json()

      if (!data.success) {
        setXdeltaBuildError(data.error)
        setXdeltaBuildState('error')
      }
      // If success, we wait for WebSocket events for progress/complete
    } catch (err) {
      setXdeltaBuildError(err.message)
      setXdeltaBuildState('error')
    }
  }

  const handleDownloadXdeltaIso = () => {
    if (!xdeltaBuildFilename) return

    const link = document.createElement('a')
    link.href = `${API_URL}/xdelta/download/${xdeltaBuildFilename}`
    link.download = xdeltaBuildFilename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const closeXdeltaBuildModal = () => {
    setShowXdeltaBuildModal(false)
    setXdeltaBuildState('idle')
    setXdeltaBuildPatch(null)
    setXdeltaBuildFilename(null)
    setXdeltaBuildError(null)
    setXdeltaBuildProgress(0)
    setXdeltaBuildMessage('')
  }

  const handleSelectModdedIso = async () => {
    try {
      // Use Electron's file dialog if available
      if (window.electron?.openIsoDialog) {
        const result = await window.electron.openIsoDialog()
        if (result) {
          setXdeltaCreateData({ ...xdeltaCreateData, moddedIsoPath: result })
        }
      } else {
        alert('File selection requires the desktop app')
      }
    } catch (err) {
      console.error('Failed to select ISO:', err)
    }
  }

  const handleStartCreateXdelta = async () => {
    if (!xdeltaCreateData.moddedIsoPath) {
      alert('Please select a modded ISO file')
      return
    }

    if (!xdeltaCreateData.name.trim()) {
      alert('Please enter a name for the patch')
      return
    }

    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')
    if (!vanillaIsoPath) {
      alert('No vanilla ISO path set. Please set it in Settings first.')
      return
    }

    // Switch to creating state
    setXdeltaCreateState('creating')
    setXdeltaCreateProgress(0)
    setXdeltaCreateMessage('Starting...')
    setXdeltaCreateError(null)
    setXdeltaCreateResult(null)

    try {
      const response = await fetch(`${API_URL}/xdelta/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          vanillaIsoPath,
          moddedIsoPath: xdeltaCreateData.moddedIsoPath,
          name: xdeltaCreateData.name,
          description: xdeltaCreateData.description
        })
      })

      const data = await response.json()

      if (data.success) {
        setXdeltaCreateId(data.create_id)
      } else {
        setXdeltaCreateError(data.error)
        setXdeltaCreateState('error')
      }
    } catch (err) {
      setXdeltaCreateError(err.message)
      setXdeltaCreateState('error')
    }
  }

  const closeXdeltaCreateModal = () => {
    setShowXdeltaCreateModal(false)
    setXdeltaCreateState('idle')
    setXdeltaCreateData({ name: '', description: '', moddedIsoPath: '' })
    setXdeltaCreateId(null)
    setXdeltaCreateProgress(0)
    setXdeltaCreateMessage('')
    setXdeltaCreateError(null)
    setXdeltaCreateResult(null)
  }

  const handleDownloadPatch = (patchId) => {
    const link = document.createElement('a')
    link.href = `${API_URL}/xdelta/download-patch/${patchId}`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleDeleteXdelta = async (patchId) => {
    if (!confirm('Are you sure you want to delete this patch?')) return

    try {
      const response = await fetch(`${API_URL}/xdelta/delete/${patchId}`, {
        method: 'POST'
      })

      const data = await response.json()

      if (data.success) {
        await fetchXdeltaPatches()
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    }
  }

  const handleEditXdelta = (patch) => {
    setEditingXdelta({ ...patch })
    setShowXdeltaEditModal(true)
  }

  const handleSaveXdeltaEdit = async () => {
    if (!editingXdelta) return

    try {
      const response = await fetch(`${API_URL}/xdelta/update/${editingXdelta.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editingXdelta.name,
          description: editingXdelta.description
        })
      })

      const data = await response.json()

      if (data.success) {
        setShowXdeltaEditModal(false)
        setEditingXdelta(null)
        await fetchXdeltaPatches()
      } else {
        alert(`Save failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Save error: ${err.message}`)
    }
  }

  const handleUpdateXdeltaImage = async (e) => {
    if (!editingXdelta) return

    const file = e.target.files[0]
    if (!file) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const response = await fetch(`${API_URL}/xdelta/update-image/${editingXdelta.id}`, {
        method: 'POST',
        body: formData
      })

      const data = await response.json()

      if (data.success) {
        setEditingXdelta({ ...editingXdelta, imageUrl: data.imageUrl })
        await fetchXdeltaPatches()
      } else {
        alert(`Image update failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Image update error: ${err.message}`)
    }
  }

  // Track loading state based on metadata
  useEffect(() => {
    if (metadata) {
      // Small delay for smooth transition
      const timer = setTimeout(() => setIsLoading(false), 300)
      return () => clearTimeout(timer)
    }
  }, [metadata])

  const fetchStageVariants = async () => {
    try {
      const response = await fetch(`${API_URL}/das/storage/variants`)
      const data = await response.json()

      if (data.success) {
        // Group variants by stage
        const grouped = {}
        data.variants.forEach(variant => {
          if (!grouped[variant.stageCode]) {
            grouped[variant.stageCode] = []
          }
          grouped[variant.stageCode].push(variant)
        })
        setStageVariants(grouped)
      }
    } catch (err) {
      console.error('Failed to fetch stage variants:', err)
    }
  }

  const handleFileImport = async (event, slippiAction = null) => {
    const file = slippiAction ? pendingFile : event.target.files[0]
    if (!file) return

    setImporting(true)
    setImportMessage('Uploading and detecting mod type...')

    try {
      const formData = new FormData()
      formData.append('file', file)
      if (slippiAction) {
        formData.append('slippi_action', slippiAction)
      }

      const response = await fetch(`${API_URL}/import/file`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()

      // Check if we need to show slippi dialog
      if (data.type === 'slippi_dialog') {
        setSlippiDialogData(data)
        setPendingFile(file)
        setShowSlippiDialog(true)
        setImporting(false)
        setImportMessage('')
        if (event && event.target) event.target.value = null
        return
      }

      if (data.success) {
        const typeMsg = data.type === 'character'
          ? `${data.imported_count} costume(s)`
          : `${data.stage} stage`
        setImportMessage(`✓ Imported ${typeMsg}! Refreshing...`)

        // Refresh metadata
        await onRefresh()

        // If we imported a stage, also refresh stage variants
        if (data.type === 'stage' && mode === 'stages') {
          await fetchStageVariants()
        }

        setImportMessage(`✓ Successfully imported ${typeMsg}!`)
        setTimeout(() => {
          setImporting(false)
          setImportMessage('')
        }, 2000)
      } else {
        setImportMessage(`✗ Import failed: ${data.error}`)
        setTimeout(() => {
          setImporting(false)
          setImportMessage('')
        }, 5000)
      }
    } catch (err) {
      setImportMessage(`✗ Error: ${err.message}`)
      setTimeout(() => {
        setImporting(false)
        setImportMessage('')
      }, 5000)
    }

    // Reset file input
    if (event && event.target) event.target.value = null
  }

  const handleSlippiChoice = (choice) => {
    setShowSlippiDialog(false)
    if (choice === 'cancel') {
      setPendingFile(null)
      setSlippiDialogData(null)
      return
    }
    handleFileImport(null, choice)
  }

  const handleSlippiRetest = async (autoFix = false) => {
    if (!editingItem || editingItem.type !== 'costume') return

    try {
      const response = await fetch(`${API_URL}/storage/costumes/retest-slippi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: editingItem.data.character,
          skinId: editingItem.data.id,
          autoFix: autoFix
        })
      })
      const data = await response.json()

      if (data.success) {
        // If not safe and not auto-fixing, show dialog
        if (!data.slippi_safe && !autoFix) {
          setRetestingItem(editingItem.data)
          setSlippiDialogData({
            unsafe_costumes: [{
              character: editingItem.data.character,
              color: editingItem.data.color
            }]
          })
          setShowSlippiDialog(true)
        } else {
          // Safe or just fixed - reload
          alert(data.message)
          window.location.reload()
        }
      } else {
        alert(`Error: ${data.error}`)
      }
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  const handleRetestFixChoice = (choice) => {
    setShowSlippiDialog(false)
    if (choice === 'cancel') {
      setRetestingItem(null)
      setSlippiDialogData(null)
      return
    }
    if (choice === 'fix') {
      // Retest with auto-fix
      handleSlippiRetest(true)
    } else if (choice === 'import_as_is') {
      // Just reload to keep current status
      window.location.reload()
    }
    setRetestingItem(null)
  }

  const handleSlippiOverride = async () => {
    if (!editingItem || editingItem.type !== 'costume') return

    const currentStatus = editingItem.data.slippi_safe
    const newStatus = !currentStatus

    try {
      const response = await fetch(`${API_URL}/storage/costumes/override-slippi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: editingItem.data.character,
          skinId: editingItem.data.id,
          slippiSafe: newStatus
        })
      })
      const data = await response.json()

      if (data.success) {
        alert(data.message)
        window.location.reload()
      } else {
        alert(`Error: ${data.error}`)
      }
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  const handleEditClick = (type, data) => {
    const item = { type, data }
    const name = type === 'costume' ? data.color : data.name
    setEditingItem(item)
    setEditName(name)
    setSaving(false)
    setDeleting(false)
    setNewScreenshot(null)
    setScreenshotPreview(null)
    setNewCsp(null)
    setCspPreview(null)
    setNewStock(null)
    setStockPreview(null)
    setEditSlippiSafe(type === 'stage' ? data.slippi_safe : null)
    setShowEditModal(true)
  }

  const handleScreenshotChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewScreenshot(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setScreenshotPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleCspChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewCsp(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setCspPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleStockChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewStock(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setStockPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleSave = async () => {
    if (!editName.trim()) {
      alert('Name cannot be empty')
      return
    }

    setSaving(true)

    try {
      // Save name change
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/rename`
        : `${API_URL}/storage/stages/rename`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id,
            newName: editName
          }
        : {
            stageFolder: editingItem.data.stageFolder,
            variantId: editingItem.data.id,
            newName: editName
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (!data.success) {
        alert(`Save failed: ${data.error}`)
        setSaving(false)
        return
      }

      // If this is a stage and there's a new screenshot, upload it
      if (editingItem.type === 'stage' && newScreenshot) {
        const formData = new FormData()
        formData.append('stageFolder', editingItem.data.stageFolder)
        formData.append('variantId', editingItem.data.id)
        formData.append('screenshot', newScreenshot)

        const screenshotResponse = await fetch(`${API_URL}/storage/stages/update-screenshot`, {
          method: 'POST',
          body: formData
        })

        const screenshotData = await screenshotResponse.json()

        if (!screenshotData.success) {
          alert(`Screenshot upload failed: ${screenshotData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a stage and slippi status changed, save it
      if (editingItem.type === 'stage' && editSlippiSafe !== editingItem.data.slippi_safe) {
        const slippiResponse = await fetch(`${API_URL}/storage/stages/set-slippi`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stageName: editingItem.data.stageFolder,
            variantId: editingItem.data.id,
            slippiSafe: editSlippiSafe
          })
        })

        const slippiData = await slippiResponse.json()

        if (!slippiData.success) {
          alert(`Slippi status update failed: ${slippiData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a character costume and there's a new CSP, upload it
      if (editingItem.type === 'costume' && newCsp) {
        const formData = new FormData()
        formData.append('character', editingItem.data.character)
        formData.append('skinId', editingItem.data.id)
        formData.append('csp', newCsp)

        const cspResponse = await fetch(`${API_URL}/storage/costumes/update-csp`, {
          method: 'POST',
          body: formData
        })

        const cspData = await cspResponse.json()

        if (!cspData.success) {
          alert(`CSP upload failed: ${cspData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a character costume and there's a new stock icon, upload it
      if (editingItem.type === 'costume' && newStock) {
        const formData = new FormData()
        formData.append('character', editingItem.data.character)
        formData.append('skinId', editingItem.data.id)
        formData.append('stock', newStock)

        const stockResponse = await fetch(`${API_URL}/storage/costumes/update-stock`, {
          method: 'POST',
          body: formData
        })

        const stockData = await stockResponse.json()

        if (!stockData.success) {
          alert(`Stock icon upload failed: ${stockData.error}`)
          setSaving(false)
          return
        }
      }

      // Refetch data before closing modal
      if (editingItem.type === 'stage') {
        await fetchStageVariants()
      }

      // Always await metadata refresh for costumes (CSP/stock updates)
      await onRefresh()

      // If we uploaded a CSP or stock, update cache-busting timestamp to force image reload
      if (newCsp || newStock) {
        setLastImageUpdate(Date.now())
      }

      setShowEditModal(false)
      setEditingItem(null)
    } catch (err) {
      alert(`Save error: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const itemName = editingItem.type === 'costume'
      ? `${editingItem.data.character} - ${editingItem.data.color}`
      : editingItem.data.name

    if (!confirm(`Are you sure you want to delete "${itemName}"? This cannot be undone.`)) {
      return
    }

    setDeleting(true)

    try {
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/delete`
        : `${API_URL}/storage/stages/delete`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id
          }
        : {
            stageFolder: editingItem.data.stageFolder,
            variantId: editingItem.data.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refetch data before closing modal
        if (editingItem.type === 'stage') {
          await fetchStageVariants()
        }

        // Always await metadata refresh for costumes
        await onRefresh()

        // Update cache-busting timestamp to force image reload after deletion
        if (editingItem.type === 'costume') {
          setLastImageUpdate(Date.now())
        }

        setShowEditModal(false)
        setEditingItem(null)
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)

    try {
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/export`
        : `${API_URL}/storage/stages/export`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id,
            colorName: editingItem.data.color
          }
        : {
            stageCode: editingItem.data.stageCode,
            stageName: editingItem.data.stageName,
            variantId: editingItem.data.id,
            variantName: editingItem.data.name
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Trigger download
        const downloadUrl = `${API_URL}/export/mod/${data.filename}`
        const link = document.createElement('a')
        link.href = downloadUrl
        link.download = data.filename
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
      } else {
        alert(`Export failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Export error: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  const handleCancel = () => {
    setShowEditModal(false)
    setEditingItem(null)
    setEditName('')
    setNewScreenshot(null)
    setScreenshotPreview(null)
    setNewCsp(null)
    setCspPreview(null)
    setNewStock(null)
    setStockPreview(null)
    setEditSlippiSafe(null)
  }

  // Drag and drop handlers
  const handleDragStart = (e, index, items) => {
    setDraggedItem({ index, id: items[index].id })
    setDragStartIndex(index) // Track original position for returning to same spot
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDragEnter = (e, index, items) => {
    e.preventDefault()
    if (!draggedItem) return

    // Only update if we've moved to a different position
    if (dragOverIndex !== index) {
      setDragOverIndex(index)

      // Calculate new preview order
      const currentOrder = previewOrder || [...items]

      // Find current position of dragged item in preview
      const draggedCurrentPos = currentOrder.findIndex(item => item.id === draggedItem.id)
      if (draggedCurrentPos === -1) return

      // Skip if already at target position in preview
      if (draggedCurrentPos === index) return

      // Create new order with item moved to target position
      const newOrder = [...currentOrder]
      const [removed] = newOrder.splice(draggedCurrentPos, 1)
      newOrder.splice(index, 0, removed)

      setPreviewOrder(newOrder)
    }
  }

  const handleDragLeave = (e) => {
    // Only clear if leaving the container entirely
    if (e.currentTarget === e.target) {
      setDragOverIndex(null)
    }
  }

  const handleSkinDrop = async (e, toIndex) => {
    e.preventDefault()
    if (!draggedItem) return

    const fromIndex = dragStartIndex

    if (fromIndex === toIndex || !selectedCharacter) {
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/costumes/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          fromIndex,
          toIndex
        })
      })

      const data = await response.json()

      if (data.success) {
        // Refresh metadata to get updated order
        await onRefresh()
      } else {
        alert(`Reorder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    } finally {
      setReordering(false)
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
    }
  }

  const handleVariantDrop = async (e, toIndex) => {
    e.preventDefault()
    if (!draggedItem) return

    const fromIndex = dragStartIndex

    if (fromIndex === toIndex || !selectedStage) {
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/stages/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stageFolder: selectedStage.folder,
          fromIndex,
          toIndex
        })
      })

      const data = await response.json()

      if (data.success) {
        // Refresh stage variants and metadata
        await fetchStageVariants()
        await onRefresh()
      } else {
        alert(`Reorder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    } finally {
      setReordering(false)
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
    }
  }

  const handleDragEnd = () => {
    setDraggedItem(null)
    setDragStartIndex(null)
    setDragOverIndex(null)
    setPreviewOrder(null)
    setDragTargetFolder(null)
  }

  // Folder helper functions
  // Build display list from skins array (which now contains both skins and folders)
  // Folder items are GROUPED right after their folder header when expanded
  const buildDisplayList = (allSkins) => {
    if (!allSkins?.length) return []

    // Build folder info and collect folder items
    const folderItems = {} // folderId -> [items with arrayIndex]
    const folders = [] // folder objects with arrayIndex
    const rootItems = [] // items not in any folder

    for (let i = 0; i < allSkins.length; i++) {
      const item = allSkins[i]

      if (item.type === 'folder') {
        folders.push({ folder: item, arrayIndex: i })
        folderItems[item.id] = []
      } else if (item.visible !== false) {
        if (item.folder_id) {
          if (!folderItems[item.folder_id]) {
            folderItems[item.folder_id] = []
          }
          folderItems[item.folder_id].push({ skin: item, arrayIndex: i })
        } else {
          rootItems.push({ skin: item, arrayIndex: i })
        }
      }
    }

    // Build display list: root items first, then folders with their items
    const result = []

    // Add root items that come before all folders
    // We need to maintain relative order, so track what we've added
    const addedIndices = new Set()

    // Go through array in order to maintain relative positioning
    for (let i = 0; i < allSkins.length; i++) {
      const item = allSkins[i]

      if (item.type === 'folder') {
        const isExpanded = expandedFolders[item.id] ?? item.expanded ?? true
        result.push({ type: 'folder', folder: item, isExpanded, arrayIndex: i })
        addedIndices.add(i)

        // If expanded, add all items belonging to this folder right after it
        if (isExpanded && folderItems[item.id]) {
          for (const folderItem of folderItems[item.id]) {
            result.push({ type: 'skin', skin: folderItem.skin, folderId: item.id, arrayIndex: folderItem.arrayIndex })
            addedIndices.add(folderItem.arrayIndex)
          }
        }
      } else if (item.visible !== false && !item.folder_id) {
        // Root item - add it
        result.push({ type: 'skin', skin: item, folderId: null, arrayIndex: i })
        addedIndices.add(i)
      }
      // Skip folder items here - they're added after their folder
    }

    return result
  }

  // Count skins in a folder (by folder_id)
  const countSkinsInFolder = (folderId, allSkins) => {
    return allSkins.filter(s => s.folder_id === folderId && s.visible !== false).length
  }

  // Determine folder membership based on position after reorder
  // Returns the folder_id the item should have at the given position
  const getFolderIdAtPosition = (allSkins, position) => {
    // Look backwards from position to find the context
    // If we find a skin with folder_id before hitting a folder or start, we're in that folder
    // If we find a folder, we're right after it (in that folder)
    // If we hit start or a skin without folder_id, we're at root
    for (let i = position - 1; i >= 0; i--) {
      const item = allSkins[i]
      if (item.type === 'folder') {
        // We're right after a folder - in that folder
        return item.id
      }
      if (item.folder_id) {
        // Previous item is in a folder - we're in that folder too
        return item.folder_id
      }
      // Previous item is at root level - we're at root
      return null
    }
    return null // At the start, root level
  }

  const toggleFolder = async (folderId) => {
    // Update local state immediately for responsive UI
    setExpandedFolders(prev => ({
      ...prev,
      [folderId]: !(prev[folderId] ?? true)
    }))

    // Also persist to backend
    try {
      await fetch(`${API_URL}/storage/folders/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          folderId
        })
      })
    } catch (err) {
      console.error('Toggle folder error:', err)
    }
  }

  const handleCreateFolder = async () => {
    try {
      const response = await fetch(`${API_URL}/storage/folders/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          name: 'New Folder'
        })
      })

      const data = await response.json()

      if (data.success) {
        await onRefresh()
        // Start editing the new folder name
        setEditingFolderId(data.folder.id)
        setEditingFolderName(data.folder.name)
      } else {
        alert(`Create folder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Create folder error:', err)
      alert(`Create folder error: ${err.message}`)
    }
  }

  const startEditingFolder = (folder) => {
    setEditingFolderId(folder.id)
    setEditingFolderName(folder.name)
  }

  const saveFolderName = async (folderId) => {
    if (!editingFolderName.trim()) {
      setEditingFolderId(null)
      return
    }

    try {
      const response = await fetch(`${API_URL}/storage/folders/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          folderId,
          newName: editingFolderName.trim()
        })
      })

      const data = await response.json()

      if (data.success) {
        await onRefresh()
      } else {
        alert(`Rename folder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Rename folder error:', err)
      alert(`Rename folder error: ${err.message}`)
    } finally {
      setEditingFolderId(null)
      setEditingFolderName('')
    }
  }

  const deleteFolder = async (folderId) => {
    if (!confirm('Delete this folder? Contents will be moved out, not deleted.')) {
      return
    }

    try {
      const response = await fetch(`${API_URL}/storage/folders/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          folderId
        })
      })

      const data = await response.json()

      if (data.success) {
        await onRefresh()
      } else {
        alert(`Delete folder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Delete folder error:', err)
      alert(`Delete folder error: ${err.message}`)
    }
  }

  const handleDropOnFolder = async (e, folderId) => {
    e.preventDefault()
    e.stopPropagation()

    if (!draggedItem) return

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/items/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          itemId: draggedItem.id,
          itemType: draggedItem.type || 'skin',
          targetFolderId: folderId,
          targetIndex: -1 // Append at end
        })
      })

      const data = await response.json()

      if (data.success) {
        await onRefresh()
      } else {
        alert(`Move to folder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Move to folder error:', err)
      alert(`Move to folder error: ${err.message}`)
    } finally {
      setReordering(false)
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      setDragTargetFolder(null)
    }
  }

  const handleItemReorder = async (fromIndex, toIndex, parentFolderId = null) => {
    if (fromIndex === toIndex) return

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/items/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          parentFolderId,
          fromIndex,
          toIndex
        })
      })

      const data = await response.json()

      if (data.success) {
        await onRefresh()
      } else {
        alert(`Reorder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    } finally {
      setReordering(false)
    }
  }

  // Context menu handlers
  const handleSkinContextMenu = (e, skin, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'skin',
      item: skin,
      index
    })
  }

  const handleVariantContextMenu = (e, variant, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'variant',
      item: variant,
      index
    })
  }

  const handleMoveToTop = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? `${API_URL}/storage/costumes/move-to-top`
        : `${API_URL}/storage/stages/move-to-top`

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refresh data
        if (contextMenu.type === 'skin') {
          await onRefresh()
        } else {
          await fetchStageVariants()
          await onRefresh()
        }
      } else {
        alert(`Move to top failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Move to top error:', err)
      alert(`Move to top error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const handleMoveToBottom = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? `${API_URL}/storage/costumes/move-to-bottom`
        : `${API_URL}/storage/stages/move-to-bottom`

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refresh data
        if (contextMenu.type === 'skin') {
          await onRefresh()
        } else {
          await fetchStageVariants()
          await onRefresh()
        }
      } else {
        alert(`Move to bottom failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Move to bottom error:', err)
      alert(`Move to bottom error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const closeContextMenu = () => {
    setContextMenu(null)
  }

  // Click-outside listener for context menu
  useEffect(() => {
    if (contextMenu) {
      const handleClick = () => closeContextMenu()
      document.addEventListener('click', handleClick)
      return () => document.removeEventListener('click', handleClick)
    }
  }, [contextMenu])

  // Merge default characters with metadata
  // Always show all 26 vanilla characters, even if they don't have custom skins
  const allCharacters = { ...metadata?.characters }

  // Add any missing default characters with 0 skins
  Object.keys(DEFAULT_CHARACTERS).forEach(charName => {
    if (!allCharacters[charName]) {
      allCharacters[charName] = { skins: [] }
    }
  })

  const characters = Object.keys(allCharacters).sort()

  // Skin Creator - Load vanilla costumes
  const loadVanillaCostumes = async (character) => {
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      const response = await fetch(`${API_URL}/vanilla/costumes/${character}`)
      const data = await response.json()
      if (data.success) {
        setVanillaCostumes(data.costumes)
      } else {
        setSkinCreatorError(data.error)
      }
    } catch (err) {
      setSkinCreatorError(err.message)
    } finally {
      setSkinCreatorLoading(false)
    }
  }

  // Skin Creator - Start viewer with selected costume
  const startSkinCreatorViewer = async (costume) => {
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      setSelectedVanillaCostume(costume)

      const response = await fetch(`${API_URL}/viewer/start-vanilla`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          costumeCode: costume.code
        })
      })

      const data = await response.json()
      if (!data.success) {
        throw new Error(data.error)
      }

      // Connect WebSocket
      const ws = new WebSocket(data.wsUrl)
      ws.binaryType = 'blob'

      ws.onopen = () => {
        setSkinCreatorLoading(false)
        setSkinCreatorStep('edit')
        // Request texture list
        ws.send(JSON.stringify({ type: 'getTextures' }))
      }

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          const bitmap = await createImageBitmap(event.data)
          const canvas = skinCreatorCanvasRef.current
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
            if (msg.type === 'textureList') {
              setModelTextures(msg.textures || [])
              if (msg.textures?.length > 0) {
                setSelectedTextureIndex(0)
              }
            } else if (msg.type === 'fullTexture') {
              // Load full texture onto paint canvas
              console.log('Received fullTexture', { index: msg.index, width: msg.width, height: msg.height, dataLength: msg.data?.length, error: msg.error })
              if (msg.error) {
                console.error('fullTexture error:', msg.error)
                return
              }
              if (!msg.data) {
                console.error('fullTexture: no data received')
                return
              }
              const canvas = paintCanvasRef.current
              console.log('Paint canvas ref:', canvas)
              if (canvas) {
                const img = new Image()
                img.onload = () => {
                  console.log('Image loaded', { imgWidth: img.width, imgHeight: img.height })
                  canvas.width = msg.width
                  canvas.height = msg.height
                  const ctx = canvas.getContext('2d')
                  ctx.imageSmoothingEnabled = false
                  ctx.drawImage(img, 0, 0)
                  console.log('Full texture loaded onto canvas', { canvasWidth: canvas.width, canvasHeight: canvas.height })
                }
                img.onerror = (err) => {
                  console.error('Failed to load texture image:', err)
                }
                img.src = `data:image/png;base64,${msg.data}`
              } else {
                console.error('Paint canvas not available')
              }
            } else if (msg.type === 'textureUpdated') {
              console.log('Received textureUpdated response:', msg)
            }
          } catch (e) {
            console.error('Error parsing WebSocket message:', e, event.data?.substring?.(0, 100))
          }
        }
      }

      ws.onerror = () => {
        setSkinCreatorError('WebSocket connection failed')
        setSkinCreatorLoading(false)
      }

      ws.onclose = () => {
        setViewerWs(null)
      }

      setViewerWs(ws)

    } catch (err) {
      setSkinCreatorError(err.message)
      setSkinCreatorLoading(false)
    }
  }

  // Skin Creator - Close and cleanup
  const closeSkinCreator = async () => {
    if (viewerWs) {
      viewerWs.close()
      setViewerWs(null)
    }
    // Stop the viewer backend
    try {
      await fetch(`${API_URL}/viewer/stop`, { method: 'POST' })
    } catch (e) {
      // Ignore errors on cleanup
    }
    setShowSkinCreator(false)
    setSkinCreatorStep('select')
    setVanillaCostumes([])
    setSelectedVanillaCostume(null)
    setSkinCreatorError(null)
    setModelTextures([])
    setSelectedTextureIndex(null)
  }

  // Skin Creator - Open and load costumes
  const openSkinCreator = () => {
    setShowSkinCreator(true)
    setSkinCreatorStep('select')
    loadVanillaCostumes(selectedCharacter)
  }

  // Skin Creator - Camera controls
  const sendViewerCamera = (deltas) => {
    if (viewerWs && viewerWs.readyState === WebSocket.OPEN) {
      viewerWs.send(JSON.stringify({ type: 'camera', ...deltas }))
    }
  }

  const handleViewerMouseDown = (e) => {
    e.preventDefault()
    setViewerDragging(true)
    setViewerDragButton(e.button)
    viewerLastMousePos.current = { x: e.clientX, y: e.clientY }
  }

  const handleViewerMouseMove = (e) => {
    if (!viewerDragging) return

    const deltaX = e.clientX - viewerLastMousePos.current.x
    const deltaY = e.clientY - viewerLastMousePos.current.y
    viewerLastMousePos.current = { x: e.clientX, y: e.clientY }

    if (viewerDragButton === 2) {
      // Right-click: Pan
      sendViewerCamera({ deltaX: -deltaX * 0.1, deltaY: deltaY * 0.1 })
    } else {
      // Left-click: Rotate
      sendViewerCamera({ deltaRotX: deltaY * 0.5, deltaRotY: deltaX * 0.5 })
    }
  }

  const handleViewerMouseUp = () => {
    setViewerDragging(false)
    setViewerDragButton(null)
  }

  const handleViewerWheel = (e) => {
    e.preventDefault()
    const zoomFactor = e.deltaY > 0 ? -0.1 : 0.1
    sendViewerCamera({ deltaZoom: zoomFactor })
  }

  const handleViewerContextMenu = (e) => {
    e.preventDefault()
  }

  // Skin Creator - Load texture onto paint canvas when selected
  // For now, use thumbnail as source (will upgrade to full res later)
  useEffect(() => {
    if (selectedTextureIndex === null || !modelTextures[selectedTextureIndex]) return

    const tex = modelTextures[selectedTextureIndex]
    const canvas = paintCanvasRef.current
    if (!canvas || !tex.thumbnail) {
      console.log('Cannot load texture - canvas or thumbnail missing', { canvas: !!canvas, thumbnail: !!tex.thumbnail })
      return
    }

    console.log('Loading texture onto canvas:', { index: selectedTextureIndex, width: tex.width, height: tex.height })

    const img = new Image()
    img.onload = () => {
      // Set canvas to actual texture size
      canvas.width = tex.width
      canvas.height = tex.height
      const ctx = canvas.getContext('2d')
      ctx.imageSmoothingEnabled = false
      // Draw thumbnail scaled up to full size (for testing)
      ctx.drawImage(img, 0, 0, tex.width, tex.height)
      console.log('Texture loaded onto canvas')
    }
    img.onerror = (err) => {
      console.error('Failed to load thumbnail image:', err)
    }
    img.src = `data:image/png;base64,${tex.thumbnail}`
  }, [selectedTextureIndex, modelTextures])

  // Skin Creator - Paint canvas mouse handlers
  const getCanvasCoords = (e) => {
    const canvas = paintCanvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    return {
      x: Math.floor((e.clientX - rect.left) * scaleX),
      y: Math.floor((e.clientY - rect.top) * scaleY)
    }
  }

  const drawPixel = (x, y) => {
    const canvas = paintCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ff0000' // Red for now
    ctx.fillRect(x, y, 1, 1)
  }

  // Bresenham's line algorithm to draw continuous lines
  const drawLine = (x0, y0, x1, y1) => {
    const dx = Math.abs(x1 - x0)
    const dy = Math.abs(y1 - y0)
    const sx = x0 < x1 ? 1 : -1
    const sy = y0 < y1 ? 1 : -1
    let err = dx - dy

    while (true) {
      drawPixel(x0, y0)
      if (x0 === x1 && y0 === y1) break
      const e2 = 2 * err
      if (e2 > -dy) { err -= dy; x0 += sx }
      if (e2 < dx) { err += dx; y0 += sy }
    }
  }

  const handlePaintMouseDown = (e) => {
    if (e.button !== 0) return // Left click only
    setIsDrawing(true)
    const coords = getCanvasCoords(e)
    if (coords) {
      drawPixel(coords.x, coords.y)
      lastDrawPos.current = coords
    }
  }

  const handlePaintMouseMove = (e) => {
    if (!isDrawing) return
    const coords = getCanvasCoords(e)
    if (coords) {
      if (lastDrawPos.current) {
        drawLine(lastDrawPos.current.x, lastDrawPos.current.y, coords.x, coords.y)
      } else {
        drawPixel(coords.x, coords.y)
      }
      lastDrawPos.current = coords
    }
  }

  const handlePaintMouseUp = () => {
    if (isDrawing) {
      setIsDrawing(false)
      lastDrawPos.current = null
      // Send updated texture to backend
      sendTextureUpdate()
    }
  }

  const sendTextureUpdate = () => {
    const canvas = paintCanvasRef.current
    console.log('sendTextureUpdate called', { canvas: !!canvas, ws: !!viewerWs, wsState: viewerWs?.readyState, selectedTextureIndex })
    if (!canvas || !viewerWs || viewerWs.readyState !== WebSocket.OPEN) {
      console.log('sendTextureUpdate: early return - missing canvas/ws or ws not open')
      return
    }
    if (selectedTextureIndex === null) return

    const ctx = canvas.getContext('2d')
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)

    // Convert to base64
    const tempCanvas = document.createElement('canvas')
    tempCanvas.width = canvas.width
    tempCanvas.height = canvas.height
    const tempCtx = tempCanvas.getContext('2d')
    tempCtx.putImageData(imageData, 0, 0)

    const dataUrl = tempCanvas.toDataURL('image/png')
    const base64 = dataUrl.replace('data:image/png;base64,', '')

    console.log('Sending updateTexture', { index: selectedTextureIndex, dataLength: base64.length, canvasSize: `${canvas.width}x${canvas.height}` })

    try {
      viewerWs.send(JSON.stringify({
        type: 'updateTexture',
        index: selectedTextureIndex,
        data: base64
      }))
      console.log('updateTexture sent successfully')
    } catch (err) {
      console.error('Error sending updateTexture:', err)
    }
  }

  // Skin Creator Modal
  const renderSkinCreator = () => (
    <>
      {showSkinCreator && (
        <div className="skin-creator-overlay">
          <div className="skin-creator-modal">
            {/* Header */}
            <div className="skin-creator-header">
              <div className="skin-creator-title">
                <h1>Skin Creator</h1>
                <span className="skin-creator-character">{selectedCharacter}</span>
                {selectedVanillaCostume && (
                  <span className="skin-creator-costume">{selectedVanillaCostume.colorName}</span>
                )}
              </div>
              <button
                className="skin-creator-close"
                onClick={closeSkinCreator}
                title="Close (Esc)"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                <span>Close</span>
              </button>
            </div>

            {/* Costume Selection Step */}
            {skinCreatorStep === 'select' && (
              <div className="skin-creator-select">
                <h2>Select a base costume</h2>
                <p>Choose a vanilla costume to use as your starting point</p>

                {skinCreatorLoading && (
                  <div className="skin-creator-loading">Loading costumes...</div>
                )}

                {skinCreatorError && (
                  <div className="skin-creator-error">{skinCreatorError}</div>
                )}

                <div className="skin-creator-costume-grid">
                  {vanillaCostumes.map(costume => (
                    <div
                      key={costume.code}
                      className="skin-creator-costume-card"
                      onClick={() => startSkinCreatorViewer(costume)}
                    >
                      <div className="costume-preview">
                        {costume.hasCsp ? (
                          <img
                            src={`${BACKEND_URL}/vanilla/${selectedCharacter}/${costume.code}/csp.png`}
                            alt={costume.colorName}
                          />
                        ) : (
                          <div className="costume-placeholder">{costume.colorCode}</div>
                        )}
                      </div>
                      <div className="costume-name">{costume.colorName}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Editor Step */}
            {skinCreatorStep === 'edit' && (
              <div className="skin-creator-body">
                {/* Left Panel - Texture List */}
                <div className="skin-creator-textures">
                  <div className="skin-creator-panel-header">Textures ({modelTextures.length})</div>
                  <div className="skin-creator-texture-list">
                    {modelTextures.length === 0 ? (
                      <div className="texture-loading">Loading textures...</div>
                    ) : (
                      modelTextures.map((tex, idx) => (
                        <div
                          key={idx}
                          className={`skin-creator-texture-item ${selectedTextureIndex === idx ? 'selected' : ''}`}
                          onClick={() => setSelectedTextureIndex(idx)}
                        >
                          <div className="texture-thumbnail">
                            {tex.thumbnail && (
                              <img src={`data:image/png;base64,${tex.thumbnail}`} alt={tex.name} />
                            )}
                          </div>
                          <div className="texture-info">
                            <span className="texture-name">{tex.name}</span>
                            <span className="texture-size">{tex.width}x{tex.height}</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Center - Paint Canvas */}
                <div className="skin-creator-canvas-area">
                  <div className="skin-creator-toolbar">
                    <button className="tool-btn active" title="Pencil">✏️</button>
                    <button className="tool-btn" title="Brush">🖌️</button>
                    <button className="tool-btn" title="Fill">🪣</button>
                    <button className="tool-btn" title="Eyedropper">💉</button>
                    <button className="tool-btn" title="Eraser">🧹</button>
                    <div className="toolbar-separator"></div>
                    <input type="color" className="color-picker" defaultValue="#ff0000" title="Color" />
                    <input type="range" className="brush-size" min="1" max="50" defaultValue="5" title="Brush Size" />
                  </div>
                  <div
                    className="skin-creator-canvas"
                    onMouseDown={handlePaintMouseDown}
                    onMouseMove={handlePaintMouseMove}
                    onMouseUp={handlePaintMouseUp}
                    onMouseLeave={handlePaintMouseUp}
                  >
                    {selectedTextureIndex === null ? (
                      <div className="canvas-placeholder">
                        <span>Paint Canvas</span>
                        <p>Select a texture to start editing</p>
                      </div>
                    ) : (
                      <canvas ref={paintCanvasRef} className="paint-canvas" />
                    )}
                  </div>
                </div>

                {/* Right Panel - 3D Viewer */}
                <div className="skin-creator-viewer">
                  <div className="skin-creator-panel-header">3D Preview</div>
                  <div
                    className="skin-creator-3d"
                    onMouseDown={handleViewerMouseDown}
                    onMouseMove={handleViewerMouseMove}
                    onMouseUp={handleViewerMouseUp}
                    onMouseLeave={handleViewerMouseUp}
                    onWheel={handleViewerWheel}
                    onContextMenu={handleViewerContextMenu}
                  >
                    {skinCreatorLoading ? (
                      <div className="viewer-placeholder">
                        <span>Loading...</span>
                      </div>
                    ) : (
                      <canvas ref={skinCreatorCanvasRef} className="viewer-canvas" />
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )

  // Edit Modal Component (reusable)
  const renderEditModal = () => (
    <>
      {showEditModal && editingItem && (
        <div className="edit-modal-fullscreen-overlay" onClick={handleCancel}>
          <div className="edit-modal-fullscreen" onClick={(e) => e.stopPropagation()}>
            {/* Close Button */}
            <button
              className="edit-modal-close"
              onClick={handleCancel}
              title="Close"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>

            {/* Modal Header */}
            <div className="edit-modal-header">
              <h2>Edit {editingItem.type === 'costume' ? 'Costume' : 'Stage Variant'}</h2>
            </div>

            {/* Main Content - Horizontal Layout */}
            <div className="edit-modal-body">
              {editingItem.type === 'costume' ? (
                <>
                  {/* LEFT: CSP Hero Image */}
                  <div className="edit-modal-csp-section">
                    <div className="edit-modal-csp-container">
                      {cspPreview ? (
                        <img
                          src={cspPreview}
                          alt="New CSP preview"
                          className="edit-modal-csp-image"
                        />
                      ) : editingItem.data.has_csp ? (
                        <img
                          src={`${editingItem.data.cspUrl}?t=${lastImageUpdate}`}
                          alt="CSP"
                          className="edit-modal-csp-image"
                          onError={(e) => e.target.style.display = 'none'}
                        />
                      ) : (
                        <div className="edit-modal-csp-placeholder">
                          <span>{editingItem.data.color[0]}</span>
                        </div>
                      )}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleCspChange}
                        style={{ display: 'none' }}
                        id="csp-file-input"
                      />
                      <button
                        className="edit-modal-image-edit-btn"
                        onClick={() => document.getElementById('csp-file-input').click()}
                        title="Replace CSP"
                      >
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                        <span>Edit CSP</span>
                      </button>
                    </div>
                    <div className="edit-modal-csp-label">Character Select Portrait</div>
                  </div>

                  {/* MIDDLE: Stock Icon + 3D Viewer */}
                  <div className="edit-modal-stock-section">
                    <div className="edit-modal-stock-container">
                      {stockPreview ? (
                        <img
                          src={stockPreview}
                          alt="New stock preview"
                          className="edit-modal-stock-image"
                        />
                      ) : editingItem.data.has_stock ? (
                        <img
                          src={`${editingItem.data.stockUrl}?t=${lastImageUpdate}`}
                          alt="Stock"
                          className="edit-modal-stock-image"
                          onError={(e) => e.target.style.display = 'none'}
                        />
                      ) : (
                        <div className="edit-modal-stock-placeholder">
                          <span>{editingItem.data.color[0]}</span>
                        </div>
                      )}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleStockChange}
                        style={{ display: 'none' }}
                        id="stock-file-input"
                      />
                      <button
                        className="edit-modal-image-edit-btn edit-modal-image-edit-btn--small"
                        onClick={() => document.getElementById('stock-file-input').click()}
                        title="Replace stock icon"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                      </button>
                    </div>
                    <div className="edit-modal-stock-label">Stock Icon</div>

                    {/* View 3D Button */}
                    <button
                      className="edit-modal-view3d-btn"
                      onClick={() => setShow3DViewer(true)}
                      disabled={saving || deleting || exporting}
                    >
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
                        <path d="M2 17l10 5 10-5"></path>
                        <path d="M2 12l10 5 10-5"></path>
                      </svg>
                      <span>View 3D Model</span>
                    </button>
                  </div>

                  {/* RIGHT: Controls Panel */}
                  <div className="edit-modal-controls-section">
                    {/* Color Name */}
                    <div className="edit-modal-field">
                      <label>Color Name</label>
                      <input
                        type="text"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder="Enter name..."
                        disabled={saving || deleting}
                        autoFocus
                      />
                    </div>

                    {/* Slippi Status Badge */}
                    <div className="edit-modal-slippi-section">
                      <div className={`edit-modal-slippi-badge ${editingItem.data.slippi_safe ? 'edit-modal-slippi-badge--safe' : 'edit-modal-slippi-badge--unsafe'}`}>
                        <div className="edit-modal-slippi-indicator"></div>
                        <span>{editingItem.data.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe'}</span>
                        {editingItem.data.slippi_manual_override && (
                          <span className="edit-modal-slippi-override">(Override)</span>
                        )}
                      </div>

                      {/* Collapsible Advanced Controls */}
                      <button
                        className="edit-modal-slippi-toggle"
                        onClick={() => setSlippiAdvancedOpen(!slippiAdvancedOpen)}
                      >
                        <span>Advanced</span>
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          style={{ transform: slippiAdvancedOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }}
                        >
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>

                      <div className={`edit-modal-slippi-advanced ${slippiAdvancedOpen ? 'edit-modal-slippi-advanced--open' : ''}`}>
                        <div className="edit-modal-slippi-advanced-inner">
                          {/* Character Info */}
                          <div className="edit-modal-info-card">
                            <div className="edit-modal-info-row">
                              <span className="edit-modal-info-label">Character</span>
                              <span className="edit-modal-info-value">{editingItem.data.character}</span>
                            </div>
                            <div className="edit-modal-info-row">
                              <span className="edit-modal-info-label">Slot ID</span>
                              <span className="edit-modal-info-value edit-modal-info-value--mono">{editingItem.data.id}</span>
                            </div>
                          </div>

                          <button
                            className="edit-modal-slippi-retest-btn"
                            onClick={() => handleSlippiRetest(false)}
                            disabled={saving || deleting}
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="23 4 23 10 17 10"></polyline>
                              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                            </svg>
                            Retest Safety
                          </button>

                          <div className="edit-modal-slippi-override-select">
                            <label>Manual Override</label>
                            <select
                              value={editingItem.data.slippi_safe ? 'safe' : 'unsafe'}
                              onChange={(e) => {
                                const newStatus = e.target.value === 'safe'
                                if (newStatus !== editingItem.data.slippi_safe) {
                                  handleSlippiOverride()
                                }
                              }}
                              disabled={saving || deleting}
                            >
                              <option value="safe">Slippi Safe</option>
                              <option value="unsafe">Not Slippi Safe</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                /* Stage Variant Layout - Simplified 2-column */
                <>
                  {/* LEFT: Stage Screenshot */}
                  <div className="edit-modal-csp-section">
                    <div className="edit-modal-csp-container">
                      {screenshotPreview ? (
                        <img
                          src={screenshotPreview}
                          alt="New screenshot preview"
                          className="edit-modal-csp-image"
                        />
                      ) : editingItem.data.hasScreenshot ? (
                        <img
                          src={editingItem.data.screenshotUrl}
                          alt="Preview"
                          className="edit-modal-csp-image"
                          onError={(e) => e.target.style.display = 'none'}
                        />
                      ) : (
                        <div className="edit-modal-csp-placeholder">
                          <span>{editingItem.data.name[0]}</span>
                        </div>
                      )}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleScreenshotChange}
                        style={{ display: 'none' }}
                        id="screenshot-file-input"
                      />
                      <button
                        className="edit-modal-image-edit-btn"
                        onClick={() => document.getElementById('screenshot-file-input').click()}
                        title="Replace screenshot"
                      >
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                        <span>Edit Screenshot</span>
                      </button>
                    </div>
                    <div className="edit-modal-csp-label">Stage Preview</div>
                  </div>

                  {/* RIGHT: Controls Panel for Stages */}
                  <div className="edit-modal-controls-section edit-modal-controls-section--wide">
                    {/* Variant Name */}
                    <div className="edit-modal-field">
                      <label>Variant Name</label>
                      <input
                        type="text"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder="Enter name..."
                        disabled={saving || deleting}
                        autoFocus
                      />
                    </div>

                    {/* Slippi Status Badge for Stages */}
                    <div className="edit-modal-slippi-section">
                      <div className={`edit-modal-slippi-badge ${
                        editSlippiSafe === null ? 'edit-modal-slippi-badge--unknown' :
                        editSlippiSafe ? 'edit-modal-slippi-badge--safe' : 'edit-modal-slippi-badge--unsafe'
                      }`}>
                        <div className="edit-modal-slippi-indicator"></div>
                        <span>
                          {editSlippiSafe === null ? 'Unknown' : editSlippiSafe ? 'Slippi Safe' : 'Not Slippi Safe'}
                        </span>
                      </div>

                      {/* Collapsible Advanced Controls */}
                      <button
                        className="edit-modal-slippi-toggle"
                        onClick={() => setSlippiAdvancedOpen(!slippiAdvancedOpen)}
                      >
                        <span>Advanced</span>
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          style={{ transform: slippiAdvancedOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }}
                        >
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>

                      <div className={`edit-modal-slippi-advanced ${slippiAdvancedOpen ? 'edit-modal-slippi-advanced--open' : ''}`}>
                        <div className="edit-modal-slippi-advanced-inner">
                          {/* Stage Info */}
                          <div className="edit-modal-info-card">
                            <div className="edit-modal-info-row">
                              <span className="edit-modal-info-label">Stage</span>
                              <span className="edit-modal-info-value">{editingItem.data.stageName}</span>
                            </div>
                            <div className="edit-modal-info-row">
                              <span className="edit-modal-info-label">Slot ID</span>
                              <span className="edit-modal-info-value edit-modal-info-value--mono">{editingItem.data.id}</span>
                            </div>
                          </div>

                          <p className="edit-modal-slippi-note">Stages cannot be auto-tested. Set manually.</p>
                          <div className="edit-modal-slippi-override-select">
                            <label>Safety Status</label>
                            <select
                              value={editSlippiSafe === null ? 'unknown' : (editSlippiSafe ? 'safe' : 'unsafe')}
                              onChange={(e) => {
                                const newValue = e.target.value
                                if (newValue === 'unknown') {
                                  setEditSlippiSafe(null)
                                } else {
                                  setEditSlippiSafe(newValue === 'safe')
                                }
                              }}
                              disabled={saving || deleting}
                            >
                              <option value="unknown">Unknown</option>
                              <option value="safe">Slippi Safe</option>
                              <option value="unsafe">Not Slippi Safe</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Bottom Action Bar */}
            <div className="edit-modal-actions">
              <button
                className="edit-modal-action-btn edit-modal-action-btn--save"
                onClick={handleSave}
                disabled={saving || deleting || exporting}
              >
                {saving ? (
                  <>
                    <span className="edit-modal-action-spinner"></span>
                    Saving...
                  </>
                ) : (
                  <>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                      <polyline points="17 21 17 13 7 13 7 21"></polyline>
                      <polyline points="7 3 7 8 15 8"></polyline>
                    </svg>
                    Save
                  </>
                )}
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--export"
                onClick={handleExport}
                disabled={saving || deleting || exporting}
              >
                {exporting ? (
                  <>
                    <span className="edit-modal-action-spinner"></span>
                    Exporting...
                  </>
                ) : (
                  <>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                    Export
                  </>
                )}
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--delete"
                onClick={handleDelete}
                disabled={saving || deleting || exporting}
              >
                {deleting ? (
                  <>
                    <span className="edit-modal-action-spinner"></span>
                    Deleting...
                  </>
                ) : (
                  <>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6"></polyline>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                    Delete
                  </>
                )}
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--cancel"
                onClick={handleCancel}
                disabled={saving || deleting || exporting}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 3D Model Viewer */}
      {show3DViewer && editingItem && editingItem.type === 'costume' && (
        <ModelViewer
          character={editingItem.data.character}
          skinId={editingItem.data.id}
          onClose={() => setShow3DViewer(false)}
        />
      )}
    </>
  )

  const renderSlippiDialog = () => {
    const isRetest = retestingItem !== null
    const handleChoice = isRetest ? handleRetestFixChoice : handleSlippiChoice

    return (
      <>
        {showSlippiDialog && slippiDialogData && (
          <div className="edit-modal-overlay" onClick={() => handleChoice('cancel')}>
            <div className="edit-modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
              <h2>Slippi Safety Warning</h2>

              <div style={{ padding: '1rem 0' }}>
                <p style={{ marginBottom: '1rem' }}>
                  This costume is not Slippi safe. Choose an action:
                </p>

                {slippiDialogData.unsafe_costumes && (
                  <div style={{
                    backgroundColor: '#fff3cd',
                    border: '1px solid #ffc107',
                    borderRadius: '4px',
                    padding: '0.75rem',
                    marginBottom: '1rem'
                  }}>
                    <strong>Affected costumes:</strong>
                    <ul style={{ marginTop: '0.5rem', marginBottom: 0 }}>
                      {slippiDialogData.unsafe_costumes.map((costume, idx) => (
                        <li key={idx}>{costume.character} - {costume.color}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button
                  className="btn-save"
                  onClick={() => handleChoice('fix')}
                  style={{ width: '100%' }}
                >
                  {isRetest ? 'Fix' : 'Fix & Import'}
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => handleChoice('import_as_is')}
                  style={{ width: '100%' }}
                >
                  {isRetest ? 'Keep As-Is' : 'Import As-Is'}
                </button>
                <button
                  className="btn-cancel"
                  onClick={() => handleChoice('cancel')}
                  style={{ width: '100%' }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    )
  }

  // Context menu component
  const renderContextMenu = () => {
    if (!contextMenu) return null

    return (
      <div
        className="context-menu"
        style={{ top: contextMenu.y, left: contextMenu.x }}
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={handleMoveToTop}>Move to Top</button>
        <button onClick={handleMoveToBottom}>Move to Bottom</button>
      </div>
    )
  }

  // If a stage is selected, show its variants
  if (selectedStage) {
    const stageInfo = selectedStage
    const variants = stageVariants[selectedStage.code] || []

    return (
      <div className="storage-viewer">
        <div className="character-detail">
          <button
            onClick={() => setSelectedStage(null)}
            className="back-button"
          >
            ← Back to Stages
          </button>

          <h2>{stageInfo?.name}</h2>
          <p className="skin-count">{variants.length} variant{variants.length !== 1 ? 's' : ''}</p>

          {variants.length === 0 ? (
            <div className="no-skins-message">
              <p>No stage variants yet. Add some to your storage!</p>
            </div>
          ) : (
            <div className="skins-grid">
              {(previewOrder || variants).map((variant, idx) => {
                const isDragging = draggedItem && variant.id === draggedItem.id
                return (
                  <div
                    key={variant.id}
                    className={`skin-card ${isDragging ? 'dragging' : ''}`}
                    draggable={!reordering}
                    onDragStart={(e) => handleDragStart(e, variants.findIndex(v => v.id === variant.id), variants)}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleDragEnter(e, idx, variants)}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleVariantDrop(e, idx)}
                    onDragEnd={handleDragEnd}
                    onContextMenu={(e) => handleVariantContextMenu(e, variant, idx)}
                    style={{ opacity: isDragging ? 0.5 : 1 }}
                  >
                  <div className="skin-images">
                    <div className="skin-image-container">
                      {variant.hasScreenshot ? (
                        <img
                          src={`${API_URL.replace('/api/mex', '')}${variant.screenshotUrl}`}
                          alt={variant.name}
                          className="skin-csp"
                          onError={(e) => {
                            e.target.style.display = 'none'
                            e.target.nextSibling.style.display = 'flex'
                          }}
                        />
                      ) : (
                        <div className="skin-placeholder" style={{ display: 'flex' }}>
                          <span className="skin-initial">{variant.name[0]}</span>
                        </div>
                      )}
                      {/* Slippi badge for stages - show unknown if not set */}
                      <div style={{
                        position: 'absolute',
                        top: '8px',
                        left: '8px',
                        backgroundColor: variant.slippi_tested
                          ? (variant.slippi_safe ? '#28a745' : '#dc3545')
                          : '#6c757d',
                        color: 'white',
                        padding: '4px 8px',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 'bold',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                      }}>
                        {variant.slippi_tested
                          ? (variant.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe')
                          : 'Unknown'}
                      </div>
                      <button
                        className="btn-edit"
                        onClick={(e) => {
                          e.stopPropagation()
                          e.preventDefault()
                          handleEditClick('stage', {
                            id: variant.id,  // ← Use the immutable ID for API calls
                            name: variant.name,  // ← Use the editable name for display
                            stageCode: stageInfo?.code,
                            stageFolder: stageInfo?.folder,
                            stageName: stageInfo?.name,
                            screenshotUrl: variant.screenshotUrl,
                            hasScreenshot: variant.hasScreenshot,
                            slippi_safe: variant.slippi_safe,
                            slippi_tested: variant.slippi_tested
                          })
                        }}
                        title="Edit variant"
                      >
                        ✎
                      </button>
                    </div>
                  </div>

                  <div className="skin-info">
                    <div className="skin-color">{variant.name}</div>
                  </div>
                </div>
              )
            })}
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
        {renderContextMenu()}
      </div>
    )
  }

  // If a character is selected, show their skins
  if (selectedCharacter) {
    const charData = allCharacters[selectedCharacter]
    // Get all skins (including folders) from character data
    const allSkins = charData?.skins || []
    // Filter to just actual skins (not folders) for the count
    const skinCount = allSkins.filter(s => s.type !== 'folder' && s.visible !== false).length
    // Build display list (handles folder collapse/expand)
    const displayList = buildDisplayList(allSkins)

    // Helper to delete a folder
    const handleDeleteFolder = async (folderId) => {
      try {
        const response = await fetch(`${API_URL}/storage/folders/delete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            character: selectedCharacter,
            folderId
          })
        })

        const data = await response.json()
        if (data.success) {
          await onRefresh()
        } else {
          alert(`Failed to delete folder: ${data.error}`)
        }
      } catch (err) {
        console.error('Delete folder error:', err)
        alert(`Error deleting folder: ${err.message}`)
      }
    }

    // Render a folder card
    const renderFolderCard = (folder, isExpanded, displayIdx, arrayIdx) => {
      const isEditing = editingFolderId === folder.id
      const folderSkinCount = countSkinsInFolder(folder.id, allSkins)
      const isDragging = draggedItem && draggedItem.id === folder.id

      return (
        <div
          key={folder.id}
          className={`folder-card ${isExpanded ? 'expanded' : ''} ${isDragging ? 'dragging' : ''}`}
          draggable={!reordering && !isEditing}
          onDragStart={(e) => handleDragStart(e, arrayIdx, allSkins)}
          onDragOver={handleDragOver}
          onDragEnter={(e) => handleDragEnter(e, displayIdx, displayList)}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleItemDrop(e, displayIdx)}
          onDragEnd={handleDragEnd}
        >
          <div className="folder-header" onClick={() => toggleFolder(folder.id)}>
            <span className="folder-chevron">{isExpanded ? '▼' : '▶'}</span>
            {isEditing ? (
              <input
                className="folder-name-input"
                value={editingFolderName}
                onChange={(e) => setEditingFolderName(e.target.value)}
                onBlur={() => saveFolderName(folder.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveFolderName(folder.id)
                  if (e.key === 'Escape') setEditingFolderId(null)
                }}
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="folder-name">{folder.name}</span>
            )}
            <span className="folder-count">{folderSkinCount}</span>
          </div>
          <div className="folder-actions">
            <button
              onClick={(e) => {
                e.stopPropagation()
                startEditingFolder(folder)
              }}
              title="Rename folder"
            >
              ✎
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleDeleteFolder(folder.id)
              }}
              title="Delete folder"
            >
              ×
            </button>
          </div>
        </div>
      )
    }

    // Custom drop handler that converts display index to allSkins index
    const handleItemDrop = async (e, displayIdx) => {
      e.preventDefault()
      if (!draggedItem) return

      const fromIndex = dragStartIndex
      const targetItem = displayList[displayIdx]
      const toIndex = targetItem?.arrayIndex ?? allSkins.length - 1

      if (fromIndex === toIndex || !selectedCharacter) {
        setDraggedItem(null)
        setDragStartIndex(null)
        setDragOverIndex(null)
        setPreviewOrder(null)
        return
      }

      setReordering(true)

      try {
        const response = await fetch(`${API_URL}/storage/costumes/reorder`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            character: selectedCharacter,
            fromIndex,
            toIndex
          })
        })

        const data = await response.json()

        if (data.success) {
          await onRefresh()
        } else {
          alert(`Reorder failed: ${data.error}`)
        }
      } catch (err) {
        console.error('Reorder error:', err)
        alert(`Reorder error: ${err.message}`)
      } finally {
        setReordering(false)
        setDraggedItem(null)
        setDragStartIndex(null)
        setDragOverIndex(null)
        setPreviewOrder(null)
      }
    }

    // Render a skin card
    const renderSkinCard = (skin, folderId, displayIdx, arrayIdx) => {
      const isDragging = draggedItem && skin.id === draggedItem.id

      return (
        <div
          key={skin.id}
          className={`skin-card ${isDragging ? 'dragging' : ''} ${folderId ? 'in-folder' : ''}`}
          draggable={!reordering}
          onDragStart={(e) => handleDragStart(e, arrayIdx, allSkins)}
          onDragOver={handleDragOver}
          onDragEnter={(e) => handleDragEnter(e, displayIdx, displayList)}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleItemDrop(e, displayIdx)}
          onDragEnd={handleDragEnd}
          onContextMenu={(e) => handleSkinContextMenu(e, skin, arrayIdx)}
          style={{ opacity: isDragging ? 0.5 : 1 }}
        >
          <div className="skin-image-container">
            {skin.has_csp ? (
              <img
                src={`${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_csp.png?t=${lastImageUpdate}`}
                alt={`${selectedCharacter} - ${skin.color}`}
                className="skin-csp"
                onError={(e) => {
                  e.target.style.display = 'none'
                  e.target.nextSibling.style.display = 'flex'
                }}
              />
            ) : null}
            <div className="skin-placeholder" style={{ display: skin.has_csp ? 'none' : 'flex' }}>
              <span className="skin-initial">{skin.color[0]}</span>
            </div>
            <button
              className="btn-edit"
              onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                handleEditClick('costume', {
                  id: skin.id,
                  character: selectedCharacter,
                  color: skin.color,
                  has_csp: skin.has_csp,
                  has_stock: skin.has_stock,
                  cspUrl: `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_csp.png`,
                  stockUrl: skin.has_stock ? `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_stc.png` : null,
                  slippi_safe: skin.slippi_safe,
                  slippi_tested: skin.slippi_tested,
                  slippi_manual_override: skin.slippi_manual_override
                })
              }}
              title="Edit costume"
            >
              ✎
            </button>
          </div>

          <div className="skin-badges-row">
            {skin.has_stock && (
              <div className="stock-icon-small">
                <img
                  src={`${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_stc.png?t=${lastImageUpdate}`}
                  alt={`${selectedCharacter} stock`}
                  className="skin-stock"
                />
              </div>
            )}
            {skin.slippi_tested && (
              <div className={`slippi-badge-small ${skin.slippi_safe ? 'safe' : 'unsafe'}`}>
                {skin.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe'}
              </div>
            )}
          </div>

          <div className="skin-info">
            <div className="skin-color">{skin.color}</div>
          </div>
        </div>
      )
    }

    return (
      <div className="storage-viewer">
        <div className="character-detail">
          <div className="character-header">
            <button
              onClick={() => setSelectedCharacter(null)}
              className="back-button"
            >
              ← Back to Characters
            </button>
            <button
              onClick={handleCreateFolder}
              className="create-folder-button"
              title="Create new folder"
            >
              + New Folder
            </button>
          </div>

          <h2>{selectedCharacter}</h2>
          <p className="skin-count">{skinCount} skin{skinCount !== 1 ? 's' : ''}</p>

          {skinCount === 0 && displayList.filter(d => d.type === 'folder').length === 0 ? (
            <div className="no-skins-message">
              <p>No custom skins yet. Add some using the intake system!</p>
            </div>
          ) : (
            <div className="skins-grid">
              {displayList.map((item, idx) => {
                if (item.type === 'folder') {
                  return renderFolderCard(item.folder, item.isExpanded, idx, item.arrayIndex)
                } else {
                  return renderSkinCard(item.skin, item.folderId, idx, item.arrayIndex)
                }
              })}
              <div
                className="skin-card create-mod-card"
                onClick={openSkinCreator}
              >
                <div className="skin-image-container">
                  <div className="create-mod-placeholder">
                    <span className="create-mod-icon">+</span>
                  </div>
                </div>
                <div className="skin-info">
                  <div className="skin-color">Create New Mod</div>
                </div>
              </div>
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
        {renderContextMenu()}
        {renderSkinCreator()}
      </div>
    )
  }

  // Character or Stage selection grid
  return (
    <div className="storage-viewer">
      {/* Mode Switcher */}
      <div className="mode-switcher">
        <button
          className={`mode-btn ${mode === 'characters' ? 'active' : ''}`}
          onClick={() => {
            setMode('characters')
            setSelectedStage(null)
          }}
        >
          Characters
        </button>
        <button
          className={`mode-btn ${mode === 'stages' ? 'active' : ''}`}
          onClick={() => {
            setMode('stages')
            setSelectedCharacter(null)
          }}
        >
          Stages
        </button>
        <button
          className={`mode-btn ${mode === 'patches' ? 'active' : ''}`}
          onClick={() => {
            setMode('patches')
            setSelectedCharacter(null)
            setSelectedStage(null)
          }}
        >
          Patches
        </button>
      </div>

      {/* Import File button - only for characters and stages */}
      {(mode === 'characters' || mode === 'stages') && (
        <div className="import-file-container">
          <label className="intake-import-btn" style={{ cursor: importing ? 'not-allowed' : 'pointer', opacity: importing ? 0.6 : 1 }}>
            {importing ? 'Importing...' : 'Import File'}
            <input
              type="file"
              accept=".zip,.7z"
              onChange={handleFileImport}
              disabled={importing}
              style={{ display: 'none' }}
            />
          </label>
          {importMessage && (
            <div className={`import-message ${importMessage.includes('failed') || importMessage.includes('Error') || importMessage.includes('✗') ? 'error' : 'success'}`}>
              {importMessage}
            </div>
          )}
        </div>
      )}

      {mode === 'characters' ? (
        <div className="characters-grid">
        {isLoading ? (
          // Skeleton loading for characters
          Array.from({ length: 12 }).map((_, idx) => (
            <SkeletonCard key={`skeleton-${idx}`} />
          ))
        ) : characters.map((characterName) => {
          const charData = allCharacters[characterName]
          // Only count visible skins (exclude hidden Ice Climbers Nana entries)
          const visibleSkins = charData?.skins?.filter(skin => skin.visible !== false) || []
          const skinCount = visibleSkins.length

          // ALWAYS use vanilla default costume code from DEFAULT_CHARACTERS
          const costumeCode = DEFAULT_CHARACTERS[characterName]?.defaultCostume

          // ALWAYS use vanilla CSP on homepage for consistency (like vanilla game)
          const vanillaCspPath = costumeCode
            ? `${BACKEND_URL}/vanilla/${characterName}/${costumeCode}/csp.png`
            : null

          return (
            <div
              key={characterName}
              className="character-card"
              onClick={() => setSelectedCharacter(characterName)}
            >
              <div className="character-image-container">
                {vanillaCspPath ? (
                  <img
                    src={vanillaCspPath}
                    alt={characterName}
                    className="character-csp"
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                ) : null}
                <div className="character-placeholder" style={{ display: vanillaCspPath ? 'none' : 'flex' }}>
                  <span className="character-initial">{characterName[0]}</span>
                </div>
              </div>

              <h3 className="character-name">{characterName}</h3>
              <p className="skin-count">{skinCount} skin{skinCount !== 1 ? 's' : ''}</p>
            </div>
          )
        })}
      </div>
      ) : mode === 'stages' ? (
        // Stages grid
        <div className="stages-grid">
          {isLoading ? (
            // Skeleton loading for stages
            Array.from({ length: 6 }).map((_, idx) => (
              <SkeletonCard key={`skeleton-stage-${idx}`} />
            ))
          ) : DAS_STAGES.map((stage) => {
            const variants = stageVariants[stage.code] || []
            const variantCount = variants.length

            // ALWAYS use vanilla stage screenshot (like how characters use vanilla CSPs)
            const vanillaImagePath = stage.vanillaImage

            return (
              <div
                key={stage.code}
                className="character-card"
                onClick={() => setSelectedStage(stage)}
              >
                <div className="character-image-container">
                  <img
                    src={vanillaImagePath}
                    alt={stage.name}
                    className="character-csp"
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                  <div className="character-placeholder" style={{ display: 'none' }}>
                    <span className="character-initial">{stage.name[0]}</span>
                  </div>
                </div>

                <h3 className="character-name">{stage.name}</h3>
                <p className="skin-count">{variantCount} variant{variantCount !== 1 ? 's' : ''}</p>
              </div>
            )
          })}
        </div>
      ) : (
        // Patches list
        <div className="patches-section">
          <div className="patches-header">
            <button
              className="intake-import-btn"
              onClick={() => setShowXdeltaImportModal(true)}
            >
              Import Patch
            </button>
          </div>

          <div className="patches-list">
            {xdeltaPatches.map((patch) => (
              <div key={patch.id} className="patch-row">
                <div className="patch-row-image">
                  {patch.imageUrl ? (
                    <img
                      src={`${BACKEND_URL}${patch.imageUrl}`}
                      alt={patch.name}
                      onError={(e) => {
                        e.target.style.display = 'none'
                        e.target.nextSibling.style.display = 'flex'
                      }}
                    />
                  ) : null}
                  <div className="patch-row-placeholder" style={{ display: patch.imageUrl ? 'none' : 'flex' }}>
                    {patch.name[0]}
                  </div>
                </div>

                <div className="patch-row-info">
                  <h4 className="patch-row-name">{patch.name}</h4>
                  {patch.description && (
                    <p className="patch-row-description">{patch.description}</p>
                  )}
                  {patch.size && (
                    <p className="patch-row-size" style={{ fontSize: '0.8em', color: 'var(--color-text-muted)', margin: 0 }}>
                      {(patch.size / (1024 * 1024)).toFixed(2)} MB
                    </p>
                  )}
                </div>

                <div className="patch-row-actions">
                  <button
                    className="btn-edit-small"
                    onClick={() => handleEditXdelta(patch)}
                    title="Edit"
                  >
                    ✎
                  </button>
                  <button
                    className="btn-edit-small"
                    onClick={() => handleDownloadPatch(patch.id)}
                    title="Download Patch"
                    style={{ fontSize: '14px' }}
                  >
                    ⬇
                  </button>
                  <button
                    className="btn-build-iso"
                    onClick={() => handleBuildXdeltaIso(patch)}
                  >
                    Build ISO
                  </button>
                </div>
              </div>
            ))}

            {/* Create New Patch Card */}
            <div
              className="patch-row create-patch-row"
              onClick={() => setShowXdeltaCreateModal(true)}
              style={{ cursor: 'pointer', borderStyle: 'dashed' }}
            >
              <div className="patch-row-image">
                <div className="patch-row-placeholder" style={{ display: 'flex', fontSize: '2rem' }}>
                  +
                </div>
              </div>

              <div className="patch-row-info">
                <h4 className="patch-row-name">Create New Patch</h4>
                <p className="patch-row-description">Create a patch from a modded ISO</p>
              </div>

              <div className="patch-row-actions">
                <button
                  className="btn-build-iso"
                  onClick={(e) => {
                    e.stopPropagation()
                    setShowXdeltaCreateModal(true)
                  }}
                >
                  Create
                </button>
              </div>
            </div>
          </div>

          {/* XDelta Import Modal */}
          {showXdeltaImportModal && (
            <div className="edit-modal-overlay" onClick={() => setShowXdeltaImportModal(false)}>
              <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
                <h2>Import XDelta Patch</h2>

                <div className="edit-field">
                  <label>XDelta File:</label>
                  <input
                    type="file"
                    accept=".xdelta"
                    onChange={(e) => setXdeltaImportData({
                      ...xdeltaImportData,
                      file: e.target.files[0],
                      name: xdeltaImportData.name || (e.target.files[0]?.name.replace('.xdelta', '') || '')
                    })}
                  />
                </div>

                <div className="edit-field">
                  <label>Name:</label>
                  <input
                    type="text"
                    value={xdeltaImportData.name}
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, name: e.target.value })}
                    placeholder="Patch name..."
                  />
                </div>

                <div className="edit-field">
                  <label>Description (optional):</label>
                  <textarea
                    value={xdeltaImportData.description}
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, description: e.target.value })}
                    placeholder="Description..."
                    rows={3}
                  />
                </div>

                <div className="edit-field">
                  <label>Image (optional):</label>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, image: e.target.files[0] })}
                  />
                </div>

                <div className="edit-buttons">
                  <button
                    className="btn-save"
                    onClick={handleImportXdelta}
                    disabled={importingXdelta || !xdeltaImportData.file}
                  >
                    {importingXdelta ? 'Importing...' : 'Import'}
                  </button>
                  <button
                    className="btn-cancel"
                    onClick={() => {
                      setShowXdeltaImportModal(false)
                      setXdeltaImportData({ name: '', description: '', file: null, image: null })
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* XDelta Edit Modal */}
          {showXdeltaEditModal && editingXdelta && (
            <div className="edit-modal-overlay" onClick={() => {
              setShowXdeltaEditModal(false)
              setEditingXdelta(null)
            }}>
              <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
                <h2>Edit Patch</h2>

                <div className="edit-preview">
                  {editingXdelta.imageUrl ? (
                    <img
                      src={`${BACKEND_URL}${editingXdelta.imageUrl}?t=${Date.now()}`}
                      alt={editingXdelta.name}
                    />
                  ) : (
                    <div className="edit-placeholder">
                      <span>{editingXdelta.name[0]}</span>
                    </div>
                  )}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleUpdateXdeltaImage}
                    style={{ display: 'none' }}
                    id="xdelta-image-input"
                  />
                  <button
                    className="btn-edit-screenshot"
                    onClick={() => document.getElementById('xdelta-image-input').click()}
                    title="Replace image"
                  >
                    ✎
                  </button>
                </div>

                <div className="edit-field">
                  <label>Name:</label>
                  <input
                    type="text"
                    value={editingXdelta.name}
                    onChange={(e) => setEditingXdelta({ ...editingXdelta, name: e.target.value })}
                  />
                </div>

                <div className="edit-field">
                  <label>Description:</label>
                  <textarea
                    value={editingXdelta.description || ''}
                    onChange={(e) => setEditingXdelta({ ...editingXdelta, description: e.target.value })}
                    rows={3}
                  />
                </div>

                <div className="edit-buttons">
                  <button className="btn-save" onClick={handleSaveXdeltaEdit}>
                    Save
                  </button>
                  <button
                    className="btn-cancel"
                    onClick={() => {
                      setShowXdeltaEditModal(false)
                      setEditingXdelta(null)
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn-delete-modal"
                    onClick={() => {
                      handleDeleteXdelta(editingXdelta.id)
                      setShowXdeltaEditModal(false)
                      setEditingXdelta(null)
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* XDelta Create Patch Modal */}
          {showXdeltaCreateModal && (
            <div className="iso-builder-overlay">
              <div className="iso-builder-modal">
                <div className="modal-header">
                  <h2>Create New Patch</h2>
                  {xdeltaCreateState !== 'creating' && (
                    <button className="close-btn" onClick={closeXdeltaCreateModal}>×</button>
                  )}
                </div>

                <div className="modal-body">
                  {xdeltaCreateState === 'idle' && (
                    <div className="create-patch-form">
                      <p style={{ color: 'var(--color-text-secondary)', marginBottom: '1.5rem' }}>
                        Create a patch by comparing a modded ISO against your vanilla ISO.
                        The patch can then be shared and applied to recreate the modded ISO.
                      </p>

                      <div className="edit-field">
                        <label>Patch Name:</label>
                        <input
                          type="text"
                          value={xdeltaCreateData.name}
                          onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, name: e.target.value })}
                          placeholder="My Awesome Mod Pack"
                        />
                      </div>

                      <div className="edit-field">
                        <label>Description (optional):</label>
                        <textarea
                          value={xdeltaCreateData.description}
                          onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, description: e.target.value })}
                          placeholder="Describe what's in this patch..."
                          rows={3}
                        />
                      </div>

                      <div className="edit-field">
                        <label>Modded ISO:</label>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                          <input
                            type="text"
                            value={xdeltaCreateData.moddedIsoPath}
                            onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, moddedIsoPath: e.target.value })}
                            placeholder="Select a modded ISO file..."
                            readOnly
                            style={{ flex: 1 }}
                          />
                          <button
                            className="btn-secondary"
                            onClick={handleSelectModdedIso}
                            style={{ whiteSpace: 'nowrap' }}
                          >
                            Browse...
                          </button>
                        </div>
                      </div>

                      <div className="edit-buttons" style={{ marginTop: '1.5rem' }}>
                        <button
                          className="btn-save"
                          onClick={handleStartCreateXdelta}
                          disabled={!xdeltaCreateData.moddedIsoPath || !xdeltaCreateData.name.trim()}
                        >
                          Create Patch
                        </button>
                        <button className="btn-cancel" onClick={closeXdeltaCreateModal}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {xdeltaCreateState === 'creating' && (
                    <div className="export-progress" style={{ textAlign: 'center' }}>
                      <div className="export-spinner">
                        <div className="spinner"></div>
                      </div>

                      <h3 style={{ marginTop: '1rem' }}>Creating Patch...</h3>

                      <p className="progress-message">
                        {xdeltaCreateMessage || 'Comparing ISOs...'}
                      </p>
                    </div>
                  )}

                  {xdeltaCreateState === 'complete' && xdeltaCreateResult && (
                    <div className="export-complete">
                      <div className="success-icon">✓</div>
                      <h3>Patch Created!</h3>
                      <p>Your patch "{xdeltaCreateResult.name}" has been created.</p>
                      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9em' }}>
                        Size: {xdeltaCreateResult.size_mb} MB
                        {xdeltaCreateResult.size_mb < 25 && (
                          <span style={{ color: 'var(--color-success)', marginLeft: '0.5rem' }}>
                            (Discord-friendly!)
                          </span>
                        )}
                      </p>
                      <div className="complete-actions">
                        <button
                          className="btn-download"
                          onClick={() => handleDownloadPatch(xdeltaCreateResult.patch_id)}
                        >
                          Download Patch
                        </button>
                        <button className="btn-secondary" onClick={closeXdeltaCreateModal}>
                          Close
                        </button>
                      </div>
                    </div>
                  )}

                  {xdeltaCreateState === 'error' && (
                    <div className="export-error">
                      <div className="error-icon">✕</div>
                      <h3>Creation Failed</h3>
                      <p className="error-message">{xdeltaCreateError}</p>
                      <button className="btn-secondary" onClick={closeXdeltaCreateModal}>
                        Close
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {renderEditModal()}
      {renderSlippiDialog()}

      {/* XDelta Build Modal */}
      {showXdeltaBuildModal && (
        <div className="iso-builder-overlay">
          <div className="iso-builder-modal">
            <div className="modal-header">
              <h2>Build ISO</h2>
              {xdeltaBuildState !== 'building' && (
                <button className="close-btn" onClick={closeXdeltaBuildModal}>×</button>
              )}
            </div>

            <div className="modal-body">
              {xdeltaBuildState === 'building' && (
                <div className="export-progress">
                  <div className="progress-header">
                    <h3>Building ISO...</h3>
                    <span className="progress-percentage">{xdeltaBuildProgress}%</span>
                  </div>

                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{ width: `${xdeltaBuildProgress}%` }}
                    ></div>
                  </div>

                  <p className="progress-message">
                    {xdeltaBuildMessage || `Applying patch: ${xdeltaBuildPatch?.name}`}
                  </p>

                  <div className="export-spinner">
                    <div className="spinner"></div>
                  </div>
                </div>
              )}

              {xdeltaBuildState === 'complete' && (
                <div className="export-complete">
                  <div className="success-icon">✓</div>
                  <h3>Build Complete!</h3>
                  <p>Your patched ISO is ready to download.</p>
                  <div className="complete-actions">
                    <button className="btn-download" onClick={handleDownloadXdeltaIso}>
                      Download {xdeltaBuildFilename}
                    </button>
                    <button className="btn-secondary" onClick={closeXdeltaBuildModal}>
                      Close
                    </button>
                  </div>
                </div>
              )}

              {xdeltaBuildState === 'error' && (
                <div className="export-error">
                  <div className="error-icon">✕</div>
                  <h3>Build Failed</h3>
                  <p className="error-message">{xdeltaBuildError}</p>
                  <button className="btn-secondary" onClick={closeXdeltaBuildModal}>
                    Close
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

