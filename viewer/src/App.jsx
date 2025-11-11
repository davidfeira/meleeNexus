import { useState, useEffect } from 'react'
import StorageViewer from './components/StorageViewer'
import MexPanel from './components/MexPanel'
import Settings from './components/Settings'
import './App.css'

const API_URL = 'http://127.0.0.1:5000/api/mex'

function App() {
  const [activeTab, setActiveTab] = useState('storage');
  const [metadata, setMetadata] = useState(null);
  const [loading, setLoading] = useState(true);

  // Slippi dialog state for nucleus:// imports
  const [showSlippiDialog, setShowSlippiDialog] = useState(false);
  const [slippiDialogData, setSlippiDialogData] = useState(null);
  const [pendingImportData, setPendingImportData] = useState(null); // Stores {blob, name} for retry

  useEffect(() => {
    fetchMetadata();

    // Listen for nucleus:// protocol imports
    if (window.electron?.onNucleusImport) {
      const cleanup = window.electron.onNucleusImport(async (data) => {
        console.log('[Nucleus] Import triggered:', data);
        const { url, name, title } = data;

        try {
          // Download the file from the URL
          const response = await fetch(url);
          const blob = await response.blob();

          // Create a FormData to send to the import API
          const formData = new FormData();
          formData.append('file', blob, `${name || 'mod'}.zip`);

          // Add custom title if provided
          if (title) {
            formData.append('custom_title', title);
          }

          // Trigger import via existing API
          const importResponse = await fetch(`${API_URL}/import/file`, {
            method: 'POST',
            body: formData
          });

          const result = await importResponse.json();

          // Check if we need to show slippi safety dialog
          if (result.type === 'slippi_dialog') {
            console.log('[Nucleus] Slippi safety dialog needed:', result);
            setSlippiDialogData(result);
            setPendingImportData({ blob, name, title });
            setShowSlippiDialog(true);
            return; // Don't show error - user will choose action
          }

          if (result.success) {
            console.log('[Nucleus] Import successful:', result);
            // Refresh metadata to show the new mod
            fetchMetadata();
            // Switch to storage tab to show the imported mod
            setActiveTab('storage');
            alert(`Successfully imported: ${name || 'mod'}`);
          } else {
            console.error('[Nucleus] Import failed:', result);
            alert(`Import failed: ${result.error || 'Unknown error'}`);
          }
        } catch (error) {
          console.error('[Nucleus] Import error:', error);
          alert(`Import failed: ${error.message}`);
        }
      });

      // Cleanup listener on unmount
      return cleanup;
    }
  }, []);

  const fetchMetadata = async () => {
    try {
      const response = await fetch(`${API_URL}/storage/metadata`);
      const data = await response.json();
      if (data.success) {
        setMetadata(data.metadata);
      }
    } catch (err) {
      console.error('Failed to fetch metadata:', err);
      setMetadata({ characters: {} });
    } finally {
      setLoading(false);
    }
  };

  // Handle slippi safety choice for nucleus imports
  const handleSlippiChoice = async (choice) => {
    setShowSlippiDialog(false);

    if (choice === 'cancel') {
      setPendingImportData(null);
      setSlippiDialogData(null);
      return;
    }

    if (!pendingImportData) {
      console.error('[Nucleus] No pending import data');
      return;
    }

    try {
      // Retry import with slippi_action
      const formData = new FormData();
      formData.append('file', pendingImportData.blob, `${pendingImportData.name || 'mod'}.zip`);
      formData.append('slippi_action', choice); // 'fix' or 'import_as_is'

      // Add custom title if provided
      if (pendingImportData.title) {
        formData.append('custom_title', pendingImportData.title);
      }

      const importResponse = await fetch(`${API_URL}/import/file`, {
        method: 'POST',
        body: formData
      });

      const result = await importResponse.json();

      if (result.success) {
        console.log('[Nucleus] Import successful after slippi choice:', result);
        fetchMetadata();
        setActiveTab('storage');
        alert(`Successfully imported: ${pendingImportData.name || 'mod'}`);
      } else {
        console.error('[Nucleus] Import failed after slippi choice:', result);
        alert(`Import failed: ${result.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('[Nucleus] Error during slippi retry:', error);
      alert(`Import failed: ${error.message}`);
    } finally {
      setPendingImportData(null);
      setSlippiDialogData(null);
    }
  };

  // Render slippi safety dialog for nucleus imports
  const renderSlippiDialog = () => {
    return (
      <>
        {showSlippiDialog && slippiDialogData && (
          <div className="edit-modal-overlay" onClick={() => handleSlippiChoice('cancel')}>
            <div className="edit-modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
              <h2>Slippi Safety Warning</h2>

              <div style={{ padding: '1rem 0' }}>
                <p style={{ marginBottom: '1rem' }}>
                  This costume is not Slippi safe. Choose an action:
                </p>

                {slippiDialogData.unsafe_costumes && (
                  <div style={{
                    background: '#2a2a2a',
                    border: '1px solid #444',
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
                <button className="btn-save" onClick={() => handleSlippiChoice('fix')} style={{ width: '100%' }}>
                  Fix & Import
                </button>
                <button className="btn-secondary" onClick={() => handleSlippiChoice('import_as_is')} style={{ width: '100%' }}>
                  Import As-Is
                </button>
                <button className="btn-cancel" onClick={() => handleSlippiChoice('cancel')} style={{ width: '100%' }}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Melee Nexus</h1>
        <nav className="app-tabs">
          <button
            className={`tab ${activeTab === 'storage' ? 'active' : ''}`}
            onClick={() => setActiveTab('storage')}
          >
            Vault
          </button>
          <button
            className={`tab ${activeTab === 'mex' ? 'active' : ''}`}
            onClick={() => setActiveTab('mex')}
          >
            MEX Manager
          </button>
          <button
            className={`tab ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            Settings
          </button>
        </nav>
      </header>

      <main className="app-content">
        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px', color: '#888' }}>
            Loading...
          </div>
        ) : (
          <>
            <div style={{ display: activeTab === 'storage' ? 'block' : 'none' }}>
              <StorageViewer metadata={metadata} onRefresh={fetchMetadata} />
            </div>
            <div style={{ display: activeTab === 'mex' ? 'block' : 'none' }}>
              <MexPanel />
            </div>
            <div style={{ display: activeTab === 'settings' ? 'block' : 'none' }}>
              <Settings metadata={metadata} />
            </div>
          </>
        )}
      </main>

      {/* Slippi safety dialog for nucleus:// imports */}
      {renderSlippiDialog()}
    </div>
  )
}

export default App
