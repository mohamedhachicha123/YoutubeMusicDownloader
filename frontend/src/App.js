import React, { useState, useEffect } from 'react';
import './App.css';
import io from 'socket.io-client';

const socket = io('http://localhost:5000');

function App() {
  const [url, setUrl] = useState('');
  const [theme, setTheme] = useState('light');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [downloadId, setDownloadId] = useState(null);
  const [downloadProgress, setDownloadProgress] = useState({});
  const [downloadStatus, setDownloadStatus] = useState(null);
  const [completedDownloads, setCompletedDownloads] = useState([]);
  const [failedDownloads, setFailedDownloads] = useState([]);
  const [selectedVideos, setSelectedVideos] = useState(new Set());

  useEffect(() => {
    socket.on('download_progress', (progress) => {
      if (progress.status === 'downloading') {
        setDownloadProgress(progress);
      } else if (progress.status === 'finished') {
        setDownloadProgress({});
      }
    });

    socket.on('download_status', (status) => {
      setDownloadStatus(status);
    });

    socket.on('video_completed', (data) => {
      setCompletedDownloads(prevCompleted => [...prevCompleted, data]);
    });

    socket.on('download_complete', (data) => {
      setIsLoading(false);
      setDownloadId(null);
      setDownloadStatus(null);
      setDownloadProgress({});
      setFailedDownloads(data.failed || []);
    });

    socket.on('download_error', (data) => {
      setError(data.error);
      setIsLoading(false);
      setDownloadId(null);
    });

    socket.on('download_stopped', () => {
      setIsLoading(false);
      setDownloadId(null);
      setDownloadStatus(null);
      setDownloadProgress({});
    });

    return () => {
      socket.off('download_progress');
      socket.off('download_status');
      socket.off('video_completed');
      socket.off('download_complete');
      socket.off('download_error');
      socket.off('download_stopped');
    };
  }, []);

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setFailedDownloads([]);
    setIsLoading(true);
    setSelectedVideos(new Set());

    try {
      const response = await fetch('http://localhost:5000/download', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to start download');
      }

      setDownloadId(data.download_id);
    } catch (err) {
      setError(err.message);
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    if (downloadId) {
      try {
        await fetch(`http://localhost:5000/stop_download/${downloadId}`, {
          method: 'POST',
        });
      } catch (err) {
        console.error('Failed to stop download:', err);
      }
    }
  };

  const handleDownloadFile = (filename) => {
    window.open(`http://localhost:5000/download_file/${encodeURIComponent(filename)}`, '_blank');
  };

  const handleSelectVideo = (filename) => {
    setSelectedVideos(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filename)) {
        newSet.delete(filename);
      } else {
        newSet.add(filename);
      }
      return newSet;
    });
  };

  const handleSelectAll = () => {
    if (selectedVideos.size === completedDownloads.length) {
      setSelectedVideos(new Set());
    } else {
      setSelectedVideos(new Set(completedDownloads.map(download => download.filename)));
    }
  };

  const handleDownloadSelected = () => {
    selectedVideos.forEach(filename => {
      handleDownloadFile(filename);
    });
  };

  const formatBytes = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  const formatSpeed = (speed) => {
    return `${formatBytes(speed)}/s`;
  };

  return (
    <div className={`App ${theme}`}>
      <div className="theme-toggle">
        <button onClick={toggleTheme}>
          {theme === 'light' ? '🌙' : '☀️'}
        </button>
      </div>
      
      <div className="container">
        <h1>YouTube Playlist Downloader</h1>
        
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Enter YouTube playlist URL"
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !url}>
            Download
          </button>
          {isLoading && downloadId && (
            <button type="button" onClick={handleStop} className="stop-button">
              Stop Download
            </button>
          )}
        </form>

        {error && <div className="error">{error}</div>}

        {downloadStatus && (
          <div className="download-status">
            <h3>Downloading: {downloadStatus.current}/{downloadStatus.total}</h3>
            <div className="current-download">
              <p>{downloadStatus.title}</p>
              {downloadProgress.downloaded_bytes && downloadProgress.total_bytes && (
                <div className="progress-bar">
                  <div
                    className="progress"
                    style={{
                      width: `${(downloadProgress.downloaded_bytes / downloadProgress.total_bytes) * 100}%`
                    }}
                  ></div>
                </div>
              )}
              {downloadProgress.speed && (
                <p>
                  Speed: {formatSpeed(downloadProgress.speed)}
                  {downloadProgress.eta && ` • ETA: ${downloadProgress.eta} seconds`}
                </p>
              )}
            </div>
          </div>
        )}

        {completedDownloads.length > 0 && (
          <div className="download-list">
            <div className="download-header">
              <h3>Successfully Downloaded:</h3>
              <div className="download-actions">
                <button 
                  onClick={handleSelectAll}
                  className="select-all-button"
                >
                  {selectedVideos.size === completedDownloads.length ? 'Deselect All' : 'Select All'}
                </button>
                {selectedVideos.size > 0 && (
                  <button 
                    onClick={handleDownloadSelected}
                    className="download-selected-button"
                  >
                    Download Selected ({selectedVideos.size})
                  </button>
                )}
              </div>
            </div>
            <ul>
              {completedDownloads.map((download, index) => (
                <li key={index} className="success">
                  <label className="download-item">
                    <input
                      type="checkbox"
                      checked={selectedVideos.has(download.filename)}
                      onChange={() => handleSelectVideo(download.filename)}
                    />
                    <span className="download-title">{download.title}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )}

        {failedDownloads.length > 0 && (
          <div className="download-list">
            <h3>Failed Downloads:</h3>
            <ul>
              {failedDownloads.map((item, index) => (
                <li key={index} className="error">{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
