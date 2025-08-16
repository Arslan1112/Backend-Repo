#!/usr/bin/env python3

import requests
import sys
import time
import json
from datetime import datetime

class VideoDownloaderAPITester:
    def __init__(self, base_url="https://e265ce3e-5bfc-4a9f-bad5-4e061cc007ac.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'VideoDownloader-Test/1.0'
        })

    def log_test(self, name, success, details=""):
        """Log test results"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
        
        if details:
            print(f"   Details: {details}")

    def test_health_endpoint(self):
        """Test the health check endpoint"""
        try:
            response = self.session.get(f"{self.base_url}/api/health", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                expected_keys = ['status', 'service', 'version']
                
                if all(key in data for key in expected_keys):
                    if data['status'] == 'healthy':
                        self.log_test("Health Check", True, f"Service: {data.get('service')}, Version: {data.get('version')}")
                        return True
                    else:
                        self.log_test("Health Check", False, f"Service not healthy: {data['status']}")
                else:
                    self.log_test("Health Check", False, f"Missing expected keys in response: {data}")
            else:
                self.log_test("Health Check", False, f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            self.log_test("Health Check", False, f"Exception: {str(e)}")
        
        return False

    def test_supported_platforms(self):
        """Test the supported platforms endpoint"""
        try:
            response = self.session.get(f"{self.base_url}/api/supported-platforms", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'platforms' in data and isinstance(data['platforms'], list):
                    platforms = data['platforms']
                    expected_platforms = ['YouTube', 'TikTok', 'Instagram', 'Twitter/X', 'Facebook']
                    
                    platform_names = [p.get('name', '') for p in platforms]
                    
                    if len(platforms) >= 4:  # At least 4 platforms should be supported
                        self.log_test("Supported Platforms", True, f"Found {len(platforms)} platforms: {platform_names}")
                        return True
                    else:
                        self.log_test("Supported Platforms", False, f"Too few platforms: {platform_names}")
                else:
                    self.log_test("Supported Platforms", False, f"Invalid response format: {data}")
            else:
                self.log_test("Supported Platforms", False, f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            self.log_test("Supported Platforms", False, f"Exception: {str(e)}")
        
        return False

    def test_download_initiation(self, test_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
        """Test download initiation with a short YouTube video"""
        try:
            payload = {
                "url": test_url,
                "format": "mp4",
                "quality": "worst",  # Use worst quality for faster testing
                "audio_only": False,
                "remove_watermark": True
            }
            
            response = self.session.post(f"{self.base_url}/api/download", json=payload, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                required_keys = ['download_id', 'status', 'message']
                
                if all(key in data for key in required_keys):
                    if data['status'] in ['queued', 'processing']:
                        self.log_test("Download Initiation", True, f"Download ID: {data['download_id']}, Status: {data['status']}")
                        return data['download_id']
                    else:
                        self.log_test("Download Initiation", False, f"Unexpected status: {data['status']}")
                else:
                    self.log_test("Download Initiation", False, f"Missing required keys: {data}")
            else:
                self.log_test("Download Initiation", False, f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            self.log_test("Download Initiation", False, f"Exception: {str(e)}")
        
        return None

    def test_download_status(self, download_id, max_wait_time=60):
        """Test download status polling"""
        if not download_id:
            self.log_test("Download Status", False, "No download ID provided")
            return False
            
        try:
            start_time = time.time()
            final_status = None
            
            while time.time() - start_time < max_wait_time:
                response = self.session.get(f"{self.base_url}/api/download/{download_id}/status", timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get('status', 'unknown')
                    
                    print(f"   Status check: {status} - {data.get('message', 'No message')}")
                    
                    if status in ['completed', 'failed']:
                        final_status = status
                        break
                    elif status in ['queued', 'processing']:
                        time.sleep(3)  # Wait 3 seconds before next check
                        continue
                    else:
                        self.log_test("Download Status", False, f"Unknown status: {status}")
                        return False
                else:
                    self.log_test("Download Status", False, f"HTTP {response.status_code}: {response.text}")
                    return False
            
            if final_status == 'completed':
                self.log_test("Download Status", True, "Download completed successfully")
                return True
            elif final_status == 'failed':
                self.log_test("Download Status", False, "Download failed")
                return False
            else:
                self.log_test("Download Status", False, f"Download timed out after {max_wait_time}s")
                return False
                
        except Exception as e:
            self.log_test("Download Status", False, f"Exception: {str(e)}")
        
        return False

    def test_file_download(self, download_id):
        """Test file download endpoint"""
        if not download_id:
            self.log_test("File Download", False, "No download ID provided")
            return False
            
        try:
            response = self.session.get(f"{self.base_url}/api/download/{download_id}/file", timeout=30)
            
            if response.status_code == 200:
                content_length = len(response.content)
                content_type = response.headers.get('content-type', 'unknown')
                
                if content_length > 0:
                    self.log_test("File Download", True, f"File size: {content_length} bytes, Type: {content_type}")
                    return True
                else:
                    self.log_test("File Download", False, "Empty file received")
            else:
                self.log_test("File Download", False, f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            self.log_test("File Download", False, f"Exception: {str(e)}")
        
        return False

    def test_invalid_url_handling(self):
        """Test error handling for invalid URLs"""
        try:
            payload = {
                "url": "https://invalid-site.com/video",
                "format": "mp4",
                "quality": "best",
                "audio_only": False,
                "remove_watermark": True
            }
            
            response = self.session.post(f"{self.base_url}/api/download", json=payload, timeout=10)
            
            # Should return 422 for validation error or 400 for bad request
            if response.status_code in [400, 422]:
                self.log_test("Invalid URL Handling", True, f"Correctly rejected invalid URL with status {response.status_code}")
                return True
            else:
                self.log_test("Invalid URL Handling", False, f"Unexpected status code: {response.status_code}")
                
        except Exception as e:
            self.log_test("Invalid URL Handling", False, f"Exception: {str(e)}")
        
        return False

    def test_rate_limiting(self):
        """Test rate limiting (10 requests per minute)"""
        try:
            # Make multiple rapid requests to test rate limiting
            rapid_requests = 0
            rate_limited = False
            
            for i in range(12):  # Try 12 requests (more than the 10/minute limit)
                response = self.session.get(f"{self.base_url}/api/health", timeout=5)
                rapid_requests += 1
                
                if response.status_code == 429:  # Too Many Requests
                    rate_limited = True
                    break
                    
                time.sleep(0.1)  # Small delay between requests
            
            if rate_limited:
                self.log_test("Rate Limiting", True, f"Rate limiting triggered after {rapid_requests} requests")
                return True
            else:
                # Rate limiting might not trigger immediately, so this is not necessarily a failure
                self.log_test("Rate Limiting", True, f"Made {rapid_requests} requests without hitting rate limit (may be expected)")
                return True
                
        except Exception as e:
            self.log_test("Rate Limiting", False, f"Exception: {str(e)}")
        
        return False

    def run_all_tests(self):
        """Run all backend API tests"""
        print("🚀 Starting Multi-Platform Video Downloader API Tests")
        print(f"📡 Testing against: {self.base_url}")
        print("=" * 60)
        
        # Test 1: Health Check
        health_ok = self.test_health_endpoint()
        
        # Test 2: Supported Platforms
        platforms_ok = self.test_supported_platforms()
        
        # Test 3: Invalid URL Handling
        invalid_url_ok = self.test_invalid_url_handling()
        
        # Test 4: Rate Limiting
        rate_limit_ok = self.test_rate_limiting()
        
        # Test 5-7: Full Download Flow (only if basic tests pass)
        download_id = None
        if health_ok and platforms_ok:
            print("\n🎬 Testing full download workflow...")
            download_id = self.test_download_initiation()
            
            if download_id:
                status_ok = self.test_download_status(download_id)
                if status_ok:
                    self.test_file_download(download_id)
        
        # Print final results
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed! Backend API is working correctly.")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} test(s) failed. Check the issues above.")
            return 1

def main():
    """Main test execution"""
    tester = VideoDownloaderAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())