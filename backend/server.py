from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, HttpUrl, validator
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime
import asyncio
import aiofiles
import tempfile
import shutil
import hashlib
import time
from contextlib import asynccontextmanager
import json
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Rate limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])

# Create the main app
app = FastAPI(
    title="Multi-Platform Video Downloader",
    description="Download videos from YouTube, TikTok, and Instagram without watermarks",
    version="1.0.0"
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Models
class VideoRequest(BaseModel):
    url: HttpUrl
    format: str = "mp4"
    quality: str = "best"
    audio_only: bool = False
    remove_watermark: bool = True
    
    @validator('url')
    def validate_supported_url(cls, v):
        supported_domains = [
            'youtube.com', 'youtu.be', 'tiktok.com', 
            'instagram.com', 'facebook.com', 'twitter.com', 'x.com'
        ]
        url_str = str(v)
        if not any(domain in url_str for domain in supported_domains):
            raise ValueError('URL must be from a supported platform')
        return v

class DownloadResponse(BaseModel):
    download_id: str
    status: str
    message: str
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    progress: Optional[str] = None
    speed: Optional[str] = None
    eta: Optional[str] = None

class VideoDownloader:
    def __init__(self):
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        self.max_file_size = 500 * 1024 * 1024  # 500MB limit
        self.timeout_duration = 600  # 10 minutes
        self.semaphore = asyncio.Semaphore(5)  # Max 5 concurrent downloads
    
    def _detect_platform(self, url: str) -> str:
        """Detect the platform from URL"""
        if 'tiktok.com' in url:
            return 'tiktok'
        elif 'instagram.com' in url:
            return 'instagram'
        elif 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'facebook.com' in url:
            return 'facebook'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'twitter'
        else:
            return 'unknown'
    
    def _get_format_string(self, request: VideoRequest, platform: str) -> str:
        """Generate format string based on request parameters"""
        if request.audio_only:
            return 'bestaudio/best'
        
        if platform == 'tiktok' and request.remove_watermark:
            # For TikTok watermark-free downloads
            return 'best[ext=mp4]'
        
        quality_map = {
            'best': 'bestvideo+bestaudio/best',
            'worst': 'worst',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        }
        
        return quality_map.get(request.quality, 'bestvideo+bestaudio/best')
    
    async def _build_yt_dlp_options(
        self, request: VideoRequest, platform: str, download_id: str
    ) -> Dict[str, Any]:
        """Build platform-specific yt-dlp options"""
        base_options = {
            'outtmpl': str(self.download_dir / f"{download_id}.%(ext)s"),
            'format': self._get_format_string(request, platform),
            'writeinfojson': True,
            'writethumbnail': False,  # Skip thumbnail for faster downloads
            'ignoreerrors': False,
            'no_warnings': False,
            'extractflat': False,
            'socket_timeout': 30,
            'retries': 3,
        }
        
        # Platform-specific configurations
        if platform == 'tiktok':
            base_options.update(await self._get_tiktok_options(request))
        elif platform == 'instagram':
            base_options.update(await self._get_instagram_options())
        elif platform == 'youtube':
            base_options.update(await self._get_youtube_options(request))
        
        return base_options
    
    async def _get_tiktok_options(self, request: VideoRequest) -> Dict[str, Any]:
        """Configure TikTok-specific options for watermark removal"""
        options = {
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            },
        }
        
        if request.remove_watermark:
            options.update({
                'extractor_args': {
                    'tiktok': {
                        'api_hostname': 'api-h2.tiktokv.com',
                        'webpage_cache': True,
                    }
                }
            })
        
        return options
    
    async def _get_instagram_options(self) -> Dict[str, Any]:
        """Configure Instagram-specific options"""
        return {
            'http_headers': {
                'User-Agent': 'Instagram 219.0.0.12.117 Android (28/9; 480dpi; 1080x2139; samsung; SM-G973F; beyond1; exynos9820; en_US; 314665256)',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            'sleep_interval': 1,
            'max_sleep_interval': 5,
        }
    
    async def _get_youtube_options(self, request: VideoRequest) -> Dict[str, Any]:
        """Configure YouTube-specific options"""
        options = {
            'extractflat': False,
            'cookies_from_browser': ('chrome',),
            'writeautomaticsub': False,  # Skip subtitles for faster downloads
            'writesubtitles': False,
        }
        
        if request.audio_only:
            options['format'] = 'bestaudio/best'
        else:
            options['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best'
        
        return options
    
    def _create_progress_hook(self, download_id: str):
        """Create progress hook for yt-dlp"""
        def progress_hook(d):
            if d['status'] == 'downloading':
                self.active_downloads[download_id].update({
                    'progress': d.get('_percent_str', 'N/A'),
                    'speed': d.get('_speed_str', 'N/A'),
                    'eta': d.get('_eta_str', 'N/A'),
                    'downloaded_bytes': d.get('downloaded_bytes', 0),
                    'total_bytes': d.get('total_bytes', 0),
                })
            elif d['status'] == 'finished':
                self.active_downloads[download_id].update({
                    'status': 'processing',
                    'message': 'Processing downloaded file...'
                })
        
        return progress_hook
    
    async def _execute_download(
        self, url: str, options: Dict[str, Any], download_id: str
    ) -> Dict[str, Any]:
        """Execute the actual download using yt-dlp"""
        import yt_dlp
        
        progress_hook = self._create_progress_hook(download_id)
        options['progress_hooks'] = [progress_hook]
        
        loop = asyncio.get_event_loop()
        
        def download_sync():
            with yt_dlp.YoutubeDL(options) as ydl:
                # First extract info to check file size
                info = ydl.extract_info(url, download=False)
                
                # Check file size if available
                if 'filesize' in info and info['filesize'] and info['filesize'] > self.max_file_size:
                    raise ValueError(f"File size ({info['filesize'] / (1024*1024):.2f}MB) exceeds maximum allowed size (500MB)")
                
                # Proceed with download
                info = ydl.extract_info(url, download=True)
                return info
        
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, download_sync),
                timeout=self.timeout_duration
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=408, detail="Download timeout - file is too large or connection is slow")
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
        
        # Find downloaded file
        downloaded_files = []
        base_path = self.download_dir / download_id
        
        # Check common video extensions
        for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov', 'flv']:
            file_path = base_path.with_suffix(f'.{ext}')
            if file_path.exists():
                downloaded_files.append(file_path)
                break
        
        # Check audio extensions if audio_only
        if not downloaded_files:
            for ext in ['mp3', 'm4a', 'wav', 'ogg', 'aac']:
                file_path = base_path.with_suffix(f'.{ext}')
                if file_path.exists():
                    downloaded_files.append(file_path)
                    break
        
        if not downloaded_files:
            raise HTTPException(status_code=500, detail="No video file was downloaded")
        
        main_file = downloaded_files[0]
        file_size = main_file.stat().st_size
        
        return {
            'file_path': str(main_file),
            'file_size': file_size,
            'filename': main_file.name,
            'metadata': {
                'title': info.get('title', 'Unknown'),
                'uploader': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', 'Unknown'),
                'platform': self._detect_platform(url)
            }
        }
    
    async def download_video(self, request: VideoRequest, download_id: str) -> Dict[str, Any]:
        """Main video download orchestration method"""
        async with self.semaphore:
            try:
                # Update download status
                self.active_downloads[download_id] = {
                    "status": "processing",
                    "start_time": time.time(),
                    "url": str(request.url),
                    "message": "Starting download..."
                }
                
                # Determine platform and configure options
                platform = self._detect_platform(str(request.url))
                yt_dlp_options = await self._build_yt_dlp_options(
                    request, platform, download_id
                )
                
                # Execute download
                result = await self._execute_download(
                    str(request.url), yt_dlp_options, download_id
                )
                
                # Update final status
                end_time = time.time()
                duration = end_time - self.active_downloads[download_id]["start_time"]
                
                self.active_downloads[download_id].update({
                    "status": "completed",
                    "end_time": end_time,
                    "duration": duration,
                    "result": result,
                    "message": "Download completed successfully!"
                })
                
                return result
                
            except Exception as e:
                self.active_downloads[download_id].update({
                    "status": "failed",
                    "error": str(e),
                    "end_time": time.time(),
                    "message": f"Download failed: {str(e)}"
                })
                raise e

# Global downloader instance
downloader = VideoDownloader()

@api_router.post("/download", response_model=DownloadResponse)
@limiter.limit("10/minute")
async def download_video(
    request: Request,
    video_request: VideoRequest, 
    background_tasks: BackgroundTasks
):
    """Initiate video download"""
    download_id = str(uuid.uuid4())
    
    # Start download in background
    background_tasks.add_task(
        downloader.download_video, video_request, download_id
    )
    
    return DownloadResponse(
        download_id=download_id,
        status="queued",
        message="Download started successfully"
    )

@api_router.get("/download/{download_id}/status", response_model=DownloadResponse)
async def get_download_status(download_id: str):
    """Get download status"""
    if download_id not in downloader.active_downloads:
        raise HTTPException(status_code=404, detail="Download not found")
    
    download_info = downloader.active_downloads[download_id]
    
    response_data = {
        "download_id": download_id,
        "status": download_info["status"],
        "message": download_info.get("message", f"Download {download_info['status']}"),
        "progress": download_info.get("progress"),
        "speed": download_info.get("speed"),
        "eta": download_info.get("eta")
    }
    
    if download_info["status"] == "completed":
        result = download_info["result"]
        response_data.update({
            "file_url": f"/api/download/{download_id}/file",
            "file_size": result["file_size"],
            "duration": download_info.get("duration"),
            "metadata": result["metadata"]
        })
    
    return DownloadResponse(**response_data)

@api_router.get("/download/{download_id}/file")
async def download_file(download_id: str):
    """Download the processed video file"""
    if download_id not in downloader.active_downloads:
        raise HTTPException(status_code=404, detail="Download not found")
    
    download_info = downloader.active_downloads[download_id]
    
    if download_info["status"] != "completed":
        raise HTTPException(status_code=400, detail="Download not completed")
    
    file_path = Path(download_info["result"]["file_path"])
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Clean filename for download
    original_filename = download_info["result"]["filename"]
    metadata = download_info["result"]["metadata"]
    clean_filename = f"{metadata.get('title', 'video')}.{file_path.suffix[1:]}"
    
    return FileResponse(
        path=file_path,
        filename=clean_filename,
        media_type="application/octet-stream"
    )

@api_router.get("/supported-platforms")
async def get_supported_platforms():
    """Get list of supported platforms"""
    return {
        "platforms": [
            {
                "name": "YouTube",
                "domain": "youtube.com",
                "features": ["High Quality", "Multiple Formats", "Subtitles"]
            },
            {
                "name": "TikTok",
                "domain": "tiktok.com", 
                "features": ["Watermark Free", "HD Quality"]
            },
            {
                "name": "Instagram",
                "domain": "instagram.com",
                "features": ["Stories", "Reels", "IGTV"]
            },
            {
                "name": "Twitter/X",
                "domain": "twitter.com",
                "features": ["Video Tweets", "High Quality"]
            },
            {
                "name": "Facebook",
                "domain": "facebook.com", 
                "features": ["Video Posts", "Stories"]
            }
        ]
    }

# Health check endpoint
@api_router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Multi-Platform Video Downloader",
        "version": "1.0.0",
        "active_downloads": len(downloader.active_downloads)
    }

@api_router.get("/")
async def root():
    return {"message": "Multi-Platform Video Downloader API", "version": "1.0.0"}

# Include the router in the main app
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    
    # Cleanup any remaining temp files
    import shutil
    temp_dir = Path("temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)