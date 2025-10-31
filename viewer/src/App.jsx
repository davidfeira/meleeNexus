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

  useEffect(() => {
    fetchMetadata();
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
    </div>
  )
}

export default App
