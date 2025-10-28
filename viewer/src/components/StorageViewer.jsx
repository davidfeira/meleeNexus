import { useState, useEffect } from 'react'
import './StorageViewer.css'
import { DEFAULT_CHARACTERS } from '../defaultCharacters'

const API_URL = 'http://127.0.0.1:5000/api/mex'

const DAS_STAGES = [
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: '/vanilla/stages/battlefield.jpg' },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: '/vanilla/stages/final destination.png' },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: '/vanilla/stages/Yoshis story.jpg' },
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: '/vanilla/stages/dreamland.jpg' },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: '/vanilla/stages/pokemon stadium.jpg' },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: '/vanilla/stages/Fountain of Dreams.webp' }
]

export default function StorageViewer({ metadata }) {
  const [mode, setMode] = useState('characters') // 'characters' or 'stages'
  const [selectedCharacter, setSelectedCharacter] = useState(null)
  const [selectedStage, setSelectedStage] = useState(null)
  const [stageVariants, setStageVariants] = useState({})
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')

  // Edit modal state
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingItem, setEditingItem] = useState(null) // { type: 'costume'/'stage', data: {...} }
  const [editName, setEditName] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [newScreenshot, setNewScreenshot] = useState(null) // File object for new screenshot
  const [screenshotPreview, setScreenshotPreview] = useState(null) // Preview URL for new screenshot

  // Fetch stage variants when in stages mode
  useEffect(() => {
    if (mode === 'stages') {
      fetchStageVariants()
    }
  }, [mode])

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

  const handleFileImport = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    setImporting(true)
    setImportMessage('Uploading and detecting mod type...')

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_URL}/import/file`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()

      if (data.success) {
        const typeMsg = data.type === 'character'
          ? `${data.character} - ${data.color}`
          : `${data.stage} stage`
        setImportMessage(`✓ Imported ${typeMsg}! Refreshing...`)
        setTimeout(() => {
          window.location.reload()
        }, 1500)
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
    event.target.value = null
  }

  const handleEditClick = (type, data) => {
    const item = { type, data }
    const name = type === 'costume' ? data.color : data.name
    setEditingItem(item)
    setEditName(name)
    setNewScreenshot(null)
    setScreenshotPreview(null)
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

      setShowEditModal(false)
      setEditingItem(null)
      window.location.reload()
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
        setShowEditModal(false)
        setEditingItem(null)
        window.location.reload()
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleCancel = () => {
    setShowEditModal(false)
    setEditingItem(null)
    setEditName('')
    setNewScreenshot(null)
    setScreenshotPreview(null)
  }

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
  const totalSkins = characters.reduce((sum, char) => {
    return sum + (allCharacters[char]?.skins?.length || 0)
  }, 0)

  // Calculate total stage variants
  const totalStageVariants = Object.values(stageVariants).reduce((sum, variants) => sum + variants.length, 0)

  // Edit Modal Component (reusable)
  const renderEditModal = () => (
    <>
      {showEditModal && editingItem && (
        <div className="edit-modal-overlay" onClick={handleCancel}>
          <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Edit {editingItem.type === 'costume' ? 'Costume' : 'Stage Variant'}</h2>

            {/* Preview Image */}
            <div className="edit-preview">
              {editingItem.type === 'costume' ? (
                editingItem.data.has_csp ? (
                  <img
                    src={editingItem.data.cspUrl}
                    alt="Preview"
                    onError={(e) => e.target.style.display = 'none'}
                  />
                ) : (
                  <div className="edit-placeholder">
                    <span>{editingItem.data.color[0]}</span>
                  </div>
                )
              ) : (
                <>
                  {/* Show new screenshot preview if selected, otherwise show current screenshot */}
                  {screenshotPreview ? (
                    <img
                      src={screenshotPreview}
                      alt="New screenshot preview"
                    />
                  ) : editingItem.data.hasScreenshot ? (
                    <img
                      src={editingItem.data.screenshotUrl}
                      alt="Preview"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  ) : (
                    <div className="edit-placeholder">
                      <span>{editingItem.data.name[0]}</span>
                    </div>
                  )}
                  {/* Hidden file input for screenshot replacement */}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleScreenshotChange}
                    style={{ display: 'none' }}
                    id="screenshot-file-input"
                  />
                  {/* Pen button overlay for stage screenshots */}
                  <button
                    className="btn-edit-screenshot"
                    onClick={() => document.getElementById('screenshot-file-input').click()}
                    title="Replace screenshot"
                  >
                    ✎
                  </button>
                </>
              )}
            </div>

            {/* Name Input */}
            <div className="edit-field">
              <label>{editingItem.type === 'costume' ? 'Color Name:' : 'Variant Name:'}</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Enter name..."
                autoFocus
              />
            </div>

            {/* Info */}
            <div className="edit-info">
              {editingItem.type === 'costume' ? (
                <>
                  <p><strong>Character:</strong> {editingItem.data.character}</p>
                  <p><strong>ID:</strong> {editingItem.data.id}</p>
                </>
              ) : (
                <>
                  <p><strong>Stage:</strong> {editingItem.data.stageName}</p>
                  <p><strong>ID:</strong> {editingItem.data.id}</p>
                </>
              )}
            </div>

            {/* Buttons */}
            <div className="edit-buttons">
              <button
                className="btn-save"
                onClick={handleSave}
                disabled={saving || deleting}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                className="btn-cancel"
                onClick={handleCancel}
                disabled={saving || deleting}
              >
                Cancel
              </button>
              <button
                className="btn-delete-modal"
                onClick={handleDelete}
                disabled={saving || deleting}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )

  // If a stage is selected, show its variants
  if (selectedStage) {
    const stageInfo = DAS_STAGES.find(s => s.code === selectedStage)
    const variants = stageVariants[selectedStage] || []

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
              {variants.map((variant) => (
                <div key={variant.name} className="skin-card">
                  <div className="skin-header">
                    <h4 className="skin-title">{variant.name}</h4>
                  </div>

                  <div className="skin-images">
                    <div className="skin-image-container">
                      {variant.hasScreenshot ? (
                        <img
                          src={variant.screenshotUrl}
                          alt={variant.name}
                          className="skin-csp"
                          style={{ width: '100%', height: 'auto' }}
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
                      <button
                        className="btn-edit"
                        onClick={(e) => {
                          e.stopPropagation()
                          e.preventDefault()
                          handleEditClick('stage', {
                            id: variant.name,
                            name: variant.name,
                            stageFolder: stageInfo?.folder,
                            stageName: stageInfo?.name,
                            screenshotUrl: variant.screenshotUrl,
                            hasScreenshot: variant.hasScreenshot
                          })
                        }}
                        title="Edit variant"
                      >
                        ✎
                      </button>
                    </div>
                  </div>

                  <div className="skin-info">
                    <div className="skin-color">{stageInfo?.name}</div>
                    <div className="skin-id">{variant.name}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {renderEditModal()}
      </div>
    )
  }

  // If a character is selected, show their skins
  if (selectedCharacter) {
    const charData = allCharacters[selectedCharacter]
    const skinCount = charData?.skins?.length || 0

    return (
      <div className="storage-viewer">
        <div className="character-detail">
          <button
            onClick={() => setSelectedCharacter(null)}
            className="back-button"
          >
            ← Back to Characters
          </button>

          <h2>{selectedCharacter}</h2>
          <p className="skin-count">{skinCount} skin{skinCount !== 1 ? 's' : ''}</p>

          {skinCount === 0 ? (
            <div className="no-skins-message">
              <p>No custom skins yet. Add some using the intake system!</p>
            </div>
          ) : (
            <div className="skins-grid">
              {charData.skins.map((skin) => (
                <div key={skin.id} className="skin-card">
                  <div className="skin-header">
                    <h4 className="skin-title">{selectedCharacter} - {skin.color}</h4>
                  </div>

                  <div className="skin-images">
                    <div className="skin-image-container">
                      {skin.has_csp ? (
                        <img
                          src={`/storage/${selectedCharacter}/${skin.id}_csp.png`}
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
                            cspUrl: `/storage/${selectedCharacter}/${skin.id}_csp.png`,
                            stockUrl: skin.has_stock ? `/storage/${selectedCharacter}/${skin.id}_stc.png` : null
                          })
                        }}
                        title="Edit costume"
                      >
                        ✎
                      </button>
                      <div className="image-label">CSP</div>
                    </div>

                    {skin.has_stock && (
                      <div className="stock-container">
                        <img
                          src={`/storage/${selectedCharacter}/${skin.id}_stc.png`}
                          alt={`${selectedCharacter} stock`}
                          className="skin-stock"
                        />
                        <div className="image-label">Stock</div>
                      </div>
                    )}
                  </div>

                  <div className="skin-info">
                    <div className="skin-color">{skin.color}</div>
                    <div className="skin-id">{skin.id}</div>
                    <div className="skin-sources">
                      <div className="source-line">CSP: {skin.csp_source}</div>
                      <div className="source-line">Stock: {skin.stock_source}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {renderEditModal()}
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
      </div>

      <div className="storage-header">
        <div className="storage-stats">
          {mode === 'characters' ? (
            <>
              <div className="stat-card">
                <div className="stat-value">{characters.length}</div>
                <div className="stat-label">Characters</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{totalSkins}</div>
                <div className="stat-label">Total Skins</div>
              </div>
            </>
          ) : (
            <>
              <div className="stat-card">
                <div className="stat-value">{DAS_STAGES.length}</div>
                <div className="stat-label">Stages</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{totalStageVariants}</div>
                <div className="stat-label">Total Variants</div>
              </div>
            </>
          )}
        </div>
        <div className="storage-actions">
          <label className="intake-import-btn" style={{ cursor: importing ? 'not-allowed' : 'pointer', opacity: importing ? 0.6 : 1 }}>
            {importing ? 'Importing...' : 'Import File'}
            <input
              type="file"
              accept=".zip"
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
      </div>

      {mode === 'characters' ? (
        <div className="characters-grid">
        {characters.map((characterName) => {
          const charData = allCharacters[characterName]
          const skinCount = charData?.skins?.length || 0

          // Find default color skin (color === "Default") to get costume code
          const defaultSkin = charData?.skins?.find(s => s.color === 'Default')
                            || charData?.skins?.[0]

          // Determine costume code: from skin metadata or from DEFAULT_CHARACTERS
          const costumeCode = defaultSkin?.costume_code || DEFAULT_CHARACTERS[characterName]?.defaultCostume

          // ALWAYS use vanilla CSP on homepage for consistency (like vanilla game)
          const vanillaCspPath = costumeCode
            ? `/vanilla/${characterName}/${costumeCode}/csp.png`
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
      ) : (
        // Stages grid
        <div className="characters-grid">
          {DAS_STAGES.map((stage) => {
            const variants = stageVariants[stage.code] || []
            const variantCount = variants.length

            // ALWAYS use vanilla stage screenshot (like how characters use vanilla CSPs)
            const vanillaImagePath = stage.vanillaImage

            return (
              <div
                key={stage.code}
                className="character-card"
                onClick={() => setSelectedStage(stage.code)}
              >
                <div className="character-image-container">
                  <img
                    src={vanillaImagePath}
                    alt={stage.name}
                    className="character-csp"
                    style={{ objectFit: 'cover' }}
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
      )}

      {renderEditModal()}
    </div>
  )
}
