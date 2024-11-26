from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import yt_dlp
import os
import logging
import re
import threading
import time

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for download control
active_downloads = {}
download_stop_flags = {}

# Ensure downloads directory exists and get its absolute path
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

def my_hook(d):
    if d['status'] == 'downloading':
        progress = {
            'title': d.get('info_dict', {}).get('title', 'Unknown'),
            'status': 'downloading',
            'downloaded_bytes': d.get('downloaded_bytes', 0),
            'total_bytes': d.get('total_bytes', 0),
            'speed': d.get('speed', 0),
            'eta': d.get('eta', 0),
            'filename': d.get('filename', '')
        }
        socketio.emit('download_progress', progress)
    elif d['status'] == 'finished':
        filename = os.path.basename(d.get('filename', ''))
        title = d.get('info_dict', {}).get('title', 'Unknown')
        progress = {
            'title': title,
            'status': 'finished',
            'filename': filename
        }
        socketio.emit('download_progress', progress)
        # Emit a separate event for completed video
        socketio.emit('video_completed', {
            'title': title,
            'filename': filename
        })

def extract_playlist_id(url):
    patterns = [
        r'list=([a-zA-Z0-9_-]+)',
        r'playlist\?list=([a-zA-Z0-9_-]+)',
        r'watch\?v=[a-zA-Z0-9_-]+&list=([a-zA-Z0-9_-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_playlist_videos(playlist_url):
    playlist_id = extract_playlist_id(playlist_url)
    if not playlist_id:
        raise Exception("Invalid playlist URL format")

    logger.info(f"Extracted playlist ID: {playlist_id}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlist_items': '1-50',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("Attempting to extract playlist info...")
            result = ydl.extract_info(f"https://www.youtube.com/playlist?list={playlist_id}", download=False)
            
            if not result:
                logger.error("No result returned from yt-dlp")
                return []
                
            logger.info(f"Playlist info extracted. Type: {type(result)}")
            
            if 'entries' in result:
                entries = [entry for entry in result['entries'] if entry is not None]
                logger.info(f"Found {len(entries)} videos in playlist")
                return entries
            else:
                logger.error("No 'entries' found in result")
                logger.debug(f"Result keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
                return []
                
    except Exception as e:
        logger.error(f"Error in get_playlist_videos: {str(e)}")
        raise

def download_playlist_task(playlist_url, download_id):
    try:
        videos = get_playlist_videos(playlist_url)
        if not videos:
            socketio.emit('download_error', {'error': 'No videos found in playlist'})
            return

        failed_downloads = []
        
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio',
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'progress_hooks': [my_hook],
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for i, video in enumerate(videos):
                if download_stop_flags.get(download_id, False):
                    logger.info(f"Download {download_id} stopped by user")
                    socketio.emit('download_stopped', {'message': 'Download stopped by user'})
                    break

                try:
                    video_url = f"https://www.youtube.com/watch?v={video['id']}"
                    logger.info(f"Downloading video {i+1}/{len(videos)}: {video.get('title', 'Unknown Title')}")
                    
                    socketio.emit('download_status', {
                        'current': i + 1,
                        'total': len(videos),
                        'title': video.get('title', 'Unknown Title')
                    })
                    
                    ydl.download([video_url])
                    
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Error downloading video: {error_message}")
                    failed_downloads.append(f"{video.get('title', 'Unknown Title')} ({error_message})")

        if not download_stop_flags.get(download_id, False):
            socketio.emit('download_complete', {
                'message': 'Download completed',
                'failed': failed_downloads
            })
    except Exception as e:
        logger.error(f"Error in download task: {str(e)}")
        socketio.emit('download_error', {'error': str(e)})
    finally:
        if download_id in active_downloads:
            del active_downloads[download_id]
        if download_id in download_stop_flags:
            del download_stop_flags[download_id]

@app.route('/download', methods=['POST'])
def download_playlist():
    data = request.json
    playlist_url = data.get('url')
    
    if not playlist_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    try:
        download_id = str(time.time())
        download_stop_flags[download_id] = False
        
        # Start download in a separate thread
        download_thread = threading.Thread(
            target=download_playlist_task,
            args=(playlist_url, download_id)
        )
        active_downloads[download_id] = download_thread
        download_thread.start()
        
        return jsonify({
            'message': 'Download started',
            'download_id': download_id
        }), 200
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error starting download: {error_msg}")
        return jsonify({
            'error': f'Error starting download: {error_msg}'
        }), 500

@app.route('/stop_download/<download_id>', methods=['POST'])
def stop_download(download_id):
    if download_id in download_stop_flags:
        download_stop_flags[download_id] = True
        return jsonify({'message': 'Stop signal sent'}), 200
    return jsonify({'error': 'Download not found'}), 404

@app.route('/download_file/<path:filename>')
def download_file(filename):
    try:
        logger.info(f"Attempting to download file: {filename}")
        logger.info(f"Looking in directory: {DOWNLOADS_DIR}")
        
        # Ensure the filename is safe
        filename = os.path.basename(filename)
        
        if not os.path.exists(os.path.join(DOWNLOADS_DIR, filename)):
            logger.error(f"File not found: {filename}")
            return jsonify({'error': 'File not found'}), 404

        return send_from_directory(
            DOWNLOADS_DIR,
            filename,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/list_downloads')
def list_downloads():
    try:
        files = []
        for filename in os.listdir(DOWNLOADS_DIR):
            if filename.endswith('.m4a'):  # Only list audio files
                filepath = os.path.join(DOWNLOADS_DIR, filename)
                files.append({
                    'filename': filename,
                    'size': os.path.getsize(filepath)
                })
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    socketio.run(app, debug=True)
